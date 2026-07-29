import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class OutboxMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: uuid.UUID
    event_type: str
    aggregate_type: str
    aggregate_id: uuid.UUID
    occurred_at: datetime
    payload: dict[str, object]
