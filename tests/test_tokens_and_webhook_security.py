import socket
import uuid
from datetime import UTC, datetime, timedelta
from socket import gaierror

import jwt
import pytest

from src.auth.security import hash_refresh_token, verify_refresh_token_hash
from src.auth.tokens import create_access_token, create_refresh_token, decode_token
from src.common.exceptions import ExpiredTokenError, InvalidTokenError
from src.config import settings
from src.webhooks import security as webhook_security


def test_access_and_refresh_tokens_round_trip() -> None:
    user_id = uuid.uuid4()
    family_id = uuid.uuid4()
    refresh_jti = uuid.uuid4()

    access_token, expires_in = create_access_token(user_id)
    refresh_token, returned_jti, returned_family_id, expires_at = create_refresh_token(
        user_id,
        family_id=family_id,
        jti=refresh_jti,
    )

    access_payload = decode_token(access_token, expected_type="access")
    refresh_payload = decode_token(refresh_token, expected_type="refresh")

    assert expires_in == settings.access_token_expire_minutes * 60
    assert access_payload["sub"] == str(user_id)
    assert refresh_payload["sub"] == str(user_id)
    assert returned_jti == refresh_jti
    assert returned_family_id == family_id
    assert expires_at > datetime.now(UTC)


def test_decode_token_rejects_wrong_type_and_expired_token() -> None:
    user_id = uuid.uuid4()
    access_token, _ = create_access_token(user_id)
    expired_token = jwt.encode(
        {
            "sub": str(user_id),
            "type": "access",
            "jti": str(uuid.uuid4()),
            "iat": datetime.now(UTC) - timedelta(hours=2),
            "nbf": datetime.now(UTC) - timedelta(hours=2),
            "exp": datetime.now(UTC) - timedelta(hours=1),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
        },
        settings.app_secret_key.get_secret_value(),
        algorithm="HS256",
    )

    with pytest.raises(InvalidTokenError):
        decode_token(access_token, expected_type="refresh")

    with pytest.raises(ExpiredTokenError):
        decode_token(expired_token, expected_type="access")

    with pytest.raises(InvalidTokenError):
        decode_token("not-a-jwt", expected_type="access")


def test_refresh_token_hash_uses_constant_time_compare() -> None:
    token = "refresh-token"
    token_hash = hash_refresh_token(token)

    assert verify_refresh_token_hash(token, token_hash) is True
    assert verify_refresh_token_hash("other-token", token_hash) is False


def test_webhook_secret_crypto_and_signature_round_trip() -> None:
    secret = webhook_security.generate_webhook_secret()
    encrypted = webhook_security.encrypt_webhook_secret(secret)
    payload: dict[str, object] = {"task_id": "123", "status": "done"}

    assert webhook_security.decrypt_webhook_secret(encrypted) == secret
    assert webhook_security.hash_webhook_secret(secret) != secret
    assert webhook_security.sign_webhook_payload(secret, 1234567890, payload)

    with pytest.raises(ValueError, match="Invalid webhook secret ciphertext"):
        webhook_security.decrypt_webhook_secret("invalid-ciphertext")


def test_webhook_url_safety_checks_dns_and_ip_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "app_env", "local")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (None, None, None, None, ("93.184.216.34", 443)),
        ],
    )

    assert webhook_security.is_safe_webhook_url("https://93.184.216.34/hook") is True
    assert webhook_security.is_safe_webhook_url("https://example.com/hook") is True
    assert webhook_security.is_safe_webhook_url("https://10.0.0.1/hook") is False
    assert webhook_security.is_safe_webhook_url("https://localhost/hook") is False
    assert (
        webhook_security.is_safe_webhook_url("https://user:pass@example.com") is False
    )
    assert webhook_security.is_safe_webhook_url("ftp://example.com/hook") is False

    monkeypatch.setattr(settings, "app_env", "production")
    assert webhook_security.is_safe_webhook_url("http://example.com/hook") is False

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (None, None, None, None, ("93.184.216.34", 443)),
            (None, None, None, None, ("127.0.0.1", 443)),
        ],
    )
    assert webhook_security.is_safe_webhook_url("https://example.com/hook") is False

    def raise_gaierror(*args: object, **kwargs: object) -> None:
        raise gaierror

    monkeypatch.setattr(socket, "getaddrinfo", raise_gaierror)
    assert webhook_security.is_safe_webhook_url("https://example.invalid/hook") is False
