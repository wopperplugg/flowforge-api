import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.enums import OrganizationRole
from src.common.exceptions import PermissionDeniedError
from src.organizations.exceptions import (
    OrganizationAlreadyExistsError,
    OrganizationNotFoundError,
)
from src.organizations.models import Organization, OrganizationMember
from src.organizations.repository import OrganizationRepository
from src.organizations.schemas import OrganizationCreate
from src.users.models import User


class OrganizationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = OrganizationRepository(session)

    async def create_organization(
        self, data: OrganizationCreate, owner: User
    ) -> Organization:
        slug = data.slug.lower()
        try:
            async with self._transaction():
                existing = await self.repository.get_by_slug(slug)
                if existing is not None:
                    raise OrganizationAlreadyExistsError()
                organization = await self.repository.add_organization(
                    Organization(name=data.name, slug=slug)
                )
                await self.repository.add_member(
                    OrganizationMember(
                        organization_id=organization.id,
                        user_id=owner.id,
                        role=OrganizationRole.OWNER,
                    )
                )
                return organization
        except IntegrityError as exc:
            raise OrganizationAlreadyExistsError() from exc

    async def list_my_organizations(self, user: User) -> list[Organization]:
        return await self.repository.list_for_user(user.id)

    async def list_members(
        self,
        organization_id: uuid.UUID,
        user: User,
    ) -> list[OrganizationMember]:
        await self._require_member(organization_id, user)
        return await self.repository.list_members(organization_id)

    async def update_member_role(
        self,
        organization_id: uuid.UUID,
        target_user_id: uuid.UUID,
        role: OrganizationRole,
        actor: User,
    ) -> OrganizationMember:
        async with self._transaction():
            await self._require_admin(organization_id, actor)
            member = await self.repository.get_member(organization_id, target_user_id)
            if member is None:
                raise OrganizationNotFoundError("Organization member was not found")
            if member.role == OrganizationRole.OWNER and role != OrganizationRole.OWNER:
                raise PermissionDeniedError(
                    "Owner role cannot be downgraded by this endpoint"
                )
            member.role = role
            return member

    async def remove_member(
        self,
        organization_id: uuid.UUID,
        target_user_id: uuid.UUID,
        actor: User,
    ) -> bool:
        async with self._transaction():
            await self._require_admin(organization_id, actor)
            member = await self.repository.get_member(organization_id, target_user_id)
            if member is None:
                raise OrganizationNotFoundError("Organization member was not found")
            if member.role == OrganizationRole.OWNER:
                raise PermissionDeniedError("Owner cannot be removed by this endpoint")
            await self.session.delete(member)
            return True

    async def _require_member(
        self, organization_id: uuid.UUID, user: User
    ) -> OrganizationMember:
        member = await self.repository.get_member(organization_id, user.id)
        if member is None:
            raise PermissionDeniedError()
        return member

    async def _require_admin(
        self, organization_id: uuid.UUID, user: User
    ) -> OrganizationMember:
        member = await self._require_member(organization_id, user)
        if member.role not in {OrganizationRole.OWNER, OrganizationRole.ADMIN}:
            raise PermissionDeniedError()
        return member

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[None]:
        if self.session.in_transaction():
            yield
            return
        async with self.session.begin():
            yield
