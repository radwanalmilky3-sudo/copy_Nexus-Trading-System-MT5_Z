"""Fail-closed contract for central-bank policy-event blackout calendars.

The calendar is an announcement-risk control, not a directional signal.  In
particular, a date-only official source represents the whole local civil day;
this module never invents a publication minute for such an event.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Final, Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TimestampQuality = Literal[
    "verified_actual_publication",
    "official_event_scheduled_time",
    "official_rule_derived",
    "official_date_only",
    "unverified_external",
]
ScheduledStatus = Literal["scheduled", "unscheduled", "cancelled", "superseded"]
EventType = Literal[
    "rate_decision",
    "asset_purchase_decision",
    "policy_framework_decision",
]

CENTRAL_BANK_COLUMNS: Final[tuple[str, ...]] = (
    "event_id",
    "currency",
    "authority",
    "event_type",
    "scheduled_status",
    "decision_date_local",
    "release_time_local",
    "release_tzid",
    "release_time_raw",
    "release_at_utc",
    "timestamp_quality",
    "rule_id",
    "rule_effective_from",
    "rule_effective_to",
    "source_url",
    "source_document_type",
    "source_title",
    "retrieved_at_utc",
    "source_sha256",
    "supersedes_event_id",
    "cancelled",
    "notes",
)

AUTHORITY_CONTRACT: Final[dict[str, tuple[str, str]]] = {
    "FED": ("USD", "America/New_York"),
    "ECB": ("EUR", "Europe/Berlin"),
    "BOE": ("GBP", "Europe/London"),
    "BOJ": ("JPY", "Asia/Tokyo"),
    "SNB": ("CHF", "Europe/Zurich"),
    "BOC": ("CAD", "America/Toronto"),
    "RBA": ("AUD", "Australia/Sydney"),
    "RBNZ": ("NZD", "Pacific/Auckland"),
}
TIMESTAMP_QUALITIES: Final[frozenset[str]] = frozenset(
    {
        "verified_actual_publication",
        "official_event_scheduled_time",
        "official_rule_derived",
        "official_date_only",
        "unverified_external",
    }
)
SCHEDULED_STATUSES: Final[frozenset[str]] = frozenset(
    {"scheduled", "unscheduled", "cancelled", "superseded"}
)
EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {"rate_decision", "asset_purchase_decision", "policy_framework_decision"}
)
_TIME_PATTERN: Final = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")
_HASH_PATTERN: Final = re.compile(r"[0-9a-f]{64}")
_EVENT_ID_PATTERN: Final = re.compile(r"[a-z0-9][a-z0-9._-]{2,127}")


class CentralBankCalendarError(ValueError):
    """Raised when policy-event timing would require an unstated guess."""


class CentralBankManifestError(CentralBankCalendarError):
    """Raised when the calendar's source audit trail is incomplete."""


@dataclass(frozen=True)
class CentralBankEvent:
    """One policy event with timing quality kept separate from its timestamp."""

    event_id: str
    currency: str
    authority: str
    event_type: EventType
    scheduled_status: ScheduledStatus
    decision_date_local: date
    release_time_local: time | None
    release_tzid: str
    release_time_raw: str
    release_at_utc: datetime | None
    timestamp_quality: TimestampQuality
    rule_id: str | None
    rule_effective_from: date | None
    rule_effective_to: date | None
    source_url: str
    source_document_type: str
    source_title: str
    retrieved_at_utc: datetime
    source_sha256: str
    supersedes_event_id: str | None
    cancelled: bool
    notes: str

    @property
    def has_verified_actual_timestamp(self) -> bool:
        """Whether the official document states the event's actual publication minute."""

        return self.timestamp_quality == "verified_actual_publication"

    @property
    def is_date_only(self) -> bool:
        """Whether the evidence establishes a local date but no publication minute."""

        return self.timestamp_quality == "official_date_only"

    def blackout_interval_utc(
        self,
        *,
        before: timedelta = timedelta(),
        after: timedelta = timedelta(),
    ) -> tuple[datetime, datetime]:
        """Return a half-open blackout interval without inventing date-only minutes.

        Timestamped events produce ``[release-before, release+after)``.  A
        date-only event produces the complete local civil day, expanded by the
        supplied buffers.  Cancelled events have no blackout interval.
        """

        if self.cancelled:
            raise CentralBankCalendarError(
                f"cancelled event {self.event_id!r} has no blackout interval"
            )
        if before < timedelta() or after < timedelta():
            raise CentralBankCalendarError("blackout buffers cannot be negative")
        if self.release_at_utc is not None:
            return self.release_at_utc - before, self.release_at_utc + after
        if not self.is_date_only:
            raise CentralBankCalendarError(
                f"event {self.event_id!r} has no usable official publication time"
            )
        zone = ZoneInfo(self.release_tzid)
        local_start = datetime.combine(self.decision_date_local, time(), tzinfo=zone)
        local_end = datetime.combine(
            self.decision_date_local + timedelta(days=1), time(), tzinfo=zone
        )
        return local_start.astimezone(UTC) - before, local_end.astimezone(UTC) + after


