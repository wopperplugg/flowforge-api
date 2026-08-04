from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from src.messaging.contracts import OutboxMessage
from src.messaging.retry import RETRY_HEADERS
from src.messaging.topology import (
    DLX_EXCHANGE,
    RETRY_EXCHANGE,
    WEBHOOK_DLQ_ROUTING_KEY,
    WEBHOOK_QUEUE,
    WEBHOOK_RETRY_10S_ROUTING_KEY,
    declare_webhook_topology,
)
from src.webhook_worker import process_message, run_worker
from src.webhooks.exceptions import RetryableWebhookError


@pytest.fixture
def outbox_message() -> OutboxMessage:
    return OutboxMessage(
        event_id=uuid4(),
        event_type="task.created",
        correlation_id=uuid4(),
        aggregate_type="task",
        aggregate_id=uuid4(),
        occurred_at=datetime.now(UTC),
        payload={
            "task_id": str(uuid4()),
            "title": "Test webhook consumer",
        },
    )


@pytest.fixture
def valid_message_body(outbox_message: OutboxMessage) -> bytes:
    return outbox_message.model_dump_json().encode("utf-8")


@pytest.fixture
def legacy_message_body() -> bytes:
    event = OutboxMessage(
        event_id=uuid4(),
        event_type="task.created",
        aggregate_type="task",
        aggregate_id=uuid4(),
        occurred_at=datetime.now(UTC),
        payload={
            "task_id": str(uuid4()),
            "title": "Test webhook consumer",
        },
    )

    return event.model_dump_json().encode("utf-8")


def create_session_maker_mock() -> tuple[
    MagicMock,
    MagicMock,
]:
    transaction_context = MagicMock()
    transaction_context.__aenter__ = AsyncMock(
        return_value=None,
    )
    transaction_context.__aexit__ = AsyncMock(
        return_value=None,
    )

    session = MagicMock()
    session.begin.return_value = transaction_context
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = uuid4()
    session.execute = AsyncMock(return_value=execute_result)
    session.add = MagicMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(
        return_value=session,
    )
    session_context.__aexit__ = AsyncMock(
        return_value=None,
    )

    session_maker = MagicMock(
        return_value=session_context,
    )

    return session_maker, session


def create_message(body: bytes) -> MagicMock:
    message = MagicMock()
    message.body = body
    message.headers = {}
    message.message_id = str(uuid4())
    message.correlation_id = None
    message.content_type = "application/json"
    message.ack = AsyncMock()
    message.reject = AsyncMock()

    retry_exchange = MagicMock()
    retry_exchange.publish = AsyncMock()

    channel = MagicMock()
    channel.get_exchange = AsyncMock(return_value=retry_exchange)
    message.channel = channel

    return message


@pytest.mark.asyncio
async def test_process_message_delivers_and_acknowledges_valid_event(
    valid_message_body: bytes,
) -> None:
    message = create_message(valid_message_body)
    session_maker, session = create_session_maker_mock()

    delivery_mock = AsyncMock()

    with (
        patch(
            "src.webhook_worker.async_session_maker",
            session_maker,
        ),
        patch(
            "src.webhook_worker.deliver_webhooks_for_outbox_event",
            new=delivery_mock,
        ),
    ):
        await process_message(message)

    delivery_mock.assert_awaited_once()
    session.execute.assert_awaited_once()

    delivery_call = delivery_mock.await_args

    assert delivery_call is not None
    assert delivery_call.args[0] is session
    assert delivery_call.kwargs["event_type"] == "task.created"

    message.ack.assert_awaited_once_with()
    message.reject.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_message_passes_event_data_to_delivery(
    valid_message_body: bytes,
) -> None:
    message = create_message(valid_message_body)
    session_maker, session = create_session_maker_mock()

    delivery_mock = AsyncMock()

    expected_event = OutboxMessage.model_validate_json(
        valid_message_body,
    )

    with (
        patch(
            "src.webhook_worker.async_session_maker",
            session_maker,
        ),
        patch(
            "src.webhook_worker.deliver_webhooks_for_outbox_event",
            new=delivery_mock,
        ),
    ):
        await process_message(message)

    delivery_mock.assert_awaited_once_with(
        session,
        event_id=expected_event.event_id,
        event_type=expected_event.event_type,
        payload=expected_event.payload,
        correlation_id=expected_event.correlation_id,
    )


