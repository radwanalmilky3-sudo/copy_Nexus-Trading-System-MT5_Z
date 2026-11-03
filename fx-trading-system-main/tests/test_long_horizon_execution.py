from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from fx_system.long_horizon_execution import run_long_horizon_execution


def _base_case(
    observations: int = 3,
    *,
    symbols: tuple[str, ...] = ("EURUSD",),
) -> dict[str, object]:
    sessions = pd.date_range("2025-01-06", periods=observations, freq="D", tz="UTC")
    rollover = sessions + pd.to_timedelta(22, unit="h")
    timestamps = pd.DataFrame(
        {
            "rollover_timestamp": rollover,
            "open_timestamp": rollover + pd.to_timedelta(1, unit="s"),
            "close_timestamp": rollover + pd.to_timedelta(86_399, unit="s"),
        },
        index=sessions,
    )
    open_mid = pd.DataFrame(1.0, index=sessions, columns=list(symbols))
    close_mid = pd.DataFrame(1.0, index=sessions, columns=list(symbols))
    half_spread = pd.DataFrame(0.001, index=sessions, columns=list(symbols))
    zeros = pd.DataFrame(0.0, index=sessions, columns=list(symbols))
    ones = pd.DataFrame(1.0, index=sessions, columns=list(symbols))
    targets = pd.DataFrame(0.0, index=sessions, columns=list(symbols))
    symbol_index = pd.Index(symbols)
    return {
        "session_timestamps": timestamps,
        "open_target_quantities": {"synthetic_sleeve": targets.copy()},
        "close_target_quantities": {"synthetic_sleeve": targets.copy()},
        "open_bid_prices": open_mid - half_spread,
        "open_ask_prices": open_mid + half_spread,
        "close_bid_prices": close_mid - half_spread,
        "close_ask_prices": close_mid + half_spread,
        "open_account_value_multipliers": ones.copy(),
        "close_account_value_multipliers": ones.copy(),
        "long_financing_per_unit": zeros.copy(),
        "short_financing_per_unit": zeros.copy(),
        "open_adverse_slippage_per_unit": zeros.copy(),
        "close_adverse_slippage_per_unit": zeros.copy(),
        "cash_interest": pd.Series(0.0, index=sessions, name="cash_interest"),
        "initial_nav": 1_000.0,
        "initial_positions": pd.Series(0.0, index=symbol_index, name="initial_position"),
        "initial_close_timestamp": rollover[0] - pd.to_timedelta(1, unit="s"),
        "initial_close_bid_prices": pd.Series(
            0.999, index=symbol_index, name="initial_close_bid"
        ),
        "initial_close_ask_prices": pd.Series(
            1.001, index=symbol_index, name="initial_close_ask"
        ),
    }


def _target_panel(kwargs: dict[str, object], phase: str) -> pd.DataFrame:
    mapping = kwargs[f"{phase}_target_quantities"]
    assert isinstance(mapping, dict)
    panel = mapping["synthetic_sleeve"]
    assert isinstance(panel, pd.DataFrame)
    return panel


def _set_mid(
    kwargs: dict[str, object],
    phase: str,
    values: list[float] | np.ndarray,
    *,
    symbol: str,
    half_spread: float = 0.001,
) -> None:
    bid = kwargs[f"{phase}_bid_prices"]
    ask = kwargs[f"{phase}_ask_prices"]
    assert isinstance(bid, pd.DataFrame)
    assert isinstance(ask, pd.DataFrame)
    bid[symbol] = np.asarray(values) - half_spread
    ask[symbol] = np.asarray(values) + half_spread


