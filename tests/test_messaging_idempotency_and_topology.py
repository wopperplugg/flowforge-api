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
    retry_exchange = MagicMock()
    dead_letter_exchange = MagicMock()
    webhook_queue = MagicMock()
    webhook_queue.bind = AsyncMock()
    retry_10s_queue = MagicMock()
    retry_10s_queue.bind = AsyncMock()
    retry_60s_queue = MagicMock()
    retry_60s_queue.bind = AsyncMock()
    retry_300s_queue = MagicMock()
    retry_300s_queue.bind = AsyncMock()
    dlq = MagicMock()
    dlq.bind = AsyncMock()

    connection.channel.return_value = channel
    channel.declare_exchange.side_effect = [
        events_exchange,
        retry_exchange,
        dead_letter_exchange,
    ]
    channel.declare_queue.side_effect = [
        webhook_queue,
        retry_10s_queue,
        retry_60s_queue,
        retry_300s_queue,
        dlq,
    ]

    await topology.declare_webhook_topology(connection)

    channel.declare_exchange.assert_any_await(
        topology.EVENTS_EXCHANGE,
        ExchangeType.TOPIC,
        durable=True,
    )
    channel.declare_exchange.assert_any_await(
        topology.RETRY_EXCHANGE,
        ExchangeType.DIRECT,
        durable=True,
    )
    channel.declare_exchange.assert_any_await(
        topology.DLX_EXCHANGE,
        ExchangeType.DIRECT,
        durable=True,
    )
    channel.declare_queue.assert_any_await(
        topology.WEBHOOK_QUEUE,
        durable=True,
        arguments={
            "x-dead-letter-exchange": topology.DLX_EXCHANGE,
            "x-dead-letter-routing-key": topology.WEBHOOK_DLQ_ROUTING_KEY,
        },
    )
    channel.declare_queue.assert_any_await(
        topology.WEBHOOK_RETRY_10S_QUEUE,
        durable=True,
        arguments={
            "x-message-ttl": 10_000,
            "x-dead-letter-exchange": topology.EVENTS_EXCHANGE,
            "x-dead-letter-routing-key": topology.WEBHOOK_ROUTING_KEY,
        },
    )
    channel.declare_queue.assert_any_await(
        topology.WEBHOOK_RETRY_60S_QUEUE,
        durable=True,
        arguments={
            "x-message-ttl": 60_000,
            "x-dead-letter-exchange": topology.EVENTS_EXCHANGE,
            "x-dead-letter-routing-key": topology.WEBHOOK_ROUTING_KEY,
        },
    )
    channel.declare_queue.assert_any_await(
        topology.WEBHOOK_RETRY_300S_QUEUE,
        durable=True,
        arguments={
            "x-message-ttl": 300_000,
            "x-dead-letter-exchange": topology.EVENTS_EXCHANGE,
            "x-dead-letter-routing-key": topology.WEBHOOK_ROUTING_KEY,
        },
    )
    channel.declare_queue.assert_any_await(topology.WEBHOOKS_DLQ, durable=True)
    webhook_queue.bind.assert_any_await(events_exchange, routing_key="task.*")
    webhook_queue.bind.assert_any_await(
        events_exchange,
        routing_key=topology.WEBHOOK_ROUTING_KEY,
    )
    retry_10s_queue.bind.assert_awaited_once_with(
        retry_exchange,
        routing_key=topology.WEBHOOK_RETRY_10S_ROUTING_KEY,
    )
    retry_60s_queue.bind.assert_awaited_once_with(
        retry_exchange,
        routing_key=topology.WEBHOOK_RETRY_60S_ROUTING_KEY,
    )
    retry_300s_queue.bind.assert_awaited_once_with(
        retry_exchange,
        routing_key=topology.WEBHOOK_RETRY_300S_ROUTING_KEY,
    )
    dlq.bind.assert_awaited_once_with(
        dead_letter_exchange,
        routing_key=topology.WEBHOOK_DLQ_ROUTING_KEY,
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
