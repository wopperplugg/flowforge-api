import uuid
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from redis.exceptions import RedisError

from src.common.exceptions import RateLimitExceededError
from src.config import settings
from src.infrastructure.rate_limit import RateLimitMiddleware
from src.webhooks import delivery
from src.webhooks.models import WebhookDelivery, WebhookSubscription


class FakeWebhookRepository:
    def __init__(self, session: object) -> None:
        self.session = session

    async def list_active_for_event(
        self,
        organization_id: uuid.UUID,
        event_type: str,
    ) -> list[WebhookSubscription]:
        return [
            WebhookSubscription(
                id=uuid.uuid4(),
                organization_id=organization_id,
                url="https://example.com/hook",
                secret_hash="hash",
                secret_encrypted="encrypted",
                event_types=[event_type],
                is_active=True,
            )
        ]


class EmptyWebhookRepository:
    def __init__(self, session: object) -> None:
        self.session = session

    async def list_active_for_event(
        self,
        organization_id: uuid.UUID,
        event_type: str,
    ) -> list[WebhookSubscription]:
        return []


class MixedWebhookRepository:
    def __init__(self, session: object) -> None:
        self.session = session

    async def list_active_for_event(
        self,
        organization_id: uuid.UUID,
        event_type: str,
    ) -> list[WebhookSubscription]:
        return [
            WebhookSubscription(
                id=uuid.uuid4(),
                organization_id=organization_id,
                url="https://example.com/no-secret",
                secret_hash="hash",
                secret_encrypted=None,
                event_types=[event_type],
                is_active=True,
            ),
            WebhookSubscription(
                id=uuid.uuid4(),
                organization_id=organization_id,
                url="http://localhost/hook",
                secret_hash="hash",
                secret_encrypted="encrypted",
                event_types=[event_type],
                is_active=True,
            ),
            WebhookSubscription(
                id=uuid.uuid4(),
                organization_id=organization_id,
                url="https://example.com/hook",
                secret_hash="hash",
                secret_encrypted="encrypted",
                event_types=[event_type],
                is_active=True,
            ),
        ]


class FakeResponse:
    status_code = 202
    text = "accepted"

    def raise_for_status(self) -> None:
        return None


class FailingResponse:
    status_code = 404
    text = "not found"

    def raise_for_status(self) -> None:
        raise httpx.HTTPStatusError(
            "not found",
            request=httpx.Request("POST", "https://example.com/hook"),
            response=httpx.Response(404),
        )


class FakeAsyncClient:
    response: object = FakeResponse()
    calls: list[tuple[str, dict[str, object], dict[str, str]]] = []

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(
        self,
        url: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
    ) -> object:
        assert headers["X-FlowForge-Signature"].startswith("sha256=")
        self.calls.append((url, json, headers))
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


class FakeDeliverySession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, item: object) -> None:
        self.added.append(item)


@pytest.mark.asyncio
async def test_deliver_webhooks_skips_missing_context_and_records_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeDeliverySession()
    organization_id = uuid.uuid4()

    await delivery.deliver_webhooks_for_outbox_event(
        session,  # type: ignore[arg-type]
        event_id=uuid.uuid4(),
        event_type="task.created",
        payload={},
    )
    assert session.added == []

    async def resolve_none(session: object, task_id: uuid.UUID) -> None:
        return None

    monkeypatch.setattr(delivery, "resolve_task_organization_id", resolve_none)
    await delivery.deliver_webhooks_for_outbox_event(
        session,  # type: ignore[arg-type]
        event_id=uuid.uuid4(),
        event_type="task.created",
        payload={"task_id": str(uuid.uuid4())},
    )
    assert session.added == []

    async def fake_resolve(session: object, task_id: uuid.UUID) -> uuid.UUID:
        return organization_id

    monkeypatch.setattr(delivery, "resolve_task_organization_id", fake_resolve)
    monkeypatch.setattr(delivery, "WebhookRepository", FakeWebhookRepository)
    monkeypatch.setattr(delivery, "is_safe_webhook_url", lambda url: True)
    monkeypatch.setattr(delivery, "decrypt_webhook_secret", lambda encrypted: "secret")
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    await delivery.deliver_webhooks_for_outbox_event(
        session,  # type: ignore[arg-type]
        event_id=uuid.uuid4(),
        event_type="task.created",
        payload={"task_id": str(uuid.uuid4())},
    )

    assert len(session.added) == 1
    assert FakeAsyncClient.calls[-1][0] == "https://example.com/hook"


@pytest.mark.asyncio
async def test_deliver_webhooks_records_http_failure_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeDeliverySession()
    organization_id = uuid.uuid4()

    async def fake_resolve(session: object, task_id: uuid.UUID) -> uuid.UUID:
        return organization_id

    FakeAsyncClient.response = FailingResponse()
    monkeypatch.setattr(delivery, "resolve_task_organization_id", fake_resolve)
    monkeypatch.setattr(delivery, "WebhookRepository", FakeWebhookRepository)
    monkeypatch.setattr(delivery, "is_safe_webhook_url", lambda url: True)
    monkeypatch.setattr(delivery, "decrypt_webhook_secret", lambda encrypted: "secret")
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    await delivery.deliver_webhooks_for_outbox_event(
        session,  # type: ignore[arg-type]
        event_id=uuid.uuid4(),
        event_type="task.created",
        payload={"task_id": str(uuid.uuid4())},
    )

    assert len(session.added) == 1
    recorded = session.added[0]
    assert isinstance(recorded, WebhookDelivery)
    assert recorded.status_code == 404
    assert recorded.response_body == "not found"
    FakeAsyncClient.response = FakeResponse()


