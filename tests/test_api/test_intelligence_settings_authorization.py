from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.nexus_api.middleware.auth import create_token
from services.nexus_api.routers import intelligence


@pytest.mark.asyncio
async def test_dynamic_settings_rejects_missing_jwt_before_redis_write(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    redis = SimpleNamespace(get=AsyncMock(return_value=None), set=AsyncMock())
    monkeypatch.setattr(intelligence, "_get_redis", AsyncMock(return_value=redis))

    response = await api_client.post(
        "/api/intelligence/settings",
        json={"settings": {"operational_tf": "M5"}},
    )

    assert response.status_code == 401
    redis.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_dynamic_settings_requires_trading_settings_before_redis_write(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    redis = SimpleNamespace(get=AsyncMock(return_value=None), set=AsyncMock())
    monkeypatch.setattr(intelligence, "_get_redis", AsyncMock(return_value=redis))

    response = await api_client.post(
        "/api/intelligence/settings",
        json={"settings": {"operational_tf": "M5"}},
        headers={"Authorization": f"Bearer {create_token('unprivileged-user')}"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "permission required: trading.settings"}
    redis.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_dynamic_settings_null_removes_only_requested_override(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    monkeypatch.setattr(intelligence, "_require", AsyncMock())
    redis = SimpleNamespace(
        get=AsyncMock(return_value='{"keep_setting": 7, "reset_setting": 3}'),
        set=AsyncMock(),
    )
    monkeypatch.setattr(intelligence, "_get_redis", AsyncMock(return_value=redis))

    response = await api_client.post(
        "/api/intelligence/settings",
        json={"settings": {"reset_setting": None}},
        headers={"Authorization": f"Bearer {create_token('settings-user')}"},
    )

    assert response.status_code == 200
    saved = json.loads(redis.set.await_args.args[1])
    assert saved == {"keep_setting": 7}
