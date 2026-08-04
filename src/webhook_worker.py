import asyncio
import logging
import signal
import time
from collections.abc import Awaitable, Callable
from typing import Protocol, cast

import aio_pika
from aio_pika.abc import AbstractIncomingMessage
from prometheus_client import start_http_server
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from src.config import settings
from src.database import async_session_maker
from src.infrastructure.metrics import (
    WEBHOOK_DLQ_TOTAL,
    WEBHOOK_MESSAGES_PROCESSED_TOTAL,
    WEBHOOK_PROCESSING_DURATION_SECONDS,
    WEBHOOK_RETRIES_TOTAL,
)
from src.messaging.contracts import OutboxMessage
from src.messaging.idempotency import try_mark_processed
from src.messaging.retry import RetryChannel, get_retry_count, publish_retry
from src.messaging.topology import (
    WEBHOOK_QUEUE,
    declare_webhook_topology,
)
from src.webhooks.delivery import deliver_webhooks_for_outbox_event
from src.webhooks.exceptions import NonRetryableWebhookError, RetryableWebhookError

logger = logging.getLogger(__name__)

CONSUMER_NAME = "webhook-worker"


class ConsumerQueue(Protocol):
    async def consume(
        self,
        callback: Callable[[AbstractIncomingMessage], Awaitable[None]],
    ) -> object: ...


async def handle_retry(
    message: AbstractIncomingMessage,
    *,
    event_id: str,
    correlation_id: str | None,
) -> None:
    retry_number = get_retry_count(message.headers or {}) + 1
    published = await publish_retry(
        cast(RetryChannel, message.channel),
        message,
        correlation_id=correlation_id,
    )

    if published:
        WEBHOOK_RETRIES_TOTAL.labels(retry_number=str(retry_number)).inc()
        await message.ack()

        logger.info(
            "Webhook event scheduled for retry",
            extra={"event_id": event_id},
        )
        return

    logger.warning(
        "Webhook event reached max retry attempts, sending to DLQ",
        extra={"event_id": event_id},
    )
    WEBHOOK_DLQ_TOTAL.labels(reason="max_retries").inc()
    await message.reject(requeue=False)


async def process_message(message: AbstractIncomingMessage) -> None:
    started_at = time.perf_counter()
    try:
        event = OutboxMessage.model_validate_json(message.body)
    except ValidationError:
        WEBHOOK_MESSAGES_PROCESSED_TOTAL.labels(
            event_type="invalid",
            result="invalid",
        ).inc()
        logger.exception("Invalid RabbitMQ message")
        await message.reject(requeue=False)
        return

    logger.info(
        "Webhook event received",
        extra={
            "event_id": str(event.event_id),
            "event_type": event.event_type,
            "correlation_id": str(event.correlation_id),
        },
    )

    try:
        async with async_session_maker() as session:
            async with session.begin():
                acquired = await try_mark_processed(
                    session,
                    message_id=event.event_id,
                    consumer_name=CONSUMER_NAME,
                )

                duplicate = not acquired

                if acquired:
                    await deliver_webhooks_for_outbox_event(
                        session,
                        event_id=event.event_id,
                        event_type=event.event_type,
                        payload=event.payload,
                        correlation_id=event.correlation_id,
                    )

    except NonRetryableWebhookError:
        WEBHOOK_MESSAGES_PROCESSED_TOTAL.labels(
            event_type=event.event_type,
            result="non_retryable_error",
        ).inc()
        WEBHOOK_DLQ_TOTAL.labels(reason="non_retryable_error").inc()
        WEBHOOK_PROCESSING_DURATION_SECONDS.labels(
            event_type=event.event_type,
        ).observe(time.perf_counter() - started_at)
        logger.exception(
            "Non-retryable webhook error",
            extra={"event_id": str(event.event_id)},
        )
        await message.reject(requeue=False)
        return

    except (RetryableWebhookError, SQLAlchemyError):
        WEBHOOK_MESSAGES_PROCESSED_TOTAL.labels(
            event_type=event.event_type,
            result="retry",
        ).inc()
        WEBHOOK_PROCESSING_DURATION_SECONDS.labels(
            event_type=event.event_type,
        ).observe(time.perf_counter() - started_at)
        logger.exception(
            "Retryable webhook error",
            extra={"event_id": str(event.event_id)},
        )
        await handle_retry(
            message,
            event_id=str(event.event_id),
            correlation_id=(
                str(event.correlation_id) if event.correlation_id is not None else None
            ),
        )
        return

    except Exception:
        WEBHOOK_MESSAGES_PROCESSED_TOTAL.labels(
            event_type=event.event_type,
            result="error",
        ).inc()
        WEBHOOK_DLQ_TOTAL.labels(reason="unexpected_error").inc()
        WEBHOOK_PROCESSING_DURATION_SECONDS.labels(
            event_type=event.event_type,
        ).observe(time.perf_counter() - started_at)
        logger.exception(
            "Webhook delivery failed",
            extra={"event_id": str(event.event_id)},
        )
        await message.reject(requeue=False)
        return

    await message.ack()

    if duplicate:
        WEBHOOK_MESSAGES_PROCESSED_TOTAL.labels(
            event_type=event.event_type,
            result="duplicate",
        ).inc()
        WEBHOOK_PROCESSING_DURATION_SECONDS.labels(
            event_type=event.event_type,
        ).observe(time.perf_counter() - started_at)
        logger.info(
            "webhook event already processed",
            extra={
                "event_id": str(event.event_id),
                "consumer_name": CONSUMER_NAME,
            },
        )
        return

    WEBHOOK_MESSAGES_PROCESSED_TOTAL.labels(
        event_type=event.event_type,
        result="processed",
    ).inc()
    WEBHOOK_PROCESSING_DURATION_SECONDS.labels(
        event_type=event.event_type,
    ).observe(time.perf_counter() - started_at)
    logger.info(
        "Webhook event processed",
        extra={
            "event_id": str(event.event_id),
            "correlation_id": str(event.correlation_id),
        },
    )


def install_shutdown_handlers(stop_event: asyncio.Event) -> None:
    def ask_exit(sig_name: str) -> None:
        logger.warning(f"Received signal {sig_name}. Initiating graceful shutdown")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, ask_exit, sig.name)


async def consume_until_stopped(
    queue: ConsumerQueue,
    stop_event: asyncio.Event,
) -> None:
    await queue.consume(process_message)
    await stop_event.wait()


async def run_worker() -> None:
    start_http_server(settings.webhook_metrics_port)

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
    install_shutdown_handlers(stop_event)

    logger.info("Webhook worker started")

    try:
        await consume_until_stopped(queue, stop_event)
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
