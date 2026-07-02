import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.organizations.models import OrganizationMember
from src.projects.models import Project


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_accessible_project(
        self,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Project | None:
        result = await self.session.execute(
            select(Project)
            .join(
                OrganizationMember,
                OrganizationMember.organization_id == Project.organization_id,
            )
            .where(Project.id == project_id, OrganizationMember.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_organization_and_key(
        self,
        organization_id: uuid.UUID,
        key: str,
    ) -> Project | None:
        result = await self.session.execute(
            select(Project).where(
                Project.organization_id == organization_id, Project.key == key
            )
        )
        return result.scalar_one_or_none()

    async def list_for_organization(
        self,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[Project]:
        result = await self.session.execute(
            select(Project)
            .join(
                OrganizationMember,
                OrganizationMember.organization_id == Project.organization_id,
            )
            .where(
                Project.organization_id == organization_id,
                OrganizationMember.user_id == user_id,
            )
            .order_by(Project.created_at.desc())
        )
        return list(result.scalars().all())

    async def add(self, project: Project) -> Project:
        self.session.add(project)
        await self.session.flush()
        await self.session.refresh(project)
        return project
