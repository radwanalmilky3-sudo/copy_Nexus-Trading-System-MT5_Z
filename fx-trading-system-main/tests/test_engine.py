from __future__ import annotations

import pytest
from conftest import make_bars

from fx_system.config import CostConfig, RiskConfig
from fx_system.engine import BacktestEngine
from fx_system.models import Side, Signal


def signal_at(frame, **overrides) -> Signal:
    values = {
        "timestamp": frame.index[0],
        "symbol": "EURUSD",
        "side": Side.LONG,
        "confidence": 0.8,
        "strategy": "test",
        "atr": 0.01,
        "stop_atr": 1.0,
        "target_atr": 0.5,
        "max_holding_hours": 24,
    }
    values.update(overrides)
    return Signal(**values)


def test_signal_executes_next_bar_and_same_bar_ambiguity_uses_stop(
    permissive_risk, zero_costs
) -> None:
    bars = make_bars([(1, 1.002, 0.998, 1), (1, 1.02, 0.98, 1.005), (1.005, 1.01, 1, 1.005)])
    result = BacktestEngine(permissive_risk, zero_costs).run({"EURUSD": bars}, [signal_at(bars)])
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_time == bars.index[1]
    assert trade.exit_time == bars.index[1]
    assert trade.exit_reason == "STOP"
    assert trade.net_pnl < 0


def test_time_exit_respects_maximum_holding(permissive_risk, zero_costs) -> None:
    bars = make_bars([(1, 1.001, 0.999, 1)] * 4)
    result = BacktestEngine(permissive_risk, zero_costs).run(
        {"EURUSD": bars}, [signal_at(bars, max_holding_hours=4, atr=0.1)]
    )
    trade = result.trades[0]
    assert trade.exit_reason == "MAX_HOLD"
    assert trade.holding_hours == 4


def test_jpy_quote_pnl_is_converted_to_account_currency(permissive_risk, zero_costs) -> None:
    bars = make_bars(
        [(150.0, 150.1, 149.9, 150.0), (150.0, 150.6, 149.95, 150.5), (150.5, 150.6, 150.4, 150.5)]
    )
    signal = signal_at(
        bars,
        symbol="USDJPY",
        atr=1.0,
        stop_atr=1.0,
        target_atr=0.5,
    )
    result = BacktestEngine(permissive_risk, zero_costs).run({"USDJPY": bars}, [signal])
    trade = result.trades[0]
    assert trade.exit_reason == "TARGET"
    expected = trade.units * 0.5 / 150.5
    assert trade.net_pnl == pytest.approx(expected)


def test_shared_usd_exposure_rejects_second_correlated_currency_trade(zero_costs) -> None:
    eur = make_bars([(1.10, 1.101, 1.099, 1.10)] * 4)
    gbp = make_bars([(1.30, 1.301, 1.299, 1.30)] * 4)
    risk = RiskConfig(
        max_currency_exposure=0.5,
        max_gross_leverage=5,
        max_open_positions=5,
        max_correlated_positions=5,
        close_before_weekend=False,
    )
    signals = [
        signal_at(eur, symbol="EURUSD", atr=0.01, confidence=0.9),
        signal_at(gbp, symbol="GBPUSD", atr=0.01, confidence=0.8),
    ]
    result = BacktestEngine(risk, zero_costs).run({"EURUSD": eur, "GBPUSD": gbp}, signals)
    reasons = {item["reason"] for item in result.rejected_signals}
    assert "max_currency_exposure" in reasons


def test_cost_model_reduces_net_pnl(permissive_risk) -> None:
    bars = make_bars([(1, 1.001, 0.999, 1), (1, 1.006, 0.999, 1.005), (1.005, 1.006, 1.004, 1.005)])
    costs = CostConfig(default_spread_pips=1, slippage_pips=0.2, commission_per_million=35)
    result = BacktestEngine(permissive_risk, costs).run({"EURUSD": bars}, [signal_at(bars)])
    trade = result.trades[0]
    assert trade.costs > 0
    assert trade.net_pnl < trade.gross_pnl
