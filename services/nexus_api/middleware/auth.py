"""JWT authentication helpers + unified administrative PIN verification.

D14/D15 (owner decision 2026-11-05):
  * ``create_token`` mints typed tokens (``access`` / ``refresh``) carrying a
    unique ``jti`` so individual tokens can be revoked server-side.
  * A Redis-backed denylist (``auth:denylist:<jti>``) is consulted on every
    authenticated HTTP request; ``POST /api/v2/auth/logout`` writes the
    presented token's ``jti`` there with a TTL equal to its remaining life.
  * ``POST /api/v2/auth/refresh`` (routers/admin.py) rotates refresh tokens
    through the same denylist, making every refresh token single-use.

Denylist availability contract (deliberate, documented): if Redis is briefly
unreachable the check fails OPEN with the entry treated as absent — a
paper-trading platform must not lock its operator out on an infra blip, and
the hard ``exp`` cap (24h access / 168h refresh) still bounds the exposure
window. The logout and refresh *writes* report ``revoked=false`` on failure
instead of crashing.
"""
from __future__ import annotations

import hmac
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header, HTTPException, status
from pydantic import BaseModel

from shared.safety import is_secure_jwt_secret

from ..deps import get_redis
from shared.redis_client import RedisClient

_JWT_ALGORITHM = "HS256"
_JWT_EXPIRE_HOURS = int(os.getenv("NEXUS_JWT_EXPIRE_HOURS", "24"))
_REFRESH_EXPIRE_HOURS = int(os.getenv("NEXUS_JWT_REFRESH_EXPIRE_HOURS", "168"))

_DENYLIST_PREFIX = "auth:denylist"


class TokenPayload(BaseModel):
    user_id: str
    exp: datetime


def _jwt_secret() -> str:
    secret = os.getenv("NEXUS_JWT_SECRET", "").strip()
    if not is_secure_jwt_secret(secret):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "NEXUS_JWT_SECRET is not configured securely",
        )
    return secret


def create_token(user_id: str, *, token_type: str = "access") -> str:
    """Mint a signed JWT with a unique ``jti`` and an explicit ``token_type``."""
    hours = _REFRESH_EXPIRE_HOURS if token_type == "refresh" else _JWT_EXPIRE_HOURS
    payload = {
        "user_id": user_id,
        "token_type": token_type,
        "jti": uuid.uuid4().hex,
        "exp": datetime.now(timezone.utc) + timedelta(hours=hours),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=_JWT_ALGORITHM)


def decode_token(token: str, *, expected_type: str | None = None) -> dict[str, Any]:
    """Decode + verify a JWT and return the full payload.

    ``expected_type`` enforces the ``token_type`` claim when given. Tokens
    minted before D14 carry no ``token_type``; they verify only as access
    tokens (and cannot be used against the refresh endpoint).
    """
    try:
        data = jwt.decode(token, _jwt_secret(), algorithms=[_JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    if data.get("user_id") is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token payload")
    if expected_type is not None and data.get("token_type", "access") != expected_type:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token type")
    return data


def verify_token(token: str) -> str:
    return str(decode_token(token)["user_id"])


# ── D15: server-side revocation (Redis denylist) ────────────────────────────

async def denylist_add(redis: Any, jti: str, ttl_sec: int) -> bool:
    """Add a token id to the logout denylist. True = stored, False = skipped."""
    if not jti or ttl_sec <= 0:
        return False
    try:
        await redis.cache_set(
            f"{_DENYLIST_PREFIX}:{jti}", True, ttl_sec=max(1, int(ttl_sec))
        )
        return True
    except Exception:  # noqa: BLE001 — revocation must not crash logout
        return False


async def denylist_is_denied(redis: Any, jti: str) -> bool:
    """True when the jti was revoked and its entry has not expired yet.

    Fails OPEN (False) when Redis is unreachable: see module docstring.
    """
    if not jti:
        return False
    try:
        return await redis.cache_get(f"{_DENYLIST_PREFIX}:{jti}") is not None
    except Exception:  # noqa: BLE001 — fail-open availability contract
        return False


def _bearer_token(authorization: str | None) -> str:
    """Extract the raw token from a Bearer header ("" when absent/malformed)."""
    scheme, _, token = (authorization or "").strip().partition(" ")
    if scheme.lower() != "bearer" or not token:
        return ""
    return token.strip()


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    redis: RedisClient = Depends(get_redis),
) -> str:
    """FastAPI dependency: validate the Bearer token and enforce revocation."""
    if authorization is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing Authorization header")
    # RFC 7235 allows one or more spaces after the auth-scheme, and some
    # clients/proxies add stray whitespace; strip before verifying so a
    # legitimately signed token is not rejected with a spurious 401.
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid auth scheme")
    payload = decode_token(token)
    if await denylist_is_denied(redis, str(payload.get("jti") or "")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token revoked (logged out)")
    return str(payload["user_id"])


CurrentUser = Annotated[str, Depends(get_current_user)]


def verify_pin(pin: str) -> None:
    """Verify the single documented ``NEXUS_ADMIN_PIN``; no insecure fallback."""
    expected = os.getenv("NEXUS_ADMIN_PIN", "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "NEXUS_ADMIN_PIN is not configured")
    if not hmac.compare_digest(str(pin), expected):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid PIN")
