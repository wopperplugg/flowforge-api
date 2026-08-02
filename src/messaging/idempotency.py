from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.messaging.models import ProcessedMessage


async def was_processed(
    session: AsyncSession,
    *,
    message_id: UUID,
    consumer_name: str,
) -> bool:
    statement = select(ProcessedMessage.message_id).where(
        ProcessedMessage.message_id == message_id,
        ProcessedMessage.consumer_name == consumer_name,
    )
    return await session.scalar(statement) is not None


def mark_processed(
    session: AsyncSession,
    *,
    message_id: UUID,
    consumer_name: str,
) -> None:
    session.add(
        ProcessedMessage(
            message_id=message_id,
            consumer_name=consumer_name,
        )
    )
