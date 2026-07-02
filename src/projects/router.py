import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from src.auth.dependencies import get_current_user
from src.common.dependencies import DbSession
from src.projects.schemas import ProjectCreate, ProjectResponse
from src.projects.service import ProjectService
from src.users.models import User

router = APIRouter(tags=["projects"])


def get_project_service(
    session: DbSession,
) -> ProjectService:
    return ProjectService(session)


@router.post(
    "/api/v1/organizations/{organization_id}/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project(
    organization_id: uuid.UUID,
    payload: ProjectCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    project_service: Annotated[ProjectService, Depends(get_project_service)],
) -> ProjectResponse:
    project = await project_service.create_project(
        organization_id, payload, current_user
    )
    return ProjectResponse.model_validate(project)


@router.get(
    "/api/v1/organizations/{organization_id}/projects",
    response_model=list[ProjectResponse],
)
async def list_projects(
    organization_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    project_service: Annotated[ProjectService, Depends(get_project_service)],
) -> list[ProjectResponse]:
    projects = await project_service.list_projects(organization_id, current_user)
    return [ProjectResponse.model_validate(project) for project in projects]


@router.get(
    "/api/v1/projects/{project_id}",
    response_model=ProjectResponse,
)
async def get_project(
    project_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    project_service: Annotated[ProjectService, Depends(get_project_service)],
) -> ProjectResponse:
    project = await project_service.get_project(project_id, current_user)
    return ProjectResponse.model_validate(project)
