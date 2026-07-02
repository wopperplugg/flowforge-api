import pytest
from pydantic import ValidationError

from src.organizations.schemas import OrganizationCreate
from src.projects.schemas import ProjectCreate
from src.webhooks.schemas import WebhookCreate
from src.webhooks.security import is_safe_webhook_url


def test_organization_slug_is_normalized() -> None:
    payload = OrganizationCreate(name="Acme Inc", slug="  Acme-Team  ")

    assert payload.slug == "acme-team"


def test_project_key_is_normalized_to_uppercase() -> None:
    payload = ProjectCreate(name="Backend", key="api")

    assert payload.key == "API"


def test_webhook_event_types_must_be_unique() -> None:
    with pytest.raises(ValidationError):
        WebhookCreate(
            url="https://example.com/hooks/flowforge",
            event_types=["task.created", "task.created"],
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/hook",
        "https://127.0.0.1/hook",
        "ftp://example.com/hook",
        "https://user:password@example.com/hook",
    ],
)
def test_unsafe_webhook_urls_are_rejected(url: str) -> None:
    assert is_safe_webhook_url(url) is False
