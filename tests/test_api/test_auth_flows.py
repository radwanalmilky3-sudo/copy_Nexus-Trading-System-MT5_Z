"""Auth flow tests — plan item 246.

login / me / session-expiry / logout / password-wrong against stubbed data
services only: auth failures must surface as 401/403 while a data-service
outage stays 503 (see test_admin_data_service), and no test may write to the
real user store — every data path is stubbed or captured in-memory.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from httpx import AsyncClient

from services.nexus_api.deps import get_data_service
from services.nexus_api.main import app
from services.nexus_api.middleware.auth import create_token
from services.nexus_api.routers import admin as admin_router
from services.nexus_api.routers.admin import _hash_password

_TEST_JWT_SECRET = "test-jwt-secret-long-enough-for-hs256"


class _RecordingDataService:
    """In-memory query stub: records calls, fails on any unexpected op."""

    def __init__(self, responses: dict | None = None) -> None:
        self._responses = responses or {}
        self.calls: list[tuple[str, dict | None]] = []

    async def query(self, operation: str, params=None):
        self.calls.append((operation, params))
        if operation in self._responses:
            return self._responses[operation]
        raise AssertionError(f"data service must not be queried for {operation!r}")


def _install(service: _RecordingDataService) -> None:
    app.dependency_overrides[get_data_service] = lambda: service


def _capture_writes(monkeypatch) -> list:
    writes: list[tuple[str, dict]] = []

    async def _capture(table: str, record: dict) -> None:
        writes.append((table, record))

    monkeypatch.setattr(admin_router, "_post_data", _capture)
    return writes


@pytest.fixture()
def jwt_secret(monkeypatch) -> str:
    monkeypatch.setenv("NEXUS_JWT_SECRET", _TEST_JWT_SECRET)
    return _TEST_JWT_SECRET


@pytest.mark.asyncio
async def test_login_rejects_unknown_user_with_401_before_any_write(api_client):
    service = _RecordingDataService({"user_by_username": []})
    _install(service)

    response = await api_client.post(
        "/api/v2/auth/login",
        json={"username": "ghost", "password": "whatever-password"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials"}
    assert [op for op, _ in service.calls] == ["user_by_username"]


@pytest.mark.asyncio
async def test_login_rejects_wrong_password_with_401(api_client):
    stored_hash = _hash_password("correct-horse-battery-staple")
    service = _RecordingDataService(
        {
            "user_by_username": [
                {
                    "user_id": "u-1",
                    "username": "ridwan",
                    "full_name": "Ridwan",
                    "active": True,
                    "password_hash": stored_hash,
                }
            ]
        }
    )
    _install(service)

    response = await api_client.post(
        "/api/v2/auth/login",
        json={"username": "ridwan", "password": "totally-wrong-pass"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials"}
    assert [op for op, _ in service.calls] == ["user_by_username"]


@pytest.mark.asyncio
async def test_login_rejects_inactive_user_with_401_without_password_check(api_client):
    service = _RecordingDataService(
        {
            "user_by_username": [
                {
                    "user_id": "u-2",
                    "username": "ridwan",
                    "full_name": "Ridwan",
                    "active": False,
                    "password_hash": "scrypt$n=1$unused",
                }
            ]
        }
    )
    _install(service)

    response = await api_client.post(
        "/api/v2/auth/login",
        json={"username": "ridwan", "password": "whatever-password"},
    )

    assert response.status_code == 401
    assert [op for op, _ in service.calls] == ["user_by_username"]


@pytest.mark.asyncio
async def test_login_success_returns_token_and_captures_only_last_login_write(
    api_client, monkeypatch, jwt_secret
):
    stored_hash = _hash_password("correct-horse-battery-staple")
    service = _RecordingDataService(
        {
            "user_by_username": [
                {
                    "user_id": "u-1",
                    "username": "ridwan",
                    "full_name": "Ridwan",
                    "active": True,
                    "password_hash": stored_hash,
                }
            ],
            "user_role_ids": [{"role_id": "super_admin"}],
        }
    )
    _install(service)
    writes = _capture_writes(monkeypatch)

    response = await api_client.post(
        "/api/v2/auth/login",
        json={"username": "ridwan", "password": "correct-horse-battery-staple"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["role"] == "super_admin"
    # Token verifies under the test secret.
    payload = pyjwt.decode(
        body["token"], _TEST_JWT_SECRET, algorithms=["HS256"]
    )
    assert payload["user_id"] == "u-1"
    # The only write is the captured last-login update; nothing reaches the
    # real store.
    assert [table for table, _ in writes] == ["app_users"]
    assert writes[0][1]["user_id"] == "u-1"
    assert "last_login_at" in writes[0][1]


@pytest.mark.asyncio
async def test_expired_token_is_rejected_401_before_any_data_query(
    api_client, jwt_secret
):
    service = _RecordingDataService()  # empty: any query would raise
    _install(service)
    expired = pyjwt.encode(
        {
            "user_id": "u-1",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        jwt_secret,
        algorithm="HS256",
    )

    response = await api_client.get(
        "/api/v2/auth/me", headers={"Authorization": f"Bearer {expired}"}
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Token expired"}
    assert service.calls == []


@pytest.mark.asyncio
async def test_logout_without_token_is_401(api_client, monkeypatch):
    writes = _capture_writes(monkeypatch)

    response = await api_client.post("/api/v2/auth/logout")

    assert response.status_code == 401
    assert writes == []


@pytest.mark.asyncio
async def test_logout_with_valid_token_captures_audit_instead_of_real_write(
    api_client, monkeypatch, jwt_secret
):
    writes = _capture_writes(monkeypatch)
    token = create_token("u-1")

    response = await api_client.post(
        "/api/v2/auth/logout", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert [table for table, _ in writes] == ["user_audit_log"]
    assert writes[0][1]["action"] == "auth.logout"
    assert writes[0][1]["actor_user_id"] == "u-1"


@pytest.mark.asyncio
async def test_bootstrap_rejects_wrong_pin_before_touching_data(api_client, monkeypatch):
    monkeypatch.setenv("NEXUS_ADMIN_PIN", "test-admin-pin-0001")
    service = _RecordingDataService()  # empty: any query would raise
    _install(service)

    response = await api_client.post(
        "/api/v2/auth/bootstrap",
        json={
            "admin_pin": "wrong-pin-9999",
            "username": "first",
            "full_name": "First Admin",
            "password": "long-enough-password",
        },
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Invalid PIN"}
    assert service.calls == []


@pytest.mark.asyncio
async def test_bootstrap_after_first_run_is_409_without_creating_any_user(
    api_client, monkeypatch
):
    monkeypatch.setenv("NEXUS_ADMIN_PIN", "test-admin-pin-0001")
    service = _RecordingDataService({"bootstrap_user_count": [{"c": 1}]})
    _install(service)
    writes = _capture_writes(monkeypatch)

    response = await api_client.post(
        "/api/v2/auth/bootstrap",
        json={
            "admin_pin": "test-admin-pin-0001",
            "username": "second",
            "full_name": "Second Admin",
            "password": "long-enough-password",
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "bootstrap already completed"}
    assert writes == []
    assert [op for op, _ in service.calls] == ["bootstrap_user_count"]
