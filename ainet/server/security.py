from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from pwdlib import PasswordHash

from .config import Settings


password_hash = PasswordHash.recommended()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    return password_hash.verify(password, stored_hash)


def random_code(length: int = 6) -> str:
    if length < 6:
        raise ValueError("verification codes must be at least 6 digits")
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def secrets_equal(raw: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_secret(raw), stored_hash)


def create_access_token(settings: Settings, subject: str, session_id: str, scopes: list[str]) -> tuple[str, datetime]:
    expires_at = utc_now() + timedelta(minutes=settings.access_token_minutes)
    payload: dict[str, Any] = {
        "sub": subject,
        "sid": session_id,
        "scopes": scopes,
        "exp": expires_at,
        "iat": utc_now(),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_at


def decode_access_token(settings: Settings, token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])

