from __future__ import annotations

import hashlib
import json
from calendar import monthrange
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fx_system.publication_calendar import (
    PublicationCalendarError,
    PublicationManifestError,
    actual_wmr_month_end,
    load_publication_calendar,
)

HEADER = "event_name,local_date,status,local_time,timezone,source_url,quality,retrieved_at\n"
SOURCE = "https://calendar.example.test/official"
CUTOFF = datetime(2026, 1, 3, tzinfo=UTC)


def _write_calendar(path: Path, rows: list[str]) -> Path:
    path.write_text(HEADER + "".join(f"{row}\n" for row in rows), encoding="utf-8")
    return path


def _wmr_row(
    local_date: str,
    status: str = "published",
    local_time: str = "16:00",
    quality: str = "verified",
    retrieved_at: str = "2026-01-02T00:00:00Z",
) -> str:
    return (
        f"wmr_fix,{local_date},{status},{local_time},Europe/London,{SOURCE},"
        f"{quality},{retrieved_at}"
    )


def _complete_wmr_month(
    year: int,
    month: int,
    overrides: dict[int, tuple[str, str, str]] | None = None,
) -> list[str]:
    overrides = overrides or {}
    rows = []
    for day in range(1, monthrange(year, month)[1] + 1):
        status, local_time, quality = overrides.get(
            day, ("not_published", "16:00", "verified")
        )
        rows.append(
            _wmr_row(
                f"{year:04d}-{month:02d}-{day:02d}",
                status,
                local_time,
                quality,
            )
        )
    return rows


