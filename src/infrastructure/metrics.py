import time
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware

HTTP_REQUESTS_TOTAL = Counter(
    "flowforge_http_requests_total",
    "Total number of HTTP requests",
    ["method", "path", "status_code"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "flowforge_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
)

OUTBOX_EVENTS_PUBLISHED_TOTAL = Counter(
    "flowforge_outbox_events_published_total",
    "Successfully published outbox events",
    ["event_type"],
)

OUTBOX_PUBLISH_FAILURES_TOTAL = Counter(
    "flowforge_outbox_publish_failures_total",
    "Failed outbox publication attempts",
    ["event_type"],
)

OUTBOX_PENDING_EVENTS = Gauge(
    "flowforge_outbox_pending_events",
    "Current number of pending outbox events",
)

WEBHOOK_MESSAGES_PROCESSED_TOTAL = Counter(
    "flowforge_webhook_messages_processed_total",
    "Processed RabbitMQ webhook messages",
    ["event_type", "result"],
)

WEBHOOK_RETRIES_TOTAL = Counter(
    "flowforge_webhook_retries_total",
    "Webhook messages scheduled for retry",
    ["retry_number"],
)

WEBHOOK_DLQ_TOTAL = Counter(
    "flowforge_webhook_dlq_total",
    "Webhook messages sent to the dead-letter queue",
    ["reason"],
)

WEBHOOK_PROCESSING_DURATION_SECONDS = Histogram(
    "flowforge_webhook_processing_duration_seconds",
    "Webhook message processing duration",
    ["event_type"],
)

router = APIRouter(tags=["metrics"])


def get_route_path(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str):
        return path
    return request.url.path


class PrometheusMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path == "/metrics":
            return await call_next(request)

        started_at = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            HTTP_REQUESTS_TOTAL.labels(
                method=request.method,
                path=get_route_path(request),
                status_code="500",
            ).inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(
                method=request.method,
                path=get_route_path(request),
            ).observe(time.perf_counter() - started_at)
            raise

        HTTP_REQUESTS_TOTAL.labels(
            method=request.method,
            path=get_route_path(request),
            status_code=str(response.status_code),
        ).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(
            method=request.method,
            path=get_route_path(request),
        ).observe(time.perf_counter() - started_at)

        return response


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
