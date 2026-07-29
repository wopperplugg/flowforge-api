from aio_pika import ExchangeType
from aio_pika.abc import AbstractChannel, AbstractRobustConnection

EVENTS_EXCHANGE = "flowforge.events"
DEAD_LETTER_EXCHANGE = "flowforge.dlx"
WEBHOOKS_QUEUE = "webhooks.events"
WEBHOOKS_DLQ = "webhooks.events.dlq"


async def declare_webhook_topology(connection: AbstractRobustConnection) -> None:
    channel: AbstractChannel = await connection.channel()

    try:
        events_exchange = await channel.declare_exchange(
            EVENTS_EXCHANGE,
            ExchangeType.TOPIC,
            durable=True,
        )

        dead_letter_exchange = await channel.declare_exchange(
            DEAD_LETTER_EXCHANGE,
            ExchangeType.FANOUT,
            durable=True,
        )

        webhook_queue = await channel.declare_queue(
            WEBHOOKS_QUEUE,
            durable=True,
            arguments={
                "x-dead-letter-exchange": DEAD_LETTER_EXCHANGE,
                "x-dead-letter-routing-key": WEBHOOKS_DLQ,
            },
        )

        await webhook_queue.bind(events_exchange, routing_key="#")
        webhook_dlq = await channel.declare_queue(
            WEBHOOKS_DLQ,
            durable=True,
        )
        await webhook_dlq.bind(dead_letter_exchange, routing_key=WEBHOOKS_DLQ)
    finally:
        await channel.close()
