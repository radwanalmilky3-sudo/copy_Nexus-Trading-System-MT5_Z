"""Sensitive financial read routes require authentication and view permission."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services.nexus_api.middleware.auth import create_token
from services.nexus_api.routers import performance, positions, risk, trades


READ_ROUTES = [
    ("/api/positions", "trading.view"),
    ("/api/positions/position-1", "trading.view"),
    ("/api/trades", "trading.view"),
    ("/api/trades/stats", "trading.view"),
    ("/api/trades/trade-1", "trading.view"),
    ("/api/performance", "trading.view"),
    ("/api/performance/equity-curve", "trading.view"),
    ("/api/performance/daily", "trading.view"),
    ("/api/performance/by-session", "trading.view"),
    ("/api/performance/by-symbol", "trading.view"),
    ("/api/risk/settings", "risk.view"),
    ("/api/risk/status", "risk.view"),
    ("/api/risk/circuit-breakers", "risk.view"),
]


@pytest.fixture
def stub_financial_read_dependencies(monkeypatch):
    monkeypatch.setattr(
        positions,
        "_fetch_live_executor_snapshot",
        AsyncMock(return_value=([], None, False, 0, 0)),
    )
    monkeypatch.setattr(
        trades,
        "_proxy_trades",
        AsyncMock(return_value={"trades": [], "total": 0}),
    )
    monkeypatch.setattr(performance, "_get", AsyncMock(return_value={}))
    monkeypatch.setattr(risk, "_risk_proxy", AsyncMock(return_value={}))


@pytest.mark.asyncio
@pytest.mark.parametrize("path,permission", READ_ROUTES)
async def test_sensitive_financial_read_requires_jwt(
    api_client, monkeypatch, stub_financial_read_dependencies, path, permission
):
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")

    response = await api_client.get(path)

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("path,permission", READ_ROUTES)
async def test_sensitive_financial_read_requires_view_permission(
    api_client, monkeypatch, stub_financial_read_dependencies, path, permission
):
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    token = create_token("unprivileged-user")

    response = await api_client.get(
        path,
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": f"permission required: {permission}"}


@pytest.mark.asyncio
@pytest.mark.parametrize("path,permission", READ_ROUTES)
async def test_user_with_view_permission_can_reach_read_handler(
    api_client,
    monkeypatch,
    stub_financial_read_dependencies,
    path,
    permission,
):
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    for module in (positions, trades, performance, risk):
        monkeypatch.setattr(module, "_require", AsyncMock(return_value=None))
    token = create_token("authorized-user")

    response = await api_client.get(
        path,
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code not in {401, 403}