@pytest.mark.asyncio
async def test_process_message_retries_failed_delivery(
    outbox_message: OutboxMessage,
) -> None:
    message = create_message(outbox_message.model_dump_json().encode("utf-8"))
    session_maker, _ = create_session_maker_mock()

    delivery_mock = AsyncMock(
        side_effect=RetryableWebhookError("Endpoint unavailable"),
    )

    with (
        patch(
            "src.webhook_worker.async_session_maker",
            session_maker,
        ),
        patch(
            "src.webhook_worker.deliver_webhooks_for_outbox_event",
            new=delivery_mock,
        ),
    ):
        await process_message(message)

    delivery_mock.assert_awaited_once()
    message.channel.get_exchange.assert_awaited_once_with(
        RETRY_EXCHANGE,
        ensure=True,
    )
    retry_exchange = message.channel.get_exchange.return_value
    retry_exchange.publish.assert_awaited_once()
    assert retry_exchange.publish.await_args.kwargs["routing_key"] == (
        WEBHOOK_RETRY_10S_ROUTING_KEY
    )
    retry_message = retry_exchange.publish.await_args.args[0]
    assert retry_message.correlation_id == str(outbox_message.correlation_id)
    message.ack.assert_awaited_once_with()
    message.reject.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_message_retries_legacy_event_with_event_id_correlation(
    legacy_message_body: bytes,
) -> None:
    message = create_message(legacy_message_body)
    session_maker, _ = create_session_maker_mock()
    expected_event = OutboxMessage.model_validate_json(legacy_message_body)

    delivery_mock = AsyncMock(
        side_effect=RetryableWebhookError("Endpoint unavailable"),
    )

    with (
        patch(
            "src.webhook_worker.async_session_maker",
            session_maker,
        ),
        patch(
            "src.webhook_worker.deliver_webhooks_for_outbox_event",
            new=delivery_mock,
        ),
    ):
        await process_message(message)

    retry_exchange = message.channel.get_exchange.return_value
    retry_message = retry_exchange.publish.await_args.args[0]
    assert retry_message.correlation_id == str(expected_event.event_id)
    message.ack.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_process_message_rejects_failed_delivery_after_max_retries(
    valid_message_body: bytes,
) -> None:
    message = create_message(valid_message_body)
    message.headers = {RETRY_HEADERS: 3}
    session_maker, _ = create_session_maker_mock()

    delivery_mock = AsyncMock(
        side_effect=RetryableWebhookError("Endpoint unavailable"),
    )

    with (
        patch(
            "src.webhook_worker.async_session_maker",
            session_maker,
        ),
        patch(
            "src.webhook_worker.deliver_webhooks_for_outbox_event",
            new=delivery_mock,
        ),
    ):
        await process_message(message)

    delivery_mock.assert_awaited_once()
    message.channel.get_exchange.assert_not_awaited()
    message.reject.assert_awaited_once_with(requeue=False)
    message.ack.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_message_acknowledges_duplicate_without_delivery(
    valid_message_body: bytes,
) -> None:
    message = create_message(valid_message_body)
    session_maker, session = create_session_maker_mock()
    session.execute.return_value.scalar_one_or_none.return_value = None

    delivery_mock = AsyncMock()

    with (
        patch(
            "src.webhook_worker.async_session_maker",
            session_maker,
        ),
        patch(
            "src.webhook_worker.deliver_webhooks_for_outbox_event",
            new=delivery_mock,
        ),
    ):
        await process_message(message)

    delivery_mock.assert_not_awaited()
    session.execute.assert_awaited_once()
    message.ack.assert_awaited_once_with()
    message.reject.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_message_retries_database_error_before_delivery(
    valid_message_body: bytes,
) -> None:
    message = create_message(valid_message_body)
    session_maker, session = create_session_maker_mock()
    session.execute.side_effect = SQLAlchemyError("database unavailable")

    delivery_mock = AsyncMock()

    with (
        patch(
            "src.webhook_worker.async_session_maker",
            session_maker,
        ),
        patch(
            "src.webhook_worker.deliver_webhooks_for_outbox_event",
            new=delivery_mock,
        ),
    ):
        await process_message(message)

    delivery_mock.assert_not_awaited()
    message.channel.get_exchange.assert_awaited_once_with(
        RETRY_EXCHANGE,
        ensure=True,
    )
    message.ack.assert_awaited_once_with()
    message.reject.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_message_rejects_invalid_event() -> None:
    message = create_message(
        b'{"invalid": "payload"}',
    )

    with (
        patch(
            "src.webhook_worker.async_session_maker",
        ) as session_maker,
        patch(
            "src.webhook_worker.deliver_webhooks_for_outbox_event",
        ) as delivery_mock,
    ):
        await process_message(message)

    message.reject.assert_awaited_once_with(
        requeue=False,
    )
    message.ack.assert_not_awaited()

    session_maker.assert_not_called()
    delivery_mock.assert_not_called()


