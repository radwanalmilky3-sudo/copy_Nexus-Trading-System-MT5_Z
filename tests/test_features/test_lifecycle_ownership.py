import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.nexus_features import main as features


@pytest.mark.asyncio
async def test_exceptional_exit_joins_all_tasks_before_closing_redis(monkeypatch):
    started = []
    stopped = []

    async def worker(*args, **kwargs):
        task = asyncio.current_task()
        started.append(task)
        try:
            await asyncio.Event().wait()
        finally:
            stopped.append(task)

    async def close():
        assert len(stopped) == 7

    connection = SimpleNamespace(aclose=AsyncMock(side_effect=close))
    monkeypatch.setattr(features.aioredis, "from_url", lambda *args, **kwargs: connection)
    monkeypatch.setattr(features, "_ensure_consumer_group", AsyncMock())
    for name in (
        "_ohlcv_consumer", "_heartbeat_loop", "cross_asset_refresh_loop",
        "shift_monitor_loop", "correlation_refresh_loop",
        "compute_cross_asset_features", "_institutional_refresh_loop",
    ):
        monkeypatch.setattr(features, name, worker)

    with pytest.raises(RuntimeError, match="application failure"):
        async with features.lifespan(features.app):
            await asyncio.sleep(0)
            assert len(started) == 7
            raise RuntimeError("application failure")

    connection.aclose.assert_awaited_once()
    assert all(task.done() for task in started)
    assert features.redis_pool is None


@pytest.mark.asyncio
async def test_initialization_failure_closes_redis(monkeypatch):
    connection = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr(features.aioredis, "from_url", lambda *args, **kwargs: connection)
    monkeypatch.setattr(features, "_ensure_consumer_group", AsyncMock(side_effect=RuntimeError("init failure")))

    with pytest.raises(RuntimeError, match="init failure"):
        async with features.lifespan(features.app):
            pytest.fail("initialization must not succeed")

    connection.aclose.assert_awaited_once()
