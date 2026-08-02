from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.messaging.models import ProcessedMessage


async def try_mark_processed(
    session: AsyncSession,
    *,
    message_id: UUID,
    consumer_name: str,
) -> bool:
    statement = (
        insert(ProcessedMessage)
        .values(
            message_id=message_id,
            consumer_name=consumer_name,
        )
        .on_conflict_do_nothing(
            index_elements=[
                ProcessedMessage.message_id,
                ProcessedMessage.consumer_name,
            ]
        )
        .returning(ProcessedMessage.message_id)
    )

    inserted_id = await session.scalar(statement)
    return inserted_id is not None
