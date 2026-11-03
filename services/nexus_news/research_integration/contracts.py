"""Immutable news contracts; these objects never authorize trading."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping


class ImpactLevel(StrEnum):
    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class BlackoutWindow:
    starts_at: datetime
    ends_at: datetime
    reason: str
    source: str
    impact: ImpactLevel = ImpactLevel.UNKNOWN

    def __post_init__(self) -> None:
        start, end = _utc(self.starts_at, "starts_at"), _utc(self.ends_at, "ends_at")
        if end <= start:
            raise ValueError("ends_at must be after starts_at")
        if not self.reason.strip() or not self.source.strip():
            raise ValueError("reason and source are required")
        object.__setattr__(self, "starts_at", start)
        object.__setattr__(self, "ends_at", end)

    def active_at(self, at: datetime) -> bool:
        point = _utc(at, "at")
        return self.starts_at <= point < self.ends_at


@dataclass(frozen=True, slots=True)
class NewsEvent:
    """Canonical event with event time, availability, vintage, and provenance."""

    event_id: str
    title: str
    event_timestamp: datetime
    available_at: datetime
    vintage: datetime
    source: str
    confidence: float
    impact: ImpactLevel = ImpactLevel.UNKNOWN
    confirmed: bool = False
    blackout: BlackoutWindow | None = None
    currency: str = ""
    country: str = ""
    actual: float | None = None
    forecast: float | None = None
    previous: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_id.strip() or not self.title.strip() or not self.source.strip():
            raise ValueError("event_id, title, and source are required")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        object.__setattr__(self, "event_timestamp", _utc(self.event_timestamp, "event_timestamp"))
        object.__setattr__(self, "available_at", _utc(self.available_at, "available_at"))
        object.__setattr__(self, "vintage", _utc(self.vintage, "vintage"))
        object.__setattr__(self, "confidence", float(self.confidence))
        object.__setattr__(self, "currency", self.currency.strip().upper())
        object.__setattr__(self, "country", self.country.strip().upper())

    def available_at_decision(self, decision_time: datetime) -> bool:
        return self.available_at <= _utc(decision_time, "decision_time")

    def in_blackout(self, at: datetime) -> bool:
        return bool(self.blackout and self.blackout.active_at(at))

    @property
    def has_verified_provenance(self) -> bool:
        return bool(self.confirmed and self.source.strip() and self.confidence > 0.0)

    @property
    def directional_research_allowed(self) -> bool:
        return bool(self.has_verified_provenance and self.actual is not None and self.forecast is not None)

    @property
    def trade_allowed(self) -> bool:
        return False
