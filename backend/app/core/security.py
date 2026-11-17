import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings


password_hash = PasswordHash.recommended()
ACCESS_TOKEN_MINUTES = 15
SESSION_LIFETIME_DAYS = 30
JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        return password_hash.verify(password, encoded_hash)
    except Exception:
        return False


def create_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(user_id: int, session_id: uuid.UUID) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "sid": str(session_id),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_MINUTES),
        "jti": str(uuid.uuid4()),
        "typ": "access",
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=JWT_ALGORITHM, headers={"kid": settings.jwt_key_id})


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    header = jwt.get_unverified_header(token)
    if header.get("alg") != JWT_ALGORITHM:
        raise jwt.InvalidAlgorithmError("Unsupported algorithm")
    key_id = header.get("kid")
    keyring = {settings.jwt_key_id: settings.jwt_secret_key}
    for entry in settings.jwt_previous_keys.split(","):
        if "=" in entry:
            kid, secret = entry.split("=", 1)
            if kid.strip() and secret.strip() and kid.strip() != settings.jwt_key_id:
                keyring[kid.strip()] = secret.strip()
    key = keyring.get(key_id)
    if key is None:
        raise jwt.InvalidTokenError("Unknown signing key")
    return jwt.decode(
        token,
        key,
        algorithms=[JWT_ALGORITHM],
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        options={"require": ["sub", "sid", "iss", "aud", "iat", "exp", "jti", "typ"]},
    )


def refresh_expiry(session_expiry: datetime) -> datetime:
    now = datetime.now(UTC)
    return min(now + timedelta(days=SESSION_LIFETIME_DAYS), session_expiry)
