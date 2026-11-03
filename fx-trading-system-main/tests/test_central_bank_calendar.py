from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fx_system.central_bank_calendar import (
    AUTHORITY_CONTRACT,
    CENTRAL_BANK_COLUMNS,
    CentralBankCalendarError,
    CentralBankManifestError,
    load_central_bank_calendar,
)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _base_rows(tmp_path: Path) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    definitions = [
        ("FED", "2020-03-15", "17:00", "2020-03-15T21:00:00Z", "verified_actual_publication"),
        ("ECB", "2020-03-18", "", "", "official_date_only"),
        ("BOE", "2020-03-19", "12:00", "2020-03-19T12:00:00Z", "official_event_scheduled_time"),
        ("BOJ", "2020-05-22", "10:01", "2020-05-22T01:01:00Z", "verified_actual_publication"),
        ("SNB", "2020-06-18", "09:30", "2020-06-18T07:30:00Z", "official_rule_derived"),
        ("BOC", "2024-01-24", "09:45", "2024-01-24T14:45:00Z", "official_rule_derived"),
        ("RBA", "2024-02-06", "14:30", "2024-02-06T03:30:00Z", "official_rule_derived"),
        ("RBNZ", "2019-02-13", "14:00", "2019-02-13T01:00:00Z", "official_rule_derived"),
    ]
    rows: list[dict[str, str]] = []
    sources: list[dict[str, object]] = []
    for authority, day, local_time, utc_time, quality in definitions:
        currency, tzid = AUTHORITY_CONTRACT[authority]
        payload = f"official evidence for {authority}".encode()
        digest = _sha(payload)
        raw = tmp_path / "raw" / f"{authority.lower()}.html"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(payload)
        sidecar = raw.with_suffix(".html.sha256")
        sidecar.write_text(f"{digest}  {raw.name}\n", encoding="ascii")
        url = f"https://official.example/{authority.lower()}"
        sources.append(
            {
                "source_id": authority.lower(),
                "url": url,
                "raw_path": str(raw.relative_to(tmp_path)),
                "sha256_path": str(sidecar.relative_to(tmp_path)),
                "raw_sha256": digest,
            }
        )
        rule = quality == "official_rule_derived"
        rows.append(
            {
                "event_id": f"{authority.lower()}.{day.replace('-', '')}.rate_decision",
                "currency": currency,
                "authority": authority,
                "event_type": "rate_decision",
                "scheduled_status": "unscheduled" if authority in {"FED", "ECB"} else "scheduled",
                "decision_date_local": day,
                "release_time_local": local_time,
                "release_tzid": tzid,
                "release_time_raw": (
                    "date stated without time" if not local_time else "official time"
                ),
                "release_at_utc": utc_time,
                "timestamp_quality": quality,
                "rule_id": f"{authority.lower()}.test.rule" if rule else "",
                "rule_effective_from": "2016-01-01" if rule else "",
                "rule_effective_to": "2025-12-31" if rule else "",
                "source_url": url,
                "source_document_type": "official_test_document",
                "source_title": f"{authority} policy evidence",
                "retrieved_at_utc": "2026-07-16T00:00:00Z",
                "source_sha256": digest,
                "supersedes_event_id": "",
                "cancelled": "false",
                "notes": "test fixture",
            }
        )
    rows.sort(
        key=lambda row: (
            row["decision_date_local"],
            row["release_at_utc"] or "9999-12-31T23:59:59Z",
            row["authority"],
            row["event_type"],
            row["event_id"],
        )
    )
    return rows, sources


