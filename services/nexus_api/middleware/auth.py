"""JWT authentication helpers + unified administrative PIN verification."""
from __future__ import annotations

import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from pydantic import BaseModel

from shared.safety import is_secure_jwt_secret

_JWT_ALGORITHM = "HS256"
_JWT_EXPIRE_HOURS = int(os.getenv("NEXUS_JWT_EXPIRE_HOURS", "24"))


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


def create_token(user_id: str) -> str:
    payload = {
        "user_id": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=_JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=_JWT_ALGORITHM)


def verify_token(token: str) -> str:
    try:
        data = jwt.decode(token, _jwt_secret(), algorithms=[_JWT_ALGORITHM])
        user_id: str | None = data.get("user_id")
        if user_id is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token payload")
        return user_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    if authorization is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing Authorization header")
    # RFC 7235 allows one or more spaces after the auth-scheme, and some
    # clients/proxies add stray whitespace; strip before verifying so a
    # legitimately signed token is not rejected with a spurious 401.
    scheme, _, token = authorization.strip().partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid auth scheme")
    return verify_token(token.strip())


CurrentUser = Annotated[str, Depends(get_current_user)]


def verify_pin(pin: str) -> None:
    """Verify the single documented ``NEXUS_ADMIN_PIN``; no insecure fallback."""
    expected = os.getenv("NEXUS_ADMIN_PIN", "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "NEXUS_ADMIN_PIN is not configured")
    if not hmac.compare_digest(str(pin), expected):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid PIN")
