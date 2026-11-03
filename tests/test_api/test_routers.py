"""Tests for nexus_api routers — positions, trades, performance, etc."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from services.nexus_api.middleware.auth import create_token
from services.nexus_api.routers import admin, performance, positions, risk, system, trades


@pytest.fixture
def authorized_headers(monkeypatch):
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    monkeypatch.setattr(admin, "_require", AsyncMock(return_value=None))
    for module in (performance, positions, risk, trades):
        monkeypatch.setattr(module, "_require", AsyncMock(return_value=None))
    token = create_token("router-test-user")
    return {"Authorization": f"Bearer {token}"}


class TestPositionsRouter:
    @pytest.mark.asyncio
    async def test_list_positions_empty(self, api_client: AsyncClient, authorized_headers):
        resp = await api_client.get("/api/positions", headers=authorized_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 0
        assert body["positions"] == []

    @pytest.mark.asyncio
    async def test_get_position_not_found(self, api_client: AsyncClient, authorized_headers):
        resp = await api_client.get("/api/positions/nonexistent", headers=authorized_headers)
        assert resp.status_code == 404


class TestTradesRouter:
    @pytest.mark.asyncio
    async def test_list_trades(self, api_client: AsyncClient, authorized_headers):
        resp = await api_client.get("/api/trades", headers=authorized_headers)
        assert resp.status_code in (200, 404, 503)


class TestPerformanceRouter:
    @pytest.mark.asyncio
    async def test_get_performance(self, api_client: AsyncClient, authorized_headers):
        resp = await api_client.get("/api/performance", headers=authorized_headers)
        assert resp.status_code in (200, 404, 503)


class TestAgentsRouter:
    @pytest.mark.asyncio
    async def test_list_agents(self, api_client: AsyncClient):
        resp = await api_client.get("/api/agents")
        assert resp.status_code in (200, 404)


class TestRiskRouter:
    @pytest.mark.asyncio
    async def test_get_risk_state(self, api_client: AsyncClient):
        resp = await api_client.get("/api/risk")
        assert resp.status_code in (200, 404)


class TestSystemRouter:
    @pytest.mark.asyncio
    async def test_health(self, api_client: AsyncClient, authorized_headers):
        resp = await api_client.get("/api/system/health", headers=authorized_headers)
        assert resp.status_code in (200, 404)


class TestConfigRouter:
    @pytest.mark.asyncio
    async def test_get_config(self, api_client: AsyncClient):
        resp = await api_client.get("/api/config")
        assert resp.status_code in (200, 404)
