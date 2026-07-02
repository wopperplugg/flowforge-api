import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from src.common.enums import OrganizationRole
from src.common.exceptions import PermissionDeniedError
from src.organizations.repository import OrganizationRepository
from src.users.models import User
from src.webhooks.models import WebhookSubscription
from src.webhooks.repository import WebhookRepository
from src.webhooks.schemas import WebhookCreate
from src.webhooks.security import (
    encrypt_webhook_secret,
    generate_webhook_secret,
    hash_webhook_secret,
    is_safe_webhook_url,
)


class WebhookService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.organizations = OrganizationRepository(session)
        self.webhooks = WebhookRepository(session)

    async def create_webhook(
        self,
        organization_id: uuid.UUID,
        data: WebhookCreate,
        user: User,
    ) -> tuple[WebhookSubscription, str]:
        async with self._transaction():
            await self._require_admin(organization_id, user)
            url = str(data.url)
            if not is_safe_webhook_url(url):
                raise PermissionDeniedError("Webhook URL is not allowed")
            secret = generate_webhook_secret()
            webhook = await self.webhooks.add(
                WebhookSubscription(
                    organization_id=organization_id,
                    url=url,
                    secret_hash=hash_webhook_secret(secret),
                    secret_encrypted=encrypt_webhook_secret(secret),
                    event_types=data.event_types,
                    is_active=True,
                )
            )
            return webhook, secret

    async def list_webhooks(
        self,
        organization_id: uuid.UUID,
        user: User,
    ) -> list[WebhookSubscription]:
        await self._require_member(organization_id, user)
        return await self.webhooks.list_for_organization(organization_id)

    async def _require_member(
        self,
        organization_id: uuid.UUID,
        user: User,
    ) -> None:
        member = await self.organizations.get_member(organization_id, user.id)
        if member is None:
            raise PermissionDeniedError()

    async def _require_admin(
        self,
        organization_id: uuid.UUID,
        user: User,
    ) -> None:
        member = await self.organizations.get_member(organization_id, user.id)
        if member is None or member.role not in {
            OrganizationRole.OWNER,
            OrganizationRole.ADMIN,
        }:
            raise PermissionDeniedError()

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[None]:
        if self.session.in_transaction():
            yield
            return
        async with self.session.begin():
            yield
