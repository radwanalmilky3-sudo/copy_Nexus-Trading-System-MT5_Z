from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import CostConfig, DataConfig, RiskConfig


class PointInTimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    provider: Literal["csv", "synthetic"] = "csv"
    directory: Path = Path("data/point_in_time")
    currency_rates_file: str = "currency_rates.csv"
    forward_points_file: str = "forward_points.csv"
    positioning_enabled: bool = False
    currency_positioning_file: str = "currency_positioning.csv"
    positioning_release_quality: Literal["approximate", "verified"] = "approximate"
    allow_legacy_unverified_carry_rows: bool = False
    require_verified_carry_manifests: bool = False
    maximum_staleness_days: int = Field(45, ge=1, le=366)
    maximum_positioning_staleness_days: int = Field(14, ge=7, le=45)
    synthetic_seed: int = 42

    @model_validator(mode="after")
    def carry_source_contract(self) -> PointInTimeConfig:
        if self.require_verified_carry_manifests and self.provider != "csv":
            raise ValueError(
                "verified carry source manifests are available only for provider=csv"
            )
        if (
            self.require_verified_carry_manifests
            and self.allow_legacy_unverified_carry_rows
        ):
            raise ValueError(
                "verified carry source manifests cannot be combined with legacy carry rows"
            )
        return self


class FactorDiscoverySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    max_generated_factors: int = Field(40, ge=1, le=250)
    max_complexity: int = Field(2, ge=1, le=3)
    windows: list[int] = Field(default_factory=lambda: [5, 20, 60])
    unary_operators: list[str] = Field(
        default_factory=lambda: ["delta", "ts_zscore", "ts_mean", "ts_std"]
    )
    include_cross_sectional_rank: bool = True
    include_regime_interactions: bool = True
    primitive_factors: list[str] = Field(
        default_factory=lambda: [
            "momentum_1",
            "momentum_12",
            "return_skew_24",
            "efficiency_24",
            "atr_percent",
            "spread_atr",
            "rate_differential",
            "forward_discount_1m",
            "carry_to_vol_20",
            "cftc_leveraged_net",
            "cftc_asset_manager_net",
            "cftc_leveraged_change_4w",
        ]
    )

    @field_validator("windows")
    @classmethod
    def valid_windows(cls, values: list[int]) -> list[int]:
        if not values or any(value < 2 or value > 252 for value in values):
            raise ValueError("discovery.windows must contain values between 2 and 252")
        return sorted(set(values))

    @field_validator("unary_operators")
    @classmethod
    def valid_operators(cls, values: list[str]) -> list[str]:
        allowed = {"delta", "ts_zscore", "ts_mean", "ts_std"}
        invalid = set(values) - allowed
        if invalid:
            raise ValueError(f"Unsupported discovery operators: {sorted(invalid)}")
        return list(dict.fromkeys(values))


class FactorSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_atr: float = Field(0.70, gt=0)
    stop_atr: float = Field(1.10, gt=0)
    max_holding_hours: int = Field(120, ge=1, le=168)
    train_bars: int = Field(1500, ge=250)
    test_bars: int = Field(400, ge=50)
    step_bars: int = Field(400, ge=50)
    embargo_bars: int = Field(5, ge=0, le=100)
    holdout_bars: int = Field(0, ge=0)
    minimum_train_samples: int = Field(5000, ge=500)
    minimum_expected_net_r: float = Field(0.03, ge=0, le=0.50)
    cost_buffer_r: float = Field(0.02, ge=0, le=0.50)
    minimum_direction_gap: float = Field(0.03, ge=0, le=0.50)
    max_signals_per_timestamp: int = Field(3, ge=1, le=20)
    max_features: int = Field(32, ge=5, le=100)
    maximum_feature_correlation: float = Field(0.90, ge=0.5, le=0.999)
    minimum_feature_coverage: float = Field(0.80, ge=0.5, le=1)
    bootstrap_samples: int = Field(500, ge=100, le=100_000)
    bootstrap_block_bars: int = Field(20, ge=2, le=250)
    factor_fdr_level: float = Field(0.10, gt=0, le=0.50)
    require_fdr_significance: bool = False
    cost_stress_multipliers: list[float] = Field(default_factory=lambda: [1.0, 1.5, 2.0])
    promotion_minimum_trades: int = Field(100, ge=20)
    promotion_minimum_positive_fold_fraction: float = Field(0.75, ge=0.5, le=1.0)
    promotion_minimum_profit_factor: float = Field(1.10, ge=1.0, le=3.0)
    promotion_required_stress_multiplier: float = Field(1.5, ge=1.0, le=5.0)
    minimum_broker_history_years: float = Field(8.0, ge=1.0, le=20.0)
    minimum_auxiliary_coverage: float = Field(0.80, ge=0.5, le=1.0)
    minimum_market_bar_coverage: float = Field(0.80, ge=0.5, le=1.0)
    minimum_cross_symbol_coverage: float = Field(0.90, ge=0.5, le=1.0)
    minimum_source_hour_coverage: float = Field(0.95, ge=0.5, le=1.0)
    maximum_market_gap_hours: int = Field(120, ge=24, le=336)
    freeze_minimum_selection_fraction: float = Field(0.75, ge=0.5, le=1.0)
    forward_minimum_days: int = Field(90, ge=30, le=366)
    minimum_forward_external_feature_coverage: float = Field(0.80, ge=0.5, le=1.0)
    model_c: float = Field(0.10, gt=0, le=100)
    model_l1_ratio: float = Field(0.15, ge=0, le=1)
    calibration_fraction: float = Field(0.20, ge=0.10, le=0.40)
    minimum_calibration_samples: int = Field(1000, ge=100)
    random_state: int = 42
    output_directory: Path = Path("outputs/factors")

    @model_validator(mode="after")
    def non_overlapping_test_windows(self) -> FactorSettings:
        if self.step_bars < self.test_bars:
            raise ValueError("factor.step_bars must be >= test_bars to avoid overlapping OOS folds")
        if 0 < self.holdout_bars < 50:
            raise ValueError("factor.holdout_bars must be zero or at least 50")
        if 1.0 not in self.cost_stress_multipliers:
            raise ValueError("factor.cost_stress_multipliers must include 1.0")
        if self.promotion_required_stress_multiplier not in self.cost_stress_multipliers:
            raise ValueError(
                "promotion_required_stress_multiplier must be included in cost_stress_multipliers"
            )
        return self

    @field_validator("cost_stress_multipliers")
    @classmethod
    def valid_cost_stress_multipliers(cls, values: list[float]) -> list[float]:
        if not values or any(value < 1 or value > 5 for value in values):
            raise ValueError("cost stress multipliers must be between 1 and 5")
        return sorted(set(values))

    @property
    def reward_risk(self) -> float:
        return self.target_atr / self.stop_atr


class FactorMiningConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: DataConfig
    costs: CostConfig = Field(default_factory=CostConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    factor: FactorSettings = Field(default_factory=FactorSettings)
    point_in_time: PointInTimeConfig = Field(default_factory=PointInTimeConfig)
    discovery: FactorDiscoverySettings = Field(default_factory=FactorDiscoverySettings)

    @model_validator(mode="after")
    def enforce_execution_limits(self) -> FactorMiningConfig:
        if self.data.provider in {"oanda", "dukascopy"} and self.data.price_mode != "bid_ask":
            raise ValueError(
                f"{self.data.provider.title()} factor data requires data.price_mode=bid_ask"
            )
        if self.factor.reward_risk > self.risk.max_reward_risk:
            raise ValueError("factor target/stop ratio exceeds risk.max_reward_risk")
        if self.factor.max_holding_hours > self.risk.max_holding_hours:
            raise ValueError("factor holding period exceeds risk.max_holding_hours")
        if self.risk.close_before_weekend:
            raise ValueError(
                "factor mining requires risk.close_before_weekend=false "
                "so labels and execution match"
            )
        if (
            self.point_in_time.positioning_enabled
            and self.point_in_time.positioning_release_quality == "verified"
        ):
            minimum_blocks = {"1h": 1560, "4h": 390, "1d": 65}
            if self.factor.bootstrap_block_bars < minimum_blocks[self.data.interval]:
                raise ValueError(
                    "verified weekly positioning requires a bootstrap block of at least "
                    "13 trading weeks"
                )
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> FactorMiningConfig:
        with Path(path).open("r", encoding="utf-8") as handle:
            return cls.model_validate(yaml.safe_load(handle))
