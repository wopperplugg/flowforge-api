import uuid 
from datetime import UTC, datetime, timedelta
from typing import Literal
import jwt
from src.common.exceptions import ExpiredTokenError, InvalidTokenError
from src.config import settings

TokenType = Literal["access", "refresh"]

def create_access_token(subject: uuid.UUID) -> tuple[str, int]:
    now = datetime.now(UTC)
    expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
    expires_at = now + expires_delta
    expires_in = int(expires_delta.total_seconds())

    payload = {
        "sub": str(subject),
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "nbf": now,
        "exp": expires_at,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    token = jwt.encode(payload, settings.app_secret_key.get_secret_value(), algorithm="HS256")
    return token, expires_in

def create_refresh_token(
        subject: uuid.UUID,
        *,
        family_id: uuid.UUID | None = None,
        jti: uuid.UUID | None = None,
) -> tuple[str, uuid.UUID, uuid.UUID, datetime]:
    now = datetime.now(UTC)
    token_family_id = family_id or uuid.uuid4()
    token_jti = jti or uuid.uuid4()
    expires_at = now + timedelta(days=settings.refresh_token_expire_days)

    payload = {
        "sub": str(subject),
        "type": "refresh",
        "jti": str(token_jti),
        "fid": str(token_family_id),
        "iat": now,
        "nbf": now,
        "exp": expires_at,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    token = jwt.encode(payload, settings.app_secret_key.get_secret_value(), algorithm="HS256")
    return token, token_jti, token_family_id, expires_at

def decode_token(token: str, expected_type: TokenType) -> dict[str, object]:
    try:
        payload = jwt.decode(
            token,
            settings.app_secret_key.get_secret_value(),
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
        )
    except jwt.ExpiredSignatureError as exc:
        raise ExpiredTokenError() from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError() from exc
    
    if payload.get("type") != expected_type:
        raise InvalidTokenError()
    
    return payload