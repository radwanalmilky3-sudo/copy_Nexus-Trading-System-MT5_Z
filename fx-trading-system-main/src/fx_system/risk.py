from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd

from .config import RiskConfig
from .models import CurrencyPair, Position, Signal
from .rates import FXRateGraph


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    units: float = 0.0
    initial_risk: float = 0.0
    reason: str = "approved"


class PortfolioRiskManager:
    def __init__(
        self,
        config: RiskConfig,
        rate_graph: FXRateGraph,
        returns: pd.DataFrame,
    ) -> None:
        self.config = config
        self.rate_graph = rate_graph
        self.returns = returns

    def currency_exposures(
        self,
        positions: Mapping[str, Position],
        prices: Mapping[str, float],
    ) -> dict[str, float]:
        native: dict[str, float] = {}
        for position in positions.values():
            pair = CurrencyPair.parse(position.symbol)
            signed_units = int(position.side) * position.units
            current_price = prices[position.symbol]
            native[pair.base] = native.get(pair.base, 0.0) + signed_units
            native[pair.quote] = native.get(pair.quote, 0.0) - signed_units * current_price
        result: dict[str, float] = {}
        for currency, amount in native.items():
            result[currency] = FXRateGraph.convert_with_prices(
                amount, currency, self.rate_graph.account_currency, prices
            )
        return result

    def gross_notional(
        self,
        positions: Mapping[str, Position],
        prices: Mapping[str, float],
    ) -> float:
        total = 0.0
        for position in positions.values():
            pair = CurrencyPair.parse(position.symbol)
            total += abs(
                FXRateGraph.convert_with_prices(
                    position.units, pair.base, self.rate_graph.account_currency, prices
                )
            )
        return total

    def _correlated_count(
        self,
        signal: Signal,
        positions: Mapping[str, Position],
        timestamp: pd.Timestamp,
    ) -> int:
        if signal.symbol not in self.returns:
            return 1
        history = self.returns.loc[self.returns.index < timestamp].tail(
            self.config.correlation_lookback
        )
        count = 1
        for position in positions.values():
            if position.symbol not in history or position.symbol == signal.symbol:
                continue
            paired = history[[signal.symbol, position.symbol]].dropna()
            if len(paired) < 3:
                continue
            correlation = paired[signal.symbol].corr(paired[position.symbol])
            if pd.notna(correlation) and (
                int(signal.side) * int(position.side) * correlation
                >= self.config.correlation_threshold
            ):
                count += 1
        return count

    def evaluate(
        self,
        signal: Signal,
        entry_mid: float,
        equity: float,
        positions: Mapping[str, Position],
        timestamp: pd.Timestamp,
        drawdown: float,
        daily_return: float,
        execution_stop_distance: float | None = None,
    ) -> RiskDecision:
        if drawdown >= self.config.max_drawdown:
            return RiskDecision(False, reason="drawdown_kill_switch")
        if daily_return <= -self.config.daily_loss_limit:
            return RiskDecision(False, reason="daily_loss_limit")
        if len(positions) >= self.config.max_open_positions:
            return RiskDecision(False, reason="max_open_positions")
        if signal.symbol in positions:
            return RiskDecision(False, reason="symbol_already_open")
        if signal.reward_risk > self.config.max_reward_risk + 1e-12:
            return RiskDecision(False, reason="reward_risk_limit")

        prices = self.rate_graph.prices_at_open(timestamp)
        prices[signal.symbol] = entry_mid
        pair = CurrencyPair.parse(signal.symbol)
        stop_distance = (
            execution_stop_distance
            if execution_stop_distance is not None
            else signal.atr * signal.stop_atr
        )
        if not math.isfinite(stop_distance) or stop_distance <= 0:
            return RiskDecision(False, reason="invalid_stop_distance")
        try:
            risk_per_unit = abs(
                FXRateGraph.convert_with_prices(
                    stop_distance, pair.quote, self.rate_graph.account_currency, prices
                )
            )
        except ValueError:
            return RiskDecision(False, reason="missing_conversion_rate")
        open_risk = sum(position.initial_risk_account for position in positions.values())
        available_risk = equity * self.config.max_portfolio_risk - open_risk
        target_risk = min(equity * self.config.risk_per_trade, available_risk)
        if target_risk <= 0:
            return RiskDecision(False, reason="max_portfolio_risk")
        raw_units = target_risk / risk_per_unit
        units = math.floor(raw_units / self.config.unit_step) * self.config.unit_step
        if units < self.config.min_units:
            return RiskDecision(False, reason="below_minimum_units")

        base_notional = abs(
            FXRateGraph.convert_with_prices(
                units, pair.base, self.rate_graph.account_currency, prices
            )
        )
        current_gross = self.gross_notional(positions, prices)
        gross_room = equity * self.config.max_gross_leverage - current_gross
        if base_notional > gross_room:
            units = (
                math.floor(units * gross_room / base_notional / self.config.unit_step)
                * self.config.unit_step
            )
        if units < self.config.min_units:
            return RiskDecision(False, reason="max_gross_leverage")

        provisional = dict(positions)
        provisional[signal.symbol] = Position(
            position_id="risk-preview",
            symbol=signal.symbol,
            strategy=signal.strategy,
            side=signal.side,
            units=units,
            entry_time=timestamp,
            entry_mid=entry_mid,
            entry_price=entry_mid,
            stop_price=entry_mid - int(signal.side) * stop_distance,
            target_price=entry_mid + int(signal.side) * stop_distance * signal.reward_risk,
            max_exit_time=timestamp,
            initial_risk_account=units * risk_per_unit,
            confidence=signal.confidence,
        )
        try:
            exposures = self.currency_exposures(provisional, prices)
        except ValueError:
            return RiskDecision(False, reason="missing_conversion_rate")
        if any(
            abs(value) > equity * self.config.max_currency_exposure for value in exposures.values()
        ):
            return RiskDecision(False, reason="max_currency_exposure")
        if (
            self._correlated_count(signal, positions, timestamp)
            > self.config.max_correlated_positions
        ):
            return RiskDecision(False, reason="correlation_cluster_limit")
        return RiskDecision(True, units=units, initial_risk=units * risk_per_unit)
