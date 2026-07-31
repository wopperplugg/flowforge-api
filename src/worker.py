import asyncio

import structlog

from src.config import settings
from src.database import async_session_maker
from src.infrastructure.logging import configure_logging
from src.messaging.contracts import OutboxMessage
from src.messaging.publisher import RabbitMQPublisher
from src.outbox.models import OutboxEvent
from src.outbox.repository import OutboxRepository

configure_logging()
logger = structlog.get_logger(__name__)


def build_outbox_message(event: OutboxEvent) -> OutboxMessage:
    return OutboxMessage(
        event_id=event.id,
        event_type=event.event_type,
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        occurred_at=event.created_at,
        payload=event.payload,
    )


async def process_outbox_once(
    publisher: RabbitMQPublisher, batch_size: int = 25
) -> int:
    async with async_session_maker() as session:
        repository = OutboxRepository(session)

        async with session.begin():
            events = await repository.claim_pending(batch_size)

        processed = 0

        for event in events:
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
                    error=str(exc),
                )

                async with session.begin():
                    await repository.mark_failed_or_retry(
                        event,
                        str(exc),
                    )

            else:
                processed += 1

                logger.info(
                    "outbox_event_published",
                    event_id=str(event.id),
                    event_type=event.event_type,
                )

        return processed


async def main() -> None:
    logger.info("outbox_publisher_started")

    async with RabbitMQPublisher(
        str(settings.rabbitmq_dsn),
    ) as publisher:
        while True:
            processed = await process_outbox_once(publisher)
            await asyncio.sleep(1 if processed else 5)


if __name__ == "__main__":
    asyncio.run(main())
