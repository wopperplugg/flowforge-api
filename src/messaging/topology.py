from aio_pika import ExchangeType
from aio_pika.abc import AbstractChannel, AbstractRobustConnection

EVENTS_EXCHANGE = "flowforge.events"
RETRY_EXCHANGE = "flowforge.retry"
DLX_EXCHANGE = "flowforge.dlx"

WEBHOOK_QUEUE = "webhooks.events"

WEBHOOK_RETRY_10S_QUEUE = "webhooks.events.retry.10s"
WEBHOOK_RETRY_60S_QUEUE = "webhooks.events.retry.60s"
WEBHOOK_RETRY_300S_QUEUE = "webhooks.events.retry.300s"

WEBHOOKS_DLQ = "webhooks.events.dlq"

WEBHOOK_ROUTING_KEY = "webhooks.events"

WEBHOOK_RETRY_10S_ROUTING_KEY = "webhooks.retry.10s"
WEBHOOK_RETRY_60S_ROUTING_KEY = "webhooks.retry.60s"
WEBHOOK_RETRY_300S_ROUTING_KEY = "webhooks.retry.300s"

WEBHOOK_DLQ_ROUTING_KEY = "webhooks.events.dlq"


async def declare_webhook_topology(
    connection: AbstractRobustConnection,
) -> None:
    channel: AbstractChannel = await connection.channel()

    try:
        events_exchange = await channel.declare_exchange(
            EVENTS_EXCHANGE,
            ExchangeType.TOPIC,
            durable=True,
        )

        retry_exchange = await channel.declare_exchange(
            RETRY_EXCHANGE,
            ExchangeType.DIRECT,
            durable=True,
        )

        dlx_exchange = await channel.declare_exchange(
            DLX_EXCHANGE,
            ExchangeType.DIRECT,
            durable=True,
        )

        webhook_queue = await channel.declare_queue(
            WEBHOOK_QUEUE,
            durable=True,
            arguments={
                "x-dead-letter-exchange": DLX_EXCHANGE,
                "x-dead-letter-routing-key": WEBHOOK_DLQ_ROUTING_KEY,
            },
        )

        await webhook_queue.bind(
            events_exchange,
            routing_key="task.*",
        )

        await webhook_queue.bind(
            events_exchange,
            routing_key=WEBHOOK_ROUTING_KEY,
        )

        retry_10s_queue = await channel.declare_queue(
            WEBHOOK_RETRY_10S_QUEUE,
            durable=True,
            arguments={
                "x-message-ttl": 10_000,
                "x-dead-letter-exchange": EVENTS_EXCHANGE,
                "x-dead-letter-routing-key": WEBHOOK_ROUTING_KEY,
            },
        )

        retry_60s_queue = await channel.declare_queue(
            WEBHOOK_RETRY_60S_QUEUE,
            durable=True,
            arguments={
                "x-message-ttl": 60_000,
                "x-dead-letter-exchange": EVENTS_EXCHANGE,
                "x-dead-letter-routing-key": WEBHOOK_ROUTING_KEY,
            },
        )

        retry_300s_queue = await channel.declare_queue(
            WEBHOOK_RETRY_300S_QUEUE,
            durable=True,
            arguments={
                "x-message-ttl": 300_000,
                "x-dead-letter-exchange": EVENTS_EXCHANGE,
                "x-dead-letter-routing-key": WEBHOOK_ROUTING_KEY,
            },
        )

        await retry_10s_queue.bind(
            retry_exchange,
            routing_key=WEBHOOK_RETRY_10S_ROUTING_KEY,
        )

        await retry_60s_queue.bind(
            retry_exchange,
            routing_key=WEBHOOK_RETRY_60S_ROUTING_KEY,
        )

        await retry_300s_queue.bind(
            retry_exchange,
            routing_key=WEBHOOK_RETRY_300S_ROUTING_KEY,
        )

        webhook_dlq = await channel.declare_queue(
            WEBHOOKS_DLQ,
            durable=True,
        )

        await webhook_dlq.bind(
            dlx_exchange,
            routing_key=WEBHOOK_DLQ_ROUTING_KEY,
        )

    finally:
        await channel.close()
