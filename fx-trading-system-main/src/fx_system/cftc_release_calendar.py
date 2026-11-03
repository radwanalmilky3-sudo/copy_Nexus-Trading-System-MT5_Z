"""Fail-closed contract for CFTC Commitments of Traders release mappings.

The annual CFTC pages describe a *tentative* release schedule.  They are not
proof that a report was published at the scheduled time.  This module keeps
that distinction explicit and only accepts ``verified_actual=true`` for an
official source which states that the exceptional report was actually issued.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Final, Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CFTCReleaseEvidence = Literal[
    "official_tentative_schedule",
    "official_exception_announced",
    "official_exception_actual",
    "rule_derived_mapping",
]
CFTCReleaseTimeEvidence = Literal[
    "official_tentative_schedule",
    "inherited_general_rule",
    "date_only_no_verified_time",
]

CFTC_RELEASE_COLUMNS: Final[tuple[str, ...]] = (
    "report_date",
    "original_release_date",
    "mapped_release_date",
    "mapped_release_time_local",
    "timezone",
    "date_evidence_kind",
    "time_evidence_kind",
    "verified_actual",
    "source_id",
    "source_url",
    "mapping_note",
    "retrieved_at",
)
CFTC_RELEASE_EVIDENCE: Final[frozenset[str]] = frozenset(
    {
        "official_tentative_schedule",
        "official_exception_announced",
        "official_exception_actual",
        "rule_derived_mapping",
    }
)
CFTC_RELEASE_TIME_EVIDENCE: Final[frozenset[str]] = frozenset(
    {
        "official_tentative_schedule",
        "inherited_general_rule",
        "date_only_no_verified_time",
    }
)
_TIME_PATTERN: Final = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")
_HASH_PATTERN: Final = re.compile(r"[0-9a-f]{64}")


class CFTCReleaseCalendarError(ValueError):
    """Raised when a CFTC release mapping would require an unstated guess."""


class CFTCReleaseManifestError(CFTCReleaseCalendarError):
    """Raised when the calendar's raw-source audit trail is incomplete."""


@dataclass(frozen=True)
class CFTCReleaseEntry:
    """One report-date to release-date mapping with explicit evidence quality."""

    report_date: date
    original_release_date: date
    mapped_release_date: date
    mapped_release_time_local: time | None
    timezone: str
    date_evidence_kind: CFTCReleaseEvidence
    time_evidence_kind: CFTCReleaseTimeEvidence
    verified_actual: bool
    source_id: str
    source_url: str
    mapping_note: str
    retrieved_at: datetime

    @property
    def mapped_release_timestamp_utc(self) -> datetime | None:
        """Return the mapped timestamp, without upgrading its evidence quality."""

        if self.mapped_release_time_local is None:
            return None
        local = datetime.combine(
            self.mapped_release_date,
            self.mapped_release_time_local,
            tzinfo=ZoneInfo(self.timezone),
        )
        return local.astimezone(UTC)

    @property
    def verified_actual_timestamp_utc(self) -> datetime | None:
        """Return a timestamp only when both actual date and time are verified.

        The official ION announcements establish actual publication *dates* but
        do not state an exact publication time.  Those rows therefore correctly
        return ``None`` here.
        """

        if not self.verified_actual:
            return None
        return self.mapped_release_timestamp_utc


@dataclass(frozen=True)
class CFTCReleaseCalendar:
    """Validated, hash-audited CFTC release calendar."""

    entries: tuple[CFTCReleaseEntry, ...]
    manifest_path: Path
    calendar_sha256: str

    def for_report_date(self, value: date | str) -> CFTCReleaseEntry:
        """Look up one explicit report date; never invent a Friday fallback."""

        report_date = _parse_date(value, field="report_date")
        matches = [entry for entry in self.entries if entry.report_date == report_date]
        if not matches:
            raise CFTCReleaseCalendarError(
                f"calendar has no explicit CFTC release mapping for {report_date.isoformat()}"
            )
        if len(matches) != 1:  # The loader already rejects this defensively.
            raise CFTCReleaseCalendarError(
                f"calendar has duplicate CFTC mappings for {report_date.isoformat()}"
            )
        return matches[0]


