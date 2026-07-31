from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.messaging.contracts import OutboxMessage
from src.webhook_worker import process_message


@pytest.fixture
def valid_message_body() -> bytes:
    event = OutboxMessage(
        event_id=uuid4(),
        event_type="task.create",
        aggregate_type="task",
        aggregate_id=uuid4(),
        occurred_at=datetime.now(UTC),
        payload={
            "task_id": str(uuid4()),
            "title": "Test webhook consumer",
        },
    )
    return event.model_dump_json().encode("utf-8")


@pytest.mark.asyncio
async def test_process_message_acknowledges_valid_event(
    valid_message_body: bytes,
) -> None:
    message = MagicMock()
    message.body = valid_message_body
    message.ack = AsyncMock()
    message.reject = AsyncMock()

    await process_message(message)

    message.ack.assert_awaited_once_with()
    message.reject.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_message_rejects_invalid_event() -> None:
    message = MagicMock()
    message.body = b'{"invalid": "payload"}'
    message.ack = AsyncMock()
    message.reject = AsyncMock()

    await process_message(message)

    message.reject.assert_awaited_once_with(requeue=False)
    message.ack.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_message_rejects_invalid_json() -> None:
    message = MagicMock()
    message.body = b"not-json"
    message.ack = AsyncMock()
    message.reject = AsyncMock()

    await process_message(message)

    message.reject.assert_awaited_once_with(requeue=False)
    message.ack.assert_not_awaited()
