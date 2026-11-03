from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import DataConfig


class LongHorizonExternalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    raw_directory: Path = Path("data/external_raw")
    cftc_file: Path = Path("data/point_in_time/currency_positioning.csv")
    official_rates_file: Path = Path(
        "data/official_rates/normalized/official_rate_observations.csv"
    )
    supplemental_file: Path = Path(
        "data/supplemental_fx/normalized/supplemental_observations.csv"
    )
    gscpi_vintages_file: Path = Path(
        "data/supplemental_fx/normalized/gscpi_vintages.csv"
    )
    reer_release_lag_days: int = Field(60, ge=30, le=120)
    reer_maximum_staleness_days: int = Field(120, ge=60, le=366)
    positioning_maximum_staleness_days: int = Field(35, ge=14, le=120)
    risk_daily_release_lag_days: int = Field(1, ge=1, le=7)
    risk_weekly_release_lag_days: int = Field(7, ge=1, le=21)
    risk_maximum_staleness_days: int = Field(21, ge=7, le=60)
    rate_reference_maximum_staleness_days: int = Field(75, ge=14, le=180)
    supplemental_maximum_staleness_days: int = Field(120, ge=45, le=366)
    gscpi_maximum_staleness_days: int = Field(75, ge=30, le=180)
    current_vintage_quality: str = "exploratory_current_vintage"


class LongHorizonSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research_mode: Literal["cross_sectional", "time_series_panel"] = "cross_sectional"
    horizons: list[int] = Field(default_factory=lambda: [21, 42, 63])
    momentum_windows: list[int] = Field(default_factory=lambda: [21, 63, 126, 252])
    trend_windows: list[int] = Field(default_factory=lambda: [63, 126, 252])
    volatility_windows: list[int] = Field(default_factory=lambda: [21, 63, 126])
    momentum_skip_days: int = Field(21, ge=1, le=63)
    reer_windows_months: list[int] = Field(default_factory=lambda: [36, 60])
    rebalance_interval_days: int = Field(21, ge=5, le=63)
    train_years: int = Field(8, ge=3, le=20)
    test_years: int = Field(2, ge=1, le=5)
    step_years: int = Field(2, ge=1, le=5)
    minimum_history_years: float = Field(10.0, ge=3.0, le=25.0)
    minimum_market_coverage: float = Field(0.80, ge=0.5, le=1.0)
    minimum_cross_symbol_coverage: float = Field(0.90, ge=0.5, le=1.0)
    minimum_factor_coverage: float = Field(0.60, ge=0.25, le=1.0)
    minimum_absolute_train_ic: float = Field(0.01, ge=0.0, le=0.25)
    factor_fdr_level: float = Field(0.10, gt=0.0, le=0.50)
    minimum_walk_forward_folds: int = Field(3, ge=1, le=10)
    bootstrap_samples: int = Field(20_000, ge=100, le=100_000)
    bootstrap_block_days: int = Field(63, ge=10, le=252)
    random_state: int = 42
    output_directory: Path = Path("outputs/long_horizon_free")

    @field_validator(
        "horizons",
        "momentum_windows",
        "trend_windows",
        "volatility_windows",
        "reer_windows_months",
    )
    @classmethod
    def unique_positive_windows(cls, values: list[int]) -> list[int]:
        if not values or any(value <= 0 for value in values):
            raise ValueError("long-horizon windows must be non-empty and positive")
        return sorted(set(values))

    @model_validator(mode="after")
    def consistent_horizons(self) -> LongHorizonSettings:
        if max(self.horizons) > 126:
            raise ValueError("long-horizon labels are limited to 126 trading days")
        if self.momentum_skip_days >= max(self.momentum_windows):
            raise ValueError("momentum_skip_days must be shorter than the longest momentum window")
        if self.step_years < self.test_years:
            raise ValueError("step_years must be >= test_years to avoid overlapping OOS windows")
        if not {63, 252}.issubset(self.momentum_windows):
            raise ValueError("momentum_windows must include 63 and 252 trading days")
        if max(self.momentum_windows) != 252 or self.momentum_skip_days != 21:
            raise ValueError("the baseline cross-sectional momentum contract requires 252-21")
        if not {21, 126}.issubset(self.volatility_windows):
            raise ValueError("volatility_windows must include 21 and 126 trading days")
        if any(window < 20 for window in self.trend_windows):
            raise ValueError("trend_windows must be at least 20 trading days")
        if 60 not in self.reer_windows_months:
            raise ValueError("reer_windows_months must include the preregistered 60-month value")
        return self

    @property
    def maximum_horizon(self) -> int:
        return max(self.horizons)


class LongHorizonConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: DataConfig
    external: LongHorizonExternalConfig = Field(default_factory=LongHorizonExternalConfig)
    research: LongHorizonSettings = Field(default_factory=LongHorizonSettings)

    @model_validator(mode="after")
    def validate_market_contract(self) -> LongHorizonConfig:
        if not self.data.symbols:
            raise ValueError("long-horizon research requires at least one FX pair")
        if self.research.research_mode == "cross_sectional" and len(self.data.symbols) < 3:
            raise ValueError(
                "cross-sectional long-horizon research requires at least three FX pairs"
            )
        if self.data.provider in {"oanda", "dukascopy"} and self.data.price_mode != "bid_ask":
            raise ValueError("execution-grade long-horizon data must use bid_ask prices")
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> LongHorizonConfig:
        with Path(path).open("r", encoding="utf-8") as handle:
            return cls.model_validate(yaml.safe_load(handle))
