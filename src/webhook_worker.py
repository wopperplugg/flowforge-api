import asyncio
import logging

import aio_pika
from aio_pika.abc import AbstractIncomingMessage
from pydantic import ValidationError

from src.config import settings
from src.messaging.contracts import OutboxMessage
from src.messaging.topology import (
    WEBHOOK_QUEUE,
    declare_webhook_topology,
)

logger = logging.getLogger(__name__)


async def process_message(message: AbstractIncomingMessage) -> None:
    try:
        event = OutboxMessage.model_validate_json(message.body)
    except ValidationError:
        logger.exception("Invalid RabbitMQ message")
        await message.reject(requeue=False)
        return

    logger.info(
        "Webhook event received",
        extra={
            "event_id": str(event.event_id),
            "event_type": event.event_type,
        },
    )

    await message.ack()


async def run_worker() -> None:
    connection = await aio_pika.connect_robust(
        str(settings.rabbitmq_dsn),
    )
    await declare_webhook_topology(connection)
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=10)

    queue = await channel.get_queue(
        WEBHOOK_QUEUE,
        ensure=True,
    )

    logger.info("Webhook worker started")

    try:
        await queue.consume(process_message)
        await asyncio.Future()
    finally:
        await channel.close()
        await connection.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
