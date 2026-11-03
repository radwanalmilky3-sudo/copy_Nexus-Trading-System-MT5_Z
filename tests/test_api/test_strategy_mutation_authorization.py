from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from services.nexus_api.middleware.auth import create_token
from services.nexus_api.routers import strategies


@pytest.mark.asyncio
async def test_strategy_service_proxy_attaches_internal_credential(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-agents-secret")
    request = AsyncMock(return_value=SimpleNamespace(
        status_code=200, content=b"{}", json=lambda: {"ok": True}
    ))

    @asynccontextmanager
    async def fake_client(*args, **kwargs):
        yield SimpleNamespace(request=request)

    monkeypatch.setattr(strategies, "new_client", fake_client)

    await strategies._proxy("POST", "/api/strategies/research", json={"n": 1})

    assert request.await_args.kwargs["headers"] == {
        "X-Nexus-Internal-Secret": "test-agents-secret"
    }


@pytest.mark.asyncio
async def test_strategy_service_proxy_fails_closed_without_internal_credential(monkeypatch):
    monkeypatch.delenv("NEXUS_INTERNAL_API_SECRET", raising=False)
    with pytest.raises(HTTPException) as exc:
        await strategies._proxy("PUT", "/api/strategies/s1/status", json={"status": "active"})
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_strategy_read_proxy_attaches_internal_credential(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-agents-secret")
    request = AsyncMock(return_value=SimpleNamespace(
        status_code=200, content=b"{}", json=lambda: {"id": "s1"}
    ))

    @asynccontextmanager
    async def fake_client(*args, **kwargs):
        yield SimpleNamespace(request=request)

    monkeypatch.setattr(strategies, "new_client", fake_client)

    await strategies._proxy("GET", "/api/strategies/s1")

    assert request.await_args.kwargs["headers"] == {
        "X-Nexus-Internal-Secret": "test-agents-secret"
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("POST", "/api/strategies/research", {"n": 1}),
        ("POST", "/api/strategies/test-strategy/reevaluate", None),
        ("PUT", "/api/strategies/test-strategy/status", {"status": "active"}),
    ],
)
async def test_strategy_mutation_rejects_missing_jwt_before_agents_proxy(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    payload: dict | None,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    proxy = AsyncMock(return_value={"status": "accepted"})
    monkeypatch.setattr(strategies, "_proxy", proxy)

    response = await api_client.request(method, path, json=payload)

    assert response.status_code == 401
    proxy.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("POST", "/api/strategies/research", {"n": 1}),
        ("POST", "/api/strategies/test-strategy/reevaluate", None),
        ("PUT", "/api/strategies/test-strategy/status", {"status": "active"}),
    ],
)
async def test_strategy_mutation_requires_trading_settings_before_agents_proxy(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    payload: dict | None,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    proxy = AsyncMock(return_value={"status": "accepted"})
    monkeypatch.setattr(strategies, "_proxy", proxy)

    response = await api_client.request(
        method,
        path,
        json=payload,
        headers={"Authorization": f"Bearer {create_token('unprivileged-user')}"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "permission required: trading.settings"}
    proxy.assert_not_awaited()
