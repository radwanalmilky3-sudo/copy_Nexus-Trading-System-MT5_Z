"""Correlation mathematics edge cases — independent acceptance (Agent 4).

Extends tests/test_correlation_windows_lag.py with the adversarial inputs the
truth contract calls out: stale (gap) series, fully-missing symbols, zero-price
rows, tiny samples, constant series, timezone-misaligned bars, and a structural
no-lookahead proof (as_of result must equal a manual truncation of the frame).

The math itself is verified against an independent NumPy recomputation, not
against the implementation's own helpers.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from services.nexus_features.correlation import (
    MIN_CORR_SAMPLES,
    WINDOW_SIZES,
    compute_lag_signals,
    compute_windowed_correlation,
)


def _walk(n: int, seed: int, start: float = 100.0, drift: float = 0.001) -> np.ndarray:
    rng = np.random.RandomState(seed)
    return start * np.cumprod(1.0 + rng.normal(drift, 0.01, n))


def _frame(**series: np.ndarray) -> pd.DataFrame:
    n = min(len(v) for v in series.values())
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame({k: v[:n] for k, v in series.items()}, index=idx)


def _finite(v) -> bool:
    return v is None or (np.isfinite(v) and abs(float(v)) <= 1.0)


# ── Prove the math against an independent recomputation ───────────────────────

def test_windowed_corr_matches_independent_numpy_recompute():
    """recompute r_b = p_b[1:]/p_b[:-1]-1 on the same window with pure NumPy."""
    rng = np.random.RandomState(7)
    shared = rng.normal(0, 0.01, 150)
    a = 100.0 * np.cumprod(1.0 + shared)
    b = 50.0 * np.cumprod(1.0 + shared + rng.normal(0, 0.004, 150))
    prices = _frame(A=a, B=b)

    out = compute_windowed_correlation(prices)
    assert tuple(sorted(int(k) for k in out)) == tuple(sorted(WINDOW_SIZES))

    w = 60
    subset = prices.tail(w).to_numpy()  # rows of the window, both symbols
    # Independent pct_change on the window (numpy only):
    with np.errstate(divide="ignore", invalid="ignore"):
        rets = subset[1:, :] / subset[:-1, :] - 1.0
    keep = np.isfinite(rets).all(axis=1)
    rets = rets[keep]
    expected = float(np.corrcoef(rets[:, 0], rets[:, 1])[0, 1])

    got = out[str(w)]
    pair = got["pairs"]["A/B"]
    assert got["sample_count"] == int(keep.sum())
    assert pair["insufficient_data"] is False
    assert pair["constant_series"] is False
    assert pair["corr"] == pytest.approx(expected, abs=1e-3)
    # Correlation of co-moving series is positive and strong here — the sign
    # must not be lost by any returns/levels mix-up.
    assert pair["corr"] > 0.8


# ── Stale / gap / corrupt series ──────────────────────────────────────────────

def test_stale_symbol_gap_reduces_samples_and_coverage_not_quality():
    a = _walk(100, seed=1)
    b = _walk(100, seed=2)
    a[40:50] = np.nan  # symbol A stopped printing for 10 sessions
    prices = _frame(A=a, B=b)

    out = compute_windowed_correlation(prices)
    w = out["120"]  # frame shorter than the window → whole frame, honest coverage
    n = w["sample_count"]
    expected_rows = max(120 - 1, 1)
    assert n < 99  # gap rows (and their return) are gone
    assert w["coverage"] == round(min(1.0, n / expected_rows), 3)
    pair = w["pairs"]["A/B"]
    assert pair["insufficient_data"] is False
    assert pair["corr"] is not None
    assert _finite(pair["corr"])
    # sample_count is reported as the synchronized sample actually used.
    assert pair["sample_count"] == n


def test_zero_price_row_dropped_never_infinite():
    a = _walk(80, seed=3)
    b = _walk(80, seed=4)
    a[30] = 0.0  # corrupt print → ±inf return must be dropped, not fed to corr
    prices = _frame(A=a, B=b)

    out = compute_windowed_correlation(prices)
    for w in out.values():
        assert w["sample_count"] < 79
        assert w["coverage"] <= 1.0
        for v in w["pairs"]["A/B"].values():
            if isinstance(v, float):
                assert np.isfinite(v)
        assert _finite(w["matrix"]["A"]["B"])


def test_fully_missing_symbol_makes_everything_insufficient_not_zero():
    a = _walk(60, seed=5)
    b = _walk(60, seed=6)
    missing = np.full(60, np.nan)
    prices = _frame(A=a, B=b, C=missing)

    out = compute_windowed_correlation(prices)
    for w in out.values():
        assert w["sample_count"] == 0
        for pair in w["pairs"].values():
            assert pair["insufficient_data"] is True
            assert pair["corr"] is None  # not 0, not a number


def test_tiny_sample_frame_flags_all_windows_insufficient():
    prices = _frame(A=_walk(6, seed=7), B=_walk(6, seed=8))

    out = compute_windowed_correlation(prices)
    assert set(out) == {"20", "60", "120"}
    for w in out.values():
        assert w["sample_count"] == 5  # 6 rows → 5 returns
        assert w["coverage"] < 1.0
        for pair in w["pairs"].values():
            assert pair["insufficient_data"] is True
            assert pair["sample_count"] < MIN_CORR_SAMPLES
            assert pair["corr"] is None


# ── Constant series ───────────────────────────────────────────────────────────

def test_constant_symbol_flags_only_pairs_that_contain_it():
    a = np.full(150, 100.0)  # stale feed: same close every day
    b = _walk(150, seed=9)
    c = _walk(150, seed=10)
    prices = _frame(A=a, B=b, C=c)

    out = compute_windowed_correlation(prices)["120"]
    assert out["pairs"]["A/B"]["constant_series"] is True
    assert out["pairs"]["A/B"]["corr"] is None
    assert out["pairs"]["A/C"]["constant_series"] is True
    assert out["pairs"]["A/C"]["corr"] is None
    # Unaffected pair still computes real math.
    healthy = out["pairs"]["B/C"]
    assert healthy["constant_series"] is False
    assert healthy["insufficient_data"] is False
    assert healthy["corr"] is not None
    assert _finite(healthy["corr"])


# ── Coverage arithmetic ───────────────────────────────────────────────────────

def test_coverage_uses_window_minus_one_and_honest_partial_windows():
    prices = _frame(A=_walk(50, seed=11), B=_walk(50, seed=12))
    out = compute_windowed_correlation(prices)

    w20, w60, w120 = out["20"], out["60"], out["120"]
    # 50-row frame: window 20 fully available → 19 returns, coverage 1.0
    assert w20["sample_count"] == 19
    assert w20["coverage"] == 1.0
    # Windows larger than the frame degrade coverage honestly.
    assert w60["sample_count"] == 49
    assert w60["coverage"] == round(49 / 59, 3)
    assert w120["sample_count"] == 49
    assert w120["coverage"] == round(49 / 119, 3)
    assert w120["coverage"] < w60["coverage"] < w20["coverage"]


def test_matrix_is_symmetric_with_none_diagonal():
    prices = _frame(A=_walk(70, seed=13), B=_walk(70, seed=14), C=_walk(70, seed=15))
    out = compute_windowed_correlation(prices)["60"]
    m = out["matrix"]
    for a in m:
        assert m[a][a] is None
        for b in m[a]:
            assert m[a][b] == m[b][a]


# ── No lookahead / timezone-misaligned bars ───────────────────────────────────

def _leading_pair(n: int = 90, lead: int = 3) -> pd.DataFrame:
    """X moves first; the reference copies it `lead` candles later."""
    rng = np.random.RandomState(21)
    x = np.cumsum(rng.normal(0, 1.0, n))
    ref = np.concatenate([np.zeros(lead), x[:-lead]])
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"X": 100.0 + x, "XAUUSD": 2000.0 + ref},
        index=idx,
    )


def _pairs_without_as_of(payload: dict) -> list[dict]:
    return [{k: v for k, v in p.items() if k != "as_of"} for p in payload["pairs"]]


def test_as_of_equals_manual_truncation_structural_no_lookahead():
    """Full-frame call with as_of must be IDENTICAL to a manually truncated
    frame — the future can change nothing about the past result."""
    prices = _leading_pair()
    as_of = "2026-01-20"  # mid-series: future rows still exist in `prices`

    full_call = compute_lag_signals(prices, as_of=as_of)
    truncated = prices[prices.index <= pd.Timestamp(as_of)]
    manual_call = compute_lag_signals(truncated)

    assert full_call["as_of"] == pd.Timestamp(as_of).isoformat()
    assert _pairs_without_as_of(full_call) == _pairs_without_as_of(manual_call)
    # And the truncated frame really did drop the future.
    assert len(truncated) < len(prices)


def test_timezone_aware_index_with_aware_as_of_no_crash_and_no_lookahead():
    prices = _leading_pair()
    prices.index = prices.index.tz_localize("UTC")  # tz-misaligned vs naive consumers
    as_of = "2026-01-25T00:00:00+00:00"

    aware_call = compute_lag_signals(prices, as_of=as_of)
    naive_as_of = pd.Timestamp(as_of).tz_localize(None)
    truncated = prices[prices.index.tz_localize(None) <= naive_as_of]
    manual_call = compute_lag_signals(truncated)

    assert aware_call["as_of"] == naive_as_of.isoformat()  # stored tz-naive
    assert _pairs_without_as_of(aware_call) == _pairs_without_as_of(manual_call)
    assert all(p["insufficient_data"] is False for p in aware_call["pairs"])


def test_naive_as_of_against_timezone_aware_index_no_crash():
    prices = _leading_pair()
    prices.index = prices.index.tz_localize("UTC")

    result = compute_lag_signals(prices, as_of="2026-01-25")

    assert result["as_of"] == "2026-01-25T00:00:00"
    assert result["pairs"]  # computed, not crashed
    assert all(p["as_of"] == "2026-01-25T00:00:00" for p in result["pairs"])


def test_lag_x_leads_direction_survives_timezone_aware_bars():
    prices = _leading_pair(lead=3)
    prices.index = prices.index.tz_localize("UTC")

    result = compute_lag_signals(prices, as_of="2026-03-31")

    pair = result["pairs"][0]
    assert pair["pair"] == "X/XAUUSD"
    assert pair["direction"] == "X_LEADS"
    assert pair["lead_asset"] == "X"
    assert pair["lag_candles"] == 3


def test_lag_result_ignores_rows_after_as_of_even_if_they_would_flip_direction():
    """Poison the future with a stronger reverse lead; the as_of answer must
    still equal the truncated-frame answer (future cannot flip the past)."""
    prices = _leading_pair(n=90, lead=3)
    future = prices.index > pd.Timestamp("2026-01-25")
    # Make the reference lead strongly in the poisoned future segment:
    ref = prices.loc[future, "XAUUSD"].to_numpy()
    prices.loc[future, "X"] = 2000.0 + 0.0  # flat
    prices.loc[future, "XAUUSD"] = ref
    # Force an artificial anti-correlation pattern after the cut:
    prices.loc[future, "X"] = 100.0 + np.linspace(0, 10, future.sum())
    prices.loc[future, "XAUUSD"] = 2000.0 + np.linspace(10, 0, future.sum())

    as_of_call = compute_lag_signals(prices, as_of="2026-01-25")
    truncated = prices[prices.index <= pd.Timestamp("2026-01-25")]
    manual_call = compute_lag_signals(truncated)

    assert _pairs_without_as_of(as_of_call) == _pairs_without_as_of(manual_call)