@pytest.mark.asyncio
async def test_deliver_webhooks_skips_when_no_subscriptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeDeliverySession()

    async def fake_resolve(session: object, task_id: uuid.UUID) -> uuid.UUID:
        return uuid.uuid4()

    class FailingAsyncClient:
        def __init__(self, timeout: float) -> None:
            raise AssertionError("HTTP client should not be created")

    monkeypatch.setattr(delivery, "resolve_task_organization_id", fake_resolve)
    monkeypatch.setattr(delivery, "WebhookRepository", EmptyWebhookRepository)
    monkeypatch.setattr(httpx, "AsyncClient", FailingAsyncClient)

    await delivery.deliver_webhooks_for_outbox_event(
        session,  # type: ignore[arg-type]
        event_id=uuid.uuid4(),
        event_type="task.created",
        payload={"task_id": str(uuid.uuid4())},
    )

    assert session.added == []


@pytest.mark.asyncio
async def test_deliver_webhooks_skips_unsafe_or_unusable_subscriptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeDeliverySession()
    organization_id = uuid.uuid4()
    FakeAsyncClient.calls = []
    FakeAsyncClient.response = FakeResponse()

    async def fake_resolve(session: object, task_id: uuid.UUID) -> uuid.UUID:
        return organization_id

    monkeypatch.setattr(delivery, "resolve_task_organization_id", fake_resolve)
    monkeypatch.setattr(delivery, "WebhookRepository", MixedWebhookRepository)
    monkeypatch.setattr(
        delivery,
        "is_safe_webhook_url",
        lambda url: url == "https://example.com/hook",
    )
    monkeypatch.setattr(delivery, "decrypt_webhook_secret", lambda encrypted: "secret")
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    await delivery.deliver_webhooks_for_outbox_event(
        session,  # type: ignore[arg-type]
        event_id=uuid.uuid4(),
        event_type="task.created",
        payload={"task_id": str(uuid.uuid4())},
    )

    assert len(session.added) == 1
    assert [call[0] for call in FakeAsyncClient.calls] == ["https://example.com/hook"]


@pytest.mark.asyncio
async def test_deliver_webhooks_records_network_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeDeliverySession()
    organization_id = uuid.uuid4()
    FakeAsyncClient.calls = []
    FakeAsyncClient.response = httpx.ConnectError("connection refused")

    async def fake_resolve(session: object, task_id: uuid.UUID) -> uuid.UUID:
        return organization_id

    monkeypatch.setattr(delivery, "resolve_task_organization_id", fake_resolve)
    monkeypatch.setattr(delivery, "WebhookRepository", FakeWebhookRepository)
    monkeypatch.setattr(delivery, "is_safe_webhook_url", lambda url: True)
    monkeypatch.setattr(delivery, "decrypt_webhook_secret", lambda encrypted: "secret")
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    await delivery.deliver_webhooks_for_outbox_event(
        session,  # type: ignore[arg-type]
        event_id=uuid.uuid4(),
        event_type="task.created",
        payload={"task_id": str(uuid.uuid4())},
    )

    assert len(session.added) == 1
    recorded = session.added[0]
    assert isinstance(recorded, WebhookDelivery)
    assert recorded.status_code is None
    assert recorded.response_body == "connection refused"
    FakeAsyncClient.response = FakeResponse()


@pytest.mark.asyncio
async def test_rate_limit_middleware_allows_health_and_handles_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def call_next(request: object) -> str:
        nonlocal calls
        calls += 1
        return "ok"

    middleware = RateLimitMiddleware(app=None)  # type: ignore[arg-type]
    health_request = SimpleNamespace(
        url=SimpleNamespace(path="/health/live"),
        client=SimpleNamespace(host="127.0.0.1"),
    )
    result: Any = await middleware.dispatch(health_request, call_next)  # type: ignore[arg-type]
    assert result == "ok"

    class FakeRedis:
        def __init__(self, value: int | BaseException) -> None:
            self.value = value

        async def incr(self, key: str) -> int:
            if isinstance(self.value, BaseException):
                raise self.value
            return self.value

        async def expire(self, key: str, seconds: int) -> None:
            assert seconds == settings.rate_limit_window_seconds

    request = SimpleNamespace(
        url=SimpleNamespace(path="/api/v1/tasks"),
        client=SimpleNamespace(host="127.0.0.1"),
    )
    monkeypatch.setattr("src.infrastructure.rate_limit.redis_client", FakeRedis(1))
    result = await middleware.dispatch(request, call_next)  # type: ignore[arg-type]
    assert result == "ok"

    monkeypatch.setattr(
        "src.infrastructure.rate_limit.redis_client",
        FakeRedis(settings.rate_limit_requests + 1),
    )
    with pytest.raises(RateLimitExceededError):
        await middleware.dispatch(request, call_next)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "src.infrastructure.rate_limit.redis_client",
        FakeRedis(RedisError("redis unavailable")),
    )
    result = await middleware.dispatch(request, call_next)  # type: ignore[arg-type]
    assert result == "ok"
