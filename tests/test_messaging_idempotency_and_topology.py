import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from aio_pika import ExchangeType

from src.messaging import topology
from src.messaging.idempotency import try_mark_processed


class FakeScalarSession:
    def __init__(self, scalar_result: object) -> None:
        self.scalar_result = scalar_result
        self.statement: object | None = None

    async def scalar(self, statement: object) -> object:
        self.statement = statement
        return self.scalar_result


@pytest.mark.asyncio
async def test_try_mark_processed_returns_true_when_insert_wins() -> None:
    session = FakeScalarSession(uuid.uuid4())

    acquired = await try_mark_processed(
        session,  # type: ignore[arg-type]
        message_id=uuid.uuid4(),
        consumer_name="webhook_worker",
    )

    assert acquired is True
    assert session.statement is not None


@pytest.mark.asyncio
async def test_try_mark_processed_returns_false_for_duplicate() -> None:
    session = FakeScalarSession(None)

    acquired = await try_mark_processed(
        session,  # type: ignore[arg-type]
        message_id=uuid.uuid4(),
        consumer_name="webhook_worker",
    )

    assert acquired is False
    assert session.statement is not None


@pytest.mark.asyncio
async def test_declare_webhook_topology_declares_bindings_and_closes_channel() -> None:
    connection = MagicMock()
    connection.channel = AsyncMock()

    channel = MagicMock()
    channel.declare_exchange = AsyncMock()
    channel.declare_queue = AsyncMock()
    channel.close = AsyncMock()

    events_exchange = MagicMock()
    dead_letter_exchange = MagicMock()
    webhook_queue = MagicMock()
    webhook_queue.bind = AsyncMock()
    dlq = MagicMock()
    dlq.bind = AsyncMock()

    connection.channel.return_value = channel
    channel.declare_exchange.side_effect = [events_exchange, dead_letter_exchange]
    channel.declare_queue.side_effect = [webhook_queue, dlq]

    await topology.declare_webhook_topology(connection)

    channel.declare_exchange.assert_any_await(
        topology.EVENTS_EXCHANGE,
        ExchangeType.TOPIC,
        durable=True,
    )
    channel.declare_exchange.assert_any_await(
        topology.DEAD_LETTER_EXCHANGE,
        ExchangeType.FANOUT,
        durable=True,
    )
    channel.declare_queue.assert_any_await(
        topology.WEBHOOK_QUEUE,
        durable=True,
        arguments={
            "x-dead-letter-exchange": topology.DEAD_LETTER_EXCHANGE,
            "x-dead-letter-routing-key": topology.WEBHOOKS_DLQ,
        },
    )
    channel.declare_queue.assert_any_await(topology.WEBHOOKS_DLQ, durable=True)
    webhook_queue.bind.assert_awaited_once_with(events_exchange, routing_key="#")
    dlq.bind.assert_awaited_once_with(
        dead_letter_exchange,
        routing_key=topology.WEBHOOKS_DLQ,
    )
    channel.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_declare_webhook_topology_closes_channel_on_failure() -> None:
    connection = MagicMock()
    connection.channel = AsyncMock()

    channel = MagicMock()
    channel.declare_exchange = AsyncMock(side_effect=RuntimeError("rabbitmq down"))
    channel.close = AsyncMock()
    connection.channel.return_value = channel

    with pytest.raises(RuntimeError, match="rabbitmq down"):
        await topology.declare_webhook_topology(connection)

    channel.close.assert_awaited_once_with()