def _write_contract(tmp_path: Path) -> tuple[Path, Path]:
    rows, sources = _base_rows(tmp_path)
    calendar_path = tmp_path / "central_bank_policy_events_2016_2025.csv"
    with calendar_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CENTRAL_BANK_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    manifest_path = tmp_path / "central_bank_policy_events_2016_2025.manifest.json"
    manifest = {
        "schema_version": 1,
        "dataset_kind": "central_bank_policy_event_calendar",
        "created_at": "2026-07-16T00:00:00Z",
        "coverage_start": "2016-01-01",
        "coverage_end": "2025-12-31",
        "calendar_file": calendar_path.name,
        "calendar_sha256": _sha(calendar_path.read_bytes()),
        "rows": len(rows),
        "adapters": [
            {"authority": authority, "status": "complete", "row_count": 1}
            for authority in AUTHORITY_CONTRACT
        ],
        "sources": sources,
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return calendar_path, manifest_path


def test_loader_preserves_actual_rule_and_date_only_timing(tmp_path: Path) -> None:
    calendar_path, manifest_path = _write_contract(tmp_path)
    calendar = load_central_bank_calendar(
        calendar_path,
        manifest_path=manifest_path,
        knowledge_cutoff="2026-07-16T00:00:00Z",
    )

    fed = calendar.event("fed.20200315.rate_decision")
    assert fed.has_verified_actual_timestamp is True
    assert fed.release_at_utc == datetime(2020, 3, 15, 21, 0, tzinfo=UTC)

    boc = calendar.event("boc.20240124.rate_decision")
    assert boc.timestamp_quality == "official_rule_derived"
    assert boc.release_at_utc == datetime(2024, 1, 24, 14, 45, tzinfo=UTC)

    rbnz = calendar.event("rbnz.20190213.rate_decision")
    assert rbnz.release_at_utc == datetime(2019, 2, 13, 1, 0, tzinfo=UTC)

    ecb = calendar.event("ecb.20200318.rate_decision")
    assert ecb.is_date_only is True
    start, end = ecb.blackout_interval_utc()
    assert start == datetime(2020, 3, 17, 23, 0, tzinfo=UTC)
    assert end == datetime(2020, 3, 18, 23, 0, tzinfo=UTC)
    assert end - start == timedelta(days=1)


def test_date_only_cannot_smuggle_a_minute(tmp_path: Path) -> None:
    calendar_path, manifest_path = _write_contract(tmp_path)
    rows = list(csv.DictReader(calendar_path.read_text(encoding="utf-8").splitlines()))
    ecb = next(row for row in rows if row["authority"] == "ECB")
    ecb["release_time_local"] = "14:00"
    ecb["release_at_utc"] = "2020-03-18T13:00:00Z"
    with calendar_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CENTRAL_BANK_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["calendar_sha256"] = _sha(calendar_path.read_bytes())
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(CentralBankCalendarError, match="cannot contain a publication minute"):
        load_central_bank_calendar(
            calendar_path,
            manifest_path=manifest_path,
            knowledge_cutoff="2026-07-16T00:00:00Z",
        )


def test_incomplete_adapter_and_tampered_raw_fail_closed(tmp_path: Path) -> None:
    calendar_path, manifest_path = _write_contract(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["adapters"][0]["status"] = "fail_closed"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CentralBankManifestError, match="incomplete adapters"):
        load_central_bank_calendar(
            calendar_path,
            manifest_path=manifest_path,
            knowledge_cutoff="2026-07-16T00:00:00Z",
        )

    manifest["adapters"][0]["status"] = "complete"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / manifest["sources"][0]["raw_path"]).write_text("tampered", encoding="utf-8")
    with pytest.raises(CentralBankManifestError, match="raw evidence hash failed"):
        load_central_bank_calendar(
            calendar_path,
            manifest_path=manifest_path,
            knowledge_cutoff="2026-07-16T00:00:00Z",
        )


def test_sha_sidecar_tampering_is_detected(tmp_path: Path) -> None:
    calendar_path, manifest_path = _write_contract(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sidecar = tmp_path / manifest["sources"][0]["sha256_path"]
    sidecar.write_text("0" * 64 + "  fake.html\n", encoding="ascii")

    with pytest.raises(CentralBankManifestError, match="sidecar does not match"):
        load_central_bank_calendar(
            calendar_path,
            manifest_path=manifest_path,
            knowledge_cutoff="2026-07-16T00:00:00Z",
        )


def test_duplicate_event_and_cancelled_blackout_are_fail_closed(tmp_path: Path) -> None:
    calendar_path, manifest_path = _write_contract(tmp_path)
    rows = list(csv.DictReader(calendar_path.read_text(encoding="utf-8").splitlines()))
    rows.append(dict(rows[0]))
    with calendar_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CENTRAL_BANK_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["calendar_sha256"] = _sha(calendar_path.read_bytes())
    manifest["rows"] = len(rows)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CentralBankCalendarError, match="duplicate event_id"):
        load_central_bank_calendar(
            calendar_path,
            manifest_path=manifest_path,
            knowledge_cutoff="2026-07-16T00:00:00Z",
        )

    calendar_path, manifest_path = _write_contract(tmp_path)
    rows = list(csv.DictReader(calendar_path.read_text(encoding="utf-8").splitlines()))
    ecb = next(row for row in rows if row["authority"] == "ECB")
    ecb["scheduled_status"] = "cancelled"
    ecb["cancelled"] = "true"
    with calendar_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CENTRAL_BANK_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["calendar_sha256"] = _sha(calendar_path.read_bytes())
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    calendar = load_central_bank_calendar(
        calendar_path,
        manifest_path=manifest_path,
        knowledge_cutoff="2026-07-16T00:00:00Z",
    )
    with pytest.raises(CentralBankCalendarError, match="has no blackout interval"):
        calendar.event("ecb.20200318.rate_decision").blackout_interval_utc()
