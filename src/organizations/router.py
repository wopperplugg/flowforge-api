import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from src.auth.dependencies import get_current_user
from src.common.dependencies import DbSession
from src.organizations.schemas import (
    OrganizationCreate,
    OrganizationMemberResponse,
    OrganizationMemberUpdate,
    OrganizationResponse,
)
from src.organizations.service import OrganizationService
from src.users.models import User

router = APIRouter(prefix="/api/v1/organizations", tags=["organizations"])


def get_organization_service(
    session: DbSession,
) -> OrganizationService:
    return OrganizationService(session)


@router.post(
    "", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED
)
async def create_organization(
    payload: OrganizationCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    organization_service: Annotated[
        OrganizationService, Depends(get_organization_service)
    ],
) -> OrganizationResponse:
    organization = await organization_service.create_organization(payload, current_user)
    return OrganizationResponse.model_validate(organization)


@router.get("", response_model=list[OrganizationResponse])
async def list_organizations(
    current_user: Annotated[User, Depends(get_current_user)],
    organization_service: Annotated[
        OrganizationService, Depends(get_organization_service)
    ],
) -> list[OrganizationResponse]:
    organizations = await organization_service.list_my_organizations(current_user)
    return [
        OrganizationResponse.model_validate(organization)
        for organization in organizations
    ]


@router.get(
    "/{organization_id}/members", response_model=list[OrganizationMemberResponse]
)
async def list_members(
    organization_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    organization_service: Annotated[
        OrganizationService, Depends(get_organization_service)
    ],
) -> list[OrganizationMemberResponse]:
    members = await organization_service.list_members(organization_id, current_user)
    return [OrganizationMemberResponse.model_validate(member) for member in members]


@router.patch(
    "/{organization_id}/members/{user_id}", response_model=OrganizationMemberResponse
)
async def update_member(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: OrganizationMemberUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    organization_service: Annotated[
        OrganizationService, Depends(get_organization_service)
    ],
) -> OrganizationMemberResponse:
    member = await organization_service.update_member_role(
        organization_id,
        user_id,
        payload.role,
        current_user,
    )
    return OrganizationMemberResponse.model_validate(member)


@router.delete("/{organization_id}/members/{user_id}")
async def remove_member(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    organization_service: Annotated[
        OrganizationService, Depends(get_organization_service)
    ],
) -> dict[str, bool]:
    removed = await organization_service.remove_member(
        organization_id, user_id, current_user
    )
    return {"removed": removed}
