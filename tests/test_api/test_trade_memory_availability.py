"""Trade-memory and cross-asset reads must distinguish empty data from an
unavailable source, and must never fabricate grades from missing inputs."""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from services.nexus_api.routers import intelligence


@pytest.mark.asyncio
async def test_trade_memory_returns_503_when_redis_is_unavailable(monkeypatch):
    async def unavailable_redis():
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(intelligence, "_get_redis", unavailable_redis)

    with pytest.raises(HTTPException) as exc:
        await intelligence.get_trade_memory_full()

    assert exc.value.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key,value",
    [
        ("nexus:trade_memory:metrics", "[]"),
        ("nexus:trade_memory:thresholds", "[]"),
        ("nexus:trade_memory:trades", "{}"),
    ],
)
async def test_trade_memory_returns_503_when_stored_json_has_wrong_shape(monkeypatch, key, value):
    class FakeRedis:
        async def get(self, requested_key):
            if requested_key == key:
                return value
            return None

    async def available_redis():
        return FakeRedis()

    monkeypatch.setattr(intelligence, "_get_redis", available_redis)

    with pytest.raises(HTTPException) as exc:
        await intelligence.get_trade_memory_full()

    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_trade_memory_empty_redis_returns_empty_metrics_not_fabricated(monkeypatch):
    """An empty store is honest empty data ({} / []), not invented totals."""
    class EmptyRedis:
        async def get(self, _key):
            return None

    async def redis():
        return EmptyRedis()

    monkeypatch.setattr(intelligence, "_get_redis", redis)

    result = await intelligence.get_trade_memory_full()

    assert result["metrics"] == {}
    assert result["thresholds"] == {}
    assert result["recent_trades"] == []
    # No fabricated headline numbers for the UI to misrender.
    assert "total_trades" not in result["metrics"]
    assert "overall_win_rate" not in result["metrics"]


@pytest.mark.asyncio
async def test_cross_asset_fallback_never_fabricates_regime_or_grade(monkeypatch):
    """UI-04 regression: with no DXY/US10Y data the gateway must not answer
    neutral + 3/5 + divergence 0 — missing inputs are UNKNOWN, not a grade."""

    async def empty_store(_key):
        return None

    monkeypatch.setattr(intelligence, "_redis_get", empty_store)

    result = await intelligence.get_cross_asset()

    assert result["dxy"] == {"level": None, "source": "no_data"}
    assert result["us10y"] == {"level": None, "source": "no_data"}
    assert result["gold_yield_regime"] == "unknown"
    assert result["cross_asset_signal_pts"] is None
    assert result["gold_dxy_divergence"] is None
    assert result["updated_at"] is None


@pytest.mark.asyncio
async def test_cross_asset_summary_passthrough_is_untouched(monkeypatch):
    """A real cached summary must be returned verbatim (no re-grading)."""
    summary = {
        "dxy": {"level": 98.4, "change_5d": -0.3, "source": "official"},
        "us10y": {"level": 4.21, "change_5d": 0.02, "source": "official"},
        "gold_yield_regime": "risk_off",
        "gold_dxy_divergence": 1,
        "cross_asset_signal_pts": 4,
        "updated_at": "2026-10-21T10:00:00Z",
    }

    async def store(key):
        if key == "nexus:cross_asset:summary":
            return json.dumps(summary)
        return None

    monkeypatch.setattr(intelligence, "_redis_get", store)

    result = await intelligence.get_cross_asset()

    assert result == summary
