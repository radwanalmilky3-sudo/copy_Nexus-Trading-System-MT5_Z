"""QA honesty-contract pins (Agent 4) — API layer.

Independent re-verification of the closed audit findings. These tests pin the
exact boundary: an empty/unavailable upstream must surface as UNKNOWN/null /
available=false — never 0, never NEUTRAL, never a ready matrix. No live Redis,
no DuckDB, no network: every route here is exercised against an in-memory stub.
"""
from __future__ import annotations

import json

import pytest

from services.nexus_api.routers import intelligence


# ── UI-04: cross-asset fallback ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_asset_empty_store_is_unknown_not_neutral_grade(monkeypatch):
    async def stub(_key, *args, **kwargs):
        return None

    monkeypatch.setattr(intelligence, "_redis_get", stub)

    result = await intelligence.get_cross_asset()

    assert result["gold_yield_regime"] == "unknown"
    assert result["gold_yield_regime"] != "neutral"
    assert result["cross_asset_signal_pts"] is None
    assert result["cross_asset_signal_pts"] != 3
    assert result["gold_dxy_divergence"] is None
    assert result["dxy"]["level"] is None
    assert result["us10y"]["level"] is None
    assert result["updated_at"] is None


# ── Signal quality: empty store is UNKNOWN, not score 0 / blocked gate ────────


@pytest.mark.asyncio
async def test_signal_quality_empty_store_is_unknown_not_zero(monkeypatch):
    async def stub(_key):
        return None

    monkeypatch.setattr(intelligence, "_redis_get", stub)

    result = await intelligence.get_signal_quality()

    assert result["available"] is False
    assert result["score"] is None
    assert result["score"] != 0
    assert result["passes"] is None
    assert result["threshold"] is None
    assert result["computed_at"] is None
    assert result["reason"] == "not_computed"


@pytest.mark.asyncio
async def test_signal_quality_real_payload_is_passed_through_with_available(monkeypatch):
    payload = {
        "score": 72,
        "max_score": 100,
        "threshold": 60,
        "passes": True,
        "computed_at": "2026-10-21T10:00:00Z",
    }

    async def stub(_key):
        return json.dumps(payload)

    monkeypatch.setattr(intelligence, "_redis_get", stub)

    result = await intelligence.get_signal_quality()

    assert result["available"] is True
    assert result["score"] == 72
    assert result["passes"] is True
    assert result["computed_at"] == "2026-10-21T10:00:00Z"


# ── Correlation: empty store is unavailable, never a zero matrix ──────────────


@pytest.mark.asyncio
async def test_correlation_empty_store_is_unavailable_not_zero_matrix(monkeypatch):
    async def stub(_key):
        return None

    monkeypatch.setattr(intelligence, "_redis_get", stub)

    result = await intelligence.get_correlation()

    assert result["available"] is False
    assert result["reason"] == "no_snapshot"
    assert result["windows"] == {}
    assert result["lag_signals"] == []
    assert result["updated_at"] is None
    # No numeric matrix content may appear anywhere in the payload.
    def _numeric_leaves(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                yield from _numeric_leaves(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                yield from _numeric_leaves(v, f"{path}[{i}]")
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            yield path, node

    assert list(_numeric_leaves(result["matrices"])) == []
    assert list(_numeric_leaves(result["windows"])) == []


@pytest.mark.asyncio
async def test_correlation_snapshot_without_timestamp_is_not_available(monkeypatch):
    """A cached matrix lacking updated_at is undated — unavailable, not ready."""
    snapshot = {
        "assets": ["XAUUSD", "BTCUSD", "OIL", "SPX"],
        "matrices": {"7d": {"XAUUSD": {"BTCUSD": 0.4}}},
        "updated_at": None,
    }

    async def stub(_key):
        return json.dumps(snapshot)

    monkeypatch.setattr(intelligence, "_redis_get", stub)

    result = await intelligence.get_correlation()

    assert result["available"] is False


@pytest.mark.asyncio
async def test_correlation_dated_snapshot_is_available_with_basis(monkeypatch):
    snapshot = {
        "assets": ["XAUUSD", "BTCUSD", "OIL", "SPX"],
        "matrices": {"7d": {}},
        "updated_at": "2026-10-21T10:00:00Z",
    }

    async def stub(_key):
        return json.dumps(snapshot)

    monkeypatch.setattr(intelligence, "_redis_get", stub)

    result = await intelligence.get_correlation()

    assert result["available"] is True
    assert result["basis"] == "synchronized_returns"
    assert result["disclaimer"]
    assert result["windows"] == {}
    assert result["lag_signals"] == []


# ── Trade-memory snapshot: empty store keeps totals absent ────────────────────


@pytest.mark.asyncio
async def test_trade_memory_empty_store_has_no_totals_to_fabricate(monkeypatch):
    class _EmptyRedis:
        async def get(self, _key):
            return None

    async def factory():
        return _EmptyRedis()

    monkeypatch.setattr(intelligence, "_get_redis", factory)

    result = await intelligence.get_trade_memory_full()

    assert result["metrics"] == {}
    for field in ("total_trades", "total_wins", "total_losses", "overall_win_rate"):
        assert field not in result["metrics"]
    assert result["thresholds"] == {}
    assert result["recent_trades"] == []
