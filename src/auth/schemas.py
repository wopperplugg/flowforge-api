import uuid 
from datetime import datetime
from pydantic import EmailStr, Field, field_validator
from src.common.schemas import BaseSchema

class LoginRequest(BaseSchema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, email: EmailStr) -> str:
        return str(email).lower()
    
class TokenResponse(BaseSchema):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int

class RefreshTokenRequest(BaseSchema):
    refresh_token: str = Field(min_length=1)

class LogoutResponse(BaseSchema):
    revoked: bool

class RefreshSessionResponse(BaseSchema):
    id: uuid.UUID
    family_id: uuid.UUID
    expires_at: datetime
    created_at: datetime
    last_used_at: datetime | None
    user_agent: str | None
    ip_address: str | None