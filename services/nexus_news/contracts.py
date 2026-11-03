"""Read-only news contracts carrying provenance and blackout metadata."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


def _utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class NewsBlackout:
    """Calendar-derived interval exposed as research context only."""

    starts_at: datetime
    ends_at: datetime
    reason: str
    impact: str = "unknown"

    def __post_init__(self) -> None:
        start = _utc(self.starts_at, field="starts_at")
        end = _utc(self.ends_at, field="ends_at")
        if end <= start:
            raise ValueError("ends_at must be after starts_at")
        object.__setattr__(self, "starts_at", start)
        object.__setattr__(self, "ends_at", end)

    def active_at(self, at: datetime) -> bool:
        point = _utc(at, field="at")
        return self.starts_at <= point < self.ends_at


@dataclass(frozen=True, slots=True)
class ResearchNewsItem:
    """News item safe to pass to research consumers, never to execution."""

    payload: Mapping[str, Any]
    available_at: datetime
    vintage: datetime
    research_only: bool = True
    blackout: NewsBlackout | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.payload, Mapping):
            raise TypeError("payload must be a mapping")
        if self.research_only is not True:
            raise ValueError("news contracts must remain research_only")
        object.__setattr__(self, "available_at", _utc(self.available_at, field="available_at"))
        object.__setattr__(self, "vintage", _utc(self.vintage, field="vintage"))

    def is_blackout(self, at: datetime | None = None) -> bool:
        return bool(self.blackout and self.blackout.active_at(at or datetime.now(timezone.utc)))