def test_long_and_short_round_trips_use_executable_sides_and_one_spread_per_trade() -> None:
    kwargs = _base_case(1, symbols=("EURUSD", "GBPUSD"))
    open_targets = _target_panel(kwargs, "open")
    close_targets = _target_panel(kwargs, "close")
    open_targets.loc[:, "EURUSD"] = 10.0
    open_targets.loc[:, "GBPUSD"] = -5.0
    close_targets.loc[:, :] = 0.0
    kwargs["open_adverse_slippage_per_unit"].loc[:, :] = 0.0002  # type: ignore[union-attr]
    kwargs["close_adverse_slippage_per_unit"].loc[:, :] = 0.0003  # type: ignore[union-attr]

    result = run_long_horizon_execution(**kwargs)  # type: ignore[arg-type]

    trades = {(trade.phase, trade.symbol): trade for trade in result.trades}
    assert trades["open", "EURUSD"].side == "buy"
    assert trades["open", "EURUSD"].quoted_execution_price == pytest.approx(1.001)
    assert trades["open", "EURUSD"].effective_execution_price == pytest.approx(1.0012)
    assert trades["close", "EURUSD"].side == "sell"
    assert trades["close", "EURUSD"].quoted_execution_price == pytest.approx(0.999)
    assert trades["close", "EURUSD"].effective_execution_price == pytest.approx(0.9987)
    assert trades["open", "GBPUSD"].side == "sell"
    assert trades["close", "GBPUSD"].side == "buy"

    entry = result.entries[0]
    expected_spread = (10.0 + 5.0) * 0.001 * 2.0
    expected_slippage = (10.0 + 5.0) * (0.0002 + 0.0003)
    assert entry.open_spread_cost + entry.close_spread_cost == pytest.approx(
        expected_spread
    )
    assert entry.open_slippage_cost + entry.close_slippage_cost == pytest.approx(
        expected_slippage
    )
    assert entry.net_pnl == pytest.approx(-expected_spread - expected_slippage)


def test_event_order_books_overnight_financing_then_open_and_intraday_close_pnl() -> None:
    kwargs = _base_case(2)
    open_targets = _target_panel(kwargs, "open")
    close_targets = _target_panel(kwargs, "close")
    open_targets.loc[:, "EURUSD"] = 10.0
    close_targets.loc[:, "EURUSD"] = [10.0, 0.0]
    _set_mid(kwargs, "open", [1.00, 1.20], symbol="EURUSD")
    _set_mid(kwargs, "close", [1.10, 1.30], symbol="EURUSD")
    kwargs["long_financing_per_unit"].loc[:, "EURUSD"] = -0.01  # type: ignore[union-attr]
    kwargs["short_financing_per_unit"].loc[:, "EURUSD"] = -0.02  # type: ignore[union-attr]
    kwargs["cash_interest"].iloc[:] = [0.25, 0.50]  # type: ignore[union-attr]

    result = run_long_horizon_execution(**kwargs)  # type: ignore[arg-type]
    first, second = result.entries

    assert first.overnight_price_pnl == 0.0
    assert first.financing == 0.0
    assert first.cash_interest == pytest.approx(0.25)
    assert first.intraday_price_pnl == pytest.approx(10.0 * (1.10 - 1.00))
    assert second.overnight_price_pnl == pytest.approx(10.0 * (1.20 - 1.10))
    assert second.financing == pytest.approx(10.0 * -0.01)
    assert second.cash_interest == pytest.approx(0.50)
    assert second.intraday_price_pnl == pytest.approx(10.0 * (1.30 - 1.20))
    assert [trade.phase for trade in result.trades] == ["open", "close"]
    assert result.trades[0].session == first.session
    assert result.trades[1].session == second.session


def test_h_session_holding_applies_financing_on_h_minus_one_old_position_rollovers() -> None:
    holding_sessions = 4
    kwargs = _base_case(holding_sessions)
    _target_panel(kwargs, "open").loc[:, "EURUSD"] = 3.0
    _target_panel(kwargs, "close").loc[:, "EURUSD"] = [3.0, 3.0, 3.0, 0.0]
    kwargs["long_financing_per_unit"].loc[:, "EURUSD"] = -0.10  # type: ignore[union-attr]

    result = run_long_horizon_execution(**kwargs)  # type: ignore[arg-type]

    financing = [entry.financing for entry in result.entries]
    assert financing == pytest.approx([0.0, -0.30, -0.30, -0.30])
    assert sum(value != 0.0 for value in financing) == holding_sessions - 1
    assert result.entries[-1].close_target_positions["EURUSD"] == 0.0


