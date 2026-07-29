import os

import pytest
from fastapi.testclient import TestClient

from src.main import app

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="integration tests требуют запущенные PostgreSQL и Redis",
)


def test_readiness_endpoint_checks_postgres_and_redis() -> None:
    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
