from datetime import datetime
from typing import Generic, TypeVar
from zoneinfo import ZoneInfo

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, field_serializer, Field

T = TypeVar("T")

class BaseSchema(BaseModel):
    """
    базовая схема проекта
    """
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )

class TimestampSchema(BaseSchema):
    """
    базовая схема для сущностей с created_at and updated_at
    """
    created_at: datetime
    updated_at: datetime

class ErrorPayload(BaseSchema):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class ErrorResponse(BaseSchema):
    error: ErrorPayload
    request_id: str

class PaginatedResponse[T](BaseSchema):
    items: list[T]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)