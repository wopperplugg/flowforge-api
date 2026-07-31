import asyncio
import logging
import signal

import aio_pika
from aio_pika.abc import AbstractIncomingMessage
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from src.config import settings
from src.database import async_session_maker
from src.messaging.contracts import OutboxMessage
from src.messaging.topology import (
    WEBHOOK_QUEUE,
    declare_webhook_topology,
)
from src.webhooks.delivery import deliver_webhooks_for_outbox_event

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

    try:
        async with async_session_maker() as session:
            async with session.begin():
                await deliver_webhooks_for_outbox_event(
                    session,
                    event_id=event.event_id,
                    event_type=event.event_type,
                    payload=event.payload,
                )
    except SQLAlchemyError:
        logger.exception(
            "Database error while processing webhook event",
            extra={"event_id": str(event.event_id)},
        )
        await message.reject(requeue=False)
        return
    except Exception:
        logger.exception(
            "Webhook delivery failed",
            extra={"event_id": str(event.event_id)},
        )
        await message.reject(requeue=False)
        return
    await message.ack()

    logger.info(
        "Webhook event processed",
        extra={"event_id": str(event.event_id)},
    )


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

    stop_event = asyncio.Event()

    def ask_exit(sig_name: str) -> None:
        logger.warning(f"Received signal {sig_name}. Initiating graceful shutdown")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, ask_exit, sig.name)

    logger.info("Webhook worker started")

    try:
        await queue.consume(process_message)
        await stop_event.wait()
        logger.info("Stop event received.")
    finally:
        logger.info("Closing channel and connection gracefully...")
        await channel.close()
        await connection.close()
        logger.info("Worker shut down successfully.")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
