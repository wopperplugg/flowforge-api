import time
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.projects.models import Project
from src.tasks.models import Task
from src.webhooks.models import WebhookDelivery
from src.webhooks.repository import WebhookRepository
from src.webhooks.security import decrypt_webhook_secret, is_safe_webhook_url, sign_webhook_payload


async def resolve_task_organization_id(
        session: AsyncSession,
        task_id: uuid.UUID,
) -> uuid.UUID | None:
    result = await session.execute(
        select(Project.organization_id)
        .join(Task, Task.project_id == Project.id)
        .where(Task.id == task_id)
    )
    return result.scalar_one_or_none()

async def deliver_webhooks_for_outbox_event(
        session: AsyncSession,
        *,
        event_id: uuid.UUID,
        event_type: str, 
        payload: dict[str, object],
) -> None:
    raw_task_id = payload.get("task_id")
    if raw_task_id is None:
        return 
    
    organization_id = await resolve_task_organization_id(session, uuid.UUID(session, uuid.UUID(str(raw_task_id))))
    if organization_id is None:
        return 
    
    repository = WebhookRepository(session)
    webhooks = await repository.list_active_for_event(organization_id, event_type)
    if not webhooks:
        return
    
    async with httpx.AsyncClient(timeout=settings.webhook_timeout_seconds) as client:
        for webhook in webhooks:
            if webhook.secret_encrypted is None or not is_safe_webhook_url(webhook.url):
                continue
            secret = decrypt_webhook_secret(webhook.secret_encrypted)
            timestamp = int(time.time())
            signature= sign_webhook_payload(secret, timestamp, payload)
            status_code: int | None = None
            response_body: str | None = None
            try:
                response = await client.post(
                    webhook.url,
                    json=payload,
                    headers={
                        "X-FlowForge-Event-ID": str(event_id),
                        "X-FlowForge-Timestamp": str(timestamp),
                        "X-FlowForge-Signature": f"sha256={signature}",
                    },
                )
                status_code = response.status_code
                response_body = response.text[:2000]
                response.raise_for_status()
            finally: 
                session.add(
                    WebhookDelivery(
                        webhook_id=webhook.id,
                        event_id=event_id,
                        payload=payload,
                        status_code=status_code,
                        response_body=response_body,
                        attempts=1,
                    )
                )