def _write_manifest(calendar_path: Path, raw_path: Path) -> Path:
    manifest_path = calendar_path.with_suffix(".manifest.json")
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dataset_kind": "benchmark_publication_calendar",
                "calendar_file": calendar_path.name,
                "calendar_sha256": hashlib.sha256(calendar_path.read_bytes()).hexdigest(),
                "sources": [
                    {
                        "url": SOURCE,
                        "raw_path": raw_path.name,
                        "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_formal_calendar_manifest_verifies_csv_and_raw_source_hashes(tmp_path: Path) -> None:
    calendar_path = _write_calendar(
        tmp_path / "calendar.csv", [_wmr_row("2025-12-30")]
    )
    raw_path = tmp_path / "official-source.pdf"
    raw_path.write_bytes(b"%PDF-verified-source")
    manifest_path = _write_manifest(calendar_path, raw_path)

    calendar = load_publication_calendar(
        calendar_path,
        knowledge_cutoff=CUTOFF,
        manifest_path=manifest_path,
        require_manifest=True,
    )

    assert calendar.manifest_verified
    assert calendar.calendar_sha256 == hashlib.sha256(calendar_path.read_bytes()).hexdigest()
    assert calendar.manifest_path == manifest_path

    raw_path.write_bytes(b"tampered")
    with pytest.raises(PublicationManifestError, match="raw evidence hash failed"):
        load_publication_calendar(
            calendar_path,
            knowledge_cutoff=CUTOFF,
            manifest_path=manifest_path,
        )


def test_required_calendar_manifest_cannot_be_omitted(tmp_path: Path) -> None:
    calendar_path = _write_calendar(
        tmp_path / "calendar.csv", [_wmr_row("2025-12-30")]
    )

    with pytest.raises(PublicationManifestError, match="source manifest is required"):
        load_publication_calendar(
            calendar_path,
            knowledge_cutoff=CUTOFF,
            require_manifest=True,
        )


def test_actual_wmr_month_end_uses_last_verified_publication_and_early_time(
    tmp_path: Path,
) -> None:
    path = _write_calendar(
        tmp_path / "calendar.csv",
        _complete_wmr_month(
            2025,
            12,
            {
                30: ("published", "16:00", "verified"),
                31: ("early_time", "13:00", "verified"),
            },
        ),
    )

    calendar = load_publication_calendar(path, knowledge_cutoff=CUTOFF)
    christmas = calendar.event_on("wmr_fix", "2025-12-25")
    month_end = actual_wmr_month_end(calendar, 2025, 12)

    assert christmas.was_published is False
    assert christmas.event_time_utc is None
    assert month_end.local_date.isoformat() == "2025-12-31"
    assert month_end.status == "early_time"
    assert month_end.local_time.isoformat(timespec="minutes") == "13:00"
    assert month_end.event_time_utc == datetime(2025, 12, 31, 13, tzinfo=UTC)


def test_rows_are_converted_individually_using_british_dst(tmp_path: Path) -> None:
    path = _write_calendar(
        tmp_path / "calendar.csv",
        [_wmr_row("2025-01-15"), _wmr_row("2025-07-15")],
    )

    calendar = load_publication_calendar(path, knowledge_cutoff=CUTOFF)

    assert calendar.event_on("wmr_fix", "2025-01-15").event_time_utc == datetime(
        2025, 1, 15, 16, tzinfo=UTC
    )
    assert calendar.event_on("wmr_fix", "2025-07-15").event_time_utc == datetime(
        2025, 7, 15, 15, tzinfo=UTC
    )


def test_tokyo_and_ecb_event_contracts_use_their_canonical_iana_zones(
    tmp_path: Path,
) -> None:
    rows = [
        f"tokyo_fix,2025-07-15,published,09:55,Asia/Tokyo,{SOURCE},verified,2026-01-02T00:00:00Z",
        f"ecb_fix,2025-07-15,published,14:15,Europe/Berlin,{SOURCE},verified,2026-01-02T00:00:00Z",
    ]
    calendar = load_publication_calendar(
        _write_calendar(tmp_path / "calendar.csv", rows), knowledge_cutoff=CUTOFF
    )

    assert calendar.event_on("tokyo_fix", "2025-07-15").event_time_utc == datetime(
        2025, 7, 15, 0, 55, tzinfo=UTC
    )
    assert calendar.event_on("ecb_fix", "2025-07-15").event_time_utc == datetime(
        2025, 7, 15, 12, 15, tzinfo=UTC
    )


def test_no_calendar_or_missing_date_refuses_weekday_fallback(tmp_path: Path) -> None:
    with pytest.raises(PublicationCalendarError, match="required"):
        load_publication_calendar(None, knowledge_cutoff=CUTOFF)
    with pytest.raises(PublicationCalendarError, match="required"):
        actual_wmr_month_end(None, 2025, 12)

    path = _write_calendar(tmp_path / "calendar.csv", [_wmr_row("2025-12-30")])
    calendar = load_publication_calendar(path, knowledge_cutoff=CUTOFF)
    with pytest.raises(PublicationCalendarError, match="inference is forbidden"):
        calendar.event_on("wmr_fix", "2025-12-29")


def test_formal_experiment_rejects_unverified_rows(tmp_path: Path) -> None:
    path = _write_calendar(
        tmp_path / "calendar.csv",
        _complete_wmr_month(
            2025,
            12,
            {day: ("not_published", "16:00", "unverified") for day in range(1, 32)}
            | {30: ("published", "16:00", "unverified")},
        ),
    )

    with pytest.raises(PublicationCalendarError, match="require quality='verified'"):
        load_publication_calendar(path, knowledge_cutoff=CUTOFF)

    exploratory = load_publication_calendar(path, knowledge_cutoff=CUTOFF, formal_experiment=False)
    assert exploratory.events[0].quality == "unverified"
    with pytest.raises(PublicationCalendarError, match="no verified published WMR"):
        exploratory.actual_wmr_month_end(2025, 12)


def test_month_end_requires_explicit_full_calendar_month_coverage(tmp_path: Path) -> None:
    path = _write_calendar(
        tmp_path / "calendar.csv",
        [_wmr_row("2025-12-30"), _wmr_row("2025-12-31", "not_published")],
    )
    calendar = load_publication_calendar(path, knowledge_cutoff=CUTOFF)

    with pytest.raises(PublicationCalendarError, match="coverage.*incomplete"):
        calendar.actual_wmr_month_end(2025, 12)


def test_duplicate_event_date_is_ambiguous_and_rejected(tmp_path: Path) -> None:
    path = _write_calendar(
        tmp_path / "calendar.csv",
        [_wmr_row("2025-12-30"), _wmr_row("2025-12-30", "not_published")],
    )

    with pytest.raises(PublicationCalendarError, match="duplicate/ambiguous"):
        load_publication_calendar(path, knowledge_cutoff=CUTOFF)


def test_retrieval_after_experiment_cutoff_is_future_information(tmp_path: Path) -> None:
    path = _write_calendar(
        tmp_path / "calendar.csv",
        [_wmr_row("2025-12-30", retrieved_at="2026-01-04T00:00:00Z")],
    )

    with pytest.raises(PublicationCalendarError, match="after knowledge_cutoff"):
        load_publication_calendar(path, knowledge_cutoff=CUTOFF)


def test_dst_ambiguous_early_local_time_is_rejected(tmp_path: Path) -> None:
    path = _write_calendar(
        tmp_path / "calendar.csv",
        [_wmr_row("2025-10-26", "early_time", "01:30")],
    )

    with pytest.raises(PublicationCalendarError, match="ambiguous local time"):
        load_publication_calendar(path, knowledge_cutoff=CUTOFF)


def test_early_time_must_explicitly_override_default_time(tmp_path: Path) -> None:
    wrong_status = _write_calendar(
        tmp_path / "wrong_status.csv", [_wmr_row("2025-12-31", "published", "13:00")]
    )
    not_early = _write_calendar(
        tmp_path / "not_early.csv", [_wmr_row("2025-12-31", "early_time", "16:00")]
    )

    with pytest.raises(PublicationCalendarError, match="use early_time"):
        load_publication_calendar(wrong_status, knowledge_cutoff=CUTOFF)
    with pytest.raises(PublicationCalendarError, match="must be earlier"):
        load_publication_calendar(not_early, knowledge_cutoff=CUTOFF)


@pytest.mark.parametrize(
    "row",
    [
        "london_fix,2025-12-30,published,16:00,Europe/London,"
        f"{SOURCE},verified,2026-01-02T00:00:00Z",
        f"wmr_fix,2025-12-30,published,16:00,Etc/UTC,{SOURCE},verified,2026-01-02T00:00:00Z",
        "wmr_fix,2025-12-30,published,16:00,Europe/London,not-a-url,verified,2026-01-02T00:00:00Z",
        f"wmr_fix,2025-12-30,published,16:00,Europe/London,{SOURCE},verified,2026-01-02T00:00:00",
    ],
)
def test_invalid_or_ambiguous_contract_fields_fail_closed(tmp_path: Path, row: str) -> None:
    path = _write_calendar(tmp_path / "calendar.csv", [row])

    with pytest.raises(PublicationCalendarError):
        load_publication_calendar(path, knowledge_cutoff=CUTOFF)


def test_extra_csv_field_is_rejected_instead_of_ignored(tmp_path: Path) -> None:
    path = _write_calendar(tmp_path / "calendar.csv", [_wmr_row("2025-12-30") + ",unexpected"])

    with pytest.raises(PublicationCalendarError, match="more fields"):
        load_publication_calendar(path, knowledge_cutoff=CUTOFF)
