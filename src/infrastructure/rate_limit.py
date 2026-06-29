from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware

from src.common.exceptions import RateLimitExceededError
from src.config import settings
from src.infrastructure.redis import redis_client


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(
            self,
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path.startswith("/health"):
            return await call_next(request)
        
        client = request.client.host if request.client else "unknown"
        key = f"rate_limit:{client}:{request.url.path}"

        try:
            current = await redis_client.incr(key)
            if current == 1:
                await redis_client.expire(key, settings.rate_limit_window_seconds)
            if current > settings.rate_limit_requests:
                raise RateLimitExceededError()
        except RedisError:
            return await call_next(request)
        return await call_next(request)