def load_cftc_release_calendar(
    path: str | Path,
    *,
    manifest_path: str | Path,
    knowledge_cutoff: datetime | str,
) -> CFTCReleaseCalendar:
    """Load a calendar and verify its CSV, manifest, raw files, and SHA sidecars."""

    calendar_path = Path(path)
    if not calendar_path.is_file():
        raise CFTCReleaseCalendarError(f"CFTC release calendar not found: {calendar_path}")
    cutoff = _parse_datetime(knowledge_cutoff, field="knowledge_cutoff")
    with calendar_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, strict=True)
        if tuple(reader.fieldnames or ()) != CFTC_RELEASE_COLUMNS:
            raise CFTCReleaseCalendarError(
                "CFTC release calendar columns do not match the frozen schema"
            )
        try:
            raw_rows = list(reader)
        except csv.Error as error:
            raise CFTCReleaseCalendarError("malformed CFTC release calendar CSV") from error
    if not raw_rows:
        raise CFTCReleaseCalendarError("CFTC release calendar cannot be empty")

    entries = tuple(
        _parse_row(row, line_number=index, knowledge_cutoff=cutoff)
        for index, row in enumerate(raw_rows, start=2)
    )
    report_dates = [entry.report_date for entry in entries]
    if len(report_dates) != len(set(report_dates)):
        raise CFTCReleaseCalendarError("CFTC release calendar has duplicate report dates")
    if list(entries) != sorted(entries, key=lambda entry: entry.report_date):
        raise CFTCReleaseCalendarError("CFTC release calendar must be sorted by report_date")

    calendar_hash = _sha256_file(calendar_path)
    source_ids = {entry.source_id for entry in entries}
    source_urls = {entry.source_url for entry in entries}
    verified_manifest = Path(manifest_path)
    _verify_manifest(
        calendar_path,
        verified_manifest,
        calendar_hash=calendar_hash,
        source_ids=source_ids,
        source_urls=source_urls,
    )
    return CFTCReleaseCalendar(entries, verified_manifest, calendar_hash)


