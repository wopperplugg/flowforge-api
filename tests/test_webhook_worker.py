from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.messaging.contracts import OutboxMessage
from src.webhook_worker import process_message


@pytest.fixture
def valid_message_body() -> bytes:
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
    session.scalar = AsyncMock(return_value=None)
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
    message.ack = AsyncMock()
    message.reject = AsyncMock()
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
    session.add.assert_called_once()

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
    )


@pytest.mark.asyncio
async def test_process_message_rejects_failed_delivery(
    valid_message_body: bytes,
) -> None:
    message = create_message(valid_message_body)
    session_maker, _ = create_session_maker_mock()

    delivery_mock = AsyncMock(
        side_effect=RuntimeError("Endpoint unavailable"),
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
    message.reject.assert_awaited_once_with(
        requeue=False,
    )
    message.ack.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_message_acknowledges_duplicate_without_delivery(
    valid_message_body: bytes,
) -> None:
    message = create_message(valid_message_body)
    session_maker, session = create_session_maker_mock()
    session.scalar.return_value = uuid4()

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
    session.add.assert_not_called()
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
