import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.enums import UserRole
from src.common.security import PASSWORD_ALGORITHM, hash_password
from src.users.exceptions import UserAlreadyExistsError, UserNotFoundError
from src.users.models import User, build_user
from src.users.repository import UserRepository
from src.users.schemas import UserCreate


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = UserRepository(session)

    async def create_user(self, data: UserCreate) -> User:
        email = data.email.lower()
        username = data.username

        try:
            async with self.session.begin():
                existing_email = await self.repository.get_by_email(email)
                existing_username = await self.repository.get_by_username(username)
                if existing_email is not None or existing_username is not None:
                    raise UserAlreadyExistsError()

                user = build_user(
                    email=email,
                    username=username,
                    hashed_password=hash_password(data.password),
                    password_algorithm=PASSWORD_ALGORITHM,
                    role=UserRole.USER,
                    is_active=True,
                )
                return await self.repository.add(user)
        except IntegrityError as exc:
            raise UserAlreadyExistsError() from exc

    async def get_user(self, user_id: uuid.UUID) -> User:
        user = await self.repository.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError()
        return user
