import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import aio_pika
import pytest
import pytest_asyncio
from aio_pika import DeliveryMode, Message
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

import src.webhook_worker as webhook_worker
from src.common.enums import OutboxStatus
from src.config import settings
from src.database import async_session_maker, dispose_engine
from src.messaging.contracts import OutboxMessage
from src.messaging.idempotency import try_mark_processed
from src.messaging.models import ProcessedMessage
from src.messaging.publisher import RabbitMQPublisher
from src.messaging.topology import EVENTS_EXCHANGE, declare_webhook_topology
from src.outbox.models import OutboxEvent
from src.webhook_worker import CONSUMER_NAME
from src.worker import build_outbox_message, process_outbox_once

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="Integration tests are disabled. Set RUN_INTEGRATION_TESTS=1 to enable.",
)


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    async with async_session_maker() as session:
        yield session

        await session.rollback()
    await dispose_engine()


@pytest_asyncio.fixture
async def rabbitmq_connection() -> AsyncIterator[aio_pika.abc.AbstractRobustConnection]:
    connection = await aio_pika.connect_robust(
        str(settings.rabbitmq_dsn),
    )

    await declare_webhook_topology(connection)

    try:
        yield connection
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_outbox_event_is_published_to_rabbitmq(
    db_session: AsyncSession,
    rabbitmq_connection: aio_pika.abc.AbstractRobustConnection,
) -> None:
    event_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    organization_id = uuid.uuid4()

    event = OutboxEvent(
        id=event_id,
        aggregate_type="task",
        aggregate_id=uuid.uuid4(),
        event_type="task.created",
        event_version=1,
        correlation_id=correlation_id,
        causation_id=None,
        organization_id=organization_id,
        payload={
            "task_id": str(uuid.uuid4()),
            "title": "Integration test task",
        },
        status=OutboxStatus.PENDING,
        attempts=0,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    db_session.add(event)
    await db_session.commit()

    try:
        channel = await rabbitmq_connection.channel()
        exchange = await channel.get_exchange(EVENTS_EXCHANGE, ensure=True)
        queue = await channel.declare_queue(
            f"test.webhooks.events.{event_id}",
            auto_delete=True,
            exclusive=True,
        )
        await queue.bind(exchange, routing_key="task.created")

        await queue.purge()

        publisher = RabbitMQPublisher(str(settings.rabbitmq_dsn))

        async with publisher:
            processed = await process_outbox_once(publisher, batch_size=10)

        assert processed == 1

        incoming = await queue.get(timeout=5, fail=False)

        try:
            assert incoming is not None

            message = OutboxMessage.model_validate_json(incoming.body)

            assert message.event_id == event_id
            assert message.event_type == "task.created"
            assert message.event_version == 1
            assert message.correlation_id == correlation_id
            assert message.organization_id == organization_id
            assert message.aggregate_type == "task"
            assert message.payload["title"] == "Integration test task"

            assert incoming.message_id == str(event_id)
            assert incoming.correlation_id == str(correlation_id)

            assert incoming.headers is not None
            assert incoming.headers["event_version"] == 1
            assert incoming.headers["organization_id"] == str(
                organization_id,
            )
            assert incoming.headers["aggregate_type"] == "task"
            assert incoming.headers["aggregate_id"] == str(event.aggregate_id)
            assert "causation_id" not in incoming.headers
        finally:
            if incoming is not None:
                await incoming.ack()
            await channel.close()

        await db_session.refresh(event)

        assert event.status == OutboxStatus.PROCESSED
        assert event.processed_at is not None
    finally:
        async with async_session_maker() as cleanup_session:
            async with cleanup_session.begin():
                await cleanup_session.execute(
                    delete(OutboxEvent).where(
                        OutboxEvent.id == event_id,
                    )
                )


@pytest.mark.asyncio
async def test_failed_publish_schedules_outbox_retry(
    db_session: AsyncSession,
) -> None:
    event_id = uuid.uuid4()

    event = OutboxEvent(
        id=event_id,
        aggregate_type="task",
        aggregate_id=uuid.uuid4(),
        event_type="task.created",
        event_version=1,
        correlation_id=event_id,
        causation_id=None,
        organization_id=uuid.uuid4(),
        payload={"task_id": str(uuid.uuid4())},
        status=OutboxStatus.PENDING,
        attempts=0,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    db_session.add(event)
    await db_session.commit()

    class FailingPublisher:
        async def publish(self, _message: OutboxMessage) -> None:
            raise RuntimeError("RabbitMQ unavailable")

    try:
        processed = await process_outbox_once(
            FailingPublisher(),  # type: ignore[arg-type]
            batch_size=10,
        )

        assert processed == 0

        await db_session.refresh(event)

        assert event.status == OutboxStatus.PENDING
        assert event.attempts == 1
        assert event.next_attempt_at is not None
        assert event.last_error == "RabbitMQ unavailable"
        assert event.processed_at is None
    finally:
        async with async_session_maker() as cleanup_session:
            async with cleanup_session.begin():
                await cleanup_session.execute(
                    delete(OutboxEvent).where(
                        OutboxEvent.id == event_id,
                    )
                )


@pytest.mark.asyncio
async def test_duplicate_rabbitmq_messages_are_processed_once(
    rabbitmq_connection: aio_pika.abc.AbstractRobustConnection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_id = uuid.uuid4()
    correlation_id = uuid.uuid4()

    event = OutboxEvent(
        id=event_id,
        aggregate_type="task",
        aggregate_id=uuid.uuid4(),
        event_type="task.created",
        event_version=1,
        correlation_id=correlation_id,
        causation_id=None,
        organization_id=uuid.uuid4(),
        payload={
            "task_id": str(uuid.uuid4()),
            "title": "Idempotent consumer task",
        },
        status=OutboxStatus.PENDING,
        attempts=0,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    outbox_message = build_outbox_message(event)

    delivery_mock = AsyncMock()
    monkeypatch.setattr(
        "src.webhook_worker.deliver_webhooks_for_outbox_event",
        delivery_mock,
    )
    acquired_results: list[bool] = []

    async def recording_try_mark_processed(
        session: AsyncSession,
        *,
        message_id: uuid.UUID,
        consumer_name: str,
    ) -> bool:
        acquired = await try_mark_processed(
            session,
            message_id=message_id,
            consumer_name=consumer_name,
        )
        acquired_results.append(acquired)
        return acquired

    monkeypatch.setattr(
        "src.webhook_worker.try_mark_processed",
        recording_try_mark_processed,
    )

    channel: aio_pika.abc.AbstractChannel | None = None

    try:
        async with async_session_maker() as cleanup_session:
            async with cleanup_session.begin():
                await cleanup_session.execute(
                    delete(ProcessedMessage).where(
                        ProcessedMessage.message_id == event_id,
                        ProcessedMessage.consumer_name == CONSUMER_NAME,
                    )
                )

        channel = await rabbitmq_connection.channel()
        queue = await channel.declare_queue(
            f"test.webhooks.idempotency.{event_id}",
            auto_delete=True,
            exclusive=True,
        )
        await queue.purge()

        for _ in range(2):
            await channel.default_exchange.publish(
                Message(
                    body=outbox_message.model_dump_json().encode(),
                    content_type="application/json",
                    delivery_mode=DeliveryMode.PERSISTENT,
                    message_id=str(event_id),
                    correlation_id=str(correlation_id),
                ),
                routing_key=queue.name,
            )

        bodies: list[bytes] = []
        for _ in range(2):
            incoming = await queue.get(timeout=5, fail=False)
            assert incoming is not None
            bodies.append(incoming.body)
            await incoming.ack()

        for body in bodies:
            assert OutboxMessage.model_validate_json(body).event_id == event_id

        async with async_session_maker() as session:
            initial_processed_count = await session.scalar(
                select(func.count())
                .select_from(ProcessedMessage)
                .where(
                    ProcessedMessage.message_id == event_id,
                    ProcessedMessage.consumer_name == CONSUMER_NAME,
                )
            )

        assert initial_processed_count == 0

        consumer_messages: list[MagicMock] = []
        for body in bodies:
            consumer_message = MagicMock()
            consumer_message.body = body
            consumer_message.ack = AsyncMock()
            consumer_message.reject = AsyncMock()
            consumer_messages.append(consumer_message)

            await webhook_worker.process_message(consumer_message)

        async with async_session_maker() as session:
            processed_count = await session.scalar(
                select(func.count())
                .select_from(ProcessedMessage)
                .where(
                    ProcessedMessage.message_id == event_id,
                    ProcessedMessage.consumer_name == CONSUMER_NAME,
                )
            )

        assert processed_count == 1
        assert acquired_results == [True, False]
        delivery_mock.assert_awaited_once()
        for consumer_message in consumer_messages:
            consumer_message.ack.assert_awaited_once_with()
            consumer_message.reject.assert_not_awaited()
    finally:
        if channel is not None:
            await channel.close()
        async with async_session_maker() as cleanup_session:
            async with cleanup_session.begin():
                await cleanup_session.execute(
                    delete(ProcessedMessage).where(
                        ProcessedMessage.message_id == event_id,
                        ProcessedMessage.consumer_name == CONSUMER_NAME,
                    )
                )
        await dispose_engine()
