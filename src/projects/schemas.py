import uuid

from pydantic import Field, field_validator, model_validator

from src.common.schemas import BaseSchema, TimestampSchema


class ProjectCreate(BaseSchema):
    name: str = Field(min_length=2, max_length=120)
    key: str = Field(min_length=2, max_length=20, pattern=r"^[A-Z][A-Z0-9]*$")
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("key", mode="before")
    @classmethod
    def normalize_key(cls, key: str) -> str:
        return key.upper()


class ProjectUpdate(BaseSchema):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def ensure_at_least_one_field(self) -> "ProjectUpdate":
        if self.name is None and self.description is None:
            raise ValueError("At least one project field must be provided")
        return self


class ProjectResponse(TimestampSchema):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    key: str
    description: str | None
