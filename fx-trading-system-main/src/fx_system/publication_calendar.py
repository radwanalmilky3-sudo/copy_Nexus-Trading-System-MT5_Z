"""Fail-closed CSV contract for externally verified FX event calendars.

This module does not infer holidays, weekdays, or publication dates.  Every
event date used by an experiment must be present in an external calendar, and
the calendar must say explicitly whether the event was published.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Final, Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fx_system.intraday_calendar import EVENT_DEFINITIONS

EventStatus = Literal["published", "not_published", "early_time"]
CalendarQuality = Literal["verified", "unverified"]

CALENDAR_COLUMNS: Final[tuple[str, ...]] = (
    "event_name",
    "local_date",
    "status",
    "local_time",
    "timezone",
    "source_url",
    "quality",
    "retrieved_at",
)
EVENT_STATUSES: Final[frozenset[str]] = frozenset({"published", "not_published", "early_time"})
CALENDAR_QUALITIES: Final[frozenset[str]] = frozenset({"verified", "unverified"})
_TIME_PATTERN: Final = re.compile(r"[0-2][0-9]:[0-5][0-9]")


class PublicationCalendarError(ValueError):
    """Raised when an external calendar cannot be used without guessing."""


class PublicationManifestError(PublicationCalendarError):
    """Raised when a calendar's source manifest or raw evidence is invalid."""


@dataclass(frozen=True)
class PublicationEvent:
    """One explicit event-calendar row converted from local civil time to UTC."""

    event_name: str
    local_date: date
    status: EventStatus
    local_time: time
    timezone: str
    source_url: str
    quality: CalendarQuality
    retrieved_at: datetime
    scheduled_time_utc: datetime

    @property
    def was_published(self) -> bool:
        """Whether an event actually occurred, including an early publication."""

        return self.status in {"published", "early_time"}

    @property
    def event_time_utc(self) -> datetime | None:
        """Actual event time, or ``None`` when the source says it was not published."""

        return self.scheduled_time_utc if self.was_published else None


@dataclass(frozen=True)
class PublicationCalendar:
    """Validated external calendar with exact-key, fail-closed lookup methods."""

    events: tuple[PublicationEvent, ...]
    knowledge_cutoff: datetime
    formal_experiment: bool
    manifest_verified: bool = False
    calendar_sha256: str | None = None
    manifest_path: Path | None = None

    def event_on(self, event_name: str, local_date: date | str) -> PublicationEvent:
        """Return an explicitly recorded row; never synthesize a weekday fallback."""

        calendar_date = _parse_local_date(local_date, field="lookup local_date")
        matches = [
            event
            for event in self.events
            if event.event_name == event_name and event.local_date == calendar_date
        ]
        if not matches:
            raise PublicationCalendarError(
                f"calendar has no explicit {event_name!r} row for {calendar_date.isoformat()}; "
                "weekday or holiday inference is forbidden"
            )
        if len(matches) != 1:  # Defensive: the loader already rejects this.
            raise PublicationCalendarError(
                f"calendar has ambiguous duplicate rows for {event_name!r} on "
                f"{calendar_date.isoformat()}"
            )
        return matches[0]

    def published_event_on(self, event_name: str, local_date: date | str) -> PublicationEvent:
        """Return an actual event, rejecting an explicit ``not_published`` row."""

        event = self.event_on(event_name, local_date)
        if not event.was_published:
            raise PublicationCalendarError(
                f"{event_name!r} was explicitly not published on {event.local_date.isoformat()}"
            )
        return event

    def actual_wmr_month_end(self, year: int, month: int) -> PublicationEvent:
        """Return the month's last verified WMR publication in the supplied calendar.

        ``early_time`` rows count as publications and retain their explicit local
        time.  No business-day or holiday calendar is consulted.
        """

        try:
            date(year, month, 1)
        except (TypeError, ValueError) as exc:
            raise PublicationCalendarError("year/month do not form a calendar month") from exc
        month_events = [
            event
            for event in self.events
            if event.event_name == "wmr_fix"
            and event.local_date.year == year
            and event.local_date.month == month
        ]
        expected_dates = {
            date(year, month, day)
            for day in range(1, monthrange(year, month)[1] + 1)
        }
        recorded_dates = {event.local_date for event in month_events}
        missing_dates = sorted(expected_dates - recorded_dates)
        if missing_dates:
            preview = ", ".join(value.isoformat() for value in missing_dates[:3])
            raise PublicationCalendarError(
                f"WMR calendar coverage for {year:04d}-{month:02d} is incomplete; "
                f"missing explicit published/not_published rows starting with {preview}"
            )
        candidates = [
            event
            for event in month_events
            if event.was_published
            and event.quality == "verified"
        ]
        if not candidates:
            raise PublicationCalendarError(
                f"calendar has no verified published WMR event for {year:04d}-{month:02d}; "
                "month-end cannot be guessed"
            )
        return max(candidates, key=lambda event: event.local_date)


def load_publication_calendar(
    path: str | Path | None,
    *,
    knowledge_cutoff: datetime | str,
    formal_experiment: bool = True,
    manifest_path: str | Path | None = None,
    require_manifest: bool = False,
) -> PublicationCalendar:
    """Load and validate an external event calendar.

    ``knowledge_cutoff`` is the latest retrieval timestamp admissible to the
    experiment.  A row retrieved after it is future information and invalidates
    the whole input.  Formal experiments reject every unverified row.
    """

    calendar_path = _require_calendar_file(path)
    cutoff = _parse_aware_datetime(knowledge_cutoff, field="knowledge_cutoff")
    with calendar_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, strict=True)
        _validate_header(reader.fieldnames)
        try:
            rows = list(reader)
        except csv.Error as exc:
            raise PublicationCalendarError(
                f"malformed publication calendar CSV near line {reader.line_num}"
            ) from exc
    if not rows:
        raise PublicationCalendarError("publication calendar cannot be empty")

    events: list[PublicationEvent] = []
    keys: set[tuple[str, date]] = set()
    for line_number, row in enumerate(rows, start=2):
        event = _parse_row(
            row,
            line_number=line_number,
            knowledge_cutoff=cutoff,
            formal_experiment=formal_experiment,
        )
        key = (event.event_name, event.local_date)
        if key in keys:
            raise PublicationCalendarError(
                f"line {line_number}: duplicate/ambiguous event key "
                f"{event.event_name!r}, {event.local_date.isoformat()}"
            )
        keys.add(key)
        events.append(event)

    events.sort(key=lambda event: (event.local_date, event.event_name))
    calendar_hash = _sha256_file(calendar_path)
    verified_manifest_path: Path | None = None
    manifest_verified = False
    if manifest_path is not None:
        verified_manifest_path = Path(manifest_path)
        _verify_publication_manifest(
            calendar_path,
            verified_manifest_path,
            calendar_hash=calendar_hash,
            event_source_urls={event.source_url for event in events},
        )
        manifest_verified = True
    elif require_manifest:
        raise PublicationManifestError(
            "a verified publication-calendar source manifest is required"
        )
    return PublicationCalendar(
        tuple(events),
        cutoff,
        formal_experiment,
        manifest_verified=manifest_verified,
        calendar_sha256=calendar_hash,
        manifest_path=verified_manifest_path,
    )


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_publication_manifest(
    calendar_path: Path,
    manifest_path: Path,
    *,
    calendar_hash: str,
    event_source_urls: set[str],
) -> None:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PublicationManifestError(
            f"cannot read publication-calendar manifest: {manifest_path}"
        ) from error
    if not isinstance(payload, dict):
        raise PublicationManifestError("publication-calendar manifest must be an object")
    expected = {
        "schema_version": 1,
        "dataset_kind": "benchmark_publication_calendar",
        "calendar_file": calendar_path.name,
        "calendar_sha256": calendar_hash,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise PublicationManifestError(
                f"publication-calendar manifest {key} does not match {value!r}"
            )
    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        raise PublicationManifestError("publication-calendar manifest sources are missing")
    manifest_root = manifest_path.resolve().parent
    catalog_urls: set[str] = set()
    for position, source in enumerate(sources):
        if not isinstance(source, dict):
            raise PublicationManifestError(f"manifest source {position} must be an object")
        url = source.get("url")
        raw_path_value = source.get("raw_path")
        raw_hash = source.get("raw_sha256")
        if (
            not isinstance(url, str)
            or urlparse(url).scheme not in {"http", "https"}
            or not urlparse(url).netloc
        ):
            raise PublicationManifestError(f"manifest source {position} URL is invalid")
        if not isinstance(raw_path_value, str) or not raw_path_value:
            raise PublicationManifestError(
                f"manifest source {position} raw_path is invalid"
            )
        if not isinstance(raw_hash, str) or re.fullmatch(r"[0-9a-f]{64}", raw_hash) is None:
            raise PublicationManifestError(
                f"manifest source {position} raw_sha256 is invalid"
            )
        raw_path = (manifest_root / raw_path_value).resolve()
        if not raw_path.is_relative_to(manifest_root):
            raise PublicationManifestError(
                f"manifest source {position} escapes the manifest directory"
            )
        if not raw_path.is_file() or _sha256_file(raw_path) != raw_hash:
            raise PublicationManifestError(
                f"manifest source {position} raw evidence hash failed: {raw_path}"
            )
        catalog_urls.add(url)
    missing_sources = sorted(event_source_urls - catalog_urls)
    if missing_sources:
        raise PublicationManifestError(
            f"calendar rows cite URLs absent from the source manifest: {missing_sources}"
        )


def actual_wmr_month_end(
    calendar: PublicationCalendar | None, year: int, month: int
) -> PublicationEvent:
    """Fail-closed functional wrapper for actual WMR month-end selection."""

    if calendar is None:
        raise PublicationCalendarError(
            "an external publication calendar is required; weekday fallback is forbidden"
        )
    if not isinstance(calendar, PublicationCalendar):
        raise TypeError("calendar must be a PublicationCalendar")
    return calendar.actual_wmr_month_end(year, month)


def _require_calendar_file(path: str | Path | None) -> Path:
    if path is None or (isinstance(path, str) and not path.strip()):
        raise PublicationCalendarError(
            "an external publication calendar CSV is required; weekday fallback is forbidden"
        )
    calendar_path = Path(path)
    if not calendar_path.is_file():
        raise PublicationCalendarError(f"publication calendar CSV does not exist: {calendar_path}")
    return calendar_path


def _validate_header(fieldnames: list[str] | None) -> None:
    if fieldnames is None:
        raise PublicationCalendarError("publication calendar is missing its header")
    if len(fieldnames) != len(set(fieldnames)):
        raise PublicationCalendarError("publication calendar has duplicate header columns")
    missing = set(CALENDAR_COLUMNS) - set(fieldnames)
    extra = set(fieldnames) - set(CALENDAR_COLUMNS)
    if missing or extra:
        raise PublicationCalendarError(
            f"publication calendar columns mismatch; missing={sorted(missing)}, "
            f"extra={sorted(extra)}"
        )


def _parse_row(
    row: dict[str, str | None],
    *,
    line_number: int,
    knowledge_cutoff: datetime,
    formal_experiment: bool,
) -> PublicationEvent:
    if None in row:
        raise PublicationCalendarError(
            f"line {line_number}: row has more fields than the calendar header"
        )
    values = {
        column: _required_text(row.get(column), column, line_number) for column in CALENDAR_COLUMNS
    }
    event_name = values["event_name"]
    try:
        definition = EVENT_DEFINITIONS[event_name]
    except KeyError as exc:
        allowed = ", ".join(EVENT_DEFINITIONS)
        raise PublicationCalendarError(
            f"line {line_number}: unknown event_name {event_name!r}; expected {allowed}"
        ) from exc

    status = values["status"]
    if status not in EVENT_STATUSES:
        raise PublicationCalendarError(
            f"line {line_number}: invalid status {status!r}; expected {sorted(EVENT_STATUSES)}"
        )
    quality = values["quality"]
    if quality not in CALENDAR_QUALITIES:
        raise PublicationCalendarError(
            f"line {line_number}: invalid quality {quality!r}; "
            f"expected {sorted(CALENDAR_QUALITIES)}"
        )
    if formal_experiment and quality != "verified":
        raise PublicationCalendarError(
            f"line {line_number}: formal experiments require quality='verified'"
        )

    timezone = values["timezone"]
    if timezone != definition.timezone:
        raise PublicationCalendarError(
            f"line {line_number}: {event_name!r} requires canonical IANA timezone "
            f"{definition.timezone!r}, got {timezone!r}"
        )
    calendar_date = _parse_local_date(values["local_date"], field=f"line {line_number} local_date")
    local_clock = _parse_local_time(values["local_time"], line_number=line_number)
    if status == "early_time":
        if local_clock >= definition.local_time:
            raise PublicationCalendarError(
                f"line {line_number}: early_time must be earlier than the default "
                f"{definition.local_time.strftime('%H:%M')}"
            )
    elif local_clock != definition.local_time:
        raise PublicationCalendarError(
            f"line {line_number}: status={status!r} requires default local_time "
            f"{definition.local_time.strftime('%H:%M')}; use early_time for an earlier event"
        )

    source_url = values["source_url"]
    parsed_url = urlparse(source_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise PublicationCalendarError(
            f"line {line_number}: source_url must be an absolute HTTP(S) URL"
        )
    retrieved_at = _parse_aware_datetime(
        values["retrieved_at"], field=f"line {line_number} retrieved_at"
    )
    if retrieved_at > knowledge_cutoff:
        raise PublicationCalendarError(
            f"line {line_number}: retrieved_at {retrieved_at.isoformat()} is after "
            f"knowledge_cutoff {knowledge_cutoff.isoformat()}"
        )

    scheduled_time_utc = _strict_local_to_utc(
        calendar_date, local_clock, timezone, line_number=line_number
    )
    return PublicationEvent(
        event_name=event_name,
        local_date=calendar_date,
        status=status,  # type: ignore[arg-type]
        local_time=local_clock,
        timezone=timezone,
        source_url=source_url,
        quality=quality,  # type: ignore[arg-type]
        retrieved_at=retrieved_at,
        scheduled_time_utc=scheduled_time_utc,
    )


def _required_text(value: str | None, field: str, line_number: int) -> str:
    if value is None or not value.strip():
        raise PublicationCalendarError(f"line {line_number}: {field} cannot be empty")
    return value.strip()


def _parse_local_date(value: date | str, *, field: str) -> date:
    if isinstance(value, datetime):
        raise PublicationCalendarError(f"{field} must be a date without a time")
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise PublicationCalendarError(f"{field} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise PublicationCalendarError(f"{field} must be an ISO date, got {value!r}") from exc
    if parsed.isoformat() != value:
        raise PublicationCalendarError(f"{field} must use canonical YYYY-MM-DD format")
    return parsed


def _parse_local_time(value: str, *, line_number: int) -> time:
    if _TIME_PATTERN.fullmatch(value) is None:
        raise PublicationCalendarError(
            f"line {line_number}: local_time must use 24-hour HH:MM format"
        )
    hour, minute = map(int, value.split(":"))
    try:
        return time(hour, minute)
    except ValueError as exc:
        raise PublicationCalendarError(f"line {line_number}: invalid local_time {value!r}") from exc


def _parse_aware_datetime(value: datetime | str, *, field: str) -> datetime:
    if isinstance(value, str):
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise PublicationCalendarError(
                f"{field} must be an ISO timestamp with a UTC offset"
            ) from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise PublicationCalendarError(f"{field} must be a timezone-aware timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PublicationCalendarError(f"{field} must include a UTC offset")
    return parsed.astimezone(UTC)


def _strict_local_to_utc(
    calendar_date: date,
    local_clock: time,
    timezone: str,
    *,
    line_number: int,
) -> datetime:
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise PublicationCalendarError(
            f"line {line_number}: unavailable IANA timezone {timezone!r}"
        ) from exc
    naive = datetime.combine(calendar_date, local_clock)
    candidates: set[datetime] = set()
    for fold in (0, 1):
        candidate = naive.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        if candidate.astimezone(zone).replace(tzinfo=None) == naive:
            candidates.add(candidate)
    if not candidates:
        raise PublicationCalendarError(
            f"line {line_number}: nonexistent local time {naive.isoformat()} in {timezone}"
        )
    if len(candidates) > 1:
        raise PublicationCalendarError(
            f"line {line_number}: ambiguous local time {naive.isoformat()} in {timezone}"
        )
    return candidates.pop()


__all__ = [
    "CALENDAR_COLUMNS",
    "CALENDAR_QUALITIES",
    "EVENT_STATUSES",
    "PublicationCalendar",
    "PublicationCalendarError",
    "PublicationEvent",
    "actual_wmr_month_end",
    "load_publication_calendar",
]
