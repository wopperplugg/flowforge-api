import uuid
from datetime import datetime
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from src.auth.models import RefreshSession

class RefreshSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, refresh_session: RefreshSession) -> RefreshSession:
        self.session.add(refresh_session)
        await self.session.flush()
        await self.session.refresh(refresh_session)
        return refresh_session
    
    async def get_by_jti(self, jti: uuid.UUID) -> RefreshSession | None:
        result = await self.session.execute(
            select(RefreshSession).where(RefreshSession.jti == jti)
        )
        return result.scalar_one_or_none()
    
    async def get_by_id_for_user(
            self,
            session_id: uuid.UUID,
            user_id: uuid.UUID,
    ) -> RefreshSession | None:
        result = await self.session.execute(
            select(RefreshSession).where(
                RefreshSession.id == session_id,
                RefreshSession.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()
    
    async def list_active_by_user_id(self, user_id: uuid.UUID) -> list[RefreshSession]:
        result = await self.session.execute(
            select(RefreshSession)
            .where(
                RefreshSession.user_id == user_id,
                RefreshSession.revoked_at.is_(None),
            )
            .order_by(RefreshSession.created_at.desc())
        )
        return list(result.scalars().all())
    
    async def revoke_family(self, family_id: uuid.UUID, revoked_at: datetime) -> None:
        await self.session.execute(
            update(RefreshSession)
            .where(RefreshSession.family_id == family_id,
                    RefreshSession.revoked_at.is_(None),
                )
                .values(revoked_at=revoked_at)
        )

    async def revoke_all_for_user(self, user_id: uuid.UUID, revoked_at: datetime) -> None:
        await self.session.execute(
            update(RefreshSession)
            .where(
                RefreshSession.user_id == user_id,
                RefreshSession.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )

    async def revoke_one_for_user(
            self,
            session_id: uuid.UUID,
            user_id: uuid.UUID,
            revoked_at: datetime,
    ) -> bool:
        refresh_session = await self.get_by_id_for_user(session_id, user_id)
        if refresh_session is None or refresh_session.revoked_at is not None:
            return False

        refresh_session.revoked_at = revoked_at
        return True