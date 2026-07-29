import uuid

from pydantic import Field, field_validator

from src.common.enums import OrganizationRole
from src.common.schemas import BaseSchema, TimestampSchema


class OrganizationCreate(BaseSchema):
    name: str = Field(min_length=2, max_length=120)
    slug: str = Field(
        min_length=3, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$"
    )

    @field_validator("slug", mode="before")
    @classmethod
    def normalize_slug(cls, slug: str) -> str:
        if isinstance(slug, str):
            return slug.strip().lower()
        return slug


class OrganizationResponse(TimestampSchema):
    id: uuid.UUID
    name: str
    slug: str


class OrganizationMemberResponse(TimestampSchema):
    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID
    role: OrganizationRole


class OrganizationMemberUpdate(BaseSchema):
    role: OrganizationRole
