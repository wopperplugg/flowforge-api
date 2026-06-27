from typing import Any


class AppError(Exception):
    code = "app_error"
    message = "Application error"
    status_code = 500

    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        self.details = details or {}


class PermissionDeniedError(AppError):
    code = "permission_denied"
    message = "Permission denied"
    status_code = 403


class RateLimitExceededError(AppError):
    code = "rate_limit_exceeded"
    message = "Too many requests"
    status_code = 429


class IdempotencyConflictError(AppError):
    code = "idempotency_conflict"
    message = "Idempotency key conflict"
    status_code = 409


class InvalidCredentialsError(AppError):
    code = "invalid_credentials"
    message = "Invalid email or password"
    status_code = 401


class InvalidTokenError(AppError):
    code = "invalid_token"
    message = "Invalid token"
    status_code = 401


class ExpiredTokenError(AppError):
    code = "expired_token"
    message = "Token has expired"
    status_code = 401
