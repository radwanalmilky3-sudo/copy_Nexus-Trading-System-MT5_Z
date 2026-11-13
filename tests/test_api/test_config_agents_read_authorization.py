"""Configuration and agent intelligence reads must not be public."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from services.nexus_api.middleware.auth import create_token
from services.nexus_api.routers import admin, agents, backtest, config, fundamental, intelligence, intermarket, ml, notifications, regime, risk, strategies, system


READ_ROUTES = [
    ("/api/config/settings", "trading.settings"),
    ("/api/config/agents", "trading.settings"),
    ("/api/config/risk", "risk.view"),
    ("/api/agents/status", "trading.view"),
    ("/api/agents/reasoning/cycle-1", "trading.view"),
    ("/api/agents/decision/EURUSD", "trading.view"),
    ("/api/agents/brain/budget", "trading.view"),
    ("/api/agents/shadow-trades/stats", "trading.view"),
    ("/api/ml/status", "trading.view"),
    ("/api/ml/predict/EURUSD", "trading.view"),
    ("/api/ml/traders/status", "trading.view"),
    ("/api/ml/traders/predict/EURUSD", "trading.view"),
    ("/api/ml/traders/predict/xgb/EURUSD", "trading.view"),
    ("/api/ml/traders/comparison", "trading.view"),
    ("/api/ml/traders/performance/xgb", "trading.view"),
    ("/api/ml/traders/signals/recent/xgb", "trading.view"),
    ("/api/ml/traders/mode", "trading.view"),
    ("/api/ml/traders/dynamic-params/EURUSD", "trading.view"),
    ("/api/ml/traders/autonomous/status", "trading.view"),
    ("/api/ml/retrain/status", "trading.view"),
    ("/api/strategies", "trading.view"),
    ("/api/strategies/research/log", "trading.view"),
    ("/api/strategies/strategy-1", "trading.view"),
    ("/api/strategies/strategy-1/mql5", "trading.view"),
    ("/api/backtest/summary", "trading.view"),
    ("/api/backtest/strategies", "trading.view"),
    ("/api/notifications/stream", "trading.view"),
    ("/api/notifications/log", "trading.view"),
    ("/api/fundamental/gold/overview", "fundamental.view"),
    ("/api/fundamental/macro", "fundamental.view"),
    ("/api/fundamental/monetary", "fundamental.view"),
    ("/api/fundamental/cross-asset", "fundamental.view"),
    ("/api/fundamental/geopolitics", "fundamental.view"),
    ("/api/fundamental/flows", "fundamental.view"),
    ("/api/fundamental/news", "fundamental.view"),
    ("/api/fundamental/learning", "fundamental.view"),
    ("/api/fundamental/sources/health", "source_manager.view"),
    ("/api/fundamental/assets/XAUUSD/latest", "fundamental.view"),
    ("/api/fundamental/events/event-1/impacts", "fundamental.view"),
    ("/api/fundamental/ticker", "ticker.view"),
    ("/api/fundamental/ticker/history", "ticker.view"),
    ("/api/fundamental/settings/news-ticker", "ticker.view"),
    ("/api/fundamental/lineage/XAUUSD", "fundamental.view"),
    ("/api/fundamental/outcomes/XAUUSD", "fundamental.view"),
    ("/api/fundamental/local-ai/history", "fundamental.view"),
    ("/api/intelligence/quality", "trading.view"),
    ("/api/intelligence/models-by-regime", "trading.view"),
    ("/api/intelligence/genai-brief", "fundamental.view"),
    ("/api/intelligence/mtf-context/EURUSD", "trading.view"),
    ("/api/intelligence/settings", "trading.settings"),
    ("/api/intelligence/cross-asset", "trading.view"),
    ("/api/intelligence/asset-profile/EURUSD", "trading.view"),
    ("/api/intelligence/shift-alerts", "trading.view"),
    ("/api/intelligence/news-alerts", "fundamental.view"),
    ("/api/intelligence/news-blackout", "fundamental.view"),
    ("/api/intelligence/brief-status", "fundamental.view"),
    ("/api/intelligence/correlation", "trading.view"),
    ("/api/intelligence/lifecycle-actions", "trading.view"),
    ("/api/intelligence/trade-memory", "trading.view"),
    ("/api/intelligence/institutional/EURUSD", "trading.view"),
    ("/api/intermarket/matrix", "trading.view"),
    ("/api/intermarket/score/EURUSD", "trading.view"),
    ("/api/intermarket/divergences", "trading.view"),
    ("/api/regime/current", "trading.view"),
    ("/api/regime/history", "trading.view"),
    ("/api/regime/thresholds", "trading.view"),
    ("/api/system/health", "trading.view"),
    ("/api/system/mode", "trading.view"),
    ("/api/system/local-ai-health", "trading.view"),
    ("/api/v2/users/other-user/avatar", "users.view"),
]

SYSTEM_MUTATIONS = [
    ("/api/system/kill-switch", {"pin": "test-pin", "reason": "authorization-test"}),
    ("/api/system/toggle-auto-trade", {"enabled": False}),
    ("/api/system/mode", {"mode": "paper"}),
]


@pytest.fixture
def stub_agent_read_dependencies(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-internal-service-secret")
    # Returns (service_online, active_cycles, total_cycles_completed,
    #          llm_model, llm_online, llm_url) — the last three feed the
    # dashboard's real model/provider display, so the stub must match the
    # live arity.
    monkeypatch.setattr(
        agents,
        "_fetch_agents_service_meta",
        AsyncMock(return_value=(False, 0, 0, "", False, "")),
    )
    monkeypatch.setattr(agents, "new_client", lambda **kwargs: _FakeClientContext())
    monkeypatch.setattr(ml, "_proxy", AsyncMock(return_value={"ok": True}))
    monkeypatch.setattr(strategies, "_proxy", AsyncMock(return_value={"id": "strategy-1"}))
    monkeypatch.setattr(notifications, "_get_redis", AsyncMock(return_value=_FakeRedis()))
    monkeypatch.setattr(notifications.aioredis, "from_url", lambda *args, **kwargs: _FakeRedis())
    monkeypatch.setattr(intelligence, "_get_redis", AsyncMock(return_value=_FakeRedis()))
    monkeypatch.setattr(regime, "_get_redis", AsyncMock(return_value=_FakeRedis()))
    # D12: system endpoints resolve Redis via the app dependency override in
    # conftest api_client — there is no system.local_health symbol to stub.
    # D13: /api/config/risk proxies the live nexus-risk service via risk._risk_proxy;
    # without this stub the test performs a real network call and the live
    # service's 403 (secret mismatch) propagates verbatim into the assertion.
    monkeypatch.setattr(
        risk, "_risk_proxy", AsyncMock(return_value={"source": "stub", "rules": {}})
    )


class _FakeResponse:
    status_code = 200
    text = ""

    @staticmethod
    def json():
        return {"ok": True}


class _FakeClientContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, *args, **kwargs):
        return _FakeResponse()


class _FakeRedis:
    async def lrange(self, *args, **kwargs):
        return []

    async def get(self, *args, **kwargs):
        return None

    async def cache_get(self, *args, **kwargs):
        return None

    def pubsub(self):
        return _FakePubSub()

    async def aclose(self):
        return None


class _FakePubSub:
    async def subscribe(self, *args, **kwargs):
        return None

    async def get_message(self, *args, **kwargs):
        raise asyncio.CancelledError

    async def unsubscribe(self, *args, **kwargs):
        return None

    async def aclose(self):
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize("path,permission", READ_ROUTES)
async def test_config_and_agent_reads_reject_anonymous_users(
    api_client, monkeypatch, stub_agent_read_dependencies, path, permission
):
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")

    response = await api_client.get(path)

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("path,permission", READ_ROUTES)
async def test_config_and_agent_reads_require_their_specific_permission(
    api_client, monkeypatch, stub_agent_read_dependencies, path, permission
):
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    token = create_token("unprivileged-user")

    response = await api_client.get(path, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert response.json() == {"detail": f"permission required: {permission}"}


@pytest.mark.asyncio
@pytest.mark.parametrize("path,permission", READ_ROUTES)
async def test_users_with_required_permission_reach_config_and_agent_handlers(
    api_client, monkeypatch, stub_agent_read_dependencies, path, permission
):
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    monkeypatch.setattr(admin, "_require", AsyncMock(return_value=None))
    for module in (config, agents, ml, strategies, backtest, notifications, fundamental):
        monkeypatch.setattr(module, "_require", AsyncMock(return_value=None))
    token = create_token("authorized-user")

    response = await api_client.get(path, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code not in {401, 403}


@pytest.mark.asyncio
@pytest.mark.parametrize("path,payload", SYSTEM_MUTATIONS)
async def test_system_controls_require_authenticated_user(api_client, monkeypatch, path, payload):
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    monkeypatch.setenv("NEXUS_ADMIN_PIN", "test-pin")

    response = await api_client.post(path, json=payload)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_enabling_auto_trade_requires_trading_execute_permission(api_client, monkeypatch):
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    monkeypatch.setenv("NEXUS_ADMIN_PIN", "test-pin")
    token = create_token("unprivileged-user")

    response = await api_client.post(
        "/api/system/toggle-auto-trade",
        json={"enabled": True, "pin": "test-pin"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "permission required: trading.execute"}


@pytest.mark.asyncio
@pytest.mark.parametrize("path,payload", SYSTEM_MUTATIONS)
async def test_authenticated_user_can_use_fail_safe_system_controls_without_role(
    api_client, monkeypatch, path, payload
):
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    monkeypatch.setenv("NEXUS_ADMIN_PIN", "test-pin")
    token = create_token("unprivileged-user")

    response = await api_client.post(
        path,
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_dashboard_cannot_report_paper_when_process_is_live(api_client, fake_redis, monkeypatch):
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    monkeypatch.setenv("NEXUS_TRADING_MODE", "live")
    token = create_token("operator")

    response = await api_client.post(
        "/api/system/mode",
        json={"mode": "paper"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409
    assert "restart" in response.json()["detail"].lower()
    assert await fake_redis.get("session:state") is None
    assert await fake_redis.get("system:auto_trade") is None


@pytest.mark.asyncio
async def test_system_mode_uses_shared_live_mode_definition(api_client, monkeypatch):
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    monkeypatch.setenv("NEXUS_TRADING_MODE", "production")
    monkeypatch.setattr(admin, "_require", AsyncMock(return_value=None))
    token = create_token("operator")

    response = await api_client.get(
        "/api/system/mode",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "live"
    assert response.json()["kill_switch"] is False


@pytest.mark.asyncio
async def test_system_mode_reports_latched_kill_switch(api_client, redis_client, monkeypatch):
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    monkeypatch.setenv("NEXUS_TRADING_MODE", "paper")
    monkeypatch.setattr(admin, "_require", AsyncMock(return_value=None))
    await redis_client.cache_set("system:kill_switch", True, ttl_sec=3600)
    token = create_token("operator")

    response = await api_client.get(
        "/api/system/mode",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["kill_switch"] is True
    assert response.json()["auto_trade"] is False


@pytest.mark.asyncio
async def test_system_mode_reports_structured_anti_tilt_kill_switch(api_client, redis_client, monkeypatch):
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    monkeypatch.setenv("NEXUS_TRADING_MODE", "paper")
    monkeypatch.setattr(admin, "_require", AsyncMock(return_value=None))
    await redis_client.cache_set("system:kill_switch", {"reason": "anti_tilt"}, ttl_sec=3600)
    token = create_token("operator")

    response = await api_client.get(
        "/api/system/mode",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["kill_switch"] is True


@pytest.mark.asyncio
async def test_agents_status_forwards_real_llm_model_from_agents_service(api_client, monkeypatch):
    """The dashboard must render the model the agents service actually reports.

    Regression guard: the flowchart previously showed hardcoded model names, so
    /api/agents/status has to carry the live ``llm_model`` verbatim (and never
    invent one when the agents service reports nothing).
    """
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    monkeypatch.setattr(agents, "_require", AsyncMock(return_value=None))

    async def _fake_meta():
        return (True, 0, 7, "glm-4.5-flash", True, "https://api.z.ai/api/paas/v4")

    monkeypatch.setattr(agents, "_fetch_agents_service_meta", _fake_meta)
    token = create_token("operator")

    response = await api_client.get(
        "/api/agents/status",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["llm_model"] == "glm-4.5-flash"
    assert body["llm_online"] is True
    assert body["llm_url"] == "https://api.z.ai/api/paas/v4"
    assert body["meta"]["total_cycles_completed"] == 7
