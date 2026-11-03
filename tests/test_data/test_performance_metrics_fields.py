"""Regression: ``GET /api/data/performance`` must return **all 8** KPI fields.

The dashboard's ``PLDashboard.coercePerf`` requires
``total_pnl, win_rate, profit_factor, sharpe_ratio, max_drawdown, total_trades``
(and optionally ``avg_win``/``avg_loss``).  The data owner used to return only
the first six, so the panel threw ``Performance response is incomplete`` and
blanked every KPI card behind it — including when the table was empty.

Formulas are checked against an independent Python reference that mirrors
``nexus_monitor.performance.PerformanceAnalyzer``.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

import pytest

from services.nexus_data.duckdb_store import DataStore

REQUIRED_FIELDS = (
    "total_pnl",
    "total_trades",
    "avg_win",
    "avg_loss",
    "win_rate",
    "profit_factor",
    "sharpe_ratio",
    "max_drawdown",
)

_EPOCH = datetime(2026, 1, 5, 12, 0, 0)


def _trade(idx: int, pnl: float, day_offset: int) -> tuple:
    closed = _EPOCH + timedelta(days=day_offset)
    return (
        f"T{idx:04d}", "XAUUSD", "buy", 100.0, 100.0 + pnl, pnl, pnl,
        2.0, 600.0, "london", 0.6, closed - timedelta(hours=1), closed,
    )


def _insert(store: DataStore, rows: list[tuple]) -> None:
    store._conn.executemany(
        """
        INSERT INTO trades (
            id, symbol, side, entry_price, exit_price, pnl_pips, pnl_usd,
            rr_ratio, duration_s, session, conviction, opened_at, closed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _ref_sharpe(daily_pnls: list[float]) -> float:
    """mean/std(ddof=1) * sqrt(252), 0.0 for <2 points or a zero std."""
    if len(daily_pnls) < 2:
        return 0.0
    mean = sum(daily_pnls) / len(daily_pnls)
    variance = sum((x - mean) ** 2 for x in daily_pnls) / (len(daily_pnls) - 1)
    std = math.sqrt(variance)
    if std == 0:
        return 0.0
    value = mean / std * math.sqrt(252)
    return round(value, 4) if math.isfinite(value) else 0.0


def _ref_max_drawdown(pnls: list[float]) -> float:
    """Peak-to-trough on the running equity; % of peak when peak > 0."""
    if len(pnls) < 2:
        return 0.0
    equity, running = [], 0.0
    for p in pnls:
        running += p
        equity.append(running)
    peak = equity[0]
    max_dd = 0.0
    peak_at_worst = peak
    for value in equity:
        peak = max(peak, value)
        dd = peak - value
        if dd > max_dd:
            max_dd = dd
            peak_at_worst = peak
    if max_dd <= 0:
        return 0.0
    if peak_at_worst > 0:
        return round(max_dd / peak_at_worst * 100, 2)
    return round(max_dd, 2)


def _assert_panel_ready(payload: dict) -> None:
    """The frontend throws on the first non-finite value — none may exist."""
    for field in REQUIRED_FIELDS:
        assert field in payload, f"{field} missing from performance payload"
        value = payload[field]
        assert isinstance(value, (int, float)), f"{field} is not numeric: {value!r}"
        assert math.isfinite(value), f"{field} is not finite: {value!r}"


@pytest.mark.asyncio
async def test_empty_trades_table_still_returns_every_kpi_field(operational_store):
    """Empty book → 8 finite zeros, never a partial payload (the reported bug)."""
    payload = await operational_store.get_performance_metrics()

    _assert_panel_ready(payload)
    assert payload["total_trades"] == 0
    assert payload["total_pnl"] == 0
    assert payload["sharpe_ratio"] == 0
    assert payload["max_drawdown"] == 0


@pytest.mark.asyncio
async def test_sharpe_and_max_drawdown_match_the_reference_formulas(operational_store):
    pnls = [120.0, -80.0, 45.0, -150.0, 60.0, 95.0, -30.0]
    rows = [_trade(i, pnl, i) for i, pnl in enumerate(pnls)]
    _insert(operational_store, rows)

    payload = await operational_store.get_performance_metrics()

    _assert_panel_ready(payload)
    assert payload["total_trades"] == len(pnls)
    assert payload["total_pnl"] == pytest.approx(sum(pnls))
    assert payload["sharpe_ratio"] == pytest.approx(_ref_sharpe(pnls))
    assert payload["max_drawdown"] == pytest.approx(_ref_max_drawdown(pnls))


@pytest.mark.asyncio
async def test_single_trade_never_divides_by_an_empty_sample(operational_store):
    _insert(operational_store, [_trade(0, 250.0, 0)])

    payload = await operational_store.get_performance_metrics()

    _assert_panel_ready(payload)
    assert payload["total_trades"] == 1
    assert payload["total_pnl"] == pytest.approx(250.0)
    # A one-point sample has no dispersion and no peak-to-trough path.
    assert payload["sharpe_ratio"] == 0
    assert payload["max_drawdown"] == 0


@pytest.mark.asyncio
async def test_winning_streak_has_zero_drawdown(operational_store):
    # Same trading day → one daily point (no dispersion), rising equity (no trough).
    pnls = [10.0, 20.0, 30.0, 40.0]
    _insert(operational_store, [_trade(i, pnl, 0) for i, pnl in enumerate(pnls)])

    payload = await operational_store.get_performance_metrics()

    _assert_panel_ready(payload)
    assert payload["max_drawdown"] == 0
    assert payload["win_rate"] == 100.0
    assert payload["sharpe_ratio"] == 0  # fewer than two daily points
