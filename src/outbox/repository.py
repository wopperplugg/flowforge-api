from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.enums import OutboxStatus
from src.outbox.models import OutboxEvent

class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def claim_pending(self, limit: int) -> list[OutboxEvent]:
        now = datetime.now(UTC)
        statement: Select[tuple[OutboxEvent]] = (
            select(OutboxEvent)
            .where(
                OutboxEvent.status == OutboxStatus.PENDING,
                or_(OutboxEvent.next_attempt_at.is_(None), OutboxEvent.next_attempt_at <= now),
            )
            .order_by(OutboxEvent.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(statement)
        events = list(result.scalars().all())
        for event in events:
            event.status = OutboxStatus.PROCESSING
        await self.session.flush()
        return events
    
    async def mark_processed(self, event: OutboxEvent) -> None:
        event.status = OutboxStatus.PROCESSED
        event.processed_at = datetime.now(UTC)
        event.last_error = None

    async def mark_failed_or_retry(
            self,
            event: OutboxEvent,
            error: str,
            *,
            max_attempts: int = 5,
    ) -> None:
        event.attempts += 1
        event.last_error = error[:2000]
        if event.attempts >= max_attempts:
            event.status = OutboxStatus.FAILED
            return
        delay_seconds = min(300, 2**event.attempts)
        event.status = OutboxStatus.PENDING
        event.next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)