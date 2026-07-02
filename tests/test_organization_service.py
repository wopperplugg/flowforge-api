import uuid

import pytest

from src.common.enums import OrganizationRole
from src.common.exceptions import PermissionDeniedError
from src.organizations.exceptions import OrganizationNotFoundError
from src.organizations.models import OrganizationMember
from src.organizations.service import OrganizationService
from src.users.models import User
from tests.fakes import FakeSession


class FakeOrganizationRepository:
    def __init__(
        self, members: dict[tuple[uuid.UUID, uuid.UUID], OrganizationMember]
    ) -> None:
        self.members = members

    async def get_member(
        self,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> OrganizationMember | None:
        return self.members.get((organization_id, user_id))


def make_user() -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4()}@example.com",
        username=f"user-{uuid.uuid4()}",
        hashed_password="hash",
    )


def make_member(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    role: OrganizationRole,
) -> OrganizationMember:
    return OrganizationMember(
        id=uuid.uuid4(),
        organization_id=organization_id,
        user_id=user_id,
        role=role,
    )


def make_service(
    members: dict[tuple[uuid.UUID, uuid.UUID], OrganizationMember],
) -> tuple[OrganizationService, FakeSession]:
    session = FakeSession()
    service = OrganizationService(session)  # type: ignore[arg-type]
    service.repository = FakeOrganizationRepository(members)  # type: ignore[assignment]
    return service, session


@pytest.mark.asyncio
async def test_member_cannot_update_roles() -> None:
    organization_id = uuid.uuid4()
    actor = make_user()
    target = make_user()
    target_member = make_member(organization_id, target.id, OrganizationRole.MEMBER)
    service, _ = make_service(
        {
            (organization_id, actor.id): make_member(
                organization_id,
                actor.id,
                OrganizationRole.MEMBER,
            ),
            (organization_id, target.id): target_member,
        }
    )

    with pytest.raises(PermissionDeniedError):
        await service.update_member_role(
            organization_id,
            target.id,
            OrganizationRole.ADMIN,
            actor,
        )

    assert target_member.role == OrganizationRole.MEMBER


@pytest.mark.asyncio
async def test_owner_cannot_be_downgraded_by_member_endpoint() -> None:
    organization_id = uuid.uuid4()
    actor = make_user()
    owner = make_user()
    owner_member = make_member(organization_id, owner.id, OrganizationRole.OWNER)
    service, _ = make_service(
        {
            (organization_id, actor.id): make_member(
                organization_id,
                actor.id,
                OrganizationRole.ADMIN,
            ),
            (organization_id, owner.id): owner_member,
        }
    )

    with pytest.raises(PermissionDeniedError):
        await service.update_member_role(
            organization_id,
            owner.id,
            OrganizationRole.MEMBER,
            actor,
        )

    assert owner_member.role == OrganizationRole.OWNER


@pytest.mark.asyncio
async def test_remove_member_rejects_owner_and_does_not_delete() -> None:
    organization_id = uuid.uuid4()
    actor = make_user()
    owner = make_user()
    owner_member = make_member(organization_id, owner.id, OrganizationRole.OWNER)
    service, session = make_service(
        {
            (organization_id, actor.id): make_member(
                organization_id,
                actor.id,
                OrganizationRole.ADMIN,
            ),
            (organization_id, owner.id): owner_member,
        }
    )

    with pytest.raises(PermissionDeniedError):
        await service.remove_member(organization_id, owner.id, actor)

    assert session.deleted == []


@pytest.mark.asyncio
async def test_update_missing_member_returns_domain_not_found() -> None:
    organization_id = uuid.uuid4()
    actor = make_user()
    missing_user_id = uuid.uuid4()
    service, _ = make_service(
        {
            (organization_id, actor.id): make_member(
                organization_id,
                actor.id,
                OrganizationRole.ADMIN,
            )
        }
    )

    with pytest.raises(OrganizationNotFoundError):
        await service.update_member_role(
            organization_id,
            missing_user_id,
            OrganizationRole.MEMBER,
            actor,
        )
