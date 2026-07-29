from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.auth.router import router as auth_router
from src.common.exceptions import AppError
from src.common.schemas import ErrorPayload, ErrorResponse
from src.config import settings
from src.database import dispose_engine
from src.infrastructure.health import router as health_router
from src.infrastructure.logging import configure_logging
from src.infrastructure.middleware import RequestContextMiddleware
from src.infrastructure.rate_limit import RateLimitMiddleware
from src.infrastructure.redis import close_redis
from src.infrastructure.request_context import get_request_id
from src.organizations.router import router as organizations_router
from src.projects.router import router as projects_router
from src.tasks.router import router as tasks_router
from src.webhooks.router import router as webhooks_router

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await close_redis()
    await dispose_engine()


app = FastAPI(
    title=settings.app_name,
    debug=settings.app_debug,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(origin) for origin in settings.app_cors_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestContextMiddleware)


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorPayload(code=exc.code, message=exc.message, details=exc.details),
        request_id=get_request_id(),
    )
    return JSONResponse(
        status_code=exc.status_code, content=payload.model_dump(mode="json")
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorPayload(
            code="internal_server_error", message="Internal server error"
        ),
        request_id=get_request_id(),
    )
    return JSONResponse(status_code=500, content=payload.model_dump(mode="json"))


@app.get("/api/v1", tags=["meta"])
async def api_root() -> dict[str, Any]:
    return {"name": settings.app_name, "version": "v1"}


@app.get("/health/live", tags=["health"])
async def health_live() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(organizations_router)
app.include_router(projects_router)
app.include_router(tasks_router)
app.include_router(webhooks_router)
app.include_router(health_router)
