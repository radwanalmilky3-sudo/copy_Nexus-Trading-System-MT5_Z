from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services.nexus_api.middleware.auth import create_token
from services.nexus_api.routers import backtest


@pytest.mark.asyncio
async def test_backtest_rejects_missing_jwt_before_fetching_history(api_client, monkeypatch):
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    fetch = AsyncMock(return_value=[])
    monkeypatch.setattr(backtest, "_fetch_trades", fetch)

    response = await api_client.post("/api/backtest", json={})

    assert response.status_code == 401
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_backtest_requires_trading_view_before_fetching_history(api_client, monkeypatch):
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    fetch = AsyncMock(return_value=[])
    monkeypatch.setattr(backtest, "_fetch_trades", fetch)

    response = await api_client.post(
        "/api/backtest",
        json={},
        headers={"Authorization": f"Bearer {create_token('unprivileged-user')}"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "permission required: trading.view"}
    fetch.assert_not_awaited()
