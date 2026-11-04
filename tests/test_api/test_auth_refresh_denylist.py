"""D14/D15 acceptance tests — refresh-token flow + server-side logout denylist.

Owner decision (2026-11-05): implement Redis-backed revocation (D15) and the
/api/v2/auth/refresh endpoint (D14). Everything runs against the api_client
fixture (FakeRedis-backed get_redis + stubbed data service), so no test can
reach the real stores.

Covers (maps to API_TEST_REPORT TC-AU-06/TC-AU-07 retest):
  D14: login returns a refresh_token; refresh rotates it single-use;
       access tokens are rejected as refresh credentials.
  D15: logout denylists the presented access token (next /me is 401);
       legacy jti-less tokens still authenticate (upgrade tolerance);
       Redis outage fails OPEN on the read path and logout stays 200.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from httpx import AsyncClient

from services.nexus_api.deps import get_data_service, get_redis
from services.nexus_api.main import app
from services.nexus_api.middleware.auth import (
    _DENYLIST_PREFIX,
    create_token,
    decode_token,
)
from services.nexus_api.routers import admin as _admin_router
from services.nexus_api.routers.admin import _hash_password

_TEST_JWT_SECRET = "test-jwt-secret-long-enough-for-hs256"

_USER = {
    "user_id": "u-1",
    "username": "ridwan",
    "full_name": "Ridwan",
    "active": True,
    "password_hash": _hash_password("correct-horse-battery-staple"),
}


def _install(responses: dict) -> list:
    """Stub the data service with per-operation responses; record calls.

    ``_post_data`` is captured in-memory (no real writes, no internal secret
    needed) — same discipline as test_auth_flows.py.
    """
    calls: list[tuple[str, dict | None]] = []

    async def _query(operation: str, params=None):
        calls.append((operation, params))
        if operation in responses:
            return responses[operation]
        return []

    async def _capture_post(table: str, record: dict) -> None:
        calls.append(("POST:" + table, record))

    app.dependency_overrides[get_data_service] = lambda: _FakeDataService(_query)
    _patcher = pytest.MonkeyPatch()
    _patcher.setattr(_admin_router, "_post_data", _capture_post)
    return calls


class _FakeDataService:
    def __init__(self, query) -> None:
        self._query = query

    async def query(self, operation: str, params=None):
        return await self._query(operation, params)


@pytest.fixture()
def jwt_secret(monkeypatch) -> str:
    monkeypatch.setenv("NEXUS_JWT_SECRET", _TEST_JWT_SECRET)
    return _TEST_JWT_SECRET


async def _login(api_client: AsyncClient) -> dict:
    response = await api_client.post(
        "/api/v2/auth/login",
        json={"username": "ridwan", "password": "correct-horse-battery-staple"},
    )
    assert response.status_code == 200
    return response.json()


# ── D14: refresh endpoint ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_returns_typed_token_pair_with_expiry(api_client, jwt_secret):
    _install({"user_by_username": [_USER], "user_role_ids": [{"role_id": "super_admin"}]})
    body = await _login(api_client)

    access = pyjwt.decode(body["token"], _TEST_JWT_SECRET, algorithms=["HS256"])
    refresh = pyjwt.decode(body["refresh_token"], _TEST_JWT_SECRET, algorithms=["HS256"])
    assert access["token_type"] == "access" and refresh["token_type"] == "refresh"
    assert access["jti"] and refresh["jti"] and access["jti"] != refresh["jti"]
    # refresh outlives access by ~6 days (168h vs 24h)
    assert refresh["exp"] - access["exp"] > 100 * 3600
    assert body["expiresAt"] and body["refreshExpiresAt"]


@pytest.mark.asyncio
async def test_refresh_rotates_to_fresh_pair(api_client, jwt_secret):
    _install({"user_by_username": [_USER]})
    body = await _login(api_client)

    response = await api_client.post(
        "/api/v2/auth/refresh", json={"refresh_token": body["refresh_token"]}
    )

    assert response.status_code == 200
    rotated = response.json()
    assert rotated["token"] and rotated["token"] != body["token"]
    assert rotated["refresh_token"] != body["refresh_token"]
    # both rotated tokens verify and are correctly typed
    assert decode_token(rotated["token"], expected_type="access")["user_id"] == "u-1"
    assert decode_token(rotated["refresh_token"], expected_type="refresh")["user_id"] == "u-1"


@pytest.mark.asyncio
async def test_refresh_token_is_single_use_replay_is_401(api_client, jwt_secret):
    _install({"user_by_username": [_USER]})
    body = await _login(api_client)

    first = await api_client.post(
        "/api/v2/auth/refresh", json={"refresh_token": body["refresh_token"]}
    )
    assert first.status_code == 200

    replay = await api_client.post(
        "/api/v2/auth/refresh", json={"refresh_token": body["refresh_token"]}
    )
    assert replay.status_code == 401
    assert replay.json() == {"detail": "Refresh token revoked"}


@pytest.mark.asyncio
async def test_refresh_rejects_access_token_as_credentials(api_client, jwt_secret):
    _install({"user_by_username": [_USER]})
    body = await _login(api_client)

    response = await api_client.post(
        "/api/v2/auth/refresh", json={"refresh_token": body["token"]}
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid refresh token"}


@pytest.mark.asyncio
async def test_refresh_rejects_garbage_and_legacy_tokens(api_client, jwt_secret):
    _install({})  # endpoint must reject before any data access
    legacy = pyjwt.encode(  # pre-D14 token: no token_type claim
        {"user_id": "u-1",
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        _TEST_JWT_SECRET, algorithm="HS256",
    )
    for bad in ("not-a-token", legacy):
        response = await api_client.post(
            "/api/v2/auth/refresh", json={"refresh_token": bad}
        )
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_rotated_access_token_authenticates_against_me(api_client, jwt_secret):
    _install(
        {
            "user_by_username": [_USER],
            "user_profile": [{**_USER, "active": True}],
            "user_role_ids": [],
            "user_permissions": [],
        }
    )
    body = await _login(api_client)
    rotated = (
        await api_client.post(
            "/api/v2/auth/refresh", json={"refresh_token": body["refresh_token"]}
        )
    ).json()

    me = await api_client.get(
        "/api/v2/auth/me", headers={"Authorization": f"Bearer {rotated['token']}"}
    )
    assert me.status_code == 200
    assert me.json()["user_id"] == "u-1"


# ── D15: logout denylist ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_logout_revokes_access_token_for_next_request(api_client, jwt_secret):
    _install(
        {
            "user_by_username": [_USER],
            "user_profile": [{**_USER, "active": True}],
            "user_role_ids": [],
            "user_permissions": [],
        }
    )
    body = await _login(api_client)
    headers = {"Authorization": f"Bearer {body['token']}"}

    me_before = await api_client.get("/api/v2/auth/me", headers=headers)
    assert me_before.status_code == 200

    out = await api_client.post("/api/v2/auth/logout", headers=headers)
    assert out.status_code == 200 and out.json()["revoked"] is True

    me_after = await api_client.get("/api/v2/auth/me", headers=headers)
    assert me_after.status_code == 401
    assert me_after.json() == {"detail": "Token revoked (logged out)"}


@pytest.mark.asyncio
async def test_logout_of_one_token_does_not_revoke_sibling_tokens(api_client, jwt_secret):
    _install(
        {
            "user_by_username": [_USER],
            "user_profile": [{**_USER, "active": True}],
            "user_role_ids": [],
            "user_permissions": [],
        }
    )
    body = await _login(api_client)
    other = create_token("u-1")  # a different session's access token

    await api_client.post(
        "/api/v2/auth/logout", headers={"Authorization": f"Bearer {body['token']}"}
    )
    me = await api_client.get(
        "/api/v2/auth/me", headers={"Authorization": f"Bearer {other}"}
    )
    assert me.status_code == 200  # per-token revocation, not per-user


@pytest.mark.asyncio
async def test_legacy_token_without_jti_still_authenticates_and_logs_out(
    api_client, jwt_secret
):
    """Pre-D14 tokens carry no jti: denylist is a no-op, access still works."""
    _install(
        {
            "user_profile": [{**_USER, "active": True}],
            "user_role_ids": [],
            "user_permissions": [],
        }
    )
    legacy = pyjwt.encode(
        {"user_id": "u-1",
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        _TEST_JWT_SECRET, algorithm="HS256",
    )
    headers = {"Authorization": f"Bearer {legacy}"}

    out = await api_client.post("/api/v2/auth/logout", headers=headers)
    assert out.status_code == 200 and out.json()["revoked"] is False

    me = await api_client.get("/api/v2/auth/me", headers=headers)
    assert me.status_code == 200  # upgrade tolerance: legacy tokens not broken


@pytest.mark.asyncio
async def test_denylist_read_failure_fails_open(api_client, jwt_secret):
    """Redis outage must not lock the operator out (documented contract)."""
    _install({"user_profile": [{**_USER, "active": True}]})

    class _BrokenRedis:
        async def cache_get(self, key: str):
            raise ConnectionError("redis down")

        async def cache_set(self, key: str, value, *, ttl_sec: int = 60):
            raise ConnectionError("redis down")

    app.dependency_overrides[get_redis] = lambda: _BrokenRedis()
    token = create_token("u-1")
    headers = {"Authorization": f"Bearer {token}"}

    me = await api_client.get("/api/v2/auth/me", headers=headers)
    assert me.status_code == 200  # fail-open on read

    out = await api_client.post("/api/v2/auth/logout", headers=headers)
    assert out.status_code == 200
    assert out.json() == {"ok": True, "revoked": False}  # honest reporting


@pytest.mark.asyncio
async def test_logout_stores_denylist_entry_with_remaining_ttl(api_client, jwt_secret):
    from shared.redis_client import RedisClient

    _install({})
    stored: dict[str, int] = {}

    class _SpyRedis:
        async def cache_set(self, key: str, value, *, ttl_sec: int = 60):
            stored[key] = ttl_sec

    app.dependency_overrides[get_redis] = lambda: _SpyRedis()
    token = create_token("u-1")

    out = await api_client.post(
        "/api/v2/auth/logout", headers={"Authorization": f"Bearer {token}"}
    )

    assert out.json()["revoked"] is True
    jti = decode_token(token)["jti"]
    assert f"{_DENYLIST_PREFIX}:{jti}" in stored
    # TTL roughly equals the remaining life of a 24h token (bounded sanity)
    assert 20 * 3600 < stored[f"{_DENYLIST_PREFIX}:{jti}"] <= 24 * 3600


@pytest.mark.asyncio
async def test_refresh_refused_when_revocation_store_unavailable(api_client, jwt_secret):
    """Rotation IS the security boundary — a failed denylist write must 503."""
    _install({})

    class _BrokenRedis:
        async def cache_get(self, key: str):
            return None

        async def cache_set(self, key: str, value, *, ttl_sec: int = 60):
            raise ConnectionError("redis down")

    app.dependency_overrides[get_redis] = lambda: _BrokenRedis()
    refresh_token = create_token("u-1", token_type="refresh")

    response = await api_client.post(
        "/api/v2/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert response.status_code == 503
    assert "Revocation store unavailable" in response.json()["detail"]
