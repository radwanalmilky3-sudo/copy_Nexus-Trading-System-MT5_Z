"""Synthetic two-stage ledger bridge tests."""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from fx_system.broker_cost_contract import audit_cost_coverage
from fx_system.long_horizon_portfolio_bridge import (
    build_execution_targets_from_frozen_schedule,
    net_component_quantity_panels,
    run_synthetic_two_stage_ledger,
)


def _base_case(observations: int = 3) -> dict[str, object]:
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
    symbols = ("EURUSD",)
    open_mid = pd.DataFrame(1.0, index=sessions, columns=list(symbols))
    half = pd.DataFrame(0.001, index=sessions, columns=list(symbols))
    zeros = pd.DataFrame(0.0, index=sessions, columns=list(symbols))
    ones = pd.DataFrame(1.0, index=sessions, columns=list(symbols))
    targets = pd.DataFrame(0.0, index=sessions, columns=list(symbols))
    targets.iloc[0, 0] = 10.0
    symbol_index = pd.Index(symbols)
    return {
        "session_timestamps": timestamps,
        "open_target_quantities": {"synthetic_sleeve": targets.copy()},
        "close_target_quantities": {"synthetic_sleeve": targets.copy()},
        "open_bid_prices": open_mid - half,
        "open_ask_prices": open_mid + half,
        "close_bid_prices": open_mid - half,
        "close_ask_prices": open_mid + half,
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
        "initial_close_bid_prices": pd.Series(0.999, index=symbol_index),
        "initial_close_ask_prices": pd.Series(1.001, index=symbol_index),
    }


def test_bridge_reconciles_nav_and_stays_cost_incomplete() -> None:
    report = audit_cost_coverage(
        swap_frame=None,
        forward_frame=None,
        required_symbols=("EURUSD",),
        broker_entity=None,
    )
    result = run_synthetic_two_stage_ledger(_base_case(), cost_report=report)
    assert result.nav_identity_ok is True
    assert result.formal_net_returns_ready is False
    assert result.trading_approval is False
    assert result.cost_verdict == "cost_incomplete_research_only"
    assert result.execution.formal_net_returns_ready is False


def test_component_panels_net_before_execution() -> None:
    sessions = pd.date_range("2025-01-06", periods=2, freq="D", tz="UTC")
    long_panel = pd.DataFrame({"EURUSD": [10.0, 0.0]}, index=sessions)
    short_panel = pd.DataFrame({"EURUSD": [-4.0, 0.0]}, index=sessions)
    net = net_component_quantity_panels({"long": long_panel, "short": short_panel})
    assert net.loc[sessions[0], "EURUSD"] == 6.0
    assert np.isclose(net.loc[sessions[1], "EURUSD"], 0.0)


def test_frozen_schedule_adapter_builds_open_and_close_account_quantity_targets() -> None:
    sessions = pd.date_range("2025-01-06", periods=4, freq="D", tz="UTC")
    schedule = pd.DataFrame(
        {
            "candidate": ["momentum__21d", "momentum__21d"],
            "symbol": ["EURUSD", "EURUSD"],
            "status": ["ready_next_open", "ready_next_open"],
            "proposed_tranche_weight": [0.5, -0.25],
            "entry_session": [sessions[0], sessions[1]],
            "scheduled_exit_session": [sessions[2], sessions[3]],
        }
    )
    opens, closes, audit = build_execution_targets_from_frozen_schedule(
        schedule,
        sessions=sessions,
        symbols=("EURUSD",),
        account_quantity_per_weight={"EURUSD": 100.0},
    )
    assert opens["momentum__21d"].loc[sessions[0], "EURUSD"] == 50.0
    assert opens["momentum__21d"].loc[sessions[1], "EURUSD"] == 25.0
    assert closes["momentum__21d"].loc[sessions[2], "EURUSD"] == -25.0
    assert closes["momentum__21d"].loc[sessions[3], "EURUSD"] == 0.0
    assert len(audit) == 2


def test_schedule_adapter_rejects_non_shared_component_index() -> None:
    sessions = pd.date_range("2025-01-06", periods=2, freq="D", tz="UTC")
    schedule = pd.DataFrame(
        {
            "candidate": ["a"],
            "symbol": ["EURUSD"],
            "status": ["ready_next_open"],
            "proposed_tranche_weight": [1.0],
            "entry_session": [sessions[0]],
            "scheduled_exit_session": [sessions[1]],
        }
    )
    with pytest.raises(ValueError, match="boundary is outside"):
        build_execution_targets_from_frozen_schedule(
            schedule,
            sessions=sessions + timedelta(days=5),
            symbols=("EURUSD",),
            account_quantity_per_weight={"EURUSD": 100.0},
        )
