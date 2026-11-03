from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services.nexus_api.middleware.auth import create_token
from services.nexus_api.routers import ml

ML_MUTATIONS = [
    ("/api/ml/traders/mode/switch", {"mode": "swing"}),
    ("/api/ml/traders/retrain/force", {"model_types": ["ml"]}),
    ("/api/ml/train", {"symbols": ["XAUUSD"]}),
]


@pytest.mark.asyncio
async def test_ml_training_rejects_missing_jwt_before_proxy(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    proxy = AsyncMock(return_value={"status": "accepted"})
    monkeypatch.setattr(ml, "_proxy", proxy)

    response = await api_client.post("/api/ml/traders/train", json={"model_types": ["ml"]})

    assert response.status_code == 401
    proxy.assert_not_awaited()


@pytest.mark.asyncio
async def test_ml_training_requires_trading_settings_before_proxy(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    proxy = AsyncMock(return_value={"status": "accepted"})
    monkeypatch.setattr(ml, "_proxy", proxy)

    response = await api_client.post(
        "/api/ml/traders/train",
        json={"model_types": ["ml"]},
        headers={"Authorization": f"Bearer {create_token('unprivileged-user')}"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "permission required: trading.settings"}
    proxy.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("path", "payload"), ML_MUTATIONS)
async def test_other_ml_mutations_reject_missing_jwt_before_proxy(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    payload: dict,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    proxy = AsyncMock(return_value={"status": "accepted"})
    monkeypatch.setattr(ml, "_proxy", proxy)

    response = await api_client.post(path, json=payload)

    assert response.status_code == 401
    proxy.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("path", "payload"), ML_MUTATIONS)
async def test_other_ml_mutations_require_trading_settings_before_proxy(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    payload: dict,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    proxy = AsyncMock(return_value={"status": "accepted"})
    monkeypatch.setattr(ml, "_proxy", proxy)

    response = await api_client.post(
        path,
        json=payload,
        headers={"Authorization": f"Bearer {create_token('unprivileged-user')}"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "permission required: trading.settings"}
    proxy.assert_not_awaited()


@pytest.mark.asyncio
async def test_autonomous_ml_toggle_rejects_missing_jwt_before_proxy(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    proxy = AsyncMock(return_value={"status": "started"})
    monkeypatch.setattr(ml, "_proxy", proxy)

    response = await api_client.post("/api/ml/traders/autonomous/toggle?enable=true")

    assert response.status_code == 401
    proxy.assert_not_awaited()


@pytest.mark.asyncio
async def test_ml_service_proxy_attaches_internal_credential(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-ml-internal-secret")
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

    monkeypatch.setattr(ml, "new_client", lambda **kwargs: FakeClient())

    result = await ml._proxy("POST", "/api/ml/train", body={"symbols": ["XAUUSD"]})

    assert result == {"ok": True}
    assert captured["kwargs"]["headers"] == {
        "X-Nexus-Internal-Secret": "test-ml-internal-secret"
    }


@pytest.mark.asyncio
async def test_ml_service_proxy_fails_closed_without_internal_credential(monkeypatch):
    monkeypatch.delenv("NEXUS_INTERNAL_API_SECRET", raising=False)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as raised:
        await ml._proxy("POST", "/api/ml/train", body={})

    assert raised.value.status_code == 503


@pytest.mark.asyncio
async def test_ml_read_proxy_attaches_internal_credential(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-ml-internal-secret")
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"models": {}}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def request(self, method, url, **kwargs):
            captured.update(method=method, url=url, kwargs=kwargs)
            return FakeResponse()

    monkeypatch.setattr(ml, "new_client", lambda **kwargs: FakeClient())

    result = await ml._proxy("GET", "/api/ml/models/status")

    assert result == {"models": {}}
    assert captured["kwargs"]["headers"] == {
        "X-Nexus-Internal-Secret": "test-ml-internal-secret"
    }


@pytest.mark.asyncio
async def test_ml_read_proxy_fails_closed_without_internal_credential(monkeypatch):
    monkeypatch.delenv("NEXUS_INTERNAL_API_SECRET", raising=False)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as raised:
        await ml._proxy("GET", "/api/ml/models/status")

    assert raised.value.status_code == 503


@pytest.mark.asyncio
async def test_autonomous_ml_toggle_requires_trading_execute_before_proxy(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    proxy = AsyncMock(return_value={"status": "started"})
    monkeypatch.setattr(ml, "_proxy", proxy)

    response = await api_client.post(
        "/api/ml/traders/autonomous/toggle?enable=true",
        headers={"Authorization": f"Bearer {create_token('unprivileged-user')}"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "permission required: trading.execute"}
    proxy.assert_not_awaited()