@pytest.mark.asyncio
async def test_process_message_rejects_invalid_json() -> None:
    message = create_message(b"not-json")

    with (
        patch(
            "src.webhook_worker.async_session_maker",
        ) as session_maker,
        patch(
            "src.webhook_worker.deliver_webhooks_for_outbox_event",
        ) as delivery_mock,
    ):
        await process_message(message)

    message.reject.assert_awaited_once_with(
        requeue=False,
    )
    message.ack.assert_not_awaited()

    session_maker.assert_not_called()
    delivery_mock.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_topology_configures_dlq() -> None:
    channel = MagicMock()
    channel.close = AsyncMock()
    channel.declare_exchange = AsyncMock()
    channel.declare_queue = AsyncMock()

    events_exchange = MagicMock()
    retry_exchange = MagicMock()
    dlx_exchange = MagicMock()
    channel.declare_exchange.side_effect = [
        events_exchange,
        retry_exchange,
        dlx_exchange,
    ]

    webhook_queue = MagicMock()
    retry_10s_queue = MagicMock()
    retry_60s_queue = MagicMock()
    retry_300s_queue = MagicMock()
    webhook_dlq = MagicMock()
    for queue in (
        webhook_queue,
        retry_10s_queue,
        retry_60s_queue,
        retry_300s_queue,
        webhook_dlq,
    ):
        queue.bind = AsyncMock()

    channel.declare_queue.side_effect = [
        webhook_queue,
        retry_10s_queue,
        retry_60s_queue,
        retry_300s_queue,
        webhook_dlq,
    ]

    connection = MagicMock()
    connection.channel = AsyncMock(return_value=channel)

    await declare_webhook_topology(connection)

    channel.declare_queue.assert_any_await(
        WEBHOOK_QUEUE,
        durable=True,
        arguments={
            "x-dead-letter-exchange": DLX_EXCHANGE,
            "x-dead-letter-routing-key": WEBHOOK_DLQ_ROUTING_KEY,
        },
    )
    webhook_dlq.bind.assert_awaited_once_with(
        dlx_exchange,
        routing_key=WEBHOOK_DLQ_ROUTING_KEY,
    )
    channel.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_worker_consumes_until_shutdown_and_closes_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = MagicMock()
    queue.consume = AsyncMock()

    channel = MagicMock()
    channel.set_qos = AsyncMock()
    channel.get_queue = AsyncMock(return_value=queue)
    channel.close = AsyncMock()

    connection = MagicMock()
    connection.channel = AsyncMock(return_value=channel)
    connection.close = AsyncMock()

    async def fake_connect_robust(dsn: str) -> MagicMock:
        return connection

    async def fake_declare_topology(connection_arg: object) -> None:
        assert connection_arg is connection

    def fake_install_shutdown_handlers(stop_event: object) -> None:
        return None

    async def fake_consume_until_stopped(
        queue_arg: object,
        stop_event: object,
    ) -> None:
        assert queue_arg is queue
        assert stop_event is not None

    monkeypatch.setattr(
        "src.webhook_worker.aio_pika.connect_robust",
        fake_connect_robust,
    )
    monkeypatch.setattr(
        "src.webhook_worker.declare_webhook_topology",
        fake_declare_topology,
    )
    monkeypatch.setattr(
        "src.webhook_worker.install_shutdown_handlers",
        fake_install_shutdown_handlers,
    )
    monkeypatch.setattr(
        "src.webhook_worker.consume_until_stopped",
        fake_consume_until_stopped,
    )
    start_metrics_server = MagicMock()
    monkeypatch.setattr(
        "src.webhook_worker.start_http_server",
        start_metrics_server,
    )

    await run_worker()

    start_metrics_server.assert_called_once()
    channel.set_qos.assert_awaited_once_with(prefetch_count=10)
    channel.get_queue.assert_awaited_once_with(
        WEBHOOK_QUEUE,
        ensure=True,
    )
    channel.close.assert_awaited_once()
    connection.close.assert_awaited_once()