@dataclass(frozen=True)
class CentralBankCalendar:
    """Validated, complete and hash-audited eight-authority event calendar."""

    events: tuple[CentralBankEvent, ...]
    manifest_path: Path
    calendar_sha256: str
    coverage_start: date
    coverage_end: date

    def event(self, event_id: str) -> CentralBankEvent:
        """Look up one explicit event identifier."""

        matches = [event for event in self.events if event.event_id == event_id]
        if not matches:
            raise CentralBankCalendarError(f"unknown central-bank event_id {event_id!r}")
        if len(matches) != 1:  # Loader already enforces this.
            raise CentralBankCalendarError(f"duplicate central-bank event_id {event_id!r}")
        return matches[0]

    def events_on(
        self,
        value: date | str,
        *,
        authority: str | None = None,
        include_cancelled: bool = False,
    ) -> tuple[CentralBankEvent, ...]:
        """Return only explicitly recorded events on a local decision date."""

        local_date = _parse_date(value, field="decision_date_local")
        normalized_authority = authority.upper() if authority is not None else None
        if normalized_authority is not None and normalized_authority not in AUTHORITY_CONTRACT:
            raise CentralBankCalendarError(f"unknown authority {authority!r}")
        return tuple(
            event
            for event in self.events
            if event.decision_date_local == local_date
            and (normalized_authority is None or event.authority == normalized_authority)
            and (include_cancelled or not event.cancelled)
        )


def load_central_bank_calendar(
    path: str | Path,
    *,
    manifest_path: str | Path,
    knowledge_cutoff: datetime | str,
    require_complete: bool = True,
    formal_experiment: bool = True,
) -> CentralBankCalendar:
    """Load and verify a policy calendar, manifest, raw files, and SHA sidecars."""

    calendar_path = Path(path)
    if not calendar_path.is_file():
        raise CentralBankCalendarError(f"central-bank calendar not found: {calendar_path}")
    cutoff = _parse_datetime(knowledge_cutoff, field="knowledge_cutoff")
    with calendar_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, strict=True)
        if tuple(reader.fieldnames or ()) != CENTRAL_BANK_COLUMNS:
            raise CentralBankCalendarError(
                "central-bank calendar columns do not match the frozen schema"
            )
        try:
            rows = list(reader)
        except csv.Error as error:
            raise CentralBankCalendarError("malformed central-bank calendar CSV") from error
    if not rows:
        raise CentralBankCalendarError("central-bank calendar cannot be empty")

    events = tuple(
        _parse_row(
            row,
            line_number=line_number,
            knowledge_cutoff=cutoff,
            formal_experiment=formal_experiment,
        )
        for line_number, row in enumerate(rows, start=2)
    )
    ids = [event.event_id for event in events]
    if len(ids) != len(set(ids)):
        raise CentralBankCalendarError("central-bank calendar has duplicate event_id values")
    def ordering(event: CentralBankEvent) -> tuple[date, datetime, str, str, str]:
        return (
            event.decision_date_local,
            event.release_at_utc or datetime.max.replace(tzinfo=UTC),
            event.authority,
            event.event_type,
            event.event_id,
        )

    if list(events) != sorted(events, key=ordering):
        raise CentralBankCalendarError(
            "central-bank calendar rows are not deterministically sorted"
        )
    _validate_supersession(events)

    calendar_hash = _sha256_file(calendar_path)
    manifest = _verify_manifest(
        calendar_path,
        Path(manifest_path),
        calendar_hash=calendar_hash,
        events=events,
        knowledge_cutoff=cutoff,
        require_complete=require_complete,
    )
    return CentralBankCalendar(
        events=events,
        manifest_path=Path(manifest_path),
        calendar_sha256=calendar_hash,
        coverage_start=_parse_date(manifest["coverage_start"], field="manifest coverage_start"),
        coverage_end=_parse_date(manifest["coverage_end"], field="manifest coverage_end"),
    )


