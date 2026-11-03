"""Contracts for research-only inputs and temporal provenance.

This module deliberately contains value objects only.  It does not fetch,
persist, publish, or authorize trading decisions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


class ResearchOnlyViolation(ValueError):
    """Raised when a research contract is asked to leave research scope."""


def _utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class BlackoutWindow:
    """A time interval in which research output must remain non-actionable."""

    starts_at: datetime
    ends_at: datetime
    reason: str
    source: str = "unknown"

    def __post_init__(self) -> None:
        start = _utc(self.starts_at, field="starts_at")
        end = _utc(self.ends_at, field="ends_at")
        if end <= start:
            raise ValueError("ends_at must be after starts_at")
        if not self.reason.strip():
            raise ValueError("reason must not be empty")
        object.__setattr__(self, "starts_at", start)
        object.__setattr__(self, "ends_at", end)

    def is_active(self, at: datetime) -> bool:
        point = _utc(at, field="at")
        return self.starts_at <= point < self.ends_at


@dataclass(frozen=True, slots=True)
class ResearchOnlyScope:
    """Explicit scope marker that cannot be used as a trading authorization."""

    research_only: bool = True

    def __post_init__(self) -> None:
        if self.research_only is not True:
            raise ResearchOnlyViolation("research contracts must remain research_only")

    def require_research_only(self) -> None:
        if self.research_only is not True:
            raise ResearchOnlyViolation("research-only scope was removed")


@dataclass(frozen=True, slots=True)
class ResearchSnapshot:
    """A source-neutral research value with publication and vintage metadata."""

    payload: Mapping[str, Any]
    available_at: datetime
    vintage: datetime
    scope: ResearchOnlyScope = ResearchOnlyScope()
    blackout: BlackoutWindow | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.payload, Mapping):
            raise TypeError("payload must be a mapping")
        object.__setattr__(self, "available_at", _utc(self.available_at, field="available_at"))
        object.__setattr__(self, "vintage", _utc(self.vintage, field="vintage"))
        self.scope.require_research_only()

    def is_blackout(self, at: datetime | None = None) -> bool:
        if self.blackout is None:
            return False
        return self.blackout.is_active(at or datetime.now(timezone.utc))
