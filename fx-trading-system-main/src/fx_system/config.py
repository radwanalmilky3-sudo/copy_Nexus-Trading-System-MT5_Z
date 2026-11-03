from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from .models import CurrencyPair


class DataConfig(BaseModel):
    provider: Literal["csv", "yahoo", "synthetic", "oanda", "dukascopy"] = "synthetic"
    directory: Path = Path("data")
    dukascopy_cache_directory: Path = Path("data/dukascopy_cache")
    dukascopy_concurrency: int = Field(8, ge=1, le=32)
    dukascopy_max_retries: int = Field(2, ge=0, le=10)
    swap_directory: Path | None = None
    maximum_swap_staleness_days: int = Field(14, ge=1, le=366)
    symbols: list[str] = Field(
        default_factory=lambda: [
            "EURUSD",
            "GBPUSD",
            "USDJPY",
            "USDCHF",
            "AUDUSD",
            "NZDUSD",
            "USDCAD",
        ]
    )
    interval: Literal["1h", "4h", "1d"] = "4h"
    price_mode: Literal["mid", "bid_ask"] = "mid"
    start: str = "2018-01-01"
    end: str | None = None
    seed: int = 42
    synthetic_bars: int = 5000

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, values: list[str]) -> list[str]:
        normalized = [CurrencyPair.parse(item).symbol for item in values]
        if len(set(normalized)) != len(normalized):
            raise ValueError("data.symbols contains duplicates")
        return normalized


class CostConfig(BaseModel):
    default_spread_pips: float = Field(0.9, ge=0)
    spread_pips: dict[str, float] = Field(default_factory=dict)
    slippage_pips: float = Field(0.15, ge=0)
    commission_per_million: float = Field(35.0, ge=0)
    daily_swap_pips_long: dict[str, float] = Field(default_factory=dict)
    daily_swap_pips_short: dict[str, float] = Field(default_factory=dict)
    quote_spread_multiplier: float = Field(1.0, ge=1.0, le=5.0)
    swap_multiplier: float = Field(1.0, ge=0.0, le=5.0)

    def spread_for(self, symbol: str) -> float:
        return self.spread_pips.get(symbol, self.default_spread_pips)


class RiskConfig(BaseModel):
    initial_equity: float = Field(100_000.0, gt=0)
    risk_per_trade: float = Field(0.003, gt=0, le=0.02)
    max_portfolio_risk: float = Field(0.015, gt=0, le=0.10)
    max_open_positions: int = Field(5, ge=1, le=30)
    max_gross_leverage: float = Field(3.0, gt=0, le=20)
    max_currency_exposure: float = Field(1.5, gt=0, le=10)
    max_correlated_positions: int = Field(2, ge=1, le=10)
    correlation_threshold: float = Field(0.80, ge=0.5, le=1)
    correlation_lookback: int = Field(120, ge=20)
    max_drawdown: float = Field(0.12, gt=0, le=0.5)
    daily_loss_limit: float = Field(0.025, gt=0, le=0.20)
    max_reward_risk: float = Field(0.85, gt=0.1, le=1.0)
    max_holding_hours: int = Field(24 * 7, ge=1, le=24 * 7)
    unit_step: int = Field(1_000, ge=1)
    min_units: int = Field(1_000, ge=1)
    close_before_weekend: bool = True


class StrategyConfig(BaseModel):
    name: Literal[
        "regime_mean_reversion",
        "trend_pullback",
        "session_breakout",
        "false_breakout_reversal",
        "currency_strength_reversion",
        "cointegration_spread",
    ]
    enabled: bool = True
    paper_enabled: bool = False
    weight: float = Field(1.0, gt=0, le=5)
    params: dict[str, Any] = Field(default_factory=dict)


class EnsembleConfig(BaseModel):
    minimum_vote: float = Field(0.50, ge=0.1, le=1)
    minimum_confidence: float = Field(0.50, ge=0, le=1)
    disagreement_penalty: float = Field(0.25, ge=0, le=1)


class OutputConfig(BaseModel):
    directory: Path = Path("outputs/latest")
    save_signals: bool = True


class SystemConfig(BaseModel):
    data: DataConfig = Field(default_factory=DataConfig)
    costs: CostConfig = Field(default_factory=CostConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    strategies: list[StrategyConfig]
    ensemble: EnsembleConfig = Field(default_factory=EnsembleConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)

    @model_validator(mode="after")
    def validate_strategy_set(self) -> SystemConfig:
        enabled = [item.name for item in self.strategies if item.enabled]
        if not enabled:
            raise ValueError("At least one strategy must be enabled")
        if len(set(enabled)) != len(enabled):
            raise ValueError("Enabled strategy names must be unique")
        if any(item.paper_enabled and not item.enabled for item in self.strategies):
            raise ValueError("paper_enabled strategies must also be enabled")
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> SystemConfig:
        config_path = Path(path)
        with config_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
        return cls.model_validate(raw)
