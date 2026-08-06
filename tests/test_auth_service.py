import uuid
from datetime import UTC, datetime, timedelta

import pytest

from src.auth.models import RefreshSession
from src.auth.schemas import RefreshTokenRequest
from src.auth.service import AuthService
from src.common.exceptions import ExpiredTokenError, InvalidTokenError
from src.users.models import User
from tests.fakes import FakeSession


class FakeUserRepository:
    def __init__(self, user: User | None) -> None:
        self.user = user

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        if self.user is None or self.user.id != user_id:
            return None
        return self.user


class FakeRefreshSessionRepository:
    def __init__(self, refresh_session: RefreshSession | None) -> None:
        self.refresh_session = refresh_session
        self.revoked_families: list[tuple[uuid.UUID, datetime]] = []
        self.added: list[RefreshSession] = []

    async def get_by_jti(self, jti: uuid.UUID) -> RefreshSession | None:
        if self.refresh_session is None or self.refresh_session.jti != jti:
            return None
        return self.refresh_session

    async def get_by_jti_for_update(self, jti: uuid.UUID) -> RefreshSession | None:
        return await self.get_by_jti(jti)

    async def revoke_family(self, family_id: uuid.UUID, revoked_at: datetime) -> None:
        self.revoked_families.append((family_id, revoked_at))

    async def add(self, refresh_session: RefreshSession) -> RefreshSession:
        self.added.append(refresh_session)
        return refresh_session


def make_user() -> User:
    return User(
        id=uuid.uuid4(),
        email="user@example.com",
        username="user",
        hashed_password="hash",
        is_active=True,
    )


def make_refresh_session(
    *,
    user_id: uuid.UUID,
    revoked_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> RefreshSession:
    return RefreshSession(
        id=uuid.uuid4(),
        user_id=user_id,
        family_id=uuid.uuid4(),
        jti=uuid.uuid4(),
        token_hash="stored-hash",
        expires_at=expires_at or datetime.now(UTC) + timedelta(days=1),
        revoked_at=revoked_at,
    )


def make_service(
    *,
    user: User | None,
    refresh_session: RefreshSession | None,
) -> tuple[AuthService, FakeRefreshSessionRepository]:
    service = AuthService(FakeSession())  # type: ignore[arg-type]
    refresh_repository = FakeRefreshSessionRepository(refresh_session)
    service.repository = FakeUserRepository(user)  # type: ignore[assignment]
    service.refresh_sessions = refresh_repository  # type: ignore[assignment]
    return service, refresh_repository


@pytest.mark.asyncio
async def test_refresh_reuse_revokes_token_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    refresh_session = make_refresh_session(
        user_id=user.id,
        revoked_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    service, refresh_repository = make_service(
        user=user,
        refresh_session=refresh_session,
    )
    monkeypatch.setattr(
        "src.auth.service.decode_token",
        lambda token, expected_type: {
            "sub": str(user.id),
            "jti": str(refresh_session.jti),
            "fid": str(refresh_session.family_id),
        },
    )

    with pytest.raises(InvalidTokenError):
        await service.refresh(RefreshTokenRequest(refresh_token="replayed-token"))

    assert len(refresh_repository.revoked_families) == 1
    assert refresh_repository.revoked_families[0][0] == refresh_session.family_id
    assert refresh_repository.added == []


@pytest.mark.asyncio
async def test_refresh_expired_token_marks_session_revoked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    refresh_session = make_refresh_session(
        user_id=user.id,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    service, refresh_repository = make_service(
        user=user,
        refresh_session=refresh_session,
    )
    monkeypatch.setattr(
        "src.auth.service.decode_token",
        lambda token, expected_type: {
            "sub": str(user.id),
            "jti": str(refresh_session.jti),
            "fid": str(refresh_session.family_id),
        },
    )

    with pytest.raises(ExpiredTokenError):
        await service.refresh(RefreshTokenRequest(refresh_token="expired-token"))

    assert refresh_session.revoked_at is not None
    assert refresh_repository.revoked_families == []
    assert refresh_repository.added == []


@pytest.mark.asyncio
async def test_refresh_hash_mismatch_revokes_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    refresh_session = make_refresh_session(user_id=user.id)
    service, refresh_repository = make_service(
        user=user,
        refresh_session=refresh_session,
    )
    monkeypatch.setattr(
        "src.auth.service.decode_token",
        lambda token, expected_type: {
            "sub": str(user.id),
            "jti": str(refresh_session.jti),
            "fid": str(refresh_session.family_id),
        },
    )
    monkeypatch.setattr(
        "src.auth.service.verify_refresh_token_hash",
        lambda token, token_hash: False,
    )

    with pytest.raises(InvalidTokenError):
        await service.refresh(RefreshTokenRequest(refresh_token="tampered-token"))

    assert len(refresh_repository.revoked_families) == 1
    assert refresh_repository.revoked_families[0][0] == refresh_session.family_id
    assert refresh_repository.added == []
