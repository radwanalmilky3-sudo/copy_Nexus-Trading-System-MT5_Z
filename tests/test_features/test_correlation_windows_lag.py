"""Task 8 — windowed correlation honesty + lag-signal semantics.

Contract under test (docs/superpowers/plans/2026-10-21-nexus-audit-remediation.md
### المهمة 8):
- Correlation is computed from SYNCHRONIZED RETURNS, never price levels.
- Windows 20/60/120 carry sample_count / coverage / constant_series /
  insufficient_data; missing math is None + flag, never a fabricated 0.
- A synthetic series that leads gold by exactly 3 candles yields an agreed
  lag direction; as_of must not read the future.
All fixtures are synthetic; no production prices and no network.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from services.nexus_features.correlation import (
    compute_lag_signals,
    compute_windowed_correlation,
)


def _prices(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.astype(np.float64)


def _walk(n: int, seed: int, start: float = 100.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, 0.01, size=n)
    return start * np.cumprod(1.0 + rets)


def _frame(**series: np.ndarray) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=len(next(iter(series.values()))), freq="D")
    return pd.DataFrame({k: v for k, v in series.items()}, index=idx)


# ── Windows ──────────────────────────────────────────────────────────────────


def test_windows_default_keys_are_20_60_120():
    prices = _frame(A=_walk(130, 1), B=_walk(130, 2))
    result = compute_windowed_correlation(prices)
    assert set(result.keys()) == {"20", "60", "120"}


def test_window_corr_is_from_returns_not_price_levels():
    """b = -x has a perfect -1 price-LEVEL correlation but, because
    pct_change cancels the sign, a +1 RETURN correlation. The stored value
    must be the returns-based one."""
    x = _walk(120, 7)
    prices = _frame(XAUUSD=x, BTCUSD=-x)

    rets = prices.pct_change().replace([np.inf, -np.inf], np.nan).dropna(how="any")
    expected = round(float(rets["XAUUSD"].corr(rets["BTCUSD"])), 3)
    levels = round(float(prices["XAUUSD"].corr(prices["BTCUSD"])), 3)
    assert levels == pytest.approx(-1.0, abs=1e-9)  # levels would mislead
    assert expected == pytest.approx(1.0, abs=1e-9)  # returns are the honest basis

    result = compute_windowed_correlation(prices)
    stored = result["120"]["pairs"]["XAUUSD/BTCUSD"]
    assert stored["corr"] == expected
    assert stored["corr"] != levels


def test_insufficient_data_is_flagged_not_zero():
    prices = _frame(A=_walk(8, 3), B=_walk(8, 4))
    result = compute_windowed_correlation(prices)
    entry = result["20"]["pairs"]["A/B"]
    assert entry["insufficient_data"] is True
    assert entry["corr"] is None
    assert entry["sample_count"] == 7  # 8 prices → 7 synchronized returns
    assert 0.0 < entry["coverage"] < 1.0
    assert result["20"]["matrix"]["A"]["B"] is None


def test_constant_series_is_flagged_not_zero():
    flat = np.full(70, 50.0)
    prices = _frame(A=_walk(70, 5), B=flat)
    result = compute_windowed_correlation(prices)
    entry = result["60"]["pairs"]["A/B"]
    assert entry["constant_series"] is True
    assert entry["insufficient_data"] is False
    assert entry["corr"] is None
    assert result["60"]["matrix"]["A"]["B"] is None


def test_coverage_and_sample_count_for_partial_window():
    prices = _frame(A=_walk(65, 6), B=_walk(65, 7))
    result = compute_windowed_correlation(prices)
    full = result["60"]
    assert full["sample_count"] == 59  # tail(60) → 60 prices → 59 returns
    assert full["coverage"] == 1.0
    assert full["pairs"]["A/B"]["sample_count"] == 59
    partial = result["120"]
    assert partial["sample_count"] == 64  # only 65 prices available
    assert partial["coverage"] == pytest.approx(round(64 / 119, 3), rel=1e-3)
    assert partial["pairs"]["A/B"]["insufficient_data"] is False  # 64 ≥ min 10


def test_window_payload_never_contains_prediction_language():
    prices = _frame(A=_walk(80, 8), B=_walk(80, 9))
    encoded = json.dumps(compute_windowed_correlation(prices), default=str)
    for banned in ("predict", "guarantee", "cause", "señal de compra", "confidence"):
        assert banned not in encoded.lower()


# ── Lag signals ──────────────────────────────────────────────────────────────


def _lead_series(n: int = 90, lag: int = 3, seed: int = 11):
    """BTCUSD moves first; XAUUSD (gold) copies it exactly `lag` candles later."""
    btc = _walk(n, seed)
    gold = np.concatenate([np.full(lag, np.nan), btc[:-lag]])
    return _frame(XAUUSD=gold, BTCUSD=btc)


def test_lag_x_leads_gold_by_exactly_three_candles():
    prices = _lead_series(lag=3)
    result = compute_lag_signals(prices, max_lag=6)
    pairs = {p["pair"]: p for p in result["pairs"]}
    entry = pairs["BTCUSD/XAUUSD"]
    assert entry["insufficient_data"] is False
    assert entry["direction"] == "X_LEADS"
    assert entry["lead_asset"] == "BTCUSD"
    assert entry["lag_candles"] == 3
    assert entry["best_corr"] == pytest.approx(1.0, abs=1e-9)


def test_lag_reference_leads_when_gold_moves_first():
    gold = _walk(90, 12)
    btc = np.concatenate([np.full(2, np.nan), gold[:-2]])
    prices = _frame(XAUUSD=gold, BTCUSD=btc)
    result = compute_lag_signals(prices, max_lag=6)
    entry = {p["pair"]: p for p in result["pairs"]}["BTCUSD/XAUUSD"]
    assert entry["direction"] == "REFERENCE_LEADS"
    assert entry["lead_asset"] == "XAUUSD"
    assert entry["lag_candles"] == 2
    assert entry["best_corr"] == pytest.approx(1.0, abs=1e-9)


def test_lag_insufficient_data_is_flagged_not_invented():
    prices = _lead_series(n=12, lag=3)
    result = compute_lag_signals(prices, min_samples=10)
    entry = {p["pair"]: p for p in result["pairs"]}["BTCUSD/XAUUSD"]
    assert entry["insufficient_data"] is True
    assert entry["direction"] is None
    assert entry["lag_candles"] is None
    assert entry["best_corr"] is None


def test_lag_as_of_does_not_read_the_future():
    """The prefix says BTC leads gold by 3; the poisoned suffix (after as_of)
    inverts the relationship. Cutting at as_of must equal a prefix-only
    computation (aside from the as_of label itself) and must keep the agreed
    direction."""

    def strip_as_of(obj):
        if isinstance(obj, dict):
            return {k: strip_as_of(v) for k, v in obj.items() if k != "as_of"}
        if isinstance(obj, list):
            return [strip_as_of(v) for v in obj]
        return obj

    base = _lead_series(n=120, lag=3, seed=21)
    poisoned = base.copy()
    future_x = _walk(30, seed=99)
    # After row 89: gold moves first, BTC copies one candle later.
    poisoned.iloc[90:, poisoned.columns.get_loc("XAUUSD")] = future_x
    poisoned.iloc[91:, poisoned.columns.get_loc("BTCUSD")] = future_x[:-1]
    poisoned.iloc[90, poisoned.columns.get_loc("BTCUSD")] = np.nan

    as_of = poisoned.index[89]
    cut = compute_lag_signals(poisoned, as_of=as_of, max_lag=6)
    prefix_only = compute_lag_signals(
        poisoned.loc[poisoned.index <= as_of], max_lag=6
    )
    assert cut["as_of"] == as_of.isoformat()
    assert strip_as_of(cut) == strip_as_of(prefix_only)
    entry = {p["pair"]: p for p in cut["pairs"]}["BTCUSD/XAUUSD"]
    assert entry["direction"] == "X_LEADS"
    assert entry["lag_candles"] == 3

    full = compute_lag_signals(poisoned, max_lag=6)
    assert strip_as_of(full) != strip_as_of(cut), (
        "poisoned future must alter the uncut result, proving as_of matters"
    )


def test_lag_missing_reference_marks_honest_unavailable():
    prices = _frame(GOLD=_walk(80, 31), OTHER=_walk(80, 32))
    result = compute_lag_signals(prices, reference="XAUUSD")
    assert result["reference"] == "XAUUSD"
    assert result["pairs"] == []
    assert result["reference_missing"] is True


def test_lag_payload_declares_basis_and_no_prediction():
    prices = _lead_series()
    result = compute_lag_signals(prices)
    assert result["basis"] == "synchronized_returns"
    assert "no es causa ni garant" in result["disclaimer"].lower()
    assert "confidence" not in json.dumps(result, default=str).lower()
