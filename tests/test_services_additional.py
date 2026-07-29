import uuid

import pytest
from pydantic import ValidationError

from src.common.enums import OrganizationRole, UserRole
from src.common.exceptions import PermissionDeniedError
from src.projects.exceptions import ProjectAlreadyExistsError, ProjectNotFoundError
from src.projects.models import Project
from src.projects.schemas import ProjectCreate
from src.projects.service import ProjectService
from src.users.exceptions import UserAlreadyExistsError, UserNotFoundError
from src.users.models import User
from src.users.schemas import (
    UserAdminUpdate,
    UserCreate,
    UserPasswordChange,
    UserProfileUpdate,
    validate_password_strength,
)
from src.users.service import UserService
from src.webhooks.models import WebhookSubscription
from src.webhooks.schemas import WebhookCreate
from src.webhooks.service import WebhookService
from tests.fakes import FakeSession


def make_user() -> User:
    return User(
        id=uuid.uuid4(),
        email="user@example.com",
        username="user",
        hashed_password="hash",
        is_active=True,
    )


class OrganizationRecord:
    def __init__(self, organization_id: uuid.UUID) -> None:
        self.id = organization_id


class MemberRecord:
    def __init__(self, role: OrganizationRole) -> None:
        self.role = role


class FakeProjectRepository:
    def __init__(self) -> None:
        self.existing: Project | None = None
        self.added: list[Project] = []

    async def get_by_organization_and_key(
        self, organization_id: uuid.UUID, key: str
    ) -> Project | None:
        return self.existing

    async def add(self, project: Project) -> Project:
        project.id = uuid.uuid4()
        self.added.append(project)
        return project

    async def list_for_organization(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[Project]:
        return self.added

    async def get_accessible_project(
        self, project_id: uuid.UUID, user_id: uuid.UUID
    ) -> Project | None:
        for project in self.added:
            if project.id == project_id:
                return project
        return None


class FakeOrganizationRepository:
    def __init__(
        self,
        organization_id: uuid.UUID,
        *,
        role: OrganizationRole | None = OrganizationRole.ADMIN,
    ) -> None:
        self.organization_id = organization_id
        self.role = role

    async def list_for_user(self, user_id: uuid.UUID) -> list[OrganizationRecord]:
        if self.role is None:
            return []
        return [OrganizationRecord(self.organization_id)]

    async def get_member(
        self,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> MemberRecord | None:
        if self.role is None:
            return None
        return MemberRecord(self.role)


class FakeUserRepository:
    def __init__(self, *, existing: User | None = None) -> None:
        self.existing = existing
        self.added: list[User] = []

    async def get_by_email(self, email: str) -> User | None:
        return self.existing

    async def get_by_username(self, username: str) -> User | None:
        return self.existing

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        if self.existing is None or self.existing.id != user_id:
            return None
        return self.existing

    async def add(self, user: User) -> User:
        user.id = uuid.uuid4()
        self.added.append(user)
        return user


class FakeWebhookRepository:
    def __init__(self) -> None:
        self.added: list[WebhookSubscription] = []

    async def add(self, webhook: WebhookSubscription) -> WebhookSubscription:
        webhook.id = uuid.uuid4()
        self.added.append(webhook)
        return webhook

    async def list_for_organization(
        self, organization_id: uuid.UUID
    ) -> list[WebhookSubscription]:
        return self.added


@pytest.mark.asyncio
async def test_project_service_create_list_and_get_project() -> None:
    organization_id = uuid.uuid4()
    user = make_user()
    service = ProjectService(FakeSession())  # type: ignore[arg-type]
    projects = FakeProjectRepository()
    service.projects = projects  # type: ignore[assignment]
    service.organizations = FakeOrganizationRepository(organization_id)  # type: ignore[assignment]

    project = await service.create_project(
        organization_id,
        ProjectCreate(name="Backend", key="api"),
        user,
    )

    assert project.key == "API"
    assert await service.list_projects(organization_id, user) == [project]
    assert await service.get_project(project.id, user) == project

    projects.existing = project
    with pytest.raises(ProjectAlreadyExistsError):
        await service.create_project(
            organization_id,
            ProjectCreate(name="Duplicate", key="api"),
            user,
        )

    with pytest.raises(ProjectNotFoundError):
        await service.get_project(uuid.uuid4(), user)


@pytest.mark.asyncio
async def test_project_service_denies_inaccessible_organization() -> None:
    service = ProjectService(FakeSession())  # type: ignore[arg-type]
    service.projects = FakeProjectRepository()  # type: ignore[assignment]
    service.organizations = FakeOrganizationRepository(  # type: ignore[assignment]
        uuid.uuid4(), role=None
    )

    with pytest.raises(PermissionDeniedError):
        await service.create_project(
            uuid.uuid4(),
            ProjectCreate(name="Hidden", key="hid"),
            make_user(),
        )


@pytest.mark.asyncio
async def test_user_service_create_and_get_user() -> None:
    service = UserService(FakeSession())  # type: ignore[arg-type]
    repository = FakeUserRepository()
    service.repository = repository  # type: ignore[assignment]

    user = await service.create_user(
        UserCreate(
            email="USER@Example.com",
            username=" user ",
            password="StrongPass123!",
        )
    )

    repository.existing = user
    assert user.email == "user@example.com"
    assert user.username == "user"
    assert await service.get_user(user.id) == user

    with pytest.raises(UserAlreadyExistsError):
        await service.create_user(
            UserCreate(
                email="user@example.com",
                username="user",
                password="StrongPass123!",
            )
        )

    repository.existing = None
    with pytest.raises(UserNotFoundError):
        await service.get_user(uuid.uuid4())


def test_user_schema_validation_branches() -> None:
    invalid_passwords = [
        " no-trim1A!",
        "short",
        "NOLOWERCASE1!",
        "nouppercase1!",
        "NoDigits!",
        "NoSpecial123",
    ]
    for password in invalid_passwords[1:]:
        with pytest.raises(ValidationError):
            UserCreate(email="user@example.com", username="user", password=password)
    for password in invalid_passwords:
        with pytest.raises(ValueError):
            validate_password_strength(password)

    assert (
        UserProfileUpdate(email="USER@EXAMPLE.COM", username=None).email
        == "user@example.com"
    )
    assert UserProfileUpdate(email=None, username=" user ").username == "user"
    with pytest.raises(ValidationError):
        UserProfileUpdate.model_validate({})

    with pytest.raises(ValidationError):
        UserPasswordChange(
            current_password="StrongPass123!",
            new_password="StrongPass123!",
        )
    with pytest.raises(ValidationError):
        UserPasswordChange(
            current_password="StrongPass123!",
            new_password="weak",
        )

    assert UserAdminUpdate(role=UserRole.ADMIN).role == UserRole.ADMIN
    assert UserAdminUpdate(is_active=False).is_active is False
    with pytest.raises(ValidationError):
        UserAdminUpdate()


@pytest.mark.asyncio
async def test_webhook_service_create_and_list_webhooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid.uuid4()
    service = WebhookService(FakeSession())  # type: ignore[arg-type]
    repository = FakeWebhookRepository()
    service.webhooks = repository  # type: ignore[assignment]
    service.organizations = FakeOrganizationRepository(organization_id)  # type: ignore[assignment]
    monkeypatch.setattr("src.webhooks.service.is_safe_webhook_url", lambda url: True)

    webhook, secret = await service.create_webhook(
        organization_id,
        WebhookCreate.model_validate(
            {
                "url": "https://example.com/hook",
                "event_types": ["task.created"],
            }
        ),
        make_user(),
    )

    assert secret
    assert webhook in await service.list_webhooks(organization_id, make_user())
    assert webhook.secret_hash
    assert webhook.secret_encrypted


@pytest.mark.asyncio
async def test_webhook_service_rejects_non_admin_and_unsafe_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid.uuid4()
    service = WebhookService(FakeSession())  # type: ignore[arg-type]
    service.webhooks = FakeWebhookRepository()  # type: ignore[assignment]
    service.organizations = FakeOrganizationRepository(  # type: ignore[assignment]
        organization_id,
        role=OrganizationRole.MEMBER,
    )

    with pytest.raises(PermissionDeniedError):
        await service.create_webhook(
            organization_id,
            WebhookCreate.model_validate(
                {
                    "url": "https://example.com/hook",
                    "event_types": ["task.created"],
                }
            ),
            make_user(),
        )

    service.organizations = FakeOrganizationRepository(organization_id)  # type: ignore[assignment]
    monkeypatch.setattr("src.webhooks.service.is_safe_webhook_url", lambda url: False)
    with pytest.raises(PermissionDeniedError):
        await service.create_webhook(
            organization_id,
            WebhookCreate.model_validate(
                {
                    "url": "https://example.com/hook",
                    "event_types": ["task.created"],
                }
            ),
            make_user(),
        )
