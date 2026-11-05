"""Tests for the scope-based rate limiter (T-001, approved design 2026-11-05).

Covers the owner-approved surface: 429 + Retry-After per scope, env
overrides (``NEXUS_RL_<SCOPE>_LIMIT`` / ``_WINDOW_SEC``), scope
isolation, the ``NEXUS_RL_ENABLED=0`` kill-switch, ``limit=0``
disabling, XFF-aware identity separation behind loopback, and fail-open
when no redis client is installed.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.rate_limit import DEFAULT_LIMITS, rate_limit_scope


class FakeRedis:
    """Minimal async redis subset: incr/expire/ttl on a dict."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, ttl: int) -> None:
        self.ttls[key] = int(ttl)

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, 60)


def make_app() -> tuple[FastAPI, FakeRedis]:
    app = FastAPI()
    fake = FakeRedis()
    app.state.nexus_redis = fake

    @app.get("/ml/train", dependencies=[rate_limit_scope("ml")])
    async def ml_train() -> dict:
        return {"ok": True}

    @app.get("/env", dependencies=[rate_limit_scope("env")])
    async def env_read() -> dict:
        return {"ok": True}

    @app.get("/admin/users", dependencies=[rate_limit_scope("admin")])
    async def admin_users() -> dict:
        return {"ok": True}

    return app, fake


def client_for(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_429_after_limit_with_retry_after() -> None:
    app, _ = make_app()
    with client_for(app) as c:
        for _ in range(DEFAULT_LIMITS["ml"]):
            assert c.get("/ml/train").status_code == 200
        r = c.get("/ml/train")
        assert r.status_code == 429
        assert int(r.headers["Retry-After"]) >= 1


def test_scope_isolation() -> None:
    app, _ = make_app()
    with client_for(app) as c:
        for _ in range(DEFAULT_LIMITS["ml"]):
            c.get("/ml/train")
        assert c.get("/ml/train").status_code == 429
        # env scope has its own bucket — untouched by ml exhaustion
        assert c.get("/env").status_code == 200


def test_env_limit_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUS_RL_ML_LIMIT", "2")
    app, _ = make_app()
    with client_for(app) as c:
        assert c.get("/ml/train").status_code == 200
        assert c.get("/ml/train").status_code == 200
        assert c.get("/ml/train").status_code == 429


def test_limit_zero_disables_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUS_RL_ADMIN_LIMIT", "0")
    app, _ = make_app()
    with client_for(app) as c:
        for _ in range(DEFAULT_LIMITS["admin"] + 5):
            assert c.get("/admin/users").status_code == 200


def test_global_kill_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUS_RL_ENABLED", "0")
    app, _ = make_app()
    with client_for(app) as c:
        for _ in range(DEFAULT_LIMITS["ml"] + 3):
            assert c.get("/ml/train").status_code == 200


def test_xff_trusted_behind_loopback() -> None:
    """House rule (mirrors admin.py): XFF is honoured only for loopback peers."""
    from shared.rate_limit import _client_identity

    class Loopback:
        host = "127.0.0.1"

    class ViaGateway:
        client = Loopback()
        headers = {"x-forwarded-for": "10.1.1.7, 10.1.1.8"}

    assert _client_identity(ViaGateway()) == "10.1.1.7"


def test_xff_spoof_not_trusted_from_non_loopback() -> None:
    from shared.rate_limit import _client_identity

    class Direct:
        host = "203.0.113.5"

    class Spoofed:
        client = Direct()
        headers = {"x-forwarded-for": "10.1.1.7"}

    assert _client_identity(Spoofed()) == "203.0.113.5"


def test_fail_open_without_redis() -> None:
    app = FastAPI()
    # no app.state.nexus_redis installed on purpose

    @app.get("/ml/train", dependencies=[rate_limit_scope("ml")])
    async def ml_train() -> dict:
        return {"ok": True}

    with client_for(app) as c:
        for _ in range(DEFAULT_LIMITS["ml"] + 3):
            assert c.get("/ml/train").status_code == 200


def test_unknown_scope_fails_fast() -> None:
    with pytest.raises(ValueError):
        rate_limit_scope("nope")
