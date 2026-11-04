"""History table, stats endpoint, and CSV must share one filter contract.

symbol/session/since (the date window) are the shared filters. account and
timeframe do not exist on either route today; the signature parity test fails
if they are ever added to only one side.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from services.nexus_api.routers import trades

HISTORY_PAGE = Path(__file__).resolve().parents[2] / "dashboard" / "src" / "app" / "nexus" / "history" / "page.tsx"

SHARED_FILTERS = {"symbol", "session", "since"}


class AuthorizedDataService:
    async def query(self, operation: str, params: dict | None = None):
        return [{"permission_code": "*"}]


@pytest.fixture
def proxy_recorder(monkeypatch):
    calls: list[dict] = []

    async def fake_proxy(params: dict):
        calls.append(dict(params))
        return {"trades": [], "total": 0}

    monkeypatch.setattr(trades, "_proxy_trades", fake_proxy)
    return calls


@pytest.mark.asyncio
async def test_table_and_stats_forward_identical_shared_filters(proxy_recorder):
    filters = {"symbol": "XAUUSD", "session": "london", "since": "2026-10-01T00:00:00Z"}
    await trades.list_trades(
        actor="tester", db=AuthorizedDataService(), side=None, page=1, page_size=50, **filters
    )
    await trades.trade_stats(actor="tester", db=AuthorizedDataService(), **filters)

    assert len(proxy_recorder) == 2
    list_params, stats_params = proxy_recorder
    for key, value in filters.items():
        assert list_params.get(key) == value, f"list_trades lost filter {key}"
        assert stats_params.get(key) == value, f"trade_stats lost filter {key}"
    assert SHARED_FILTERS <= set(list_params)
    assert SHARED_FILTERS <= set(stats_params)


def test_route_filter_signatures_are_identical():
    def filter_params(fn) -> set[str]:
        return set(inspect.signature(fn).parameters) - {"actor", "db", "side", "page", "page_size"}

    assert filter_params(trades.list_trades) == SHARED_FILTERS
    assert filter_params(trades.trade_stats) == SHARED_FILTERS


def test_history_page_sends_one_shared_query_to_table_and_stats():
    source = HISTORY_PAGE.read_text(encoding="utf-8")
    assert "/api/trades?${params}" in source, "table must query with the shared params"
    assert "/api/trades/stats?${params}" in source, "stats must reuse the same shared params"
    assert "params.set('since'" in source
    assert "params.set('symbol'" in source
    assert "stats?${since" not in source, "stats must not build a narrower query anymore"
