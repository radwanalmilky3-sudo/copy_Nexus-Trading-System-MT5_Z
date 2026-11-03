from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services.nexus_api.middleware.auth import create_token
from services.nexus_api.routers import risk
from fastapi import HTTPException


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/risk/settings", {"risk_per_trade_pct": 1.0}),
        ("/api/risk/reset-day", None),
        ("/api/risk/pause?paused=true", None),
    ],
)
async def test_risk_mutation_rejects_missing_jwt_before_proxy(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    payload: dict[str, float] | None,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    proxy = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(risk, "_risk_proxy", proxy)

    response = await api_client.post(path, json=payload)

    assert response.status_code == 401
    proxy.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/risk/settings", {"risk_per_trade_pct": 1.0}),
        ("/api/risk/reset-day", None),
        ("/api/risk/pause?paused=true", None),
    ],
)
async def test_risk_mutation_requires_risk_modify_before_proxy(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    payload: dict[str, float] | None,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    proxy = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(risk, "_risk_proxy", proxy)

    response = await api_client.post(
        path,
        json=payload,
        headers={"Authorization": f"Bearer {create_token('unprivileged-user')}"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "permission required: risk.modify"}
    proxy.assert_not_awaited()


@pytest.mark.asyncio
async def test_risk_service_proxy_attaches_internal_credential(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-internal-secret")
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def request(self, method, url, **kwargs):
            captured.update(method=method, url=url, kwargs=kwargs)
            return FakeResponse()

    monkeypatch.setattr(risk, "new_client", lambda **kwargs: FakeClient())

    result = await risk._risk_proxy("POST", "/api/risk/reset-day")

    assert result == {"ok": True}
    assert captured["kwargs"]["headers"] == {
        "X-Nexus-Internal-Secret": "test-internal-secret"
    }


@pytest.mark.asyncio
async def test_risk_service_proxy_fails_closed_without_internal_credential(monkeypatch):
    monkeypatch.delenv("NEXUS_INTERNAL_API_SECRET", raising=False)

    with pytest.raises(HTTPException) as raised:
        await risk._risk_proxy("POST", "/api/risk/reset-day")

    assert raised.value.status_code == 503


@pytest.mark.asyncio
async def test_risk_read_proxy_attaches_internal_credential(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-internal-secret")
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"settings": {}}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def request(self, method, url, **kwargs):
            captured.update(method=method, url=url, kwargs=kwargs)
            return FakeResponse()

    monkeypatch.setattr(risk, "new_client", lambda **kwargs: FakeClient())

    result = await risk._risk_proxy("GET", "/api/risk/settings")

    assert result == {"settings": {}}
    assert captured["kwargs"]["headers"] == {
        "X-Nexus-Internal-Secret": "test-internal-secret"
    }


@pytest.mark.asyncio
async def test_risk_read_proxy_fails_closed_without_internal_credential(monkeypatch):
    monkeypatch.delenv("NEXUS_INTERNAL_API_SECRET", raising=False)

    with pytest.raises(HTTPException) as raised:
        await risk._risk_proxy("GET", "/api/risk/settings")

    assert raised.value.status_code == 503
