from __future__ import annotations

import math

import pandas as pd
import pytest

from fx_system.portfolio import CommonSessionCalendar, OverlappingSleevePortfolio


def _calendar(periods: int = 160) -> CommonSessionCalendar:
    return CommonSessionCalendar(pd.bdate_range("2020-01-01", periods=periods, tz="UTC"))


def test_common_calendar_uses_intersection_and_expiry_counts_common_sessions() -> None:
    eur_sessions = pd.DatetimeIndex(
        [
            "2025-01-06 21:00:00+00:00",
            "2025-01-07 21:00:00+00:00",
            "2025-01-08 21:00:00+00:00",
            "2025-01-09 21:00:00+00:00",
        ]
    )
    gbp_sessions = pd.DatetimeIndex(
        [
            "2025-01-06 22:00:00+00:00",
            "2025-01-08 22:00:00+00:00",
            "2025-01-09 22:00:00+00:00",
        ]
    )

    calendar = CommonSessionCalendar.from_market_data(
        {
            "GBPUSD": pd.DataFrame(index=gbp_sessions),
            "EURUSD": pd.DataFrame(index=eur_sessions),
        }
    )

    assert calendar.symbols == ("EURUSD", "GBPUSD")
    assert list(calendar.sessions) == [
        pd.Timestamp("2025-01-06", tz="UTC"),
        pd.Timestamp("2025-01-08", tz="UTC"),
        pd.Timestamp("2025-01-09", tz="UTC"),
    ]
    assert calendar.advance("2025-01-06", 1) == pd.Timestamp("2025-01-08", tz="UTC")


def test_21_42_63_day_sleeves_conserve_budget_without_warmup_amplification() -> None:
    calendar = _calendar()
    portfolio = OverlappingSleevePortfolio(
        calendar,
        {21: 0.30, 42: 0.30, 63: 0.40},
        rebalance_interval_sessions=21,
    )
    rebalance_sessions = calendar.rebalance_sessions(21)

    assert [portfolio.slot_count(horizon) for horizon in (21, 42, 63)] == [1, 2, 3]
    assert portfolio.slot_budget(21) == pytest.approx(0.30)
    assert portfolio.slot_budget(42) == pytest.approx(0.15)
    assert portfolio.slot_budget(63) == pytest.approx(0.40 / 3)

    first = portfolio.rebalance(
        rebalance_sessions[0],
        {horizon: {"EURUSD": 1.0} for horizon in (21, 42, 63)},
    )
    second = portfolio.rebalance(
        rebalance_sessions[1],
        {horizon: {"EURUSD": 1.0} for horizon in (21, 42, 63)},
    )
    third = portfolio.rebalance(
        rebalance_sessions[2],
        {horizon: {"EURUSD": 1.0} for horizon in (21, 42, 63)},
    )
    fourth = portfolio.rebalance(
        rebalance_sessions[3],
        {horizon: {"EURUSD": 1.0} for horizon in (21, 42, 63)},
    )

    assert first.committed_sleeve_gross == pytest.approx(0.30 + 0.15 + 0.40 / 3)
    assert second.committed_sleeve_gross == pytest.approx(0.30 + 0.30 + 2 * 0.40 / 3)
    assert third.committed_sleeve_gross == pytest.approx(1.0)
    assert fourth.committed_sleeve_gross == pytest.approx(1.0)
    assert [
        sum(sleeve.horizon_sessions == horizon for sleeve in fourth.active_sleeves)
        for horizon in (21, 42, 63)
    ] == [1, 2, 3]
    assert all(
        transition.committed_sleeve_gross <= 1.0 + 1e-12
        for transition in (first, second, third, fourth)
    )


def test_opposing_sleeves_are_netted_before_turnover_and_costing() -> None:
    calendar = _calendar()
    portfolio = OverlappingSleevePortfolio(calendar, {21: 0.25, 42: 0.50})

    transition = portfolio.rebalance(
        calendar.sessions[0],
        {
            21: {"EURUSD": 1.0},
            42: {"EURUSD": -1.0},
        },
    )

    # Each sleeve commits 0.25, but the master account never trades. Applying
    # spread/cost to the sleeves separately would incorrectly create a cost.
    assert transition.committed_sleeve_gross == pytest.approx(0.50)
    assert dict(transition.target) == {}
    assert dict(transition.net_trade) == {}
    assert transition.one_way_turnover == 0.0


def test_full_position_reversal_has_twice_the_position_turnover() -> None:
    calendar = _calendar()
    portfolio = OverlappingSleevePortfolio(calendar, {21: 1.0})
    sessions = calendar.rebalance_sessions(21)

    opened = portfolio.rebalance(sessions[0], {21: {"EURUSD": 1.0}})
    reversed_position = portfolio.rebalance(sessions[1], {21: {"EURUSD": -1.0}})

    assert opened.one_way_turnover == pytest.approx(1.0)
    assert reversed_position.previous_target["EURUSD"] == pytest.approx(1.0)
    assert reversed_position.target["EURUSD"] == pytest.approx(-1.0)
    assert reversed_position.net_trade["EURUSD"] == pytest.approx(-2.0)
    assert reversed_position.one_way_turnover == pytest.approx(2.0)
    assert len(reversed_position.expired_sleeves) == 1
    assert len(reversed_position.active_sleeves) == 1


def test_invalid_horizon_modulo_rebalance_and_overbudget_targets_are_rejected() -> None:
    calendar = _calendar()

    with pytest.raises(ValueError, match="H % R"):
        OverlappingSleevePortfolio(calendar, {22: 1.0}, rebalance_interval_sessions=21)
    with pytest.raises(ValueError, match="capital_limit"):
        OverlappingSleevePortfolio(calendar, {21: 0.6, 42: 0.5})

    portfolio = OverlappingSleevePortfolio(calendar, {21: 1.0})
    with pytest.raises(ValueError, match="gross weight"):
        portfolio.rebalance(
            calendar.sessions[0],
            {21: {"EURUSD": 0.75, "GBPUSD": -0.75}},
        )

    # Failed validation is atomic: the first valid session remains processable.
    transition = portfolio.rebalance(calendar.sessions[0], {21: {"EURUSD": 1.0}})
    assert math.isclose(transition.one_way_turnover, 1.0)


def test_rebalance_requires_common_eligible_session_and_complete_expiry() -> None:
    calendar = _calendar(periods=64)
    portfolio = OverlappingSleevePortfolio(calendar, {21: 1.0})

    with pytest.raises(ValueError, match="eligible rebalance"):
        portfolio.rebalance(calendar.sessions[1], {21: {"EURUSD": 1.0}})

    portfolio.rebalance(calendar.sessions[42], {21: {"EURUSD": 1.0}})
    with pytest.raises(ValueError, match="insufficient common sessions"):
        portfolio.rebalance(calendar.sessions[63], {21: {"EURUSD": 1.0}})