def _parse_row(
    row: dict[str, str],
    *,
    line_number: int,
    knowledge_cutoff: datetime,
) -> CFTCReleaseEntry:
    report_date = _parse_date(row["report_date"], field=f"line {line_number} report_date")
    original_release = _parse_date(
        row["original_release_date"],
        field=f"line {line_number} original_release_date",
    )
    mapped_release = _parse_date(
        row["mapped_release_date"],
        field=f"line {line_number} mapped_release_date",
    )
    if mapped_release < report_date:
        raise CFTCReleaseCalendarError(
            f"line {line_number}: mapped release predates the report date"
        )

    raw_time = row["mapped_release_time_local"].strip()
    if raw_time:
        if _TIME_PATTERN.fullmatch(raw_time) is None:
            raise CFTCReleaseCalendarError(
                f"line {line_number}: invalid mapped_release_time_local"
            )
        mapped_time = time.fromisoformat(raw_time)
    else:
        mapped_time = None
    timezone = row["timezone"].strip()
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as error:
        raise CFTCReleaseCalendarError(
            f"line {line_number}: invalid timezone {timezone!r}"
        ) from error

    date_evidence = row["date_evidence_kind"].strip()
    if date_evidence not in CFTC_RELEASE_EVIDENCE:
        raise CFTCReleaseCalendarError(
            f"line {line_number}: unknown date evidence {date_evidence!r}"
        )
    time_evidence = row["time_evidence_kind"].strip()
    if time_evidence not in CFTC_RELEASE_TIME_EVIDENCE:
        raise CFTCReleaseCalendarError(
            f"line {line_number}: unknown time evidence {time_evidence!r}"
        )
    if row["verified_actual"] not in {"true", "false"}:
        raise CFTCReleaseCalendarError(
            f"line {line_number}: verified_actual must be literal true or false"
        )
    verified_actual = row["verified_actual"] == "true"
    if verified_actual != (date_evidence == "official_exception_actual"):
        raise CFTCReleaseCalendarError(
            f"line {line_number}: only official_exception_actual may be verified_actual"
        )
    if time_evidence == "date_only_no_verified_time" and mapped_time is not None:
        raise CFTCReleaseCalendarError(
            f"line {line_number}: date-only evidence cannot contain an exact time"
        )
    if time_evidence != "date_only_no_verified_time" and mapped_time is None:
        raise CFTCReleaseCalendarError(
            f"line {line_number}: a non-date-only mapping requires a time"
        )
    if verified_actual and time_evidence != "date_only_no_verified_time":
        raise CFTCReleaseCalendarError(
            f"line {line_number}: current exception sources verify dates, not exact times"
        )

    source_id = row["source_id"].strip()
    if not source_id:
        raise CFTCReleaseCalendarError(f"line {line_number}: source_id is empty")
    source_url = row["source_url"].strip()
    parsed_url = urlparse(source_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise CFTCReleaseCalendarError(f"line {line_number}: source_url is invalid")
    mapping_note = row["mapping_note"].strip()
    if not mapping_note:
        raise CFTCReleaseCalendarError(f"line {line_number}: mapping_note is empty")
    retrieved_at = _parse_datetime(
        row["retrieved_at"], field=f"line {line_number} retrieved_at"
    )
    if retrieved_at > knowledge_cutoff:
        raise CFTCReleaseCalendarError(
            f"line {line_number}: source was retrieved after the knowledge cutoff"
        )
    return CFTCReleaseEntry(
        report_date=report_date,
        original_release_date=original_release,
        mapped_release_date=mapped_release,
        mapped_release_time_local=mapped_time,
        timezone=timezone,
        date_evidence_kind=date_evidence,  # type: ignore[arg-type]
        time_evidence_kind=time_evidence,  # type: ignore[arg-type]
        verified_actual=verified_actual,
        source_id=source_id,
        source_url=source_url,
        mapping_note=mapping_note,
        retrieved_at=retrieved_at,
    )


def _verify_manifest(
    calendar_path: Path,
    manifest_path: Path,
    *,
    calendar_hash: str,
    source_ids: set[str],
    source_urls: set[str],
) -> None:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CFTCReleaseManifestError(
            f"cannot read CFTC release manifest: {manifest_path}"
        ) from error
    expected = {
        "schema_version": 1,
        "dataset_kind": "cftc_cot_release_calendar",
        "calendar_file": calendar_path.name,
        "calendar_sha256": calendar_hash,
    }
    for key, value in expected.items():
        if not isinstance(manifest, dict) or manifest.get(key) != value:
            raise CFTCReleaseManifestError(
                f"CFTC release manifest {key} does not match {value!r}"
            )
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise CFTCReleaseManifestError("CFTC release manifest sources are missing")
    manifest_root = manifest_path.resolve().parent
    catalog_ids: set[str] = set()
    catalog_urls: set[str] = set()
    for position, source in enumerate(sources):
        if not isinstance(source, dict):
            raise CFTCReleaseManifestError(f"manifest source {position} must be an object")
        source_id = source.get("source_id")
        url = source.get("url")
        raw_path_value = source.get("raw_path")
        hash_path_value = source.get("sha256_path")
        raw_hash = source.get("raw_sha256")
        if not isinstance(source_id, str) or not source_id:
            raise CFTCReleaseManifestError(f"manifest source {position} ID is invalid")
        if source_id in catalog_ids:
            raise CFTCReleaseManifestError(f"duplicate manifest source ID {source_id!r}")
        if (
            not isinstance(url, str)
            or urlparse(url).scheme not in {"http", "https"}
            or not urlparse(url).netloc
        ):
            raise CFTCReleaseManifestError(f"manifest source {position} URL is invalid")
        if not isinstance(raw_path_value, str) or not raw_path_value:
            raise CFTCReleaseManifestError(f"manifest source {position} raw_path is invalid")
        if not isinstance(hash_path_value, str) or not hash_path_value:
            raise CFTCReleaseManifestError(
                f"manifest source {position} sha256_path is invalid"
            )
        if not isinstance(raw_hash, str) or _HASH_PATTERN.fullmatch(raw_hash) is None:
            raise CFTCReleaseManifestError(f"manifest source {position} SHA-256 is invalid")
        raw_path = (manifest_root / raw_path_value).resolve()
        hash_path = (manifest_root / hash_path_value).resolve()
        if not raw_path.is_relative_to(manifest_root) or not hash_path.is_relative_to(
            manifest_root
        ):
            raise CFTCReleaseManifestError(
                f"manifest source {position} escapes the manifest directory"
            )
        if not raw_path.is_file() or _sha256_file(raw_path) != raw_hash:
            raise CFTCReleaseManifestError(
                f"manifest source {position} raw file or SHA-256 does not match"
            )
        try:
            sidecar_hash = hash_path.read_text(encoding="ascii").split()[0]
        except (OSError, UnicodeError, IndexError) as error:
            raise CFTCReleaseManifestError(
                f"manifest source {position} SHA-256 sidecar is unreadable"
            ) from error
        if sidecar_hash != raw_hash:
            raise CFTCReleaseManifestError(
                f"manifest source {position} SHA-256 sidecar does not match"
            )
        catalog_ids.add(source_id)
        catalog_urls.add(url)
    if not source_ids.issubset(catalog_ids):
        raise CFTCReleaseManifestError(
            "calendar references source IDs absent from the raw-source manifest"
        )
    if not source_urls.issubset(catalog_urls):
        raise CFTCReleaseManifestError(
            "calendar references source URLs absent from the raw-source manifest"
        )


def _parse_date(value: date | str, *, field: str) -> date:
    if isinstance(value, datetime):
        raise CFTCReleaseCalendarError(f"{field} must be a date without a time")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError) as error:
        raise CFTCReleaseCalendarError(f"{field} is not an ISO date") from error


def _parse_datetime(value: datetime | str, *, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except (TypeError, ValueError) as error:
            raise CFTCReleaseCalendarError(f"{field} is not an ISO datetime") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CFTCReleaseCalendarError(f"{field} must include an explicit timezone")
    return parsed.astimezone(UTC)


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
