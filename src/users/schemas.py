from uuid import UUID 
import re
from pydantic import EmailStr, Field, field_validator, model_validator

from src.common.enums import UserRole
from src.common.schemas import BaseSchema, TimestampSchema

USERNAME_PATTERN = r"^[a-zA-Z0-9_.-]+$"
PASSWORD_SPECIAL_CHARS_PATTERN = r"""[!@#$%^&*(),.?":{}| <>]"""

def validate_password_strength(password: str) -> str:
    if not password or password != password.strip():
        raise ValueError("Password must not start or end with whitespace")
    if len(password) < 8:
        raise ValueError("Password must contain at least 8 characters")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase Latin letter")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase Latin letter")
    if not re.search(r"\d", password):
        raise ValueError("Password must contain at least one digit")
    if not re.search(PASSWORD_SPECIAL_CHARS_PATTERN, password):
        raise ValueError("Password must contain at least one special character")
    return password

class UserBase(BaseSchema):
    """
    общие публичные поля пользователя
    """

    email: EmailStr
    username: str = Field(
        min_length=3,
        max_length=64,
        pattern=USERNAME_PATTERN,
        examples=["john_doe"],
    )

    @field_validator("email")
    @classmethod
    def normalize_email(cls, email: EmailStr) -> str:
        return str(email).lower()
    
    @field_validator("username")
    @classmethod
    def normalize_username(cls, username: str) -> str:
        return username.strip()

class UserCreate(UserBase):
    """
    Схема публичной регистрации.
    """
    password: str = Field(
        min_length=8,
        max_length=128,
        examples=["StrongPassword123!"],
    )

    @field_validator("password")
    @classmethod
    def validate_password(cls, password: str) -> str:
        return validate_password_strength(password)
    
class UserRead(UserBase, TimestampSchema):
    """
    публичное представление пользователя
    """

    id: UUID
    email: EmailStr
    username: str
    is_active: bool
    role: UserRole

class UserResponse(UserRead):
    pass

class UserShortRead(BaseSchema):
    """
    краткая схема для вложенных обьектов
    """
    id: UUID
    username: str

class UserProfileUpdate(BaseSchema):
    """
    поля которые пользователь может изменить самостоятельно
    """

    email: EmailStr | None = None
    username: str | None = Field(
        min_length=3,
        max_length=64,
        pattern=r"[a-zA-Z0-9_-]+$",   
    )
    @field_validator("email")
    @classmethod
    def normalize_email(cls, email: EmailStr | None) -> str | None:
        if email is None:
            return None
        
        return str(email).lower()
    
    @field_validator("username")
    @classmethod
    def normalize_username(cls, username: str | None) -> str | None:
        if username is None:
            return None
        
        return str(username).strip()
    
    @model_validator(mode="after")
    def ensure_at_least_one_field(self) -> "UserProfileUpdate":
        if self.email is None and self.username is None:
            raise ValueError("все поля должны быть заполнены")
        return self
    
class UserPasswordChange(BaseSchema):
    """
    Смена пароля авторизованным пользователем
    """

    current_password: str = Field(
        min_length=8,
        max_length=128,
    )
    new_password: str = Field(
        min_length=8,
        max_length=128,
    )

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, password: str) -> str:
        return validate_password_strength(password)
    
    @model_validator(mode="after")
    def passwords_must_be_different(self) -> "UserPasswordChange":
        if self.current_password == self.new_password:
            raise ValueError(
                "новый пароль должен отличаться от предыдущего"
            )
        return self
    
class UserAdminUpdate(BaseSchema):
    """
    поля которые может изменять только системный администратор
    """
    role: UserRole | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def ensure_at_least_one_field(self) -> "UserAdminUpdate":
        if self.role is None and self.is_active is None:
            raise ValueError("все поля должны быть заполнены")
        
        return self
    
class UserFilterParams(BaseSchema):
    """
    фильтрация пользователей в административном endpoint
    """
    email: EmailStr | None = None
    username: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
    )
    role: UserRole | None = None
    is_active: bool | None = None