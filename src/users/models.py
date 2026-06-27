import uuid

from sqlalchemy import Boolean, Index, String, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import ENUM
from src.common.enums import UserRole
from src.common.models import TimestampMixin, UUIDPrimaryKeyMixin
from src.database import Base

class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        UniqueConstraint("username", name="uq_users_username"),
        Index("ix_users_role", "role"),
    )

    email: Mapped[str] = mapped_column(
        String(320),
        nullable=False,
    )
    username: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    hashed_password: Mapped[str] = mapped_column(
        String(250),
        nullable=False,
    )
    password_algorithm: Mapped[str] = mapped_column(
        String(50),
        server_default="argon2id",
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        server_default=true(),
        nullable=False,
    )
    role: Mapped[UserRole] = mapped_column(
        ENUM(UserRole, name="user_role", native_enum=True, create_type=False, values_callable=lambda enum_cls: [item.value for item in enum_cls]),
        server_default=UserRole.USER.value,
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"User(id={self.id!s}, email={self.email!r})"
    

def build_user(
        *, 
        email: str,
        username: str,
        hashed_password: str,
        password_algorithm: str,
        role: UserRole = UserRole.USER,
        is_active: bool = True,
) -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        username=username,
        hashed_password=hashed_password,
        password_algorithm=password_algorithm,
        role=role,
        is_active=is_active,
    )