import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from aio_pika import DeliveryMode, ExchangeType

from src.messaging.contracts import OutboxMessage
from src.messaging.publisher import RabbitMQPublisher


@pytest.fixture
def outbox_message() -> OutboxMessage:
    return OutboxMessage(
        event_id=uuid4(),
        event_type="task.created",
        aggregate_type="task",
        aggregate_id=uuid4(),
        occurred_at=datetime.now(UTC),
        payload={
            "task_id": str(uuid4()),
            "title": "Implement RabbitMQ publisher",
        },
    )


@pytest.mark.asyncio
async def test_connect_declares_durable_topic_exchange() -> None:
    connection = MagicMock()
    connection.is_closed = False
    connection.channel = AsyncMock()

    channel = MagicMock()
    channel.is_closed = False
    channel.declare_exchange = AsyncMock()

    exchange = MagicMock()

    connection.channel.return_value = channel
    channel.declare_exchange.return_value = exchange

    with patch(
        "src.messaging.publisher.aio_pika.connect_robust",
        new=AsyncMock(return_value=connection),
    ) as connect_robust:
        publisher = RabbitMQPublisher("amqp://flowforge:flowforge@localhost:5672/")
        await publisher.connect()

    connect_robust.assert_awaited_once_with(
        "amqp://flowforge:flowforge@localhost:5672/"
    )

    connection.channel.assert_awaited_once_with(publisher_confirms=True)
    channel.declare_exchange.assert_awaited_once_with(
        "flowforge.events",
        ExchangeType.TOPIC,
        durable=True,
    )


@pytest.mark.asyncio
async def test_publish_sends_persistent_message(
    outbox_message: OutboxMessage,
) -> None:
    publisher = RabbitMQPublisher("amqp://flowforge:flowforge@localhost:5672/")

    exchange = MagicMock()
    exchange.publish = AsyncMock()
    publisher._exchange = exchange
    await publisher.publish(outbox_message)
    exchange.publish.assert_awaited_once()
    published_message = exchange.publish.call_args.args[0]
    assert published_message.message_id == str(outbox_message.event_id)
    assert published_message.type == outbox_message.event_type
    assert published_message.timestamp == outbox_message.occurred_at
    assert published_message.delivery_mode == DeliveryMode.PERSISTENT
    assert published_message.content_type == "application/json"
    assert published_message.headers == {
        "event_version": outbox_message.event_version,
        "aggregate_type": outbox_message.aggregate_type,
        "aggregate_id": str(outbox_message.aggregate_id),
        "correlation_id": str(outbox_message.correlation_id),
    }
    assert json.loads(published_message.body) == json.loads(
        outbox_message.model_dump_json()
    )

    exchange.publish.assert_awaited_once_with(
        published_message,
        routing_key=outbox_message.event_type,
        mandatory=True,
    )


@pytest.mark.asyncio
async def test_publish_requires_connection(
    outbox_message: OutboxMessage,
) -> None:
    publisher = RabbitMQPublisher("amqp://flowforge:flowforge@localhost:5672/")

    with pytest.raises(
        RuntimeError,
        match="RabbitMQ publisher is not connected",
    ):
        await publisher.publish(outbox_message)


@pytest.mark.asyncio
async def test_close_closes_channel_and_connection() -> None:
    publisher = RabbitMQPublisher("amqp://flowforge:flowforge@localhost:5672/")

    channel = MagicMock()
    channel.is_closed = False
    channel.close = AsyncMock()

    connection = MagicMock()
    connection.is_closed = False
    connection.close = AsyncMock()

    publisher._channel = channel
    publisher._connection = connection
    publisher._exchange = MagicMock()

    await publisher.close()

    channel.close.assert_awaited_once()
    connection.close.assert_awaited_once()

    assert publisher._channel is None
    assert publisher._connection is None
    assert publisher._exchange is None


@pytest.mark.asyncio
async def test_close_skips_already_closed_channel() -> None:
    publisher = RabbitMQPublisher("amqp://flowforge:flowforge@localhost:5672/")

    channel = MagicMock()
    channel.is_closed = True
    channel.close = AsyncMock()

    connection = MagicMock()
    connection.close = AsyncMock()

    publisher._channel = channel
    publisher._connection = connection

    await publisher.close()

    channel.close.assert_not_awaited()
    connection.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_context_manager_connects_and_closes() -> None:
    publisher = RabbitMQPublisher("amqp://flowforge:flowforge@localhost:5672/")
    publisher.connect = AsyncMock()  # type: ignore[method-assign]
    publisher.close = AsyncMock()  # type: ignore[method-assign]

    async with publisher as entered:
        assert entered is publisher

    publisher.connect.assert_awaited_once_with()
    publisher.close.assert_awaited_once_with()
