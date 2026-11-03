from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .enums import (
    ConfidenceValidation,
    DataOrigin,
    FreshnessState,
    FundamentalDomain,
    GoldDirection,
    HorizonClass,
    PredictionStage,
    ProviderHealth,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SourceEvidence(BaseModel):
    source_id: str
    source_name: str
    source_name_ar: str = ""
    source_url: str | None = None
    source_timestamp: datetime | None = None
    received_at: datetime = Field(default_factory=utcnow)
    origin: DataOrigin = DataOrigin.UNKNOWN
    freshness: FreshnessState = FreshnessState.UNAVAILABLE
    trust_score: float = Field(default=50.0, ge=0, le=100)
    quality_score: float = Field(default=0.0, ge=0, le=100)
    causal_group_id: str | None = None
    independence_group: str | None = None
    story_cluster_id: str | None = None
    is_reprint: bool = False


class FundamentalDriver(BaseModel):
    code: str
    label_ar: str
    label_en: str
    native_score: float = Field(default=0.0, ge=-100, le=100)
    gold_impact_score: float = Field(default=0.0, ge=-100, le=100)
    strength: float = Field(default=0.0, ge=0, le=100)
    confidence: float = Field(default=0.0, ge=0, le=100)
    explanation_ar: str = ""
    horizon_class: HorizonClass = HorizonClass.TACTICAL
    sources: list[SourceEvidence] = Field(default_factory=list)


class FundamentalFactorResult(BaseModel):
    domain: FundamentalDomain
    native_score: float = Field(ge=-100, le=100)
    gold_impact_score: float = Field(ge=-100, le=100)
    direction: GoldDirection
    strength: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=100)
    coverage_score: float = Field(ge=0, le=100)
    freshness_score: float = Field(ge=0, le=100)
    data_quality_score: float = Field(ge=0, le=100)
    reliability_score: float = Field(default=50.0, ge=0, le=100)
    horizon_class: HorizonClass
    primary_drivers: list[FundamentalDriver] = Field(default_factory=list)
    counter_drivers: list[FundamentalDriver] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utcnow)
    engine_version: str = "1.0.0"
    metadata: dict[str, Any] = Field(default_factory=dict)


class FusionWeight(BaseModel):
    domain: FundamentalDomain
    raw_gold_score: float = Field(ge=-100, le=100)
    base_weight: float = Field(ge=0, le=1)
    effective_weight: float = Field(ge=0, le=1)
    normalized_weight: float = Field(ge=0, le=1)
    freshness_factor: float = Field(ge=0, le=1)
    quality_factor: float = Field(ge=0, le=1)
    relevance_factor: float = Field(ge=0, le=1)
    reliability_factor: float = Field(ge=0, le=1)
    regime_factor: float = Field(ge=0, le=2)
    independence_factor: float = Field(ge=0, le=1)
    reason_ar: str


class FundamentalFusionResult(BaseModel):
    fusion_id: str
    symbol: str = "XAUUSD"
    event_id: str | None = None
    net_score: float = Field(ge=-100, le=100)
    direction: GoldDirection
    strength: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=100)
    coverage_score: float = Field(ge=0, le=100)
    agreement_score: float = Field(ge=0, le=100)
    conflict_score: float = Field(ge=0, le=100)
    freshness_score: float = Field(ge=0, le=100)
    data_quality_score: float = Field(ge=0, le=100)
    weights: list[FusionWeight]
    primary_drivers: list[FundamentalDriver] = Field(default_factory=list)
    counter_drivers: list[FundamentalDriver] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utcnow)
    fusion_version: str = "1.0.0"


class HorizonProbability(BaseModel):
    bullish: float = Field(ge=0, le=1)
    bearish: float = Field(ge=0, le=1)
    neutral: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def probabilities_sum(self) -> "HorizonProbability":
        total = self.bullish + self.bearish + self.neutral
        if abs(total - 1.0) > 0.02:
            raise ValueError("horizon probabilities must sum to ~1")
        return self


class GoldImpactResult(BaseModel):
    prediction_id: str
    symbol: str = "XAUUSD"
    event_id: str | None = None
    fusion_id: str | None = None
    stage: PredictionStage = PredictionStage.AT_RELEASE
    direction: GoldDirection
    strength: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=100)
    confidence_validation: ConfidenceValidation = ConfidenceValidation.UNVALIDATED
    coverage_score: float = Field(ge=0, le=100)
    conflict_score: float = Field(ge=0, le=100)
    freshness_score: float = Field(ge=0, le=100)
    data_quality_score: float = Field(ge=0, le=100)
    horizon_5m: HorizonProbability
    horizon_15m: HorizonProbability
    horizon_60m: HorizonProbability
    horizon_4h: HorizonProbability
    structural_bias: GoldDirection = GoldDirection.NEUTRAL
    primary_drivers: list[FundamentalDriver] = Field(default_factory=list)
    counter_drivers: list[FundamentalDriver] = Field(default_factory=list)
    confirmations_ar: list[str] = Field(default_factory=list)
    contradictions_ar: list[str] = Field(default_factory=list)
    weakening_factors_ar: list[str] = Field(default_factory=list)
    invalidation_conditions_ar: list[str] = Field(default_factory=list)
    transmission_chain_ar: list[str] = Field(default_factory=list)
    blackout_active: bool = False
    blackout_reason_ar: str | None = None
    generated_at: datetime = Field(default_factory=utcnow)
    model_version: str = "1.0.0"


class ArabicExplanation(BaseModel):
    prediction_id: str
    headline_ar: str
    what_happened_ar: str
    why_it_matters_ar: str
    transmission_to_gold_ar: str
    gold_effect_ar: str
    confirmations_ar: list[str] = Field(default_factory=list)
    contradictions_ar: list[str] = Field(default_factory=list)
    weakening_factors_ar: list[str] = Field(default_factory=list)
    invalidation_ar: list[str] = Field(default_factory=list)
    confidence_reason_ar: str
    horizon_ar: str
    actual_outcome_ar: str = "لم يتم تقييم النتيجة الفعلية بعد."
    lesson_ar: str = "لم تتوفر نتيجة كافية للتعلم بعد."
    simple_summary_ar: str
    advanced_summary_ar: str
    explanation_version: str = "1.0.0"


class SourceHealthDTO(BaseModel):
    source_id: str
    name_ar: str
    name_en: str
    health: ProviderHealth
    health_description_ar: str
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    latency_ms: float | None = None
    freshness: FreshnessState = FreshnessState.UNAVAILABLE
    origin: DataOrigin = DataOrigin.UNKNOWN
    records_received: int = 0
    records_accepted: int = 0
