from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gains = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    losses = -delta.clip(upper=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    relative_strength = gains / losses.replace(0, np.nan)
    return 100 - (100 / (1 + relative_strength))


def rolling_zscore(series: pd.Series, period: int) -> pd.Series:
    mean = series.rolling(period, min_periods=period).mean()
    std = series.rolling(period, min_periods=period).std(ddof=0).replace(0, np.nan)
    return (series - mean) / std


def trend_strength(
    frame: pd.DataFrame, fast: int = 20, slow: int = 50, atr_period: int = 14
) -> pd.Series:
    scale = atr(frame, atr_period).replace(0, np.nan)
    return (ema(frame["close"], fast) - ema(frame["close"], slow)).abs() / scale


def donchian(frame: pd.DataFrame, period: int) -> tuple[pd.Series, pd.Series]:
    # Shifted channels guarantee that today's signal cannot use today's high/low as history.
    upper = frame["high"].shift(1).rolling(period, min_periods=period).max()
    lower = frame["low"].shift(1).rolling(period, min_periods=period).min()
    return upper, lower
