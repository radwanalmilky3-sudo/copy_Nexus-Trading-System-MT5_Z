from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from ..indicators import atr, donchian, ema, rolling_zscore, rsi, trend_strength
from ..models import Side, Signal
from .base import Strategy


def _signals_from_series(
    symbol: str,
    side: pd.Series,
    confidence: pd.Series,
    atr_values: pd.Series,
    strategy: str,
    stop_atr: float,
    target_atr: float,
    max_holding_hours: int,
    reason: str,
) -> list[Signal]:
    output: list[Signal] = []
    active = side.fillna(0).astype(int)
    for timestamp in active.index[active != 0]:
        current_atr = float(atr_values.loc[timestamp])
        current_confidence = float(confidence.loc[timestamp])
        if not np.isfinite(current_atr) or current_atr <= 0 or not np.isfinite(current_confidence):
            continue
        output.append(
            Signal(
                timestamp=timestamp,
                symbol=symbol,
                side=Side(int(active.loc[timestamp])),
                confidence=float(np.clip(current_confidence, 0, 1)),
                strategy=strategy,
                atr=current_atr,
                stop_atr=stop_atr,
                target_atr=target_atr,
                max_holding_hours=max_holding_hours,
                reason=reason,
            )
        )
    return output


class RegimeMeanReversion(Strategy):
    name = "regime_mean_reversion"

    def __init__(
        self,
        lookback: int = 30,
        entry_z: float = 1.65,
        max_trend_strength: float = 1.25,
        stop_atr: float = 1.15,
        target_atr: float = 0.72,
        max_holding_hours: int = 72,
    ) -> None:
        self.lookback = lookback
        self.entry_z = entry_z
        self.max_trend_strength = max_trend_strength
        self.stop_atr = stop_atr
        self.target_atr = target_atr
        self.max_holding_hours = max_holding_hours

    def generate(self, data: Mapping[str, pd.DataFrame]) -> list[Signal]:
        output: list[Signal] = []
        for symbol, frame in data.items():
            zscore = rolling_zscore(frame["close"], self.lookback)
            strength = trend_strength(frame)
            momentum = rsi(frame["close"], 14)
            ranging = strength <= self.max_trend_strength
            side = pd.Series(0, index=frame.index)
            long_setup = (zscore <= -self.entry_z) & (momentum < 38) & ranging
            short_setup = (zscore >= self.entry_z) & (momentum > 62) & ranging
            side[long_setup & ~long_setup.shift(1, fill_value=False)] = Side.LONG
            side[short_setup & ~short_setup.shift(1, fill_value=False)] = Side.SHORT
            confidence = ((zscore.abs() - self.entry_z) / 1.5 + 0.55).clip(0, 1)
            output.extend(
                _signals_from_series(
                    symbol,
                    side,
                    confidence,
                    atr(frame),
                    self.name,
                    self.stop_atr,
                    self.target_atr,
                    self.max_holding_hours,
                    "z-score exhaustion in a non-trending regime",
                )
            )
        return output


class TrendPullback(Strategy):
    name = "trend_pullback"

    def __init__(
        self,
        fast: int = 20,
        slow: int = 60,
        stop_atr: float = 1.25,
        target_atr: float = 0.90,
        max_holding_hours: int = 120,
    ) -> None:
        self.fast = fast
        self.slow = slow
        self.stop_atr = stop_atr
        self.target_atr = target_atr
        self.max_holding_hours = max_holding_hours

    def generate(self, data: Mapping[str, pd.DataFrame]) -> list[Signal]:
        output: list[Signal] = []
        for symbol, frame in data.items():
            fast_line = ema(frame["close"], self.fast)
            slow_line = ema(frame["close"], self.slow)
            momentum = rsi(frame["close"], 14)
            current_atr = atr(frame)
            previous = frame["close"].shift(1)
            long_pullback = (
                (fast_line > slow_line)
                & (frame["close"] > slow_line)
                & (previous <= fast_line.shift(1))
                & (frame["close"] > fast_line)
                & (momentum.between(42, 62))
            )
            short_pullback = (
                (fast_line < slow_line)
                & (frame["close"] < slow_line)
                & (previous >= fast_line.shift(1))
                & (frame["close"] < fast_line)
                & (momentum.between(38, 58))
            )
            side = pd.Series(0, index=frame.index)
            side[long_pullback] = Side.LONG
            side[short_pullback] = Side.SHORT
            separation = (fast_line - slow_line).abs() / current_atr.replace(0, np.nan)
            confidence = (0.50 + separation / 4).clip(0, 0.95)
            output.extend(
                _signals_from_series(
                    symbol,
                    side,
                    confidence,
                    current_atr,
                    self.name,
                    self.stop_atr,
                    self.target_atr,
                    self.max_holding_hours,
                    "continuation after an EMA pullback",
                )
            )
        return output


