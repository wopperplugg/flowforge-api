import uuid


from pydantic import AnyUrl, Field, field_validator
from src.common.schemas import BaseSchema, TimestampSchema

class WebhookCreate(BaseSchema):
    url: AnyUrl
    event_types: list[str] = Field(min_length=1, max_length=50)

    @field_validator("event_types")
    @classmethod
    def normalize_event_types(cls, event_types: list[str]) -> list[str]:
        normalized = [event_type.strip() for event_type in event_types]
        if any(not event_type for event_type in normalized):
            raise ValueError("Event types must not be empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Event types must be unique")
        return normalized
    
class WebhookResponse(TimestampSchema):
    id: uuid.UUID
    organization_id: uuid.UUID
    url: str
    event_types: list[str]
    is_active: bool

class WebhookCreateResponse(WebhookResponse):
    secret: str