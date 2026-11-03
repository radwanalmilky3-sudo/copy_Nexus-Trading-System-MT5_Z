from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from services.nexus_api.middleware.auth import create_token
from services.nexus_api.routers import positions


class _ClientContext:
    def __init__(self, client: AsyncMock) -> None:
        self.client = client

    async def __aenter__(self) -> AsyncMock:
        return self.client

    async def __aexit__(self, *_: object) -> None:
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("POST", "/api/positions/123/close", None),
        ("POST", "/api/positions/123/modify", {"sl": 1.08}),
    ],
)
async def test_position_mutation_rejects_missing_jwt_before_executor_call(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    payload: dict[str, float] | None,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    client = AsyncMock()
    client.delete.return_value = httpx.Response(200, request=httpx.Request("DELETE", "http://executor"))
    client.put.return_value = httpx.Response(200, request=httpx.Request("PUT", "http://executor"))
    monkeypatch.setattr(positions, "new_client", lambda **_: _ClientContext(client))

    response = await api_client.request(method, path, json=payload)

    assert response.status_code == 401
    client.delete.assert_not_awaited()
    client.put.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("POST", "/api/positions/123/close", None),
        ("POST", "/api/positions/123/modify", {"sl": 1.08}),
    ],
)
async def test_position_mutation_requires_trading_execute_permission(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    payload: dict[str, float] | None,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    client = AsyncMock()
    client.delete.return_value = httpx.Response(200, request=httpx.Request("DELETE", "http://executor"))
    client.put.return_value = httpx.Response(200, request=httpx.Request("PUT", "http://executor"))
    monkeypatch.setattr(positions, "new_client", lambda **_: _ClientContext(client))

    response = await api_client.request(
        method,
        path,
        json=payload,
        headers={"Authorization": f"Bearer {create_token('unprivileged-user')}"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "permission required: trading.execute"}
    client.delete.assert_not_awaited()
    client.put.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "payload", "client_method"),
    [
        ("POST", "/api/positions/123/close", None, "delete"),
        ("POST", "/api/positions/123/modify", {"sl": 1.08}, "put"),
    ],
)
async def test_authorized_position_proxy_passes_internal_executor_credential(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    payload: dict[str, float] | None,
    client_method: str,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-executor-internal-secret")
    monkeypatch.setattr(positions, "_require", AsyncMock(return_value=None))
    client = AsyncMock()
    response = httpx.Response(
        200,
        json={"status": "FILLED"},
        request=httpx.Request("POST", "http://executor"),
    )
    getattr(client, client_method).return_value = response
    monkeypatch.setattr(positions, "new_client", lambda **_: _ClientContext(client))

    result = await api_client.request(
        method,
        path,
        json=payload,
        headers={"Authorization": f"Bearer {create_token('authorized-user')}"},
    )

    if path.endswith("/modify"):
        assert result.status_code == 200
        assert result.json()["status"] == "FILLED"
    else:
        assert result.status_code == 202
    call = getattr(client, client_method).await_args
    assert call.kwargs["headers"] == {
        "X-Nexus-Internal-Secret": "test-executor-internal-secret"
    }


@pytest.mark.asyncio
async def test_modify_position_surfaces_executor_rejection_instead_of_accepted_202(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-executor-internal-secret")
    monkeypatch.setattr(positions, "_require", AsyncMock(return_value=None))
    client = AsyncMock()
    client.put.return_value = httpx.Response(
        200,
        json={"status": "REJECTED", "error": "invalid stops"},
        request=httpx.Request("PUT", "http://executor/api/executor/position/123"),
    )
    monkeypatch.setattr(positions, "new_client", lambda **_: _ClientContext(client))

    response = await api_client.post(
        "/api/positions/123/modify",
        json={"sl": 1.08},
        headers={"Authorization": f"Bearer {create_token('authorized-user')}"},
    )

    assert response.status_code == 502
    assert "invalid stops" in response.json()["detail"]


@pytest.mark.asyncio
async def test_modify_position_preserves_executor_pending_status(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-executor-internal-secret")
    monkeypatch.setattr(positions, "_require", AsyncMock(return_value=None))
    client = AsyncMock()
    client.put.return_value = httpx.Response(
        200,
        json={"status": "PENDING", "order_id": "123"},
        request=httpx.Request("PUT", "http://executor/api/executor/position/123"),
    )
    monkeypatch.setattr(positions, "new_client", lambda **_: _ClientContext(client))

    response = await api_client.post(
        "/api/positions/123/modify",
        json={"tp1": 1.12},
        headers={"Authorization": f"Bearer {create_token('authorized-user')}"},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "PENDING"


@pytest.mark.asyncio
async def test_position_read_proxy_passes_internal_executor_credential(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-executor-internal-secret")
    client = AsyncMock()
    response = httpx.Response(
        200,
        json={"positions": [], "account": {}, "nexus_count": 0, "external_count": 0},
        request=httpx.Request("GET", "http://executor/api/executor/positions"),
    )
    client.get.return_value = response
    monkeypatch.setattr(positions, "new_client", lambda **_: _ClientContext(client))

    await positions._fetch_live_executor_snapshot()

    assert client.get.await_args.kwargs["headers"] == {
        "X-Nexus-Internal-Secret": "test-executor-internal-secret"
    }


@pytest.mark.asyncio
async def test_position_read_proxy_fails_closed_without_internal_secret(monkeypatch):
    monkeypatch.delenv("NEXUS_INTERNAL_API_SECRET", raising=False)
    client = AsyncMock()
    monkeypatch.setattr(positions, "new_client", lambda **_: _ClientContext(client))

    with pytest.raises(HTTPException) as raised:
        await positions._fetch_live_executor_snapshot()

    assert getattr(raised.value, "status_code", None) == 503
    client.get.assert_not_awaited()
