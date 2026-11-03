"""Point-in-time event-window features for research only."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from .contracts import ImpactLevel, NewsEvent


@dataclass(frozen=True, slots=True)
class WindowSpec:
    name: str
    before: timedelta = timedelta(minutes=30)
    after: timedelta = timedelta(minutes=60)

    def __post_init__(self) -> None:
        if not self.name.strip() or self.before < timedelta(0) or self.after < timedelta(0):
            raise ValueError("invalid event window")


@dataclass(frozen=True, slots=True)
class EventWindowFeatures:
    event_id: str
    decision_time: datetime
    window_name: str
    point_in_time_available: bool
    event_known: bool
    in_pre_window: bool
    in_post_window: bool
    in_blackout: bool
    minutes_to_event: float | None
    event_age_seconds: float | None
    impact: str
    confidence: float
    confirmed: bool
    surprise: float | None
    directional_research_allowed: bool
    trade_allowed: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id, "decision_time": self.decision_time.isoformat(),
            "window_name": self.window_name, "point_in_time_available": self.point_in_time_available,
            "event_known": self.event_known, "in_pre_window": self.in_pre_window,
            "in_post_window": self.in_post_window, "in_blackout": self.in_blackout,
            "minutes_to_event": self.minutes_to_event, "event_age_seconds": self.event_age_seconds,
            "impact": self.impact, "confidence": self.confidence, "confirmed": self.confirmed,
            "surprise": self.surprise, "directional_research_allowed": self.directional_research_allowed,
            "trade_allowed": False,
        }


def build_event_window_features(event: NewsEvent, decision_time: datetime, *,
                                spec: WindowSpec = WindowSpec("default")) -> EventWindowFeatures:
    if decision_time.tzinfo is None or decision_time.utcoffset() is None:
        raise ValueError("decision_time must be timezone-aware")
    decision = decision_time.astimezone(timezone.utc)
    available = event.available_at_decision(decision)
    delta = event.event_timestamp - decision
    pre = available and event.event_timestamp - spec.before <= decision < event.event_timestamp
    post = available and event.event_timestamp <= decision <= event.event_timestamp + spec.after
    surprise = event.actual - event.forecast if available and event.actual is not None and event.forecast is not None else None
    return EventWindowFeatures(
        event_id=event.event_id, decision_time=decision, window_name=spec.name,
        point_in_time_available=available, event_known=available, in_pre_window=pre,
        in_post_window=post, in_blackout=available and event.in_blackout(decision),
        minutes_to_event=delta.total_seconds() / 60.0 if available else None,
        event_age_seconds=(decision - event.event_timestamp).total_seconds() if available else None,
        impact=event.impact.value if isinstance(event.impact, ImpactLevel) else str(event.impact),
        confidence=event.confidence if available else 0.0,
        confirmed=event.confirmed if available else False, surprise=surprise,
        directional_research_allowed=available and event.directional_research_allowed,
        trade_allowed=False,
    )


def build_event_windows(events: Iterable[NewsEvent], decision_time: datetime, *,
                        spec: WindowSpec = WindowSpec("default")) -> tuple[EventWindowFeatures, ...]:
    return tuple(build_event_window_features(event, decision_time, spec=spec) for event in events)


__all__ = ["EventWindowFeatures", "WindowSpec", "build_event_window_features", "build_event_windows"]
