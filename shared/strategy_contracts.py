"""Contracts for strategy research and backtest provenance.

This module is declarative only.  It does not load market data, start a
service, place orders, or execute a backtest.  The contracts intentionally
keep selection, point-in-time eligibility, execution costs, and out-of-sample
evidence explicit so future runners cannot silently downgrade them.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SCHEMA_VERSION = "1.0"
Timestamp = datetime
Scalar = bool | float | int | str


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class ContractModel(BaseModel):
    """Common strict model settings for strategy research artifacts."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    schema_version: str = SCHEMA_VERSION


class StrategyFamily(StrEnum):
    TREND = "trend"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"
    MULTICURRENCY = "multicurrency"
    ENSEMBLE = "ensemble"
    CUSTOM = "custom"


class SignalTiming(StrEnum):
    CLOSE_OF_BAR = "close_of_bar"
    NEXT_BAR_OPEN = "next_bar_open"


class ParameterSelectionScope(StrEnum):
    TRAIN_ONLY = "train_only"
    TRAIN_VALIDATION_ONLY = "train_validation_only"
    FROZEN = "frozen"


class BacktestStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    REJECTED = "rejected"


class BenchmarkKind(StrEnum):
    FLAT = "flat"
    BUY_AND_HOLD = "buy_and_hold"
    RISK_FREE = "risk_free"
    CUSTOM = "custom"


class NewsHookAction(StrEnum):
    BLOCK_ENTRIES = "block_entries"
    TAG_REGIME = "tag_regime"
    SCALE_EXPOSURE = "scale_exposure"


class CostQuality(StrEnum):
    BROKER_HISTORICAL = "broker_historical"
    BROKER_SNAPSHOT = "broker_snapshot"
    RESEARCH_FIXTURE = "research_fixture"
    UNKNOWN_UNVERIFIED = "unknown_unverified"


class PointInTimeReference(ContractModel):
    """One source value and the earliest time it was eligible for use."""

    source_id: str = Field(min_length=1)
    observation_time: Timestamp
    available_time: Timestamp
    vintage_id: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    as_of_key: str = Field(min_length=1)
    source_version: str = ""

    _observation_aware = field_validator("observation_time")(
        lambda value: _aware(value, "observation_time")
    )
    _available_aware = field_validator("available_time")(
        lambda value: _aware(value, "available_time")
    )

    @model_validator(mode="after")
    def validate_order(self) -> "PointInTimeReference":
        if self.available_time < self.observation_time:
            raise ValueError("available_time cannot precede observation_time")
        return self


class AntiLeakageContract(ContractModel):
    """Fail-closed rules for feature, label, and split eligibility."""

    pit: bool = Field(default=True, alias="PIT")
    pit_required: bool = True
    decision_time_field: str = "decision_time"
    available_time_field: str = "available_time"
    observation_time_field: str = "observation_time"
    vintage_id_field: str = "vintage_id"
    content_hash_field: str = "content_hash"
    label_horizon_bars: int = Field(default=1, ge=1)
    purge_bars: int = Field(default=0, ge=0)
    embargo_bars: int = Field(default=0, ge=0)
    allowed_lookahead_bars: int = Field(default=0, ge=0)
    require_vintage_id: bool = True
    require_content_hash: bool = True
    allow_revised_values: bool = False
    future_data_policy: Literal["fail_closed", "record_violation"] = "fail_closed"
    train_test_overlap_forbidden: bool = True

    @model_validator(mode="after")
    def validate_no_lookahead(self) -> "AntiLeakageContract":
        if self.pit_required and not self.pit:
            raise ValueError("pit must remain true when pit_required is enabled")
        if self.pit_required and self.allowed_lookahead_bars != 0:
            raise ValueError("PIT contracts cannot allow lookahead bars")
        return self


