import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.exceptions import PermissionDeniedError
from src.organizations.repository import OrganizationRepository
from src.projects.exceptions import ProjectAlreadyExistsError, ProjectNotFoundError
from src.projects.models import Project
from src.projects.repository import ProjectRepository
from src.projects.schemas import ProjectCreate
from src.users.models import User


class ProjectService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.projects = ProjectRepository(session)
        self.organizations = OrganizationRepository(session)

    async def create_project(
        self,
        organization_id: uuid.UUID,
        data: ProjectCreate,
        user: User,
    ) -> Project:
        try:
            async with self._transaction():
                organizations = await self.organizations.list_for_user(user.id)
                if not any(
                    organization.id == organization_id for organization in organizations
                ):
                    raise PermissionDeniedError()
                existing = await self.projects.get_by_organization_and_key(
                    organization_id,
                    data.key,
                )
                if existing is not None:
                    raise ProjectAlreadyExistsError()
                return await self.projects.add(
                    Project(
                        organization_id=organization_id,
                        name=data.name,
                        key=data.key,
                        description=data.description,
                    )
                )
        except IntegrityError as exc:
            raise ProjectAlreadyExistsError() from exc

    async def list_projects(
        self, organization_id: uuid.UUID, user: User
    ) -> list[Project]:
        return await self.projects.list_for_organization(organization_id, user.id)

    async def get_project(self, project_id: uuid.UUID, user: User) -> Project:
        project = await self.projects.get_accessible_project(project_id, user.id)
        if project is None:
            raise ProjectNotFoundError()
        return project

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[None]:
        if self.session.in_transaction():
            yield
            return
        async with self.session.begin():
            yield
