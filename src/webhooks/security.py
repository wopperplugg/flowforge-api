import hashlib 
import hmac
import ipaddress
import json
import secrets
import socket
from base64 import urlsafe_b64encode
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken

from src.config import settings

DISALLOWED_HOSTNAMES = {"localhost", "localhost.localdomain"}

def _webhook_secret_cipher() -> Fernet:
    source_key = settings.webhook_secret_encryption_key or settings.app_secret_key
    key = hashlib.sha256(source_key.encode()).digest()
    return Fernet(urlsafe_b64encode(key))

def generate_webhook_secret() -> str:
    return secrets.token_urlsafe(32)

def hash_webhook_secret(secret: str) -> str:
    return hmac.new(
        settings.app_secret_key.encode(),
        secret.encode(),
        hashlib.sha256,
    ).hexdigest()

def encrypt_webhook_secret(secret: str) -> str:
    return _webhook_secret_cipher().encrypt(secret.encode()).decode()

def decrypt_webhook_secret(encrypted_secret: str) -> str:
    try: 
        return _webhook_secret_cipher().decrypt(encrypted_secret.encode()).decode()
    except InvalidToken as exc:
        msg = "Invalid webhook secret ciphertext"
        raise ValueError(msg) from exc
    
def sign_webhook_payload(secret: str, timestamp: int, payload: dict[str, object]):
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    message = f"{timestamp}.{body}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()

def is_safe_webhook_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if settings.app_env == "production" and parsed.scheme !="https":
        return False
    if parsed.username or parsed.password:
        return False
    if parsed.hostname.lower() in DISALLOWED_HOSTNAMES:
        return False
    try:
        ip = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return _hostname_resolves_to_public_addresses(parsed.hostname)
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast)
    


def _hostname_resolves_to_public_addresses(hostname: str) -> bool:
    try: 
        addresses = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False
    resolved_ips = {str(item[4][0] for item in addresses)}
    if not resolved_ips:
        return False
    return all(_is_public_ip(address) for address in resolved_ips)

def _is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )