"""Civil-time templates for intraday FX events and sessions.

The definitions in this module deliberately do not contain a holiday calendar.
They convert a requested *local civil date* to UTC using IANA time-zone rules;
callers remain responsible for deciding whether that date is a trading day or
an event publication day.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from importlib import metadata
from pathlib import Path
from types import MappingProxyType
from typing import Final
from zoneinfo import TZPATH, ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class TzdbInfo:
    """Identify the time-zone database used for a calendar conversion."""

    source: str
    version: str | None

    @property
    def identifier(self) -> str:
        suffix = self.version or "version-unknown"
        return f"{self.source} ({suffix})"


@dataclass(frozen=True)
class EventWindow:
    """One event center and its half-open UTC measurement window."""

    name: str
    local_date: date
    timezone: str
    center_utc: datetime
    start_utc: datetime
    end_utc: datetime
    tzdb: TzdbInfo

    def __post_init__(self) -> None:
        _validate_utc(self.center_utc, "center_utc")
        _validate_utc(self.start_utc, "start_utc")
        _validate_utc(self.end_utc, "end_utc")
        if not self.start_utc < self.center_utc < self.end_utc:
            raise ValueError("event bounds must satisfy start < center < end")

    @property
    def duration(self) -> timedelta:
        return self.end_utc - self.start_utc


@dataclass(frozen=True)
class SessionWindow:
    """A half-open local-time session converted to UTC."""

    name: str
    local_date: date
    timezone: str
    start_utc: datetime
    end_utc: datetime
    tzdb: TzdbInfo

    def __post_init__(self) -> None:
        _validate_utc(self.start_utc, "start_utc")
        _validate_utc(self.end_utc, "end_utc")
        if self.start_utc >= self.end_utc:
            raise ValueError("session bounds must satisfy start < end")

    @property
    def duration(self) -> timedelta:
        return self.end_utc - self.start_utc


@dataclass(frozen=True)
class _EventDefinition:
    timezone: str
    local_time: time


@dataclass(frozen=True)
class _SessionDefinition:
    timezone: str
    start: time
    end: time


EVENT_WINDOW_HALF_WIDTH: Final = timedelta(minutes=2, seconds=30)

EVENT_DEFINITIONS: Final[Mapping[str, _EventDefinition]] = MappingProxyType(
    {
        "tokyo_fix": _EventDefinition("Asia/Tokyo", time(9, 55)),
        "ecb_fix": _EventDefinition("Europe/Berlin", time(14, 15)),
        "wmr_fix": _EventDefinition("Europe/London", time(16, 0)),
    }
)

SESSION_DEFINITIONS: Final[Mapping[str, _SessionDefinition]] = MappingProxyType(
    {
        "tokyo": _SessionDefinition("Asia/Tokyo", time(8, 0), time(15, 0)),
        "london": _SessionDefinition("Europe/London", time(7, 0), time(15, 0)),
        "new_york": _SessionDefinition("America/New_York", time(8, 0), time(16, 0)),
        "sydney": _SessionDefinition("Australia/Sydney", time(10, 0), time(16, 0)),
        "asia_formation": _SessionDefinition("Asia/Tokyo", time(8, 0), time(15, 0)),
        "london_response": _SessionDefinition(
            "Europe/London", time(7, 0), time(10, 0)
        ),
    }
)

FX_SESSION_TIMEZONE: Final = "America/New_York"
FX_SESSION_BOUNDARY: Final = time(17, 0)


def tzdb_info() -> TzdbInfo:
    """Return a reproducibility identifier for the active IANA database.

    ``zoneinfo`` searches the system ``TZPATH`` before falling back to Python's
    separately installed ``tzdata`` wheel, so the same order is used here.  A
    concrete search-path identifier is still returned on systems without a
    readable version header.
    """

    for root in map(Path, TZPATH):
        version_file = root / "tzdata.zi"
        try:
            first_line = version_file.open(encoding="utf-8").readline().strip()
        except OSError:
            continue
        marker = "# version "
        parsed = first_line[len(marker) :].strip() if first_line.startswith(marker) else None
        return TzdbInfo(source=f"system:{version_file}", version=parsed or None)

    try:
        version = metadata.version("tzdata")
    except metadata.PackageNotFoundError:
        version = None
    else:
        return TzdbInfo(source="python-package:tzdata", version=version)

    paths = ":".join(str(path) for path in TZPATH) or "stdlib-fallback"
    return TzdbInfo(source=f"zoneinfo-search-path:{paths}", version=version)


def event_window(name: str, local_date: date | datetime | str) -> EventWindow:
    """Build the frozen five-minute window around an FX benchmark event.

    The window is represented as ``[start_utc, end_utc)`` and centered on the
    named event.  ``local_date`` is interpreted in the event's own time zone.
    """

    definition = _lookup(EVENT_DEFINITIONS, name, "event")
    calendar_date = _coerce_date(local_date)
    center = _local_to_utc(calendar_date, definition.local_time, definition.timezone)
    return EventWindow(
        name=name,
        local_date=calendar_date,
        timezone=definition.timezone,
        center_utc=center,
        start_utc=center - EVENT_WINDOW_HALF_WIDTH,
        end_utc=center + EVENT_WINDOW_HALF_WIDTH,
        tzdb=tzdb_info(),
    )


def daily_event_windows(local_date: date | datetime | str) -> dict[str, EventWindow]:
    """Build all frozen benchmark windows for their respective local date."""

    return {name: event_window(name, local_date) for name in EVENT_DEFINITIONS}


def session_window(name: str, local_date: date | datetime | str) -> SessionWindow:
    """Build one frozen half-open session for its local civil date."""

    definition = _lookup(SESSION_DEFINITIONS, name, "session")
    calendar_date = _coerce_date(local_date)
    end_date = calendar_date
    if definition.end <= definition.start:
        end_date += timedelta(days=1)
    return SessionWindow(
        name=name,
        local_date=calendar_date,
        timezone=definition.timezone,
        start_utc=_local_to_utc(calendar_date, definition.start, definition.timezone),
        end_utc=_local_to_utc(end_date, definition.end, definition.timezone),
        tzdb=tzdb_info(),
    )


def daily_session_windows(local_date: date | datetime | str) -> dict[str, SessionWindow]:
    """Build all frozen session templates for their respective local date."""

    return {name: session_window(name, local_date) for name in SESSION_DEFINITIONS}


def fx_session_boundary(local_date: date | datetime | str) -> datetime:
    """Return the 17:00 New York FX boundary occurring on ``local_date`` in UTC."""

    return _local_to_utc(
        _coerce_date(local_date), FX_SESSION_BOUNDARY, FX_SESSION_TIMEZONE
    )


def fx_session_bounds(local_date: date | datetime | str) -> SessionWindow:
    """Return consecutive New York 17:00 boundaries beginning on ``local_date``.

    The elapsed UTC duration can be 23 or 25 hours across US daylight-saving
    transitions.  This is expected and is why the two boundaries are localized
    independently rather than adding 24 elapsed hours.
    """

    calendar_date = _coerce_date(local_date)
    return SessionWindow(
        name="fx_session",
        local_date=calendar_date,
        timezone=FX_SESSION_TIMEZONE,
        start_utc=fx_session_boundary(calendar_date),
        end_utc=fx_session_boundary(calendar_date + timedelta(days=1)),
        tzdb=tzdb_info(),
    )


def _coerce_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"local_date must be an ISO date, got {value!r}") from exc
    raise TypeError("local_date must be a date, datetime, or ISO date string")


def _lookup(definitions: Mapping[str, object], name: str, kind: str):
    try:
        return definitions[name]
    except KeyError as exc:
        allowed = ", ".join(definitions)
        raise ValueError(f"unknown {kind} {name!r}; expected one of: {allowed}") from exc


def _zone(timezone: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"IANA time zone is unavailable: {timezone}") from exc


def _local_to_utc(calendar_date: date, local_time: time, timezone: str) -> datetime:
    """Strictly localize one civil time and convert it to UTC.

    Localizing each endpoint independently preserves DST behavior.  A generic
    caller cannot silently choose a side of an ambiguous wall time or normalize
    a nonexistent one; both conditions are rejected.
    """

    if local_time.tzinfo is not None:
        raise ValueError("local_time must be timezone-naive")
    naive = datetime.combine(calendar_date, local_time)
    zone = _zone(timezone)
    candidates: dict[datetime, datetime] = {}
    for fold in (0, 1):
        localized = naive.replace(tzinfo=zone, fold=fold)
        utc_value = localized.astimezone(UTC)
        round_trip = utc_value.astimezone(zone).replace(tzinfo=None)
        if round_trip == naive:
            candidates[utc_value] = localized
    if not candidates:
        raise ValueError(f"nonexistent local time {naive.isoformat()} in {timezone}")
    if len(candidates) > 1:
        raise ValueError(f"ambiguous local time {naive.isoformat()} in {timezone}")
    return next(iter(candidates)).astimezone(UTC)


def _validate_utc(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must be timezone-aware UTC")


__all__ = [
    "EVENT_DEFINITIONS",
    "EVENT_WINDOW_HALF_WIDTH",
    "FX_SESSION_BOUNDARY",
    "FX_SESSION_TIMEZONE",
    "SESSION_DEFINITIONS",
    "EventWindow",
    "SessionWindow",
    "TzdbInfo",
    "daily_event_windows",
    "daily_session_windows",
    "event_window",
    "fx_session_boundary",
    "fx_session_bounds",
    "session_window",
    "tzdb_info",
]
