import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from src.auth.dependencies import get_current_user
from src.common.enums import TaskPriority, TaskStatus
from src.common.pagination import Page, PaginationParams
from src.infrastructure.metrics import HTTP_REQUESTS_TOTAL
from src.infrastructure.metrics import metrics as metrics_endpoint
from src.main import app
from src.tasks.router import get_task_service
from src.tasks.schemas import TaskResponse
from src.users.models import User


class FakeTaskService:
    def __init__(self) -> None:
        self.calls: list[tuple[uuid.UUID, uuid.UUID, PaginationParams]] = []
        self.delete_calls: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]] = []

    async def list_tasks(
        self,
        project_id: uuid.UUID,
        current_user: User,
        pagination: PaginationParams,
    ) -> Page[TaskResponse]:
        self.calls.append((project_id, current_user.id, pagination))
        return Page[TaskResponse](
            items=[
                TaskResponse(
                    id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
                    project_id=project_id,
                    created_by_id=current_user.id,
                    assigned_to_id=None,
                    title="Review API",
                    description=None,
                    status=TaskStatus.TODO,
                    priority=TaskPriority.MEDIUM,
                    position=0,
                    due_date=None,
                    version=1,
                    created_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
                    updated_at=datetime(2026, 1, 2, 3, 5, 6, tzinfo=UTC),
                )
            ],
            total=3,
            limit=pagination.limit,
            offset=pagination.offset,
        )

    async def delete_task(
        self,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        current_user: User,
    ) -> None:
        self.delete_calls.append((project_id, task_id, current_user.id))


class FakeRedis:
    async def incr(self, key: str) -> int:
        return 1

    async def expire(self, key: str, seconds: int) -> None:
        return None


def make_user() -> User:
    return User(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        email="owner@example.com",
        username="owner",
        hashed_password="hash",
    )


def test_openapi_contains_core_resource_routes() -> None:
    schema = app.openapi()

    assert "/api/v1/auth/register" in schema["paths"]
    assert "/api/v1/organizations" in schema["paths"]
    assert "/api/v1/organizations/{organization_id}/projects" in schema["paths"]
    assert "/api/v1/projects/{project_id}/tasks" in schema["paths"]
    assert "/api/v1/projects/{project_id}/tasks/{task_id}" in schema["paths"]
    assert "/api/v1/organizations/{organization_id}/webhooks" in schema["paths"]


def test_openapi_documents_task_list_pagination_contract() -> None:
    schema = app.openapi()
    operation = schema["paths"]["/api/v1/projects/{project_id}/tasks"]["get"]

    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert parameters["limit"]["in"] == "query"
    assert parameters["limit"]["required"] is False
    assert parameters["limit"]["schema"] == {
        "type": "integer",
        "maximum": 100,
        "minimum": 1,
        "default": 20,
        "title": "Limit",
    }
    assert parameters["offset"]["in"] == "query"
    assert parameters["offset"]["required"] is False
    assert parameters["offset"]["schema"] == {
        "type": "integer",
        "minimum": 0,
        "default": 0,
        "title": "Offset",
    }
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/Page_TaskResponse_"
    }
    assert set(schema["components"]["schemas"]["Page_TaskResponse_"]["required"]) == {
        "items",
        "total",
        "limit",
        "offset",
    }


def test_list_tasks_returns_paginated_http_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    task_service = FakeTaskService()
    project_id = uuid.UUID("22222222-2222-2222-2222-222222222222")

    monkeypatch.setattr("src.infrastructure.rate_limit.redis_client", FakeRedis())
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_task_service] = lambda: task_service
    try:
        client = TestClient(app)
        response = client.get(
            f"/api/v1/projects/{project_id}/tasks",
            params={"limit": 2, "offset": 1},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": "33333333-3333-3333-3333-333333333333",
                "project_id": str(project_id),
                "created_by_id": str(user.id),
                "assigned_to_id": None,
                "title": "Review API",
                "description": None,
                "status": "todo",
                "priority": "medium",
                "position": 0,
                "due_date": None,
                "version": 1,
                "created_at": "2026-01-02T03:04:05Z",
                "updated_at": "2026-01-02T03:05:06Z",
            }
        ],
        "total": 3,
        "limit": 2,
        "offset": 1,
    }
    assert task_service.calls == [
        (project_id, user.id, PaginationParams(limit=2, offset=1))
    ]


def test_delete_task_returns_no_content_and_delegates_to_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    task_service = FakeTaskService()
    project_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    task_id = uuid.UUID("33333333-3333-3333-3333-333333333333")

    monkeypatch.setattr("src.infrastructure.rate_limit.redis_client", FakeRedis())
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_task_service] = lambda: task_service
    try:
        client = TestClient(app)
        response = client.delete(f"/api/v1/projects/{project_id}/tasks/{task_id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204
    assert response.content == b""
    assert task_service.delete_calls == [(project_id, task_id, user.id)]


def test_liveness_endpoint_returns_ok() -> None:
    client = TestClient(app)
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_prometheus_text() -> None:
    HTTP_REQUESTS_TOTAL.labels(
        method="GET",
        path="/health/live",
        status_code="200",
    ).inc()
    response = await metrics_endpoint()

    assert response.status_code == 200
    assert response.media_type is not None
    assert response.media_type.startswith("text/plain")
    body = bytes(response.body).decode()
    assert "flowforge_http_requests_total" in body
    assert 'path="/health/live"' in body
    assert "/metrics" not in app.openapi()["paths"]


def test_task_status_review_value_is_stable() -> None:
    assert TaskStatus.REVIEW.value == "review"
