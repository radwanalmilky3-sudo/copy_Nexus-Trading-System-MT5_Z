from __future__ import annotations

import pytest
from fastapi import HTTPException

from services.nexus_api.middleware.auth import create_token, verify_token


@pytest.mark.parametrize("secret", ["", "change-me-jwt-secret", "short"])
def test_jwt_token_creation_rejects_insecure_secret(monkeypatch, secret):
    monkeypatch.setenv("NEXUS_JWT_SECRET", secret)

    with pytest.raises(HTTPException) as exc:
        create_token("user-1")

    assert exc.value.status_code == 503
    assert "NEXUS_JWT_SECRET" in exc.value.detail


def test_jwt_token_works_with_strong_configured_secret(monkeypatch):
    monkeypatch.setenv("NEXUS_JWT_SECRET", "a-long-random-jwt-secret-with-at-least-32-chars")

    assert verify_token(create_token("user-1")) == "user-1"
