"""Read-only mapping from the strategy catalog to Research Lab backtests.

This module only builds immutable request/schema objects.  It does not load
market data, call an API, start a service, execute a backtest, or authorize
trading.  LIVE is represented so callers can distinguish it from BACKTEST and
PAPER, but it is rejected at the schema boundary.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .catalog import REFERENCE_PARAMETER_SETS, REFERENCE_STRATEGIES
from shared.strategy_contracts import ParameterSelectionScope, ParameterSet, StrategyDefinition


class IntegrationMode(StrEnum):
    """Execution-context label carried by a read-only integration request."""

    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


class LiveModeRejected(ValueError):
    """Raised when a request attempts to cross the LIVE boundary."""


class ResearchBacktestRequest(BaseModel):
    """Immutable schema for presenting one catalog strategy to Research Lab."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["1.0"] = "1.0"
    request_type: Literal["research_lab_backtest"] = "research_lab_backtest"
    strategy_id: str = Field(min_length=1)
    strategy_version: str = Field(min_length=1)
    parameter_set_id: str = Field(min_length=1)
    mode: IntegrationMode = IntegrationMode.BACKTEST
    read_only: Literal[True] = True
    execute: Literal[False] = False
    symbols: tuple[str, ...] = ()
    timeframes: tuple[str, ...] = ()
    required_columns: tuple[str, ...] = ()
    feature_names: tuple[str, ...] = ()
    parameters: dict[str, bool | float | int | str] = Field(default_factory=dict)
    selection_scope: ParameterSelectionScope = ParameterSelectionScope.TRAIN_ONLY
    regime_labels: tuple[str, ...] = ()
    news_regime_hook_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def reject_live_mode(self) -> "ResearchBacktestRequest":
        if self.mode is IntegrationMode.LIVE:
            raise LiveModeRejected(
                "LIVE mode is not permitted by the read-only Research Lab integration"
            )
        return self


def _catalog_indexes() -> tuple[dict[str, StrategyDefinition], dict[str, ParameterSet]]:
    strategies = {item.strategy_id: item for item in REFERENCE_STRATEGIES}
    parameter_sets = {item.parameter_set_id: item for item in REFERENCE_PARAMETER_SETS}
    return strategies, parameter_sets


def _request_for(
    strategy: StrategyDefinition,
    parameter_set: ParameterSet,
    *,
    mode: IntegrationMode,
) -> ResearchBacktestRequest:
    if parameter_set.strategy_id != strategy.strategy_id:
        raise ValueError("catalog strategy and parameter set must identify the same strategy")
    if parameter_set.parameter_set_id != strategy.parameter_set_id:
        raise ValueError("catalog strategy and parameter set ids must match")

    return ResearchBacktestRequest(
        strategy_id=strategy.strategy_id,
        strategy_version=strategy.version,
        parameter_set_id=parameter_set.parameter_set_id,
        mode=mode,
        symbols=strategy.symbols,
        timeframes=strategy.timeframes,
        required_columns=strategy.required_columns,
        feature_names=strategy.feature_names,
        parameters=dict(parameter_set.parameters),
        selection_scope=parameter_set.selection_scope,
        regime_labels=strategy.regime_labels,
        news_regime_hook_ids=strategy.news_regime_hook_ids,
    )


def build_backtest_request(
    strategy_id: str,
    *,
    mode: IntegrationMode = IntegrationMode.BACKTEST,
) -> ResearchBacktestRequest:
    """Map one catalog strategy to an immutable Research Lab request schema."""

    if mode is IntegrationMode.LIVE:
        raise LiveModeRejected(
            "LIVE mode is not permitted by the read-only Research Lab integration"
        )

    strategies, parameter_sets = _catalog_indexes()
    try:
        strategy = strategies[strategy_id]
    except KeyError as exc:
        raise KeyError(f"unknown catalog strategy: {strategy_id}") from exc

    try:
        parameter_set = parameter_sets[strategy.parameter_set_id]
    except KeyError as exc:
        raise KeyError(
            f"missing catalog parameter set: {strategy.parameter_set_id}"
        ) from exc

    return _request_for(strategy, parameter_set, mode=mode)


def strategy_catalog_to_backtest_schema(
    *,
    mode: IntegrationMode = IntegrationMode.BACKTEST,
) -> Mapping[str, ResearchBacktestRequest]:
    """Return the catalog-to-schema mapping without any execution side effect."""

    if mode is IntegrationMode.LIVE:
        raise LiveModeRejected(
            "LIVE mode is not permitted by the read-only Research Lab integration"
        )

    return MappingProxyType(
        {
            strategy.strategy_id: build_backtest_request(strategy.strategy_id, mode=mode)
            for strategy in REFERENCE_STRATEGIES
        }
    )


STRATEGY_BACKTEST_REQUESTS: Mapping[str, ResearchBacktestRequest] = (
    strategy_catalog_to_backtest_schema()
)


__all__ = [
    "IntegrationMode",
    "LiveModeRejected",
    "ResearchBacktestRequest",
    "STRATEGY_BACKTEST_REQUESTS",
    "build_backtest_request",
    "strategy_catalog_to_backtest_schema",
]
