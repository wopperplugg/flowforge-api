import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OutboxMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: uuid.UUID
    event_type: str
    event_version: int = Field(default=1, ge=1)

    aggregate_type: str
    aggregate_id: uuid.UUID

    correlation_id: uuid.UUID | None = None
    causation_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None

    occurred_at: datetime
    payload: dict[str, object]

    @model_validator(mode="before")
    @classmethod
    def default_correlation_id(
        cls,
        data: Any,
    ) -> Any:
        if isinstance(data, dict) and data.get("correlation_id") is None:
            data = data.copy()
            data["correlation_id"] = data.get("event_id")
        return data