def _parse_row(
    row: dict[str, str],
    *,
    line_number: int,
    knowledge_cutoff: datetime,
    formal_experiment: bool,
) -> CentralBankEvent:
    if None in row:
        raise CentralBankCalendarError(f"line {line_number}: too many CSV fields")
    values = {key: str(row.get(key, "")).strip() for key in CENTRAL_BANK_COLUMNS}
    event_id = values["event_id"]
    if _EVENT_ID_PATTERN.fullmatch(event_id) is None:
        raise CentralBankCalendarError(f"line {line_number}: invalid event_id {event_id!r}")
    authority = values["authority"].upper()
    if authority not in AUTHORITY_CONTRACT:
        raise CentralBankCalendarError(f"line {line_number}: unknown authority {authority!r}")
    expected_currency, expected_tzid = AUTHORITY_CONTRACT[authority]
    currency = values["currency"].upper()
    if currency != expected_currency:
        raise CentralBankCalendarError(
            f"line {line_number}: {authority} requires currency={expected_currency!r}"
        )
    tzid = values["release_tzid"]
    if tzid != expected_tzid:
        raise CentralBankCalendarError(
            f"line {line_number}: {authority} requires release_tzid={expected_tzid!r}"
        )
    try:
        ZoneInfo(tzid)
    except ZoneInfoNotFoundError as error:
        raise CentralBankCalendarError(
            f"line {line_number}: unavailable IANA timezone {tzid!r}"
        ) from error

    event_type = values["event_type"]
    if event_type not in EVENT_TYPES:
        raise CentralBankCalendarError(f"line {line_number}: invalid event_type {event_type!r}")
    scheduled_status = values["scheduled_status"]
    if scheduled_status not in SCHEDULED_STATUSES:
        raise CentralBankCalendarError(
            f"line {line_number}: invalid scheduled_status {scheduled_status!r}"
        )
    quality = values["timestamp_quality"]
    if quality not in TIMESTAMP_QUALITIES:
        raise CentralBankCalendarError(
            f"line {line_number}: invalid timestamp_quality {quality!r}"
        )
    if formal_experiment and quality == "unverified_external":
        raise CentralBankCalendarError(
            f"line {line_number}: formal experiments reject unverified_external timing"
        )

    local_date = _parse_date(
        values["decision_date_local"], field=f"line {line_number} decision_date_local"
    )
    local_time = _parse_optional_time(values["release_time_local"], line_number=line_number)
    release_at = _parse_optional_datetime(
        values["release_at_utc"], field=f"line {line_number} release_at_utc"
    )
    if release_at is not None and release_at.utcoffset() != timedelta():
        raise CentralBankCalendarError(
            f"line {line_number}: release_at_utc must use the UTC offset"
        )
    if quality == "official_date_only":
        if local_time is not None or release_at is not None:
            raise CentralBankCalendarError(
                f"line {line_number}: official_date_only cannot contain a publication minute"
            )
        if not values["release_time_raw"]:
            raise CentralBankCalendarError(
                f"line {line_number}: date-only evidence needs release_time_raw context"
            )
    else:
        if local_time is None or release_at is None or not values["release_time_raw"]:
            raise CentralBankCalendarError(
                f"line {line_number}: timestamped evidence requires local/raw/UTC time"
            )
        expected_utc = _strict_local_to_utc(local_date, local_time, tzid, line_number=line_number)
        if release_at != expected_utc:
            raise CentralBankCalendarError(
                f"line {line_number}: release_at_utc does not match the local civil time"
            )

    rule_id = values["rule_id"] or None
    rule_from = _parse_optional_date(
        values["rule_effective_from"], field=f"line {line_number} rule_effective_from"
    )
    rule_to = _parse_optional_date(
        values["rule_effective_to"], field=f"line {line_number} rule_effective_to"
    )
    if quality == "official_rule_derived":
        if rule_id is None or rule_from is None:
            raise CentralBankCalendarError(
                f"line {line_number}: official_rule_derived requires rule metadata"
            )
        if local_date < rule_from or (rule_to is not None and local_date > rule_to):
            raise CentralBankCalendarError(
                f"line {line_number}: event is outside its rule effective interval"
            )
    elif rule_id is not None or rule_from is not None or rule_to is not None:
        raise CentralBankCalendarError(
            f"line {line_number}: rule metadata is only valid for official_rule_derived"
        )
    if rule_from is not None and rule_to is not None and rule_from > rule_to:
        raise CentralBankCalendarError(f"line {line_number}: inverted rule interval")

    source_url = values["source_url"]
    parsed_url = urlparse(source_url)
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        raise CentralBankCalendarError(
            f"line {line_number}: source_url must be an absolute HTTPS URL"
        )
    for field in ("source_document_type", "source_title", "release_time_raw"):
        if not values[field]:
            raise CentralBankCalendarError(f"line {line_number}: {field} cannot be empty")
    retrieved_at = _parse_datetime(
        values["retrieved_at_utc"], field=f"line {line_number} retrieved_at_utc"
    )
    if retrieved_at > knowledge_cutoff:
        raise CentralBankCalendarError(
            f"line {line_number}: source was retrieved after the knowledge cutoff"
        )
    source_hash = values["source_sha256"]
    if _HASH_PATTERN.fullmatch(source_hash) is None:
        raise CentralBankCalendarError(f"line {line_number}: invalid source_sha256")
    cancelled = _parse_bool(values["cancelled"], field=f"line {line_number} cancelled")
    if cancelled != (scheduled_status == "cancelled"):
        raise CentralBankCalendarError(
            f"line {line_number}: cancelled flag and scheduled_status disagree"
        )
    if cancelled and quality != "official_date_only":
        raise CentralBankCalendarError(
            f"line {line_number}: cancelled events cannot claim a publication timestamp"
        )

    return CentralBankEvent(
        event_id=event_id,
        currency=currency,
        authority=authority,
        event_type=event_type,  # type: ignore[arg-type]
        scheduled_status=scheduled_status,  # type: ignore[arg-type]
        decision_date_local=local_date,
        release_time_local=local_time,
        release_tzid=tzid,
        release_time_raw=values["release_time_raw"],
        release_at_utc=release_at,
        timestamp_quality=quality,  # type: ignore[arg-type]
        rule_id=rule_id,
        rule_effective_from=rule_from,
        rule_effective_to=rule_to,
        source_url=source_url,
        source_document_type=values["source_document_type"],
        source_title=values["source_title"],
        retrieved_at_utc=retrieved_at,
        source_sha256=source_hash,
        supersedes_event_id=values["supersedes_event_id"] or None,
        cancelled=cancelled,
        notes=values["notes"],
    )


