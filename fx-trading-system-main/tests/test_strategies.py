from __future__ import annotations

import numpy as np
import pandas as pd

from fx_system.config import EnsembleConfig
from fx_system.data import SyntheticFXProvider
from fx_system.ensemble import SignalEnsembler
from fx_system.strategies import (
    CointegrationSpread,
    CurrencyStrengthReversion,
    FalseBreakoutReversal,
    RegimeMeanReversion,
    SessionBreakout,
    TrendPullback,
)


def _ohlc(close: pd.Series) -> pd.DataFrame:
    open_ = close.shift(1).fillna(close.iloc[0])
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) * 1.002,
            "low": np.minimum(open_, close) * 0.998,
            "close": close,
            "volume": 1000.0,
        },
        index=close.index,
    )


def test_every_strategy_default_has_low_reward_risk_and_weekly_cap() -> None:
    strategies = [
        RegimeMeanReversion(),
        TrendPullback(),
        SessionBreakout(),
        FalseBreakoutReversal(),
        CurrencyStrengthReversion(),
        CointegrationSpread(),
    ]
    for strategy in strategies:
        assert strategy.target_atr / strategy.stop_atr <= 0.85
        assert strategy.max_holding_hours <= 168


def test_currency_strength_signals_do_not_change_when_future_is_removed() -> None:
    data = SyntheticFXProvider(seed=11).generate(
        ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"], bars=600, interval="4h"
    )
    strategy = CurrencyStrengthReversion(strength_z=0.6, pair_z=0.6)
    cutoff = data["EURUSD"].index[450]
    prefix = {symbol: frame.loc[:cutoff] for symbol, frame in data.items()}
    full_past = [s.to_dict() for s in strategy.generate(data) if s.timestamp <= cutoff]
    prefix_signals = [s.to_dict() for s in strategy.generate(prefix)]
    assert full_past == prefix_signals


def test_false_breakout_strategy_runs_on_multisymbol_data() -> None:
    data = SyntheticFXProvider(seed=9).generate(["EURUSD", "USDJPY"], bars=250, interval="4h")
    signals = FalseBreakoutReversal(range_bars=12).generate(data)
    assert all(signal.strategy == "false_breakout_reversal" for signal in signals)


def test_cointegration_emits_atomic_two_leg_groups() -> None:
    rng = np.random.default_rng(12)
    index = pd.date_range("2023-01-02", periods=500, freq="4h", tz="UTC")
    common = np.cumsum(rng.normal(0, 0.001, len(index)))
    spread = np.zeros(len(index))
    for i in range(1, len(index)):
        spread[i] = 0.75 * spread[i - 1] + rng.normal(0, 0.0015)
    right = pd.Series(np.exp(np.log(1.25) + common), index=index)
    left = pd.Series(np.exp(np.log(1.08) + common + spread), index=index)
    data = {"EURUSD": _ohlc(left), "GBPUSD": _ohlc(right)}
    strategy = CointegrationSpread(
        pairs=[["EURUSD", "GBPUSD"]], lookback=80, entry_z=1.3, max_pvalue=0.2, retest_bars=10
    )
    signals = strategy.generate(data)
    assert signals
    group_counts = pd.Series([signal.group_id for signal in signals]).value_counts()
    assert set(group_counts) == {2}


def test_ensemble_drops_incomplete_linked_group() -> None:
    data = SyntheticFXProvider(seed=2).generate(["EURUSD", "GBPUSD"], bars=10, interval="4h")
    timestamp = data["EURUSD"].index[-1]
    from fx_system.models import Side, Signal

    linked = [
        Signal(timestamp, "EURUSD", Side.LONG, 0.8, "linked", 0.01, 1, 0.5, 24, group_id="g"),
        Signal(timestamp, "GBPUSD", Side.SHORT, 0.8, "linked", 0.01, 1, 0.5, 24, group_id="g"),
        Signal(timestamp, "GBPUSD", Side.LONG, 1.0, "other", 0.01, 1, 0.5, 24),
    ]
    ensemble = SignalEnsembler(
        EnsembleConfig(minimum_vote=0.1, minimum_confidence=0.1), {"linked": 1, "other": 2}
    )
    combined = ensemble.combine(linked)
    assert not any(signal.group_id == "g" for signal in combined)
