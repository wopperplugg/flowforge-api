import uuid
from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from src.auth.models import RefreshSession
from src.auth.schemas import LoginRequest, RefreshTokenRequest
from src.auth.service import AuthService
from src.common.exceptions import InvalidCredentialsError, InvalidTokenError
from src.users.models import User
from tests.fakes import FakeSession


def make_user(*, active: bool = True) -> User:
    return User(
        id=uuid.uuid4(),
        email="user@example.com",
        username="user",
        hashed_password="hash",
        is_active=active,
    )


class FakeUserRepository:
    def __init__(self, user: User | None) -> None:
        self.user = user

    async def get_by_email(self, email: str) -> User | None:
        return self.user

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        if self.user is None or self.user.id != user_id:
            return None
        return self.user


class FakeRefreshRepository:
    def __init__(self, session: RefreshSession | None = None) -> None:
        self.session = session
        self.added: list[RefreshSession] = []
        self.revoked_users: list[uuid.UUID] = []
        self.revoked_sessions: list[tuple[uuid.UUID, uuid.UUID]] = []
        self.raise_integrity = False

    async def add(self, refresh_session: RefreshSession) -> RefreshSession:
        if self.raise_integrity:
            raise IntegrityError("statement", "params", Exception("duplicate"))
        self.session = refresh_session
        self.added.append(refresh_session)
        return refresh_session

    async def get_by_jti(self, jti: uuid.UUID) -> RefreshSession | None:
        if self.session is None or self.session.jti != jti:
            return None
        return self.session

    async def get_by_jti_for_update(self, jti: uuid.UUID) -> RefreshSession | None:
        return await self.get_by_jti(jti)

    async def revoke_all_for_user(
        self, user_id: uuid.UUID, revoked_at: datetime
    ) -> None:
        self.revoked_users.append(user_id)

    async def list_active_by_user_id(self, user_id: uuid.UUID) -> list[RefreshSession]:
        return [self.session] if self.session is not None else []

    async def revoke_one_for_user(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        revoked_at: datetime,
    ) -> bool:
        self.revoked_sessions.append((session_id, user_id))
        return True

    async def revoke_family(self, family_id: uuid.UUID, revoked_at: datetime) -> None:
        return None


def make_service(
    user: User | None,
    refresh_repository: FakeRefreshRepository | None = None,
) -> tuple[AuthService, FakeRefreshRepository]:
    service = AuthService(FakeSession())  # type: ignore[arg-type]
    repository = refresh_repository or FakeRefreshRepository()
    service.repository = FakeUserRepository(user)  # type: ignore[assignment]
    service.refresh_sessions = repository  # type: ignore[assignment]
    return service, repository


@pytest.mark.asyncio
async def test_login_logout_and_session_management(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    service, refresh_repository = make_service(user)
    monkeypatch.setattr("src.auth.service.verify_password", lambda raw, hashed: True)

    tokens = await service.login(
        LoginRequest(email="USER@example.com", password="StrongPass123!"),
        user_agent="pytest",
        ip_address="127.0.0.1",
    )

    assert tokens.access_token
    assert tokens.refresh_token
    assert refresh_repository.session is not None
    assert refresh_repository.session.user_agent == "pytest"

    assert await service.logout(RefreshTokenRequest(refresh_token=tokens.refresh_token))
    assert refresh_repository.session.revoked_at is not None
    assert await service.logout_all(user) is True
    assert refresh_repository.revoked_users == [user.id]
    assert await service.list_sessions(user) == [refresh_repository.session]
    assert await service.revoke_session(user, refresh_repository.session.id) is True


@pytest.mark.asyncio
async def test_login_rejects_missing_user_invalid_password_and_inactive_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = make_service(None)
    with pytest.raises(InvalidCredentialsError):
        await service.login(LoginRequest(email="none@example.com", password="password"))

    service, _ = make_service(make_user())
    monkeypatch.setattr("src.auth.service.verify_password", lambda raw, hashed: False)
    with pytest.raises(InvalidCredentialsError):
        await service.login(LoginRequest(email="user@example.com", password="password"))

    service, _ = make_service(make_user(active=False))
    monkeypatch.setattr("src.auth.service.verify_password", lambda raw, hashed: True)
    with pytest.raises(InvalidCredentialsError):
        await service.login(LoginRequest(email="user@example.com", password="password"))


@pytest.mark.asyncio
async def test_refresh_success_and_invalid_payload_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    service, refresh_repository = make_service(user)
    monkeypatch.setattr("src.auth.service.verify_password", lambda raw, hashed: True)
    tokens = await service.login(LoginRequest(email=user.email, password="password"))

    monkeypatch.setattr(
        "src.auth.service.verify_refresh_token_hash",
        lambda token, token_hash: True,
    )
    refreshed = await service.refresh(
        RefreshTokenRequest(refresh_token=tokens.refresh_token)
    )

    assert refreshed.refresh_token
    assert refresh_repository.session is not None

    with pytest.raises(InvalidTokenError):
        service._parse_refresh_payload({"sub": "bad", "jti": "bad", "fid": "bad"})
    with pytest.raises(InvalidTokenError):
        service._parse_refresh_payload({})


@pytest.mark.asyncio
async def test_issue_token_pair_wraps_integrity_error() -> None:
    user = make_user()
    refresh_repository = FakeRefreshRepository()
    refresh_repository.raise_integrity = True
    service, _ = make_service(user, refresh_repository)

    with pytest.raises(InvalidTokenError):
        await service._issue_token_pair(user)