def _validate_supersession(events: tuple[CentralBankEvent, ...]) -> None:
    by_id = {event.event_id: event for event in events}
    for event in events:
        target_id = event.supersedes_event_id
        if target_id is None:
            continue
        if target_id == event.event_id or target_id not in by_id:
            raise CentralBankCalendarError(
                f"event {event.event_id!r} has invalid supersedes_event_id {target_id!r}"
            )
        target = by_id[target_id]
        if target.authority != event.authority:
            raise CentralBankCalendarError(
                f"event {event.event_id!r} cannot supersede a different authority"
            )
        if target.decision_date_local > event.decision_date_local:
            raise CentralBankCalendarError(
                f"event {event.event_id!r} cannot supersede a future event"
            )


def _verify_manifest(
    calendar_path: Path,
    manifest_path: Path,
    *,
    calendar_hash: str,
    events: tuple[CentralBankEvent, ...],
    knowledge_cutoff: datetime,
    require_complete: bool,
) -> dict[str, object]:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CentralBankManifestError(
            f"cannot read central-bank calendar manifest: {manifest_path}"
        ) from error
    if not isinstance(payload, dict):
        raise CentralBankManifestError("central-bank calendar manifest must be an object")
    expected: dict[str, object] = {
        "schema_version": 1,
        "dataset_kind": "central_bank_policy_event_calendar",
        "calendar_file": calendar_path.name,
        "calendar_sha256": calendar_hash,
        "rows": len(events),
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise CentralBankManifestError(f"manifest {key} does not match {value!r}")
    coverage_start = _parse_date(payload.get("coverage_start"), field="manifest coverage_start")
    coverage_end = _parse_date(payload.get("coverage_end"), field="manifest coverage_end")
    if coverage_start > coverage_end:
        raise CentralBankManifestError("manifest coverage interval is inverted")
    if any(
        event.decision_date_local < coverage_start or event.decision_date_local > coverage_end
        for event in events
    ):
        raise CentralBankManifestError("calendar row falls outside manifest coverage")
    created_at = _parse_datetime(payload.get("created_at"), field="manifest created_at")
    if created_at > knowledge_cutoff:
        raise CentralBankManifestError("manifest was created after the knowledge cutoff")

    adapters = payload.get("adapters")
    if not isinstance(adapters, list):
        raise CentralBankManifestError("manifest adapters must be a list")
    adapter_by_authority: dict[str, dict[str, object]] = {}
    for index, adapter in enumerate(adapters):
        if not isinstance(adapter, dict):
            raise CentralBankManifestError(f"manifest adapter {index} must be an object")
        authority = adapter.get("authority")
        status = adapter.get("status")
        if authority not in AUTHORITY_CONTRACT or authority in adapter_by_authority:
            raise CentralBankManifestError(f"manifest adapter {index} authority is invalid")
        if status not in {"complete", "incomplete", "fail_closed"}:
            raise CentralBankManifestError(f"manifest adapter {authority} status is invalid")
        adapter_by_authority[str(authority)] = adapter
    if set(adapter_by_authority) != set(AUTHORITY_CONTRACT):
        raise CentralBankManifestError("manifest must declare all eight authority adapters")
    if require_complete:
        incomplete = sorted(
            authority
            for authority, adapter in adapter_by_authority.items()
            if adapter.get("status") != "complete"
        )
        if incomplete:
            raise CentralBankManifestError(
                f"central-bank calendar is fail-closed; incomplete adapters={incomplete}"
            )
    row_counts = {authority: 0 for authority in AUTHORITY_CONTRACT}
    for event in events:
        row_counts[event.authority] += 1
    for authority, count in row_counts.items():
        adapter_count = adapter_by_authority[authority].get("row_count")
        if adapter_count != count:
            raise CentralBankManifestError(
                f"manifest adapter {authority} row_count does not match {count}"
            )
        if require_complete and count == 0:
            raise CentralBankManifestError(f"complete adapter {authority} has no events")

    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        raise CentralBankManifestError("manifest sources are missing")
    manifest_root = manifest_path.resolve().parent
    catalog: dict[tuple[str, str], str] = {}
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise CentralBankManifestError(f"manifest source {index} must be an object")
        url = source.get("url")
        raw_path_value = source.get("raw_path")
        sidecar_path_value = source.get("sha256_path")
        raw_hash = source.get("raw_sha256")
        if (
            not isinstance(url, str)
            or urlparse(url).scheme != "https"
            or not urlparse(url).netloc
        ):
            raise CentralBankManifestError(f"manifest source {index} URL is invalid")
        if not isinstance(raw_hash, str) or _HASH_PATTERN.fullmatch(raw_hash) is None:
            raise CentralBankManifestError(f"manifest source {index} raw_sha256 is invalid")
        raw_path = _safe_manifest_path(
            manifest_root, raw_path_value, field=f"manifest source {index} raw_path"
        )
        sidecar_path = _safe_manifest_path(
            manifest_root,
            sidecar_path_value,
            field=f"manifest source {index} sha256_path",
        )
        if not raw_path.is_file() or _sha256_file(raw_path) != raw_hash:
            raise CentralBankManifestError(
                f"manifest source {index} raw evidence hash failed: {raw_path}"
            )
        if not sidecar_path.is_file():
            raise CentralBankManifestError(
                f"manifest source {index} SHA-256 sidecar is missing"
            )
        sidecar_hash = sidecar_path.read_text(encoding="ascii").strip().split(maxsplit=1)[0]
        if sidecar_hash != raw_hash:
            raise CentralBankManifestError(
                f"manifest source {index} SHA-256 sidecar does not match raw evidence"
            )
        catalog[(url, raw_hash)] = str(source.get("source_id", ""))
    missing = sorted(
        {(event.source_url, event.source_sha256) for event in events} - set(catalog)
    )
    if missing:
        raise CentralBankManifestError(
            f"calendar rows cite source URL/hash pairs absent from manifest: {missing[:3]}"
        )
    return payload


def _safe_manifest_path(root: Path, value: object, *, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise CentralBankManifestError(f"{field} is invalid")
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise CentralBankManifestError(f"{field} escapes the manifest directory")
    return path


def _parse_date(value: object, *, field: str) -> date:
    if isinstance(value, datetime):
        raise CentralBankCalendarError(f"{field} must be a date without a time")
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise CentralBankCalendarError(f"{field} must be a canonical ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise CentralBankCalendarError(f"{field} must be a canonical ISO date") from error
    if parsed.isoformat() != value:
        raise CentralBankCalendarError(f"{field} must use YYYY-MM-DD")
    return parsed


def _parse_optional_date(value: str, *, field: str) -> date | None:
    return None if not value else _parse_date(value, field=field)


def _parse_optional_time(value: str, *, line_number: int) -> time | None:
    if not value:
        return None
    if _TIME_PATTERN.fullmatch(value) is None:
        raise CentralBankCalendarError(
            f"line {line_number}: release_time_local must use HH:MM"
        )
    return time.fromisoformat(value)


def _parse_datetime(value: object, *, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as error:
            raise CentralBankCalendarError(
                f"{field} must be an ISO timestamp with offset"
            ) from error
    else:
        raise CentralBankCalendarError(f"{field} must be an ISO timestamp with offset")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CentralBankCalendarError(f"{field} must include a UTC offset")
    return parsed.astimezone(UTC)


def _parse_optional_datetime(value: str, *, field: str) -> datetime | None:
    return None if not value else _parse_datetime(value, field=field)


def _parse_bool(value: str, *, field: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise CentralBankCalendarError(f"{field} must be lowercase true or false")


def _strict_local_to_utc(
    local_date: date,
    local_time: time,
    tzid: str,
    *,
    line_number: int,
) -> datetime:
    zone = ZoneInfo(tzid)
    naive = datetime.combine(local_date, local_time)
    candidates: set[datetime] = set()
    for fold in (0, 1):
        candidate = naive.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        if candidate.astimezone(zone).replace(tzinfo=None) == naive:
            candidates.add(candidate)
    if not candidates:
        raise CentralBankCalendarError(
            f"line {line_number}: nonexistent local time {naive.isoformat()} in {tzid}"
        )
    if len(candidates) > 1:
        raise CentralBankCalendarError(
            f"line {line_number}: ambiguous local time {naive.isoformat()} in {tzid}"
        )
    return candidates.pop()


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "AUTHORITY_CONTRACT",
    "CENTRAL_BANK_COLUMNS",
    "EVENT_TYPES",
    "SCHEDULED_STATUSES",
    "TIMESTAMP_QUALITIES",
    "CentralBankCalendar",
    "CentralBankCalendarError",
    "CentralBankEvent",
    "CentralBankManifestError",
    "load_central_bank_calendar",
]