class CostModel(ContractModel):
    """Broker-aware cost assumptions used by a research run."""

    cost_currency: str = Field(default="USD", min_length=3, max_length=3)
    spread_pips: float = Field(default=0.0, ge=0.0)
    slippage_pips: float = Field(default=0.0, ge=0.0)
    slippage_stress_multiplier: float = Field(default=1.0, ge=0.0)
    commission_per_million: float = Field(default=0.0, ge=0.0)
    commission_per_lot: float = Field(default=0.0, ge=0.0)
    fixed_commission: float = Field(default=0.0, ge=0.0)
    financing_long_pips_per_day: float = 0.0
    financing_short_pips_per_day: float = 0.0
    triple_swap_weekday: int | None = Field(default=None, ge=0, le=6)
    source_quality: CostQuality = CostQuality.UNKNOWN_UNVERIFIED
    source_id: str = ""
    source_version: str = ""
    source_manifest_hash: str = ""
    available_time: Timestamp | None = None
    mid_only_input: bool = False
    formal_net_returns_eligible: bool = False

    _currency_upper = field_validator("cost_currency")(
        lambda value: value.upper()
    )

    @field_validator("available_time")
    @classmethod
    def available_time_aware(cls, value: Timestamp | None) -> Timestamp | None:
        return _aware(value, "available_time") if value is not None else None


class StrategyDefinition(ContractModel):
    """Versioned, non-executable description of a strategy."""

    strategy_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    family: StrategyFamily
    description: str = ""
    symbols: tuple[str, ...] = ()
    timeframes: tuple[str, ...] = ()
    required_columns: tuple[str, ...] = ("open", "high", "low", "close")
    feature_names: tuple[str, ...] = ()
    entry_rule: str = Field(min_length=1)
    exit_rule: str = Field(min_length=1)
    signal_timing: SignalTiming = SignalTiming.CLOSE_OF_BAR
    execution_timing: SignalTiming = SignalTiming.NEXT_BAR_OPEN
    parameter_set_id: str = Field(min_length=1)
    regime_labels: tuple[str, ...] = ()
    news_regime_hook_ids: tuple[str, ...] = ()
    code_version: str = ""
    code_hash: str = ""
    approved_for_trading: bool = False

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(value.upper().replace("/", "") for value in values)

    @model_validator(mode="after")
    def require_next_bar_execution(self) -> "StrategyDefinition":
        if self.signal_timing == SignalTiming.CLOSE_OF_BAR and self.execution_timing != SignalTiming.NEXT_BAR_OPEN:
            raise ValueError("close-of-bar signals must execute at next_bar_open")
        if self.approved_for_trading:
            raise ValueError("strategy contracts cannot grant trading approval")
        return self


class ParameterSet(ContractModel):
    """Frozen parameters selected without observing the future test window."""

    parameter_set_id: str = Field(min_length=1)
    strategy_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    parameters: dict[str, Scalar] = Field(default_factory=dict)
    selection_scope: ParameterSelectionScope = ParameterSelectionScope.TRAIN_ONLY
    selected_in_run_id: str = Field(min_length=1)
    frozen_at: Timestamp | None = None
    selection_metric: str = Field(min_length=1)
    selection_score: float | None = None
    candidate_count: int = Field(default=1, ge=1)

    @field_validator("frozen_at")
    @classmethod
    def frozen_at_aware(cls, value: Timestamp | None) -> Timestamp | None:
        return _aware(value, "frozen_at") if value is not None else None


class WalkForwardSpec(ContractModel):
    """Rolling/expanding train, validation, purge, embargo, and OOS rules."""

    train_bars: int = Field(default=1200, ge=1)
    validation_bars: int = Field(default=0, ge=0)
    test_bars: int = Field(default=400, ge=1)
    step_bars: int = Field(default=400, ge=1)
    warmup_bars: int = Field(default=250, ge=0)
    purge_bars: int = Field(default=0, ge=0)
    embargo_bars: int = Field(default=0, ge=0)
    top_k: int = Field(default=1, ge=1)
    expanding_train: bool = False
    selection_metric: str = Field(default="net_sharpe", min_length=1)
    require_unseen_test_window: bool = True

    @model_validator(mode="after")
    def validate_step(self) -> "WalkForwardSpec":
        if self.step_bars > self.test_bars:
            raise ValueError("step_bars cannot exceed test_bars without an explicit gap policy")
        return self


