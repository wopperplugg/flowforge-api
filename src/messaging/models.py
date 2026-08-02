from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class ProcessedMessage(Base):
    __tablename__ = "processed_messages"

    message_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    consumer_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
