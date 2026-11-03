"""Service-to-service authentication for mutating nexus-ml endpoints."""
from __future__ import annotations

import hmac
import os

from fastapi import HTTPException


def verify_internal_service_secret(provided_secret: str | None) -> None:
    expected = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
    if not expected:
        raise HTTPException(503, "NEXUS_INTERNAL_API_SECRET is not configured")
    if not provided_secret or not hmac.compare_digest(expected, provided_secret):
        raise HTTPException(403, "invalid internal service credential")