class OutOfSampleWindow(ContractModel):
    """One auditable train/validation/test window."""

    fold: int = Field(ge=1)
    train_start: Timestamp
    train_end: Timestamp
    validation_start: Timestamp | None = None
    validation_end: Timestamp | None = None
    purge_start: Timestamp | None = None
    purge_end: Timestamp | None = None
    embargo_start: Timestamp | None = None
    embargo_end: Timestamp | None = None
    test_start: Timestamp
    test_end: Timestamp
    warmup_start: Timestamp | None = None
    is_out_of_sample: bool = True

    @field_validator(
        "train_start",
        "train_end",
        "validation_start",
        "validation_end",
        "purge_start",
        "purge_end",
        "embargo_start",
        "embargo_end",
        "test_start",
        "test_end",
        "warmup_start",
    )
    @classmethod
    def timestamps_aware(cls, value: Timestamp | None) -> Timestamp | None:
        return _aware(value, "window timestamp") if value is not None else None

    @model_validator(mode="after")
    def validate_window_order(self) -> "OutOfSampleWindow":
        if self.train_end >= self.test_start:
            raise ValueError("train window must end before test window")
        if self.validation_start is not None and self.validation_end is not None:
            if self.validation_start <= self.train_end or self.validation_end >= self.test_start:
                raise ValueError("validation window must be between train and test")
        if self.test_start > self.test_end:
            raise ValueError("test_start must not exceed test_end")
        if not self.is_out_of_sample:
            raise ValueError("backtest windows must be explicitly out-of-sample")
        return self


