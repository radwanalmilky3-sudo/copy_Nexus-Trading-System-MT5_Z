from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services.nexus_api.middleware.auth import create_token
from services.nexus_api.routers import fundamental


def install_active_ticker(monkeypatch: pytest.MonkeyPatch) -> None:
    item = {"ticker_item_id": "item-1", "source_id": "calendar_secondary"}

    async def snap(redis, key, default):
        if key in {"news:ticker:active", "news:ticker:lifecycle"}:
            return [dict(item)]
        return default

    monkeypatch.setattr(fundamental, "_snap", snap)


@pytest.mark.asyncio
async def test_global_ticker_settings_rejects_missing_jwt_before_redis_write(
    api_client,
    redis_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    cache_set = AsyncMock()
    monkeypatch.setattr(redis_client, "cache_set", cache_set)

    response = await api_client.put("/api/fundamental/settings/news-ticker", json={"enabled": False})

    assert response.status_code == 401
    cache_set.assert_not_awaited()


@pytest.mark.asyncio
async def test_global_ticker_settings_requires_manage_permission_before_redis_write(
    api_client,
    redis_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    cache_set = AsyncMock()
    monkeypatch.setattr(redis_client, "cache_set", cache_set)

    response = await api_client.put(
        "/api/fundamental/settings/news-ticker",
        json={"enabled": False},
        headers={"Authorization": f"Bearer {create_token('unprivileged-user')}"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "permission required: ticker.manage_global"}
    cache_set.assert_not_awaited()


@pytest.mark.asyncio
async def test_ticker_acknowledgement_rejects_missing_jwt_before_mutation(
    api_client,
    redis_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    cache_set = AsyncMock()
    monkeypatch.setattr(redis_client, "cache_set", cache_set)
    post_data = AsyncMock()
    monkeypatch.setattr(fundamental, "_post_data", post_data)
    install_active_ticker(monkeypatch)

    response = await api_client.post(
        "/api/fundamental/ticker/item-1/acknowledge",
        json={"acknowledged": True, "actor": "forged"},
    )

    assert response.status_code == 401
    cache_set.assert_not_awaited()
    post_data.assert_not_awaited()


@pytest.mark.asyncio
async def test_ticker_acknowledgement_requires_permission_before_mutation(
    api_client,
    redis_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    cache_set = AsyncMock()
    monkeypatch.setattr(redis_client, "cache_set", cache_set)
    post_data = AsyncMock()
    monkeypatch.setattr(fundamental, "_post_data", post_data)

    response = await api_client.post(
        "/api/fundamental/ticker/item-1/acknowledge",
        json={"acknowledged": True, "actor": "forged"},
        headers={"Authorization": f"Bearer {create_token('unprivileged-user')}"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "permission required: ticker.acknowledge"}
    cache_set.assert_not_awaited()
    post_data.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("unprivileged", [False, True])
async def test_ticker_delivery_requires_acknowledge_permission_before_write(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
    unprivileged: bool,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    post_data = AsyncMock(return_value=True)
    monkeypatch.setattr(fundamental, "_post_data", post_data)

    headers = {"Authorization": f"Bearer {create_token('unprivileged-user')}"} if unprivileged else None
    response = await api_client.post(
        "/api/fundamental/ticker/delivery",
        json={"ticker_item_id": "item-1", "channel": "browser"},
        headers=headers,
    )

    assert response.status_code == (403 if unprivileged else 401)
    post_data.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("unprivileged", [False, True])
async def test_local_ai_analysis_requires_fundamental_view_before_read_or_write(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
    unprivileged: bool,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    overview = AsyncMock(return_value={})
    snap = AsyncMock(return_value={})
    post_data = AsyncMock(return_value=True)
    monkeypatch.setattr(fundamental, "_overview_payload", overview)
    monkeypatch.setattr(fundamental, "_snap", snap)
    monkeypatch.setattr(fundamental, "_post_data", post_data)

    headers = {"Authorization": f"Bearer {create_token('unprivileged-user')}"} if unprivileged else None
    response = await api_client.post(
        "/api/fundamental/local-ai/analyze",
        json={"question": "Explain the current outlook", "asset": "XAUUSD"},
        headers=headers,
    )

    assert response.status_code == (403 if unprivileged else 401)
    expected_permission = "fundamental.view"
    if unprivileged:
        assert response.json() == {"detail": f"permission required: {expected_permission}"}
    overview.assert_not_awaited()
    snap.assert_not_awaited()
    post_data.assert_not_awaited()
