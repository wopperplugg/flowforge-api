import asyncio
import signal

import structlog
from opentelemetry import trace
from prometheus_client import start_http_server

from src.config import settings
from src.database import async_session_maker, dispose_engine, engine
from src.infrastructure.logging import configure_logging
from src.infrastructure.metrics import (
    OUTBOX_EVENTS_PUBLISHED_TOTAL,
    OUTBOX_PENDING_EVENTS,
    OUTBOX_PUBLISH_FAILURES_TOTAL,
)
from src.infrastructure.tracing import (
    configure_tracing,
    instrument_sqlalchemy,
    shutdown_tracing,
)
from src.messaging.contracts import OutboxMessage
from src.messaging.publisher import RabbitMQPublisher
from src.outbox.models import OutboxEvent
from src.outbox.repository import OutboxRepository

configure_logging()
configure_tracing(
    service_name=f"{settings.otel_service_name}-outbox-worker",
    service_version=settings.app_version,
    deployment_environment=settings.app_env,
    endpoint=settings.otel_exporter_otlp_endpoint,
    enabled=settings.otel_enabled,
    insecure=settings.otel_exporter_otlp_insecure,
)
instrument_sqlalchemy(engine, enabled=settings.otel_enabled)
logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


def build_outbox_message(event: OutboxEvent) -> OutboxMessage:
    correlation_id = event.correlation_id or event.id

    return OutboxMessage(
        event_id=event.id,
        event_type=event.event_type,
        event_version=event.event_version or 1,
        correlation_id=correlation_id,
        causation_id=event.causation_id,
        organization_id=event.organization_id,
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        occurred_at=event.created_at,
        payload=event.payload,
    )


async def process_outbox_once(
    publisher: RabbitMQPublisher,
    batch_size: int = 25,
) -> int:
    async with async_session_maker() as session:
        repository = OutboxRepository(session)

        async with session.begin():
            pending_events = await repository.count_pending()
            events = await repository.claim_pending(batch_size)

        OUTBOX_PENDING_EVENTS.set(pending_events)

        processed = 0

        for event in events:
            with tracer.start_as_current_span(
                "outbox.publish",
                attributes={
                    "flowforge.event_id": str(event.id),
                    "flowforge.event_type": event.event_type,
                    "flowforge.aggregate_type": event.aggregate_type,
                },
            ):
                try:
                    message = build_outbox_message(event)
                    await publisher.publish(message)

                    async with session.begin():
                        await repository.mark_processed(event)

                except Exception as exc:
                    logger.exception(
                        "outbox_publish_failed",
                        event_id=str(event.id),
                        event_type=event.event_type,
                        correlation_id=str(event.correlation_id),
                        error=str(exc),
                    )
                    OUTBOX_PUBLISH_FAILURES_TOTAL.labels(
                        event_type=event.event_type,
                    ).inc()

                    async with session.begin():
                        await repository.mark_failed_or_retry(
                            event,
                            str(exc),
                        )

                else:
                    processed += 1
                    OUTBOX_EVENTS_PUBLISHED_TOTAL.labels(
                        event_type=event.event_type,
                    ).inc()

                    logger.info(
                        "outbox_event_published",
                        event_id=str(event.id),
                        event_type=event.event_type,
                        correlation_id=str(event.correlation_id),
                    )

        return processed


def install_shutdown_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()

    def request_shutdown() -> None:
        logger.info("outbox_publisher_shutdown_requested")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, request_shutdown)


async def run_outbox_loop(
    publisher: RabbitMQPublisher,
    stop_event: asyncio.Event,
    *,
    batch_size: int,
    active_poll_interval: float,
    idle_poll_interval: float,
) -> None:
    while not stop_event.is_set():
        try:
            processed = await process_outbox_once(
                publisher,
                batch_size=batch_size,
            )
        except Exception:
            logger.exception("outbox_batch_failed")
            processed = 0

        timeout = active_poll_interval if processed else idle_poll_interval

        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=timeout,
            )
        except TimeoutError:
            pass


async def main() -> None:
    stop_event = asyncio.Event()
    install_shutdown_handlers(stop_event)

    start_http_server(settings.outbox_metrics_port)
    logger.info("outbox_publisher_started")

    async with RabbitMQPublisher(
        str(settings.rabbitmq_dsn),
    ) as publisher:
        try:
            await run_outbox_loop(
                publisher,
                stop_event,
                batch_size=settings.outbox_batch_size,
                active_poll_interval=settings.outbox_active_poll_interval,
                idle_poll_interval=settings.outbox_idle_poll_interval,
            )
        finally:
            await dispose_engine()
            shutdown_tracing()

    logger.info("outbox_publisher_stopped")


if __name__ == "__main__":
    asyncio.run(main())
