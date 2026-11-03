"""Regime history must distinguish an empty history from unavailable data."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from services.nexus_api.routers import regime


@pytest.mark.asyncio
async def test_regime_history_returns_503_when_redis_is_unavailable(monkeypatch):
    async def unavailable_redis():
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(regime, "_get_redis", unavailable_redis)

    with pytest.raises(HTTPException) as exc:
        await regime.get_regime_history()

    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_regime_history_returns_503_when_cached_json_is_invalid(monkeypatch):
    class FakeRedis:
        async def lrange(self, *_args):
            return ["not-json"]

    async def available_redis():
        return FakeRedis()

    monkeypatch.setattr(regime, "_get_redis", available_redis)

    with pytest.raises(HTTPException) as exc:
        await regime.get_regime_history()

    assert exc.value.status_code == 503