def test_short_old_position_uses_short_account_currency_financing_rate() -> None:
    kwargs = _base_case(2)
    _target_panel(kwargs, "open").loc[:, "EURUSD"] = -4.0
    _target_panel(kwargs, "close").loc[:, "EURUSD"] = [-4.0, 0.0]
    kwargs["long_financing_per_unit"].loc[:, "EURUSD"] = 99.0  # type: ignore[union-attr]
    kwargs["short_financing_per_unit"].loc[:, "EURUSD"] = -0.07  # type: ignore[union-attr]

    result = run_long_horizon_execution(**kwargs)  # type: ignore[arg-type]

    assert result.entries[0].financing == 0.0
    assert result.entries[1].financing == pytest.approx(4.0 * -0.07)


def test_real_new_york_rollovers_preserve_22_to_21_utc_dst_transition() -> None:
    kwargs = _base_case(2)
    sessions = kwargs["session_timestamps"].index  # type: ignore[union-attr]
    timestamps = pd.DataFrame(
        {
            "rollover_timestamp": [
                pd.Timestamp("2025-03-07 22:00:00", tz="UTC"),
                pd.Timestamp("2025-03-10 21:00:00", tz="UTC"),
            ],
            "open_timestamp": [
                pd.Timestamp("2025-03-07 22:00:01", tz="UTC"),
                pd.Timestamp("2025-03-10 21:00:01", tz="UTC"),
            ],
            "close_timestamp": [
                pd.Timestamp("2025-03-10 20:59:59", tz="UTC"),
                pd.Timestamp("2025-03-11 20:59:59", tz="UTC"),
            ],
        },
        index=sessions,
    )
    kwargs["session_timestamps"] = timestamps
    kwargs["initial_close_timestamp"] = pd.Timestamp(
        "2025-03-07 21:59:59", tz="UTC"
    )

    result = run_long_horizon_execution(**kwargs)  # type: ignore[arg-type]

    assert result.entries[0].rollover_timestamp.hour == 22
    assert result.entries[1].rollover_timestamp.hour == 21
    assert result.entries[1].previous_close_timestamp == result.entries[0].close_timestamp
    assert all(entry.rollover_timestamp.hour != 0 for entry in result.entries)


def test_component_targets_are_netted_before_any_broker_cost() -> None:
    kwargs = _base_case(1)
    sessions = kwargs["session_timestamps"].index  # type: ignore[union-attr]
    long_component = pd.DataFrame(10.0, index=sessions, columns=["EURUSD"])
    short_component = pd.DataFrame(-10.0, index=sessions, columns=["EURUSD"])
    zeros = pd.DataFrame(0.0, index=sessions, columns=["EURUSD"])
    kwargs["open_target_quantities"] = {
        "long_sleeve": long_component,
        "short_sleeve": short_component,
    }
    kwargs["close_target_quantities"] = {
        "long_sleeve": zeros.copy(),
        "short_sleeve": zeros.copy(),
    }
    kwargs["open_adverse_slippage_per_unit"].loc[:, :] = 50.0  # type: ignore[union-attr]
    kwargs["close_adverse_slippage_per_unit"].loc[:, :] = 50.0  # type: ignore[union-attr]

    result = run_long_horizon_execution(**kwargs)  # type: ignore[arg-type]

    assert result.trades == ()
    entry = result.entries[0]
    assert entry.open_target_positions["EURUSD"] == 0.0
    assert entry.open_broker_turnover == 0.0
    assert entry.open_spread_cost == 0.0
    assert entry.open_slippage_cost == 0.0
    targets = result.target_quantities_frame()
    assert set(targets["component"]) == {"long_sleeve", "short_sleeve"}


