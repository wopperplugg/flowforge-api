from fastapi.testclient import TestClient

from src.common.enums import TaskStatus
from src.main import app


def test_openapi_contains_core_resource_routes() -> None:
    schema = app.openapi()

    assert "/api/v1/auth/register" in schema["paths"]
    assert "/api/v1/organizations" in schema["paths"]
    assert "/api/v1/organizations/{organization_id}/projects" in schema["paths"]
    assert "/api/v1/projects/{project_id}/tasks" in schema["paths"]
    assert "/api/v1/organizations/{organization_id}/webhooks" in schema["paths"]


def test_liveness_endpoint_returns_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_metrics_endpoint_exposes_prometheus_text() -> None:
    with TestClient(app) as client:
        client.get("/health/live")
        response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "flowforge_http_requests_total" in response.text
    assert 'path="/health/live"' in response.text
    assert "/metrics" not in app.openapi()["paths"]


def test_task_status_review_value_is_stable() -> None:
    assert TaskStatus.REVIEW.value == "review"
