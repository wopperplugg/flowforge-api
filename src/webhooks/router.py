import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from src.auth.dependencies import get_current_user
from src.common.dependencies import DbSession
from src.users.models import User
from src.webhooks.schemas import WebhookCreate, WebhookCreateResponse, WebhookResponse
from src.webhooks.service import WebhookService

router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/webhooks", tags=["webhooks"]
)


def get_webhook_service(session: DbSession) -> WebhookService:
    return WebhookService(session)


@router.post(
    "", response_model=WebhookCreateResponse, status_code=status.HTTP_201_CREATED
)
async def create_webhook(
    organization_id: uuid.UUID,
    payload: WebhookCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    webhook_service: Annotated[WebhookService, Depends(get_webhook_service)],
) -> WebhookCreateResponse:
    webhook, secret = await webhook_service.create_webhook(
        organization_id,
        payload,
        current_user,
    )
    response = WebhookCreateResponse.model_validate(webhook)
    return response.model_copy(update={"secret": secret})


@router.get("", response_model=list[WebhookResponse])
async def list_webhooks(
    organization_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    webhook_service: Annotated[WebhookService, Depends(get_webhook_service)],
) -> list[WebhookResponse]:
    webhooks = await webhook_service.list_webhooks(organization_id, current_user)
    return [WebhookResponse.model_validate(webhook) for webhook in webhooks]
