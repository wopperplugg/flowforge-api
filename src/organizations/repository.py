import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.organizations.models import Organization, OrganizationMember


class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_slug(self, slug: str) -> Organization | None:
        result = await self.session.execute(
            select(Organization).where(Organization.slug == slug)
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> list[Organization]:
        result = await self.session.execute(
            select(Organization)
            .join(
                OrganizationMember,
                OrganizationMember.organization_id == Organization.id,
            )
            .where(OrganizationMember.user_id == user_id)
            .order_by(Organization.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_member(
        self,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> OrganizationMember | None:
        result = await self.session.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_members(
        self, organization_id: uuid.UUID
    ) -> list[OrganizationMember]:
        result = await self.session.execute(
            select(OrganizationMember)
            .where(OrganizationMember.organization_id == organization_id)
            .order_by(OrganizationMember.created_at.asc())
        )
        return list(result.scalars().all())

    async def add_organization(self, organization: Organization) -> Organization:
        self.session.add(organization)
        await self.session.flush()
        await self.session.refresh(organization)
        return organization

    async def add_member(self, member: OrganizationMember) -> OrganizationMember:
        self.session.add(member)
        await self.session.flush()
        await self.session.refresh(member)
        return member
