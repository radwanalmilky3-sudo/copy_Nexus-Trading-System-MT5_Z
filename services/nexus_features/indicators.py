"""
Technical indicator calculations — fully vectorised with pandas / numpy.

Uses pandas_ta as the primary engine with manual fallbacks where needed.
Every function accepts a DataFrame with columns: open, high, low, close, volume
and returns the *same* DataFrame with new indicator columns appended.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from shared.pandas_ta_compat import ta


# ── EMA ──────────────────────────────────────────────────────────────────────

def calculate_ema(
    df: pd.DataFrame,
    periods: list[int] | None = None,
) -> pd.DataFrame:
    if periods is None:
        periods = [9, 21, 50, 200]
    for p in periods:
        df[f"ema_{p}"] = ta.ema(df["close"], length=p)
    return df


# ── RSI ──────────────────────────────────────────────────────────────────────

def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    df["rsi"] = ta.rsi(df["close"], length=period)
    return df


# ── MACD ─────────────────────────────────────────────────────────────────────

def calculate_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    macd = ta.macd(df["close"], fast=fast, slow=slow, signal=signal)
    if macd is not None and not macd.empty:
        df["macd"] = macd.iloc[:, 0]
        df["macd_histogram"] = macd.iloc[:, 1]
        df["macd_signal"] = macd.iloc[:, 2]
    return df


# ── Bollinger Bands ──────────────────────────────────────────────────────────

def calculate_bollinger_bands(
    df: pd.DataFrame,
    period: int = 20,
    std: float = 2.0,
) -> pd.DataFrame:
    bb = ta.bbands(df["close"], length=period, std=std)
    if bb is not None and not bb.empty:
        df["bb_lower"] = bb.iloc[:, 0]
        df["bb_mid"] = bb.iloc[:, 1]
        df["bb_upper"] = bb.iloc[:, 2]
        df["bb_bandwidth"] = bb.iloc[:, 3]
        df["bb_pct_b"] = bb.iloc[:, 4]
    return df


# ── Stochastic Oscillator ───────────────────────────────────────────────────

def calculate_stochastic(
    df: pd.DataFrame,
    k: int = 14,
    d: int = 3,
) -> pd.DataFrame:
    stoch = ta.stoch(df["high"], df["low"], df["close"], k=k, d=d)
    if stoch is not None and not stoch.empty:
        df["stoch_k"] = stoch.iloc[:, 0]
        df["stoch_d"] = stoch.iloc[:, 1]
    return df


# ── VWAP ─────────────────────────────────────────────────────────────────────

def calculate_vwap(df: pd.DataFrame) -> pd.DataFrame:
    if "volume" not in df.columns or df["volume"].sum() == 0:
        df["vwap"] = np.nan
        return df
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    cum_tp_vol = (typical * df["volume"]).cumsum()
    cum_vol = df["volume"].cumsum()
    df["vwap"] = cum_tp_vol / cum_vol.replace(0, np.nan)
    return df


# ── ATR ──────────────────────────────────────────────────────────────────────

def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=period)
    return df


# ── ADX ──────────────────────────────────────────────────────────────────────

def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    adx = ta.adx(df["high"], df["low"], df["close"], length=period)
    if adx is not None and not adx.empty:
        df["adx"] = adx.iloc[:, 0]
        df["di_plus"] = adx.iloc[:, 1]
        df["di_minus"] = adx.iloc[:, 2]
    return df


# ── Ichimoku Cloud ───────────────────────────────────────────────────────────

# pandas_ta / pandas_ta_classic name the Ichimoku columns by role prefix:
#   ITS_ = Tenkan-sen (conversion), IKS_ = Kijun-sen (base),
#   ISA_ = Senkou Span A,           ISB_ = Senkou Span B.
# Mapping by prefix avoids the positional swap that previously labelled
# Senkou Span A as "conversion" and Tenkan as "span_a".  Only frame 0 is
# used; frame 1 holds forward-displaced (future) spans and is never read.
_ICHIMOKU_PREFIX_MAP: tuple[tuple[str, str], ...] = (
    ("ITS_", "ichi_conversion"),
    ("IKS_", "ichi_base"),
    ("ISA_", "ichi_span_a"),
    ("ISB_", "ichi_span_b"),
)


def calculate_ichimoku(df: pd.DataFrame) -> pd.DataFrame:
    ichi = ta.ichimoku(df["high"], df["low"], df["close"])
    if ichi is not None and isinstance(ichi, tuple) and len(ichi) >= 1:
        frame = ichi[0]
        if frame is not None and not frame.empty:
            for col in frame.columns:
                name = str(col)
                for prefix, dst in _ICHIMOKU_PREFIX_MAP:
                    if name.startswith(prefix):
                        series = frame[col]
                        # Align positionally when lengths match (normal path);
                        # fall back to index alignment otherwise.  Senkou spans
                        # are shifted +26 inside the engine, so every value is
                        # computed from bars that already closed — no lookahead.
                        if len(series) == len(df):
                            df[dst] = series.to_numpy()
                        else:
                            df[dst] = series.reindex(df.index).to_numpy()
                        break
    return df


# ── Master function ──────────────────────────────────────────────────────────

def calculate_all(df: pd.DataFrame) -> pd.DataFrame:
    """Run *every* indicator and return the enriched DataFrame."""
    df = df.copy()
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)

    df = calculate_ema(df)
    df = calculate_rsi(df)
    df = calculate_macd(df)
    df = calculate_bollinger_bands(df)
    df = calculate_stochastic(df)
    df = calculate_vwap(df)
    df = calculate_atr(df)
    df = calculate_adx(df)
    df = calculate_ichimoku(df)
    return df
