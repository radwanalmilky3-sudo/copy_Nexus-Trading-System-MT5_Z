from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint

from ..indicators import atr, rolling_zscore
from ..models import CurrencyPair, Side, Signal
from .base import Strategy


class CurrencyStrengthReversion(Strategy):
    """Trades pair exhaustion only when the whole currency graph confirms the imbalance."""

    name = "currency_strength_reversion"

    def __init__(
        self,
        lookback: int = 18,
        strength_z: float = 1.25,
        pair_z: float = 1.35,
        stop_atr: float = 1.15,
        target_atr: float = 0.70,
        max_holding_hours: int = 72,
    ) -> None:
        self.lookback = lookback
        self.strength_z = strength_z
        self.pair_z = pair_z
        self.stop_atr = stop_atr
        self.target_atr = target_atr
        self.max_holding_hours = max_holding_hours

    def generate(self, data: Mapping[str, pd.DataFrame]) -> list[Signal]:
        closes = pd.concat(
            {symbol: frame["close"] for symbol, frame in data.items()}, axis=1
        ).sort_index()
        returns = np.log(closes).diff()
        contributions: dict[str, list[pd.Series]] = defaultdict(list)
        for symbol in returns:
            pair = CurrencyPair.parse(symbol)
            contributions[pair.base].append(returns[symbol])
            contributions[pair.quote].append(-returns[symbol])
        currency_returns = pd.DataFrame(
            {
                currency: pd.concat(parts, axis=1).mean(axis=1)
                for currency, parts in contributions.items()
            }
        )
        strength = currency_returns.rolling(self.lookback, min_periods=self.lookback).sum()
        strength_zscores = strength.apply(lambda column: rolling_zscore(column, self.lookback * 2))

        output: list[Signal] = []
        for symbol, frame in data.items():
            pair = CurrencyPair.parse(symbol)
            relative = strength_zscores[pair.base] - strength_zscores[pair.quote]
            price_z = rolling_zscore(frame["close"].reindex(closes.index), self.lookback * 2)
            side = pd.Series(0, index=closes.index)
            long_setup = (relative <= -self.strength_z) & (price_z <= -self.pair_z)
            short_setup = (relative >= self.strength_z) & (price_z >= self.pair_z)
            side[long_setup & ~long_setup.shift(1, fill_value=False)] = Side.LONG
            side[short_setup & ~short_setup.shift(1, fill_value=False)] = Side.SHORT
            confidence = (
                0.45
                + (relative.abs() - self.strength_z).clip(lower=0) / 4
                + (price_z.abs() - self.pair_z).clip(lower=0) / 4
            ).clip(0, 1)
            current_atr = atr(frame).reindex(closes.index)
            for timestamp in side.index[side != 0]:
                if timestamp not in frame.index:
                    continue
                values = (current_atr.loc[timestamp], confidence.loc[timestamp])
                if not all(np.isfinite(value) for value in values) or values[0] <= 0:
                    continue
                output.append(
                    Signal(
                        timestamp=timestamp,
                        symbol=symbol,
                        side=Side(int(side.loc[timestamp])),
                        confidence=float(values[1]),
                        strategy=self.name,
                        atr=float(values[0]),
                        stop_atr=self.stop_atr,
                        target_atr=self.target_atr,
                        max_holding_hours=self.max_holding_hours,
                        reason=(
                            f"currency graph imbalance {pair.base}-{pair.quote}="
                            f"{relative.loc[timestamp]:.2f}"
                        ),
                    )
                )
        return output


class CointegrationSpread(Strategy):
    """Rolling Engle-Granger spread strategy for related major pairs."""

    name = "cointegration_spread"

    def __init__(
        self,
        pairs: list[list[str]] | None = None,
        lookback: int = 180,
        entry_z: float = 2.0,
        max_pvalue: float = 0.10,
        retest_bars: int = 24,
        stop_atr: float = 1.30,
        target_atr: float = 0.90,
        max_holding_hours: int = 120,
    ) -> None:
        self.pairs = pairs or [["EURUSD", "GBPUSD"], ["AUDUSD", "NZDUSD"]]
        self.lookback = lookback
        self.entry_z = entry_z
        self.max_pvalue = max_pvalue
        self.retest_bars = retest_bars
        self.stop_atr = stop_atr
        self.target_atr = target_atr
        self.max_holding_hours = max_holding_hours

    def generate(self, data: Mapping[str, pd.DataFrame]) -> list[Signal]:
        output: list[Signal] = []
        for pair_index, raw_pair in enumerate(self.pairs):
            left, right = (CurrencyPair.parse(item).symbol for item in raw_pair)
            if left not in data or right not in data:
                continue
            aligned = pd.concat(
                {left: np.log(data[left]["close"]), right: np.log(data[right]["close"])}, axis=1
            ).dropna()
            if len(aligned) < self.lookback + 2:
                continue
            covariance = aligned[left].rolling(self.lookback).cov(aligned[right])
            variance = aligned[right].rolling(self.lookback).var().replace(0, np.nan)
            beta = covariance / variance
            spread = aligned[left] - beta * aligned[right]
            spread_z = rolling_zscore(spread, self.lookback)
            valid = pd.Series(False, index=aligned.index)
            for end in range(self.lookback, len(aligned), self.retest_bars):
                window = aligned.iloc[end - self.lookback : end]
                try:
                    pvalue = float(coint(window[left], window[right], trend="c")[1])
                except (ValueError, np.linalg.LinAlgError):
                    pvalue = 1.0
                valid.iloc[end : min(end + self.retest_bars, len(valid))] = (
                    pvalue <= self.max_pvalue
                )
            triggers = (
                valid & (spread_z.abs() >= self.entry_z) & (spread_z.shift(1).abs() < self.entry_z)
            )
            left_atr, right_atr = atr(data[left]), atr(data[right])
            for timestamp in aligned.index[triggers]:
                direction = -1 if spread_z.loc[timestamp] > 0 else 1
                confidence = float(
                    np.clip(0.55 + (abs(spread_z.loc[timestamp]) - self.entry_z) / 3, 0, 1)
                )
                group_id = f"coint-{pair_index}-{timestamp.isoformat()}"
                for symbol, side, atr_values in (
                    (left, Side(direction), left_atr),
                    (right, Side(-direction), right_atr),
                ):
                    current_atr = float(atr_values.get(timestamp, np.nan))
                    if not np.isfinite(current_atr) or current_atr <= 0:
                        continue
                    output.append(
                        Signal(
                            timestamp=timestamp,
                            symbol=symbol,
                            side=side,
                            confidence=confidence,
                            strategy=self.name,
                            atr=current_atr,
                            stop_atr=self.stop_atr,
                            target_atr=self.target_atr,
                            max_holding_hours=self.max_holding_hours,
                            reason=f"Engle-Granger spread z={spread_z.loc[timestamp]:.2f}",
                            group_id=group_id,
                        )
                    )
        return output
