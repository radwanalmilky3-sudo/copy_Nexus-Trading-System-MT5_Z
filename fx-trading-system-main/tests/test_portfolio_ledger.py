from __future__ import annotations

import math

import pandas as pd
import pytest

from fx_system.portfolio_ledger import (
    MasterAccountLedger,
    book_day_bid_ask,
    book_day_mid_plus_half_spread,
)


def test_constant_mid_round_trip_loses_exactly_one_full_spread() -> None:
    ledger = MasterAccountLedger(initial_nav=100.0)
    opened = ledger.book_mid_plus_half_spread(
        timestamp="2025-01-02",
        target_positions={"EURUSD": 10.0},
        mid_prices={"EURUSD": 1.20},
        half_spreads={"EURUSD": 0.001},
    )
    closed = ledger.book_mid_plus_half_spread(
        timestamp="2025-01-03",
        target_positions={},
        mid_prices={"EURUSD": 1.20},
        half_spreads={"EURUSD": 0.001},
    )

    assert opened.price_pnl == 0.0
    assert closed.price_pnl == 0.0
    assert opened.spread_cost + closed.spread_cost == pytest.approx(10.0 * 0.002)
    assert ledger.nav == pytest.approx(100.0 - 10.0 * 0.002)


def test_full_reversal_trades_and_costs_twice_absolute_position() -> None:
    entry = book_day_mid_plus_half_spread(
        timestamp="2025-01-02",
        previous_nav=100.0,
        previous_positions={"EURUSD": 5.0},
        target_positions={"EURUSD": -5.0},
        previous_mid_prices={"EURUSD": 1.20},
        mid_prices={"EURUSD": 1.20},
        half_spreads={"EURUSD": 0.001},
    )

    assert entry.net_trades["EURUSD"] == pytest.approx(-10.0)
    assert entry.broker_turnover == pytest.approx(2 * 5.0)
    assert entry.spread_cost == pytest.approx(2 * 5.0 * 0.001)


@pytest.mark.parametrize("mode", ["mid", "bid_ask"])
def test_unchanged_net_position_has_zero_trading_cost(mode: str) -> None:
    common = {
        "timestamp": "2025-01-02",
        "previous_nav": 100.0,
        "previous_positions": {"EURUSD": 7.0},
        "target_positions": {"EURUSD": 7.0},
        "previous_mid_prices": {"EURUSD": 1.20},
        "mid_prices": {"EURUSD": 1.21},
        "slippage_per_unit": {"EURUSD": 99.0},
    }
    if mode == "mid":
        entry = book_day_mid_plus_half_spread(
            **common,
            half_spreads={"EURUSD": 0.001},
        )
    else:
        entry = book_day_bid_ask(
            **common,
            bids={"EURUSD": 1.209},
            asks={"EURUSD": 1.211},
        )

    assert dict(entry.net_trades) == {}
    assert entry.broker_turnover == 0.0
    assert entry.spread_cost == 0.0
    assert entry.slippage_cost == 0.0
    assert entry.price_pnl == pytest.approx(7.0 * 0.01)


def test_symmetric_bid_ask_and_explicit_half_spread_accounting_are_equivalent() -> None:
    common = {
        "timestamp": "2025-01-02",
        "previous_nav": 1_000.0,
        "previous_positions": {"EURUSD": 2.0, "USDJPY": -3.0},
        "target_positions": {"EURUSD": -4.0, "USDJPY": 1.0},
        "previous_mid_prices": {"EURUSD": 1.19, "USDJPY": 150.0},
        "mid_prices": {"EURUSD": 1.20, "USDJPY": 149.5},
        "slippage_per_unit": {"EURUSD": 0.0002, "USDJPY": 0.01},
        "financing": -0.12,
        "cash_interest": 0.03,
        "account_value_multipliers": {"EURUSD": 1.0, "USDJPY": 0.01},
    }
    midpoint = book_day_mid_plus_half_spread(
        **common,
        half_spreads={"EURUSD": 0.001, "USDJPY": 0.05},
    )
    executable = book_day_bid_ask(
        **common,
        bids={"EURUSD": 1.199, "USDJPY": 149.45},
        asks={"EURUSD": 1.201, "USDJPY": 149.55},
    )

    fields = (
        "price_pnl",
        "spread_cost",
        "slippage_cost",
        "financing",
        "cash_interest",
        "net_pnl",
        "nav",
        "simple_return",
        "broker_turnover",
    )
    for field in fields:
        assert getattr(executable, field) == pytest.approx(getattr(midpoint, field))


def test_pnl_components_reconcile_exactly_to_nav_change() -> None:
    entry = book_day_bid_ask(
        timestamp="2025-01-02",
        previous_nav=1_000.0,
        previous_positions={"EURUSD": 100.0},
        target_positions={"EURUSD": -50.0},
        previous_mid_prices={"EURUSD": 1.10},
        mid_prices={"EURUSD": 1.12},
        bids={"EURUSD": 1.119},
        asks={"EURUSD": 1.121},
        slippage_per_unit={"EURUSD": 0.0004},
        financing=-0.30,
        cash_interest=0.20,
    )

    component_sum = math.fsum(
        (
            entry.price_pnl,
            -entry.spread_cost,
            -entry.slippage_cost,
            entry.financing,
            entry.cash_interest,
        )
    )
    assert entry.net_pnl == component_sum
    assert entry.nav - entry.previous_nav == pytest.approx(component_sum)


def test_daily_returns_compound_to_final_nav() -> None:
    ledger = MasterAccountLedger(initial_nav=100.0)
    ledger.book_mid_plus_half_spread(
        timestamp="2025-01-02",
        target_positions={"EURUSD": 10.0},
        mid_prices={"EURUSD": 1.00},
        half_spreads={"EURUSD": 0.001},
        cash_interest=0.10,
    )
    ledger.book_mid_plus_half_spread(
        timestamp="2025-01-03",
        target_positions={"EURUSD": 10.0},
        mid_prices={"EURUSD": 1.10},
        half_spreads={},
        financing=-0.05,
    )
    ledger.book_mid_plus_half_spread(
        timestamp="2025-01-06",
        target_positions={},
        mid_prices={"EURUSD": 1.08},
        half_spreads={"EURUSD": 0.001},
    )

    compounded_growth = math.prod(1.0 + entry.simple_return for entry in ledger.entries)
    assert 100.0 * compounded_growth == pytest.approx(ledger.nav)
    assert compounded_growth - 1.0 == pytest.approx(ledger.compounded_return)
    frame = ledger.to_frame()
    assert isinstance(frame.index, pd.DatetimeIndex)
    assert frame.iloc[-1]["nav"] == pytest.approx(ledger.nav)


def test_bid_ask_path_rejects_crossed_or_missing_executable_quotes() -> None:
    common = {
        "timestamp": "2025-01-02",
        "previous_nav": 100.0,
        "previous_positions": {},
        "target_positions": {"EURUSD": 1.0},
        "previous_mid_prices": {},
        "mid_prices": {"EURUSD": 1.20},
    }
    with pytest.raises(ValueError, match="bid cannot exceed ask"):
        book_day_bid_ask(
            **common,
            bids={"EURUSD": 1.21},
            asks={"EURUSD": 1.19},
        )
    with pytest.raises(ValueError, match="asks is missing EURUSD"):
        book_day_bid_ask(**common, bids={"EURUSD": 1.19}, asks={})


def test_failed_out_of_order_post_does_not_mutate_ledger() -> None:
    ledger = MasterAccountLedger(initial_nav=100.0)
    ledger.book_mid_plus_half_spread(
        timestamp="2025-01-03",
        target_positions={"EURUSD": 1.0},
        mid_prices={"EURUSD": 1.20},
        half_spreads={"EURUSD": 0.001},
    )
    nav = ledger.nav
    positions = dict(ledger.positions)

    with pytest.raises(ValueError, match="strictly increasing"):
        ledger.book_mid_plus_half_spread(
            timestamp="2025-01-02",
            target_positions={},
            mid_prices={"EURUSD": 1.20},
            half_spreads={"EURUSD": 0.001},
        )

    assert ledger.nav == nav
    assert dict(ledger.positions) == positions
    assert len(ledger.entries) == 1


def test_ledger_rejects_nonpositive_starting_nav() -> None:
    with pytest.raises(ValueError, match="positive"):
        MasterAccountLedger(initial_nav=0.0)
    with pytest.raises(ValueError, match="positive"):
        book_day_mid_plus_half_spread(
            timestamp="2025-01-02",
            previous_nav=-1.0,
            previous_positions={},
            target_positions={},
            previous_mid_prices={},
            mid_prices={},
            half_spreads={},
        )
