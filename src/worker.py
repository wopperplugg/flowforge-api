import asyncio 
import structlog
from src.database import async_session_maker
from src.infrastructure.logging import configure_logging
from src.outbox.repository import OutboxRepository
from src.webhooks.delivery import deliver_webhooks_for_outbox_event

configure_logging()
logger = structlog.get_logger(__name__)

async def handle_outbox_event(
        event_id: str, 
        event_type: str, 
        payload: dict[str, object],
) -> None:
    logger.info("outbox_event_handled", event_type=event_type, payload=payload)

async def process_outbox_once(batch_size: int = 25) -> int:
    async with async_session_maker() as session:
        repository = OutboxRepository(session)
        async with session.begin():
            events = await repository.claim_pending(batch_size)

        processed = 0
        for event in events:
            try: 
                await handle_outbox_event(str(event.id), event.event_type, event.payload)
                async with session.begin():
                    await deliver_webhooks_for_outbox_event(
                        session,
                        event_id=event.id,
                        event_type=event.event_type,
                        payload=event.payload,
                    )
                    await repository.mark_processed(event)
            except Exception as exc:
                async with session.begin():
                    await repository.mark_failed_or_retry(event, str(exc))
            else: 
                processed += 1
            
        return processed

async def main() -> None:
    logger.info("worker_started")
    while True:
        processed = await process_outbox_once()
        await asyncio.sleep(1 if processed else 5)

if __name__ == "__main__":
    asyncio.run(main())