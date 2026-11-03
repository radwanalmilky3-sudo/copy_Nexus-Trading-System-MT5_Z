from __future__ import annotations

import math

import pandas as pd
import pandas.testing as pdt
import pytest

from fx_system.portfolio import CommonSessionCalendar
from fx_system.portfolio_runner import run_portfolio


def _calendar(periods: int) -> CommonSessionCalendar:
    return CommonSessionCalendar(
        pd.bdate_range("2025-01-02", periods=periods, tz="UTC"),
        symbols=("EURUSD", "GBPUSD"),
    )


def _constant_prices(calendar: CommonSessionCalendar) -> pd.DataFrame:
    return pd.DataFrame(
        {"EURUSD": 1.10, "GBPUSD": 1.25},
        index=calendar.sessions,
    )


def test_runner_handles_21_42_63_warmup_expiry_and_tail_without_opening() -> None:
    calendar = _calendar(127)
    prices = _constant_prices(calendar)
    rebalance_sessions = calendar.rebalance_sessions(21)
    targets = {
        session: {
            21: {"EURUSD": 1.0},
            42: {"EURUSD": 1.0},
            63: {"EURUSD": 1.0},
        }
        for session in rebalance_sessions
    }

    result = run_portfolio(
        calendar=calendar,
        horizon_budgets={21: 0.30, 42: 0.30, 63: 0.40},
        targets_by_rebalance=targets,
        mid_prices=prices,
        initial_nav=100.0,
    )

    committed = [transition.committed_sleeve_gross for transition in result.transitions]
    assert committed[:3] == pytest.approx(
        [
            0.30 + 0.15 + 0.40 / 3,
            0.30 + 0.30 + 2 * 0.40 / 3,
            1.0,
        ]
    )
    third_counts = [
        sum(sleeve.horizon_sessions == horizon for sleeve in result.transitions[2].active_sleeves)
        for horizon in (21, 42, 63)
    ]
    assert third_counts == [1, 2, 3]

    # The final valid vintages all expire on the last common session. New
    # targets at the right edge are recorded as skipped, never opened.
    assert dict(result.transitions[-1].target) == {}
    assert {sleeve.horizon_sessions for sleeve in result.transitions[-1].expired_sleeves} == {
        21,
        42,
        63,
    }
    assert len(result.skipped_targets) == 6
    assert {(item.session, item.horizon_sessions) for item in result.skipped_targets} >= {
        (rebalance_sessions[-1], 21),
        (rebalance_sessions[-1], 42),
        (rebalance_sessions[-1], 63),
    }
    assert len(result.entries) == len(calendar.sessions)
    assert result.entries[-1].timestamp == calendar.sessions[-1]
    assert dict(result.entries[-1].target_positions) == {}
    assert result.final_nav == pytest.approx(100.0)


def test_runner_nets_opposing_sleeves_before_charging_execution_cost() -> None:
    calendar = _calendar(43)
    prices = _constant_prices(calendar)
    spreads = pd.DataFrame(0.01, index=calendar.sessions, columns=prices.columns)
    slippage = pd.DataFrame(99.0, index=calendar.sessions, columns=prices.columns)

    result = run_portfolio(
        calendar=calendar,
        horizon_budgets={21: 0.25, 42: 0.50},
        targets_by_rebalance={
            calendar.sessions[0]: {
                21: {"EURUSD": 1.0},
                42: {"EURUSD": -1.0},
            }
        },
        mid_prices=prices,
        half_spreads=spreads,
        slippage_per_unit=slippage,
        initial_nav=100.0,
    )

    transition = result.transitions[0]
    opening_entry = result.entries[0]
    assert transition.committed_sleeve_gross == pytest.approx(0.50)
    assert dict(transition.target) == {}
    assert dict(opening_entry.net_trades) == {}
    assert opening_entry.broker_turnover == 0.0
    assert opening_entry.spread_cost == 0.0
    assert opening_entry.slippage_cost == 0.0


def test_daily_non_usd_quote_multiplier_scales_price_spread_and_net_slippage() -> None:
    calendar = CommonSessionCalendar(
        pd.bdate_range("2025-01-02", periods=22, tz="UTC"), symbols=("USDJPY",)
    )
    mids = pd.DataFrame(151.0, index=calendar.sessions, columns=["USDJPY"])
    mids.iloc[0, 0] = 150.0
    spreads = pd.DataFrame(0.10, index=calendar.sessions, columns=["USDJPY"])
    slippage = pd.DataFrame(0.05, index=calendar.sessions, columns=["USDJPY"])
    multipliers = pd.DataFrame(0.02, index=calendar.sessions, columns=["USDJPY"])
    multipliers.iloc[0, 0] = 0.01
    multipliers.iloc[-1, 0] = 0.03

    result = run_portfolio(
        calendar=calendar,
        horizon_budgets={21: 1.0},
        targets_by_rebalance={calendar.sessions[0]: {21: {"USDJPY": 1.0}}},
        mid_prices=mids,
        half_spreads=spreads,
        slippage_per_unit=slippage,
        account_value_multipliers=multipliers,
        initial_nav=100.0,
    )

    opened, marked, closed = result.entries[0], result.entries[1], result.entries[-1]
    assert opened.net_trades["USDJPY"] == pytest.approx(1.0)
    assert opened.spread_cost == pytest.approx(0.10 * 0.01)
    assert opened.slippage_cost == pytest.approx(0.05 * 0.01)
    assert marked.price_pnl == pytest.approx((151.0 - 150.0) * 0.02)
    assert closed.net_trades["USDJPY"] == pytest.approx(-1.0)
    assert closed.spread_cost == pytest.approx(0.10 * 0.03)
    assert closed.slippage_cost == pytest.approx(0.05 * 0.03)
    assert result.to_frame()["price_pnl"].sum() == pytest.approx(0.02)
    assert result.to_frame()["spread_cost"].sum() == pytest.approx(0.004)
    assert result.to_frame()["slippage_cost"].sum() == pytest.approx(0.002)


def test_runner_daily_ledger_and_final_nav_components_reconcile_including_cash_days() -> None:
    calendar = _calendar(43)
    step = pd.Series(range(len(calendar.sessions)), index=calendar.sessions, dtype=float)
    mids = pd.DataFrame(
        {
            "EURUSD": 1.0 + 0.01 * step,
            "GBPUSD": 1.25,
        },
        index=calendar.sessions,
    )
    bids = mids - 0.001
    asks = mids + 0.001
    financing = pd.Series(0.0, index=calendar.sessions)
    financing.iloc[:22] = -0.01
    cash_interest = pd.Series(0.002, index=calendar.sessions)

    result = run_portfolio(
        calendar=calendar,
        horizon_budgets={21: 1.0},
        targets_by_rebalance={calendar.sessions[0]: {21: {"EURUSD": 1.0}}},
        mid_prices=mids,
        bids=bids,
        asks=asks,
        financing=financing,
        cash_interest=cash_interest,
        initial_nav=100.0,
    )

    frame = result.to_frame()
    expected_change = math.fsum(
        (
            frame["price_pnl"].sum(),
            -frame["spread_cost"].sum(),
            -frame["slippage_cost"].sum(),
            frame["financing"].sum(),
            frame["cash_interest"].sum(),
        )
    )
    assert len(frame) == len(calendar.sessions)
    assert result.final_nav - 100.0 == pytest.approx(expected_change)
    assert frame["price_pnl"].sum() == pytest.approx(0.21)
    assert frame["spread_cost"].sum() == pytest.approx(0.002)
    assert all(not entry.target_positions for entry in result.entries[21:])
    assert frame.iloc[-1]["cash_interest"] == pytest.approx(0.002)


def test_input_date_symbol_and_mapping_order_do_not_change_result() -> None:
    calendar = _calendar(64)
    steps = pd.Series(range(len(calendar.sessions)), index=calendar.sessions, dtype=float)
    mids = pd.DataFrame(
        {
            "EURUSD": 1.10 + steps * 0.001,
            "GBPUSD": 1.25 - steps * 0.0005,
        },
        index=calendar.sessions,
    )
    spreads = pd.DataFrame(
        {"EURUSD": 0.0001, "GBPUSD": 0.0002}, index=calendar.sessions
    )
    financing = pd.Series(0.00001 * steps, index=calendar.sessions)
    first, second = calendar.sessions[[0, 21]]
    ordered_targets = {
        first: {
            21: {"EURUSD": 0.6, "GBPUSD": -0.4},
            42: {"EURUSD": -0.25, "GBPUSD": 0.75},
        },
        second: {
            21: {"EURUSD": -0.5, "GBPUSD": 0.5},
            42: {"EURUSD": 0.8, "GBPUSD": -0.2},
        },
    }
    reversed_targets = {
        second: {
            42: {"GBPUSD": -0.2, "EURUSD": 0.8},
            21: {"GBPUSD": 0.5, "EURUSD": -0.5},
        },
        first: {
            42: {"GBPUSD": 0.75, "EURUSD": -0.25},
            21: {"GBPUSD": -0.4, "EURUSD": 0.6},
        },
    }

    ordered = run_portfolio(
        calendar=calendar,
        horizon_budgets={21: 0.5, 42: 0.5},
        targets_by_rebalance=ordered_targets,
        mid_prices=mids,
        half_spreads=spreads,
        financing=financing,
        initial_nav=100.0,
    )
    shuffled = run_portfolio(
        calendar=calendar,
        horizon_budgets={42: 0.5, 21: 0.5},
        targets_by_rebalance=reversed_targets,
        mid_prices=mids.iloc[::-1, ::-1],
        half_spreads=spreads.iloc[::-1, ::-1],
        financing=financing.iloc[::-1],
        initial_nav=100.0,
    )

    pdt.assert_frame_equal(ordered.to_frame(), shuffled.to_frame())
    assert [dict(item.target) for item in ordered.transitions] == [
        dict(item.target) for item in shuffled.transitions
    ]


def test_runner_rejects_a_missing_common_market_date() -> None:
    calendar = _calendar(22)
    prices = _constant_prices(calendar).drop(index=calendar.sessions[7])

    with pytest.raises(ValueError, match="mid_prices is missing common sessions"):
        run_portfolio(
            calendar=calendar,
            horizon_budgets={21: 1.0},
            targets_by_rebalance={},
            mid_prices=prices,
        )


@pytest.mark.parametrize("input_name", ["slippage_per_unit", "account_value_multipliers"])
def test_runner_fails_closed_when_a_daily_cost_input_misses_common_date(
    input_name: str,
) -> None:
    calendar = _calendar(22)
    prices = _constant_prices(calendar)
    incomplete = pd.DataFrame(
        0.001,
        index=calendar.sessions.delete(5),
        columns=prices.columns,
    )
    if input_name == "account_value_multipliers":
        incomplete[:] = 1.0

    with pytest.raises(ValueError, match=f"{input_name} is missing common sessions"):
        run_portfolio(
            calendar=calendar,
            horizon_budgets={21: 1.0},
            targets_by_rebalance={},
            mid_prices=prices,
            **{input_name: incomplete},
        )