class SessionBreakout(Strategy):
    name = "session_breakout"

    def __init__(
        self,
        breakout_buffer_atr: float = 0.08,
        max_asian_range_atr: float = 2.2,
        stop_atr: float = 1.20,
        target_atr: float = 0.78,
        max_holding_hours: int = 20,
    ) -> None:
        self.breakout_buffer_atr = breakout_buffer_atr
        self.max_asian_range_atr = max_asian_range_atr
        self.stop_atr = stop_atr
        self.target_atr = target_atr
        self.max_holding_hours = max_holding_hours

    def generate(self, data: Mapping[str, pd.DataFrame]) -> list[Signal]:
        output: list[Signal] = []
        for symbol, frame in data.items():
            if len(frame.index) < 2 or (frame.index[1] - frame.index[0]) >= pd.Timedelta(days=1):
                continue
            current_atr = atr(frame)
            dates = pd.Series(frame.index.date, index=frame.index)
            asian = frame.index.hour <= 6
            asian_high = frame["high"].where(asian).groupby(dates).transform("max")
            asian_low = frame["low"].where(asian).groupby(dates).transform("min")
            london = (frame.index.hour >= 7) & (frame.index.hour <= 11)
            compact = (asian_high - asian_low) <= self.max_asian_range_atr * current_atr
            buffer = self.breakout_buffer_atr * current_atr
            upper, lower = asian_high + buffer, asian_low - buffer
            previous = frame["close"].shift(1)
            side = pd.Series(0, index=frame.index)
            side[london & compact & (frame["close"] > upper) & (previous <= upper.shift(1))] = (
                Side.LONG
            )
            side[london & compact & (frame["close"] < lower) & (previous >= lower.shift(1))] = (
                Side.SHORT
            )
            extension = pd.concat(
                [(frame["close"] - upper).clip(lower=0), (lower - frame["close"]).clip(lower=0)],
                axis=1,
            ).max(axis=1)
            confidence = (0.55 + extension / current_atr.replace(0, np.nan)).clip(0, 1)
            output.extend(
                _signals_from_series(
                    symbol,
                    side,
                    confidence,
                    current_atr,
                    self.name,
                    self.stop_atr,
                    self.target_atr,
                    self.max_holding_hours,
                    "London-session break of the completed Asian range",
                )
            )
        return output


class FalseBreakoutReversal(Strategy):
    """Fades a rejected multi-day range break only outside strong trend regimes."""

    name = "false_breakout_reversal"

    def __init__(
        self,
        range_bars: int = 18,
        max_trend_strength: float = 1.4,
        stop_atr: float = 1.10,
        target_atr: float = 0.68,
        max_holding_hours: int = 36,
    ) -> None:
        self.range_bars = range_bars
        self.max_trend_strength = max_trend_strength
        self.stop_atr = stop_atr
        self.target_atr = target_atr
        self.max_holding_hours = max_holding_hours

    def generate(self, data: Mapping[str, pd.DataFrame]) -> list[Signal]:
        output: list[Signal] = []
        for symbol, frame in data.items():
            current_atr = atr(frame)
            upper, lower = donchian(frame, self.range_bars)
            strength = trend_strength(frame)
            momentum = rsi(frame["close"], 14)
            side = pd.Series(0, index=frame.index)
            rejected_high = (
                (frame["high"] > upper)
                & (frame["close"] < upper)
                & (momentum > 55)
                & (strength < self.max_trend_strength)
            )
            rejected_low = (
                (frame["low"] < lower)
                & (frame["close"] > lower)
                & (momentum < 45)
                & (strength < self.max_trend_strength)
            )
            side[rejected_high] = Side.SHORT
            side[rejected_low] = Side.LONG
            rejection_depth = pd.concat(
                [
                    (upper - frame["close"]).clip(lower=0),
                    (frame["close"] - lower).clip(lower=0),
                ],
                axis=1,
            ).max(axis=1)
            confidence = (0.55 + rejection_depth / current_atr.replace(0, np.nan)).clip(0, 1)
            output.extend(
                _signals_from_series(
                    symbol,
                    side,
                    confidence,
                    current_atr,
                    self.name,
                    self.stop_atr,
                    self.target_atr,
                    self.max_holding_hours,
                    "failed break of the shifted multi-day range",
                )
            )
        return output
