import hashlib
import hmac

from src.config import settings


def hash_refresh_token(token: str) -> str:
    return hmac.new(
        settings.app_secret_key.get_secret_value().encode(),
        token.encode(),
        hashlib.sha256,
    ).hexdigest()


def verify_refresh_token_hash(token: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_refresh_token(token), token_hash)
