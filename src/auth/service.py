import uuid 
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import RefreshSession
from src.auth.repository import RefreshSessionRepository
from src.auth.schemas import LoginRequest, RefreshTokenRequest, TokenResponse
from src.auth.security import hash_refresh_token, verify_refresh_token_hash
from src.auth.tokens import create_access_token, create_refresh_token, decode_token
from src.common.exceptions import (
    AppError,
    ExpiredTokenError,
    InvalidCredentialsError,
    InvalidTokenError,
)
from src.common.security import verify_password
from src.users.models import User
from src.users.repository import UserRepository




class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = UserRepository(session)
        self.refresh_sessions = RefreshSessionRepository(session)

    
    async def login(
            self,
            data: LoginRequest,
            *,
            user_agent: str | None = None,
            ip_address: str | None = None,
    ) -> TokenResponse:
        async with self._transaction():
            user = await self.repository.get_by_email(data.email.lower())
            if user is None:
                raise InvalidCredentialsError()
            
            valid_password = verify_password(data.password, user.hashed_password)
            if not valid_password or not user.is_active:
                raise InvalidCredentialsError()

            return await self._issue_token_pair(
                user,
                user_agent=user_agent,
                ip_address=ip_address,
            )
    async def refresh(
            self,
            data: RefreshTokenRequest,
            *,
            user_agent: str | None = None,
            ip_address: str | None = None,
    ) -> TokenResponse:
        payload = decode_token(data.refresh_token, expected_type="refresh")
        user_id, jti, family_id = self._parse_refresh_payload(payload)
        error: AppError | None = None
        token_response: TokenResponse | None = None

        async with self._transaction():
            refresh_session = await self.refresh_sessions.get_by_jti(jti)
            if refresh_session is None or refresh_session.user_id != user_id:
                error = InvalidTokenError()
            else: 
                now = datetime.now(UTC)
                if refresh_session.revoked_at is not None:
                    await self.refresh_sessions.revoke_family(refresh_session.family_id, now)
                    error = InvalidTokenError()
                elif refresh_session.expires_at <= now:
                    refresh_session.revoked_at = now
                    error = ExpiredTokenError()
                elif not verify_refresh_token_hash(data.refresh_token, refresh_session.token_hash):
                    await self.refresh_sessions.revoke_family(refresh_session.family_id, now)
                    error = InvalidTokenError()
                else: 
                    user = await self.repository.get_by_id(user_id)
                    if user is None or not user.is_active:
                        await self.refresh_sessions.revoke_family(refresh_session.family_id, now)
                        error = InvalidTokenError()

                    else: 
                        refresh_session.revoked_at = now
                        refresh_session.last_used_at = now

                        token_response = await self._issue_token_pair(
                            user,
                            family_id=family_id,
                            user_agent=user_agent,
                            ip_address=ip_address,
                        )
                        new_payload = decode_token(
                            token_response.refresh_token,
                            expected_type="refresh",
                        )
                        refresh_session.replaced_by_jti = uuid.UUID(str(new_payload["jti"]))
        if error is not None:
            raise error
        if token_response is None:
            raise InvalidTokenError()
        return token_response
    
    async def logout(self, data: RefreshTokenRequest) -> bool:
        payload = decode_token(data.refresh_token, expected_type="refresh")
        _, jti, _ = self._parse_refresh_payload(payload)
        error: AppError | None = None

        async with self._transaction():
            refresh_session = await self.refresh_sessions.get_by_jti(jti)
            if refresh_session is None:
                error = InvalidTokenError()
            elif not verify_refresh_token_hash(data.refresh_token, refresh_session.token_hash):
                await self.refresh_sessions.revoke_family(
                    refresh_session.family_id,
                    datetime.now(UTC),
                )
                error = InvalidTokenError()
            elif refresh_session.revoked_at is None:
                refresh_session.revoked_at = datetime.now(UTC)
        
        if error is not None: 
            raise error
        return True

    async def logout_all(self, user: User) -> bool:
        async with self._transaction():
            await self.refresh_sessions.revoke_all_for_user(user.id, datetime.now(UTC))
        return True
    
    async def list_sessions(self, user: User) -> list[RefreshSession]:
        return await self.refresh_sessions.list_active_by_user_id(user.id)
    
    async def revoke_session(self, user: User, session_id: uuid.UUID) -> bool:
        async with self._transaction():
            revoked = await self.refresh_sessions.revoke_one_for_user(
                session_id,
                user.id,
                datetime.now(UTC),
            )
        return revoked

    async def _issue_token_pair(
            self,
            user: User,
            *, 
            family_id: uuid.UUID | None = None,
            user_agent: str | None = None,
            ip_address: str | None = None,
    ) -> TokenResponse:
        access_token, expires_in = create_access_token(user.id)
        refresh_token, refresh_jti, refresh_family_id, refresh_expires_at = create_refresh_token(
            user.id,
            family_id=family_id,
        )
        refresh_session = RefreshSession(
            user_id=user.id,
            family_id=refresh_family_id,
            jti=refresh_jti,
            token_hash=hash_refresh_token(refresh_token),
            expires_at=refresh_expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        try: 
            await self.refresh_sessions.add(refresh_session)
        except IntegrityError as exc:
            raise InvalidTokenError() from exc
        
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        )
    
    def _parse_refresh_payload(
            self,
            payload: dict[str, object],
    ) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
        try: 
            user_id = uuid.UUID(str(payload["sub"]))
            jti = uuid.UUID(str(payload["jti"]))
            family_id = uuid.UUID(str(payload["fid"]))
        except(KeyError, ValueError) as exc: 
            raise InvalidTokenError() from exc
        return user_id, jti, family_id

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[None]:
        if not self.session.in_transaction():
            async with self.session.begin():
                yield
            return 
        try: 
            yield
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
