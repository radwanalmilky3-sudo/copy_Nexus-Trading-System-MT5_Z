"""
Trend detection and market-structure analysis.

All functions are vectorised.  ``detect_market_structure`` uses a
rolling-window approach to identify swing points and label them as
Higher-Highs, Higher-Lows, Lower-Highs, Lower-Lows.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Literal

import numpy as np
import pandas as pd
from shared.pandas_ta_compat import ta


@unique
class Trend(StrEnum):
    UPTREND   = "UPTREND"
    DOWNTREND = "DOWNTREND"
    SIDEWAYS  = "SIDEWAYS"


@dataclass(frozen=True)
class TrendResult:
    direction: Trend
    strength: float          # 0‒100


@dataclass(frozen=True)
class SwingPoint:
    index: int
    price: float
    kind: Literal["HIGH", "LOW"]
    timestamp: str | None = None


@dataclass(frozen=True)
class MarketStructure:
    label: str               # e.g. "HH", "HL", "LH", "LL"
    swing: SwingPoint


# ── Swing-point detection ────────────────────────────────────────────────────

def find_swing_points(
    df: pd.DataFrame,
    order: int = 5,
) -> list[SwingPoint]:
    """
    Find local swing highs and lows using a rolling window of *order* bars
    on each side.
    """
    highs: list[SwingPoint] = []
    lows: list[SwingPoint] = []
    if not {"high", "low"}.issubset(df.columns):
        return []
    h = pd.to_numeric(df["high"], errors="coerce").to_numpy(dtype=float)
    l = pd.to_numeric(df["low"], errors="coerce").to_numpy(dtype=float)
    n = len(df)
    if n == 0:
        return []

    ts_col = None
    if "timestamp" in df.columns:
        ts_col = df["timestamp"].astype(str).values

    for i in range(order, n - order):
        if h[i] == np.max(h[i - order : i + order + 1]):
            highs.append(SwingPoint(
                index=i,
                price=float(h[i]),
                kind="HIGH",
                timestamp=ts_col[i] if ts_col is not None else None,
            ))
        if l[i] == np.min(l[i - order : i + order + 1]):
            lows.append(SwingPoint(
                index=i,
                price=float(l[i]),
                kind="LOW",
                timestamp=ts_col[i] if ts_col is not None else None,
            ))

    merged = sorted(highs + lows, key=lambda s: s.index)
    return merged


# ── Market-structure labelling ───────────────────────────────────────────────

def detect_market_structure(
    df: pd.DataFrame,
    order: int = 5,
) -> list[MarketStructure]:
    """
    Walk through swing points and label each as HH / HL / LH / LL relative
    to its predecessor of the same kind.
    """
    swings = find_swing_points(df, order=order)
    results: list[MarketStructure] = []
    last_high: SwingPoint | None = None
    last_low: SwingPoint | None = None

    for sp in swings:
        if sp.kind == "HIGH":
            if last_high is not None:
                label = "HH" if sp.price > last_high.price else "LH"
                results.append(MarketStructure(label=label, swing=sp))
            last_high = sp
        else:
            if last_low is not None:
                label = "HL" if sp.price > last_low.price else "LL"
                results.append(MarketStructure(label=label, swing=sp))
            last_low = sp

    return results


# ── Trend detection ──────────────────────────────────────────────────────────

def detect_trend(
    df: pd.DataFrame,
    order: int = 5,
) -> TrendResult:
    """
    Classify the current trend based on the last N market-structure labels
    and the trend score.
    """
    score = calculate_trend_score(df)
    if score > 30:
        direction = Trend.UPTREND
    elif score < -30:
        direction = Trend.DOWNTREND
    else:
        direction = Trend.SIDEWAYS
    return TrendResult(direction=direction, strength=abs(score))


# ── Composite trend score ────────────────────────────────────────────────────

def calculate_trend_score(df: pd.DataFrame) -> float:
    """
    Composite score from **-100** to **+100** using:

    1. EMA alignment (9 > 21 > 50 > 200)
    2. ADX + DI spread
    3. Recent market-structure labels (HH/HL vs LH/LL)
    4. Price relative to Ichimoku cloud
    """
    # Guard empty / malformed frames: short-window indicators would otherwise
    # raise on ``iloc[-1]`` or divide by zero on empty rolling windows.
    if df is None or len(df) < 2 or not {"close", "high", "low"}.issubset(df.columns):
        return 0.0

    score = 0.0
    close = df["close"].iloc[-1]
    if not np.isfinite(close):
        return 0.0

    # 1 — EMA alignment (max ±30)
    ema9 = ta.ema(df["close"], length=9)
    ema21 = ta.ema(df["close"], length=21)
    ema50 = ta.ema(df["close"], length=50)
    ema200 = ta.ema(df["close"], length=200)
    emas = [ema9, ema21, ema50, ema200]
    vals = [s.iloc[-1] if s is not None and len(s) else np.nan for s in emas]
    if all(np.isfinite(v) for v in vals):
        aligned_bull = all(vals[i] >= vals[i + 1] for i in range(len(vals) - 1))
        aligned_bear = all(vals[i] <= vals[i + 1] for i in range(len(vals) - 1))
        if aligned_bull:
            score += 30
        elif aligned_bear:
            score -= 30
        else:
            if vals[0] > vals[1]:
                score += 10
            else:
                score -= 10

    # 2 — ADX + DI (max ±30)
    adx_df = ta.adx(df["high"], df["low"], df["close"], length=14)
    if adx_df is not None and not adx_df.empty:
        adx_val = adx_df.iloc[-1, 0]
        di_plus = adx_df.iloc[-1, 1]
        di_minus = adx_df.iloc[-1, 2]
        if np.isfinite(adx_val) and np.isfinite(di_plus) and np.isfinite(di_minus):
            trend_strength = min(adx_val / 50, 1.0)
            di_diff = (di_plus - di_minus) / max(di_plus + di_minus, 1)
            score += 30 * di_diff * trend_strength

    # 3 — Market-structure labels (max ±25)
    structures = detect_market_structure(df)
    if structures:
        recent = structures[-min(6, len(structures)) :]
        bull_labels = sum(1 for s in recent if s.label in ("HH", "HL"))
        bear_labels = sum(1 for s in recent if s.label in ("LH", "LL"))
        total = bull_labels + bear_labels
        if total:
            score += 25 * (bull_labels - bear_labels) / total

    # 4 — Ichimoku cloud position (max ±15)
    # The cloud is Senkou Span A + Span B (columns ISA_*/ISB_*).  Selecting by
    # name avoids the previous positional read of col 2/3, which were actually
    # Tenkan/Kijun — not the cloud.  Spans are shifted +26 inside the engine,
    # so each plotted value comes from bars that already closed (no lookahead).
    ichi = ta.ichimoku(df["high"], df["low"], df["close"])
    if ichi is not None and isinstance(ichi, tuple) and len(ichi) >= 1:
        frame = ichi[0]
        if frame is not None and not frame.empty:
            span_a_col = next(
                (c for c in frame.columns if str(c).startswith("ISA_")), None
            )
            span_b_col = next(
                (c for c in frame.columns if str(c).startswith("ISB_")), None
            )
            if span_a_col is not None and span_b_col is not None:
                span_a = frame[span_a_col].iloc[-1]
                span_b = frame[span_b_col].iloc[-1]
                if np.isfinite(span_a) and np.isfinite(span_b):
                    cloud_top = max(span_a, span_b)
                    cloud_bot = min(span_a, span_b)
                    if close > cloud_top:
                        score += 15
                    elif close < cloud_bot:
                        score -= 15

    return float(np.clip(score, -100, 100))
