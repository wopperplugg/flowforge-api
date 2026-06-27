from typing import Annotated

from fastapi import APIRouter, Depends, status
from redis.asyncio import Redis
from sqlalchemy import text

from src.common.dependencies import DbSession
from src.infrastructure.redis import get_redis

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", status_code=status.HTTP_200_OK)
async def liveness() -> dict[str, str]:
    return {"status", "ok"}


@router.get("/ready", status_code=status.HTTP_200_OK)
async def readiness(
    db: DbSession,
    redis: Annotated[Redis, Depends(get_redis)],
) -> dict[str, str]:
    await db.execute(text("select 1"))
    await redis.ping()
    return {"status", "ok"}