"""Pure economic-calendar normalization; no I/O or execution dependencies."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .contracts import BlackoutWindow, ImpactLevel, NewsEvent

UTC = timezone.utc


def _get(record: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(record, Mapping) and name in record:
            return record[name]
        if hasattr(record, name):
            return getattr(record, name)
    return default


def _dt(value: Any, name: str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime or ISO-8601 string")
    return value.astimezone(UTC)


def parse_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text or text.lower() in {"-", "n/a", "na", "null"}:
        return None
    multiplier = {"K": 1_000.0, "M": 1_000_000.0, "B": 1_000_000_000.0}.get(text[-1:].upper(), 1.0)
    if multiplier != 1.0:
        text = text[:-1]
    text = text.replace("%", "").strip()
    try:
        return float(text) * multiplier
    except ValueError:
        match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
        return float(match.group(0)) * multiplier if match else None


def _impact(value: Any) -> ImpactLevel:
    value = {"moderate": "medium", "major": "high", "severe": "critical"}.get(str(value or "").lower(), str(value or "").lower())
    try:
        return ImpactLevel(value)
    except ValueError:
        return ImpactLevel.UNKNOWN


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "verified", "confirmed", "released"}


def _event_id(title: str, timestamp: datetime, source: str, currency: str) -> str:
    raw = "|".join((source, currency, title.lower().strip(), timestamp.isoformat()))
    return "news-" + hashlib.sha256(raw.encode()).hexdigest()[:24]


class EconomicCalendarNormalizer:
    """Normalize a loaded mapping or CalendarEvent-like object."""

    def __init__(self, *, default_source: str = "unknown") -> None:
        self.default_source = default_source.strip() or "unknown"

    def normalize(self, record: Mapping[str, Any] | Any, *, retrieved_at: datetime | None = None,
                  source: str | None = None) -> NewsEvent:
        raw_event_time = _get(record, "event_timestamp", "timestamp", "release_timestamp", "scheduled_at")
        if raw_event_time is None:
            raise ValueError("calendar record requires event timestamp")
        event_time = _dt(raw_event_time, "event_timestamp")

        raw_available = _get(record, "available_at", "received_at", "published_at", "retrieved_at")
        available = _dt(raw_available or retrieved_at or event_time, "available_at")
        raw_vintage = _get(record, "vintage", "vintage_at")
        vintage = _dt(raw_vintage, "vintage") if raw_vintage is not None else available

        title = str(_get(record, "title", "event_name", "headline", default="")).strip()
        if not title:
            raise ValueError("calendar record requires title/event_name")
        source_name = str(source or _get(record, "source", "source_name", "provider", default=self.default_source) or self.default_source).strip()
        currency = str(_get(record, "currency", "country", default="") or "").strip().upper()
        country = str(_get(record, "country", default="") or "").strip().upper()
        impact = _impact(_get(record, "impact", "declared_impact", default="unknown"))
        actual, forecast = parse_number(_get(record, "actual")), parse_number(_get(record, "forecast", "consensus", "median"))
        previous = parse_number(_get(record, "previous"))
        confidence = parse_number(_get(record, "confidence", "trust_score", "quality_score", default=0.0)) or 0.0
        confirmed = _truthy(_get(record, "confirmed", "is_confirmed", "verified", "status"))
        event_id = str(_get(record, "event_id", "id", default="") or "").strip() or _event_id(title, event_time, source_name, currency)

        blackout_raw = _get(record, "blackout")
        if isinstance(blackout_raw, Mapping):
            blackout = BlackoutWindow(
                _dt(blackout_raw["starts_at"], "blackout.starts_at"),
                _dt(blackout_raw["ends_at"], "blackout.ends_at"),
                str(blackout_raw.get("reason", title)),
                str(blackout_raw.get("source", source_name)),
                _impact(blackout_raw.get("impact", impact.value)),
            )
        elif impact in {ImpactLevel.HIGH, ImpactLevel.CRITICAL}:
            blackout = BlackoutWindow(
                event_time - timedelta(minutes=30), event_time + timedelta(minutes=60),
                f"scheduled {impact.value}-impact event: {title}", source_name, impact,
            )
        else:
            blackout = None

        return NewsEvent(
            event_id=event_id, title=title, event_timestamp=event_time,
            available_at=available, vintage=vintage, source=source_name or self.default_source,
            confidence=max(0.0, min(1.0, confidence)), impact=impact, confirmed=confirmed,
            blackout=blackout, currency=currency, country=country, actual=actual,
            forecast=forecast, previous=previous,
            metadata={"normalization": "economic_calendar_v1", "source_confirmed": confirmed},
        )


def normalize_calendar_event(record: Mapping[str, Any] | Any, *, retrieved_at: datetime | None = None,
                             source: str | None = None) -> NewsEvent:
    return EconomicCalendarNormalizer(default_source=source or "unknown").normalize(
        record, retrieved_at=retrieved_at, source=source,
    )


__all__ = ["EconomicCalendarNormalizer", "normalize_calendar_event", "parse_number"]
