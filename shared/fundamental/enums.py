from __future__ import annotations

from enum import StrEnum


class FundamentalDomain(StrEnum):
    MACRO = "macro"
    MONETARY = "monetary"
    CROSS_ASSET = "cross_asset"
    GEOPOLITICAL = "geopolitical"
    FLOWS = "flows"


class GoldDirection(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    CONFLICTED = "conflicted"


class DataOrigin(StrEnum):
    REAL = "real"
    PROXY = "proxy"
    SYNTHETIC = "synthetic"
    TEST = "test"
    UNKNOWN = "unknown"


class FreshnessState(StrEnum):
    LIVE = "live"
    FRESH = "fresh"
    STALE = "stale"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ProviderHealth(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    RATE_LIMITED = "rate_limited"
    CONFIG_REQUIRED = "config_required"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


class ImpactLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class HorizonClass(StrEnum):
    EVENT_SHOCK = "event_shock"
    TACTICAL = "tactical"
    STRUCTURAL = "structural"


class PredictionStage(StrEnum):
    PRE_EVENT = "pre_event"
    AT_RELEASE = "at_release"
    INITIAL_REACTION = "initial_reaction"
    CONFIRMATION = "confirmation"
    SECONDARY_REACTION = "secondary_reaction"
    REVERSED = "reversed"
    NORMALIZED = "normalized"


class ConfidenceValidation(StrEnum):
    CALIBRATED = "calibrated"
    PARTIAL = "partial"
    UNVALIDATED = "unvalidated"
