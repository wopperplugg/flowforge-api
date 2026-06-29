import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.webhooks.models import WebhookSubscription

class WebhookRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, webhook: WebhookSubscription) -> WebhookSubscription:
        self.session.add(webhook)
        await self.session.flush()
        await self.session.refresh(webhook)
        return webhook
    
    async def list_for_organization(self, organization_id: uuid.UUID, limit: int = 100, offset: int = 0) -> list[WebhookSubscription]:
        result = await self.session.execute(
            select(WebhookSubscription)
            .where(WebhookSubscription.organization_id == organization_id)
            .order_by(WebhookSubscription.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())
    
    async def list_active_for_event(
            self,
            organization_id: uuid.UUID,
            event_type: str,
    ) -> list[WebhookSubscription]:
        result = await self.session.execute(
            select(WebhookSubscription).where(
                WebhookSubscription.organization_id == organization_id,
                WebhookSubscription.is_active.is_(True),
                WebhookSubscription.event_types.contains([event_type]),
            )
        )
        return list(result.scalars().all())