def test_explicit_boundary_settlement_multipliers_apply_to_non_usd_quote_pnl() -> None:
    kwargs = _base_case(1, symbols=("USDJPY",))
    _target_panel(kwargs, "open").loc[:, "USDJPY"] = 1.0
    _target_panel(kwargs, "close").loc[:, "USDJPY"] = 0.0
    kwargs["initial_positions"].loc["USDJPY"] = 1.0  # type: ignore[union-attr]
    kwargs["initial_close_bid_prices"].loc["USDJPY"] = 148.9  # type: ignore[union-attr]
    kwargs["initial_close_ask_prices"].loc["USDJPY"] = 149.1  # type: ignore[union-attr]
    _set_mid(kwargs, "open", [150.0], symbol="USDJPY", half_spread=0.1)
    _set_mid(kwargs, "close", [151.0], symbol="USDJPY", half_spread=0.1)
    kwargs["open_account_value_multipliers"].loc[:, "USDJPY"] = 0.02  # type: ignore[union-attr]
    kwargs["close_account_value_multipliers"].loc[:, "USDJPY"] = 0.01  # type: ignore[union-attr]
    kwargs["close_adverse_slippage_per_unit"].loc[:, "USDJPY"] = 0.05  # type: ignore[union-attr]

    result = run_long_horizon_execution(**kwargs)  # type: ignore[arg-type]
    entry = result.entries[0]

    assert entry.overnight_price_pnl == pytest.approx((150.0 - 149.0) * 0.02)
    assert entry.intraday_price_pnl == pytest.approx((151.0 - 150.0) * 0.01)
    assert entry.open_broker_turnover == 0.0
    assert entry.close_spread_cost == pytest.approx(0.1 * 0.01)
    assert entry.close_slippage_cost == pytest.approx(0.05 * 0.01)
    assert result.account_pnl_settlement_assumption == (
        "account_currency_cash_settlement_or_mark_reset_at_each_boundary"
    )
    assert (
        "multi_currency_unrealized_pnl_cost_basis_and_broker_settlement"
        in result.external_dependencies_remaining
    )
    assert "broker_commission_and_other_fees" in result.external_dependencies_remaining
    assert "per_symbol_quote_timestamp_and_staleness" in (
        result.external_dependencies_remaining
    )
    assert result.formal_net_returns_ready is False


def test_nav_and_every_segment_reconcile_without_double_deducting_spread() -> None:
    kwargs = _base_case(3)
    _target_panel(kwargs, "open").loc[:, "EURUSD"] = [2.0, 2.0, 2.0]
    _target_panel(kwargs, "close").loc[:, "EURUSD"] = [2.0, 2.0, 0.0]
    _set_mid(kwargs, "open", [1.00, 1.03, 1.06], symbol="EURUSD")
    _set_mid(kwargs, "close", [1.02, 1.05, 1.08], symbol="EURUSD")
    kwargs["long_financing_per_unit"].loc[:, "EURUSD"] = -0.001  # type: ignore[union-attr]
    kwargs["cash_interest"].iloc[:] = [0.01, 0.02, 0.03]  # type: ignore[union-attr]

    result = run_long_horizon_execution(**kwargs)  # type: ignore[arg-type]
    frame = result.ledger_frame()

    expected_change = math.fsum(frame["net_pnl"])
    assert result.final_nav - result.initial_nav == pytest.approx(expected_change)
    assert math.prod(1.0 + frame["simple_return"]) == pytest.approx(
        result.final_nav / result.initial_nav
    )
    assert frame["accounting_reconciled"].all()
    # One opening buy and one final sell: exactly two half-spreads, not an
    # executable-price cost plus another duplicate spread deduction.
    assert frame["open_spread_cost"].sum() == pytest.approx(2.0 * 0.001)
    assert frame["close_spread_cost"].sum() == pytest.approx(2.0 * 0.001)


def test_session_ledger_rejects_post_construction_accounting_tampering() -> None:
    kwargs = _base_case(1)
    _target_panel(kwargs, "open").loc[:, "EURUSD"] = 1.0
    _target_panel(kwargs, "close").loc[:, "EURUSD"] = 0.0
    result = run_long_horizon_execution(**kwargs)  # type: ignore[arg-type]
    entry = result.entries[0]

    with pytest.raises(ValueError, match="net PnL reconciliation"):
        replace(entry, net_pnl=entry.net_pnl + 1.0)
    with pytest.raises(ValueError, match="quantities do not reconcile"):
        replace(result.trades[0], target_quantity=2.0)
    with pytest.raises(ValueError, match="blockers cannot be removed"):
        replace(result, external_dependencies_remaining=())


def test_all_mandatory_inputs_have_no_implicit_default() -> None:
    kwargs = _base_case(1)
    del kwargs["cash_interest"]

    with pytest.raises(TypeError, match="cash_interest"):
        run_long_horizon_execution(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_slippage", "contains missing or infinite"),
        ("shifted_multiplier", "exactly the common session index"),
        ("missing_target_symbol", "exactly the common symbol columns"),
        ("crossed_open_quote", "open quotes cannot be crossed"),
        ("crossed_close_quote", "close quotes cannot be crossed"),
        ("crossed_initial_quote", "initial close quotes cannot be crossed"),
        ("midnight_rollover", "17:00 America/New_York"),
        ("wrong_dst_rollover", "17:00 America/New_York"),
        ("bad_event_order", "rollover <= open < close"),
        ("overlapping_sessions", "previous close must strictly precede rollover"),
        ("wrong_target_components", "component names must match"),
        ("nonfinite_component_net", "netting produced a non-finite quantity"),
    ],
)
def test_execution_fails_closed_on_missing_misaligned_or_invalid_inputs(
    mutation: str,
    message: str,
) -> None:
    kwargs = _base_case(2, symbols=("EURUSD", "GBPUSD"))
    if mutation == "missing_slippage":
        kwargs["open_adverse_slippage_per_unit"].iloc[0, 0] = np.nan  # type: ignore[union-attr]
    elif mutation == "shifted_multiplier":
        multiplier = kwargs["close_account_value_multipliers"]
        assert isinstance(multiplier, pd.DataFrame)
        multiplier.index = multiplier.index.shift(1, freq="D")
    elif mutation == "missing_target_symbol":
        mapping = kwargs["open_target_quantities"]
        assert isinstance(mapping, dict)
        mapping["synthetic_sleeve"] = mapping["synthetic_sleeve"].drop(  # type: ignore[union-attr]
            columns="GBPUSD"
        )
    elif mutation == "crossed_open_quote":
        kwargs["open_bid_prices"].iloc[0, 0] = 2.0  # type: ignore[union-attr]
    elif mutation == "crossed_close_quote":
        kwargs["close_bid_prices"].iloc[0, 0] = 2.0  # type: ignore[union-attr]
    elif mutation == "crossed_initial_quote":
        kwargs["initial_close_bid_prices"].loc["EURUSD"] = 2.0  # type: ignore[union-attr]
    elif mutation == "midnight_rollover":
        timestamps = kwargs["session_timestamps"]
        assert isinstance(timestamps, pd.DataFrame)
        timestamps.iloc[0, timestamps.columns.get_loc("rollover_timestamp")] = pd.Timestamp(
            "2025-01-06 00:00:00", tz="UTC"
        )
    elif mutation == "wrong_dst_rollover":
        timestamps = kwargs["session_timestamps"]
        assert isinstance(timestamps, pd.DataFrame)
        timestamps.iloc[0, timestamps.columns.get_loc("rollover_timestamp")] = pd.Timestamp(
            "2025-07-01 22:00:00", tz="UTC"
        )
    elif mutation == "bad_event_order":
        timestamps = kwargs["session_timestamps"]
        assert isinstance(timestamps, pd.DataFrame)
        timestamps.iloc[0, timestamps.columns.get_loc("open_timestamp")] = timestamps.iloc[
            0
        ]["close_timestamp"]
    elif mutation == "overlapping_sessions":
        timestamps = kwargs["session_timestamps"]
        assert isinstance(timestamps, pd.DataFrame)
        timestamps.iloc[0, timestamps.columns.get_loc("close_timestamp")] = (
            timestamps.iloc[1]["rollover_timestamp"] + pd.to_timedelta(1, unit="s")
        )
    elif mutation == "wrong_target_components":
        mapping = kwargs["close_target_quantities"]
        assert isinstance(mapping, dict)
        mapping["other_name"] = mapping.pop("synthetic_sleeve")
    elif mutation == "nonfinite_component_net":
        mapping = kwargs["open_target_quantities"]
        assert isinstance(mapping, dict)
        base = mapping["synthetic_sleeve"]
        assert isinstance(base, pd.DataFrame)
        mapping["synthetic_sleeve"] = pd.DataFrame(
            1e308, index=base.index, columns=base.columns
        )
        mapping["second_finite_component"] = pd.DataFrame(
            1e308, index=base.index, columns=base.columns
        )
        close_mapping = kwargs["close_target_quantities"]
        assert isinstance(close_mapping, dict)
        close_mapping["second_finite_component"] = close_mapping[
            "synthetic_sleeve"
        ].copy()

    with pytest.raises(ValueError, match=message):
        run_long_horizon_execution(**kwargs)  # type: ignore[arg-type]