class NewsRegimeHook(ContractModel):
    """A declared, PIT-aware bridge from news/calendar events to strategy policy."""

    hook_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    action: NewsHookAction
    impact_levels: tuple[str, ...] = ("high",)
    currencies: tuple[str, ...] = ()
    regime_label: str = "news_risk"
    pre_event_minutes: int = Field(default=0, ge=0)
    post_event_minutes: int = Field(default=0, ge=0)
    exposure_multiplier: float = Field(default=1.0, ge=0.0, le=1.0)
    use_scheduled_events: bool = False
    require_pit_available_time: bool = True
    source_ids: tuple[str, ...] = ()

    @field_validator("currencies")
    @classmethod
    def normalize_currencies(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(value.upper() for value in values)

    @model_validator(mode="after")
    def validate_action(self) -> "NewsRegimeHook":
        if self.action != NewsHookAction.SCALE_EXPOSURE and self.exposure_multiplier != 1.0:
            raise ValueError("exposure_multiplier only applies to scale_exposure hooks")
        return self


class NewsEvent(ContractModel):
    """Minimal event record consumed by news-regime hooks."""

    event_id: str = Field(min_length=1)
    event_time: Timestamp
    available_time: Timestamp
    impact: str = "low"
    currencies: tuple[str, ...] = ()
    regime_label: str = "news_risk"
    source_id: str = Field(min_length=1)
    vintage_id: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    scheduled: bool = False

    @field_validator("event_time", "available_time")
    @classmethod
    def event_times_aware(cls, value: Timestamp) -> Timestamp:
        return _aware(value, "news event timestamp")

    @field_validator("currencies")
    @classmethod
    def normalize_event_currencies(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(value.upper() for value in values)

    @model_validator(mode="after")
    def validate_event_order(self) -> "NewsEvent":
        if self.available_time > self.event_time and not self.scheduled:
            raise ValueError("unscheduled news cannot become available after its event time")
        return self


class NewsRegimeDecision(ContractModel):
    """Pure evaluation result for a news hook at a decision timestamp."""

    decision_time: Timestamp
    matched_event_ids: tuple[str, ...] = ()
    active_hook_ids: tuple[str, ...] = ()
    regime_labels: tuple[str, ...] = ()
    block_entries: bool = False
    exposure_multiplier: float = Field(default=1.0, ge=0.0, le=1.0)
    pit_eligible: bool = True

    _decision_aware = field_validator("decision_time")
    @classmethod
    def decision_time_aware(cls, value: Timestamp) -> Timestamp:
        return _aware(value, "decision_time")


class BacktestMetrics(ContractModel):
    """Net and gross performance metrics with explicit cost attribution."""

    total_return: float = 0.0
    annualized_return: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_duration_bars: int = Field(default=0, ge=0)
    total_trades: int = Field(default=0, ge=0)
    winning_trades: int = Field(default=0, ge=0)
    losing_trades: int = Field(default=0, ge=0)
    win_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    profit_factor: float = Field(default=0.0, ge=0.0)
    expectancy: float = 0.0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    spread_cost: float = Field(default=0.0, ge=0.0)
    slippage_cost: float = Field(default=0.0, ge=0.0)
    commission_cost: float = Field(default=0.0, ge=0.0)
    financing_cost: float = 0.0
    rejected_signals: int = Field(default=0, ge=0)
    oos: bool = True
    by_regime: dict[str, dict[str, float]] = Field(default_factory=dict)
    by_news_regime: dict[str, dict[str, float]] = Field(default_factory=dict)


class BenchmarkDefinition(ContractModel):
    """Comparable baseline using the same data window and cost disclosure."""

    benchmark_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: BenchmarkKind
    symbols: tuple[str, ...] = ()
    rule: str = Field(min_length=1)
    parameter_set_id: str | None = None
    cost_model_id: str = Field(min_length=1)
    data_snapshot_id: str = Field(min_length=1)
    pit_eligible: bool = True


class BacktestRun(ContractModel):
    """Complete manifest for one planned or completed strategy backtest."""

    run_id: str = Field(min_length=1)
    status: BacktestStatus = BacktestStatus.PLANNED
    strategy: StrategyDefinition
    parameter_set: ParameterSet
    data_snapshot_id: str = Field(min_length=1)
    point_in_time_references: tuple[PointInTimeReference, ...] = ()
    anti_leakage: AntiLeakageContract = Field(default_factory=AntiLeakageContract)
    cost_model: CostModel
    walk_forward: WalkForwardSpec
    out_of_sample_windows: tuple[OutOfSampleWindow, ...] = ()
    benchmarks: tuple[BenchmarkDefinition, ...] = ()
    news_hooks: tuple[NewsRegimeHook, ...] = ()
    metrics: BacktestMetrics | None = None
    created_at: Timestamp
    completed_at: Timestamp | None = None
    code_version: str = ""
    input_manifest_ids: tuple[str, ...] = ()
    execution_policy: Literal["next_bar_open"] = "next_bar_open"

    @field_validator("created_at", "completed_at")
    @classmethod
    def run_times_aware(cls, value: Timestamp | None) -> Timestamp | None:
        return _aware(value, "backtest run timestamp") if value is not None else None

    @model_validator(mode="after")
    def validate_run_consistency(self) -> "BacktestRun":
        if self.parameter_set.strategy_id != self.strategy.strategy_id:
            raise ValueError("parameter_set.strategy_id must match strategy.strategy_id")
        if self.parameter_set.parameter_set_id != self.strategy.parameter_set_id:
            raise ValueError("strategy.parameter_set_id must match parameter_set.parameter_set_id")
        if self.status == BacktestStatus.COMPLETED and self.metrics is None:
            raise ValueError("completed backtest runs require metrics")
        if self.completed_at is not None and self.completed_at < self.created_at:
            raise ValueError("completed_at cannot precede created_at")
        return self


class AntiLeakageAudit(ContractModel):
    """Recorded result of a future pure anti-leakage check."""

    audit_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    valid: bool
    checked_records: int = Field(default=0, ge=0)
    violations: tuple[str, ...] = ()
    checked_at: Timestamp
    decision_time: Timestamp

    @field_validator("checked_at", "decision_time")
    @classmethod
    def audit_times_aware(cls, value: Timestamp) -> Timestamp:
        return _aware(value, "anti-leakage audit timestamp")


__all__ = [
    "AntiLeakageAudit",
    "AntiLeakageContract",
    "BacktestMetrics",
    "BacktestRun",
    "BacktestStatus",
    "BenchmarkDefinition",
    "BenchmarkKind",
    "ContractModel",
    "CostModel",
    "CostQuality",
    "NewsEvent",
    "NewsHookAction",
    "NewsRegimeDecision",
    "NewsRegimeHook",
    "OutOfSampleWindow",
    "ParameterSelectionScope",
    "ParameterSet",
    "PointInTimeReference",
    "SCHEMA_VERSION",
    "SignalTiming",
    "StrategyDefinition",
    "StrategyFamily",
    "WalkForwardSpec",
]
