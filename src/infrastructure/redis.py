from collections.abc import AsyncIterator

from redis.asyncio import Redis

from src.config import settings

redis_client: Redis = Redis.from_url(
    str(settings.redis_dsn),
    encoding="utf-8",
    decode_response=True,
)

async def get_redis() -> AsyncIterator[Redis]:
    yield redis_client

async def close_redis() -> None:
    await redis_client.aclose()