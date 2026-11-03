from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services.nexus_api.routers import positions


@pytest.mark.asyncio
async def test_closed_positions_do_not_reuse_open_status_cache(monkeypatch):
    open_position = {
        "id": "open-1",
        "symbol": "EURUSD",
        "side": "BUY",
        "entry_price": 1.1,
        "status": "open",
    }
    closed_position = {
        "id": "closed-1",
        "symbol": "EURUSD",
        "side": "BUY",
        "entry_price": 1.1,
        "status": "closed",
    }

    class FakeRedis:
        def __init__(self):
            self.cache = {"positions:all": [open_position]}

        async def cache_get(self, key):
            return self.cache.get(key)

        async def cache_set(self, key, value, *, ttl_sec):
            self.cache[key] = value

    db = type("FakeDataService", (), {})()
    db.query = AsyncMock(return_value=[closed_position])
    monkeypatch.setattr(positions, "_require", AsyncMock(return_value=None))
    monkeypatch.setattr(
        positions,
        "_fetch_live_executor_snapshot",
        AsyncMock(return_value=([], None, False, 0, 0)),
    )

    result = await positions.list_positions(
        actor=object(),
        db=db,
        symbol=None,
        status_filter="closed",
        redis=FakeRedis(),
    )

    assert [position.id for position in result["positions"]] == ["closed-1"]
    db.query.assert_awaited_once_with("positions_by_status", {"status": "closed"})
