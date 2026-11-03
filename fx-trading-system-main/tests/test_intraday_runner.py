from __future__ import annotations

import hashlib
import json
import lzma
import sqlite3
import struct
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from fx_system.data import DUKASCOPY_PRICE_DIVISORS
from fx_system.dukascopy_event_data import BASE_URL, PARSER_VERSION
from fx_system.intraday_calendar import event_window
from fx_system.intraday_research import FIX_W_G9_LEGS, fix_w_segment_plan
from fx_system.intraday_runner import (
    fix_w_candidate_return_series,
    run_fix_w_from_sqlite,
)
from fx_system.publication_calendar import PublicationCalendar, PublicationEvent

DATABASE_SQL = """
CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE hours (
    hour_utc INTEGER PRIMARY KEY,
    status TEXT NOT NULL,
    payload BLOB,
    payload_sha256 TEXT,
    compressed_bytes INTEGER NOT NULL,
    tick_count INTEGER NOT NULL,
    first_offset_ms INTEGER,
    last_offset_ms INTEGER,
    http_status INTEGER,
    retrieved_at TEXT NOT NULL,
    source_url TEXT NOT NULL
);
CREATE INDEX idx_hours_status ON hours(status);
"""
TICK_RECORD = struct.Struct(">iiiff")


def _calendar(local_date: date, *, wmr_published: bool = True) -> PublicationCalendar:
    events: list[PublicationEvent] = []
    for name in ("tokyo_fix", "ecb_fix", "wmr_fix"):
        window = event_window(name, local_date)
        events.append(
            PublicationEvent(
                event_name=name,
                local_date=local_date,
                status=(
                    "not_published"
                    if name == "wmr_fix" and not wmr_published
                    else "published"
                ),
                local_time=window.center_utc.astimezone(
                    ZoneInfo(window.timezone)
                ).time().replace(tzinfo=None),
                timezone=window.timezone,
                source_url="https://calendar.example.test/official",
                quality="verified",
                retrieved_at=datetime(2026, 1, 2, tzinfo=UTC),
                scheduled_time_utc=window.center_utc,
            )
        )
    return PublicationCalendar(
        tuple(events),
        knowledge_cutoff=datetime(2026, 1, 3, tzinfo=UTC),
        formal_experiment=True,
        manifest_verified=True,
    )


def _calendar_for_dates(local_dates: list[date]) -> PublicationCalendar:
    return PublicationCalendar(
        tuple(
            event
            for local_date in local_dates
            for event in _calendar(local_date).events
        ),
        knowledge_cutoff=datetime(2026, 1, 3, tzinfo=UTC),
        formal_experiment=True,
        manifest_verified=True,
    )


def _market_mid(symbol: str) -> float:
    if symbol == "USDJPY":
        return 150.0
    if symbol in {"USDNOK", "USDSEK"}:
        return 10.0
    return 1.2


def _write_g9_databases(
    root: Path,
    local_date: date | list[date],
    calendar: PublicationCalendar,
    *,
    omit: tuple[str, pd.Timestamp] | None = None,
) -> Path:
    root.mkdir()
    local_dates = [local_date] if isinstance(local_date, date) else local_date
    segments = tuple(
        segment
        for value in local_dates
        for segment in fix_w_segment_plan(value, publication_calendar=calendar)
    )
    boundaries = sorted(
        {
            pd.Timestamp(boundary)
            for segment in segments
            for boundary in (segment.start_time, segment.end_time)
        }
    )
    manifest_entries: dict[str, object] = {}
    for _, (symbol, _) in FIX_W_G9_LEGS.items():
        divisor = DUKASCOPY_PRICE_DIVISORS[symbol]
        mid_integer = round(_market_mid(symbol) * divisor)
        records_by_hour: dict[pd.Timestamp, list[tuple[int, int, int, float, float]]] = {}
        for boundary in boundaries:
            for timestamp in (boundary - timedelta(seconds=1), boundary + timedelta(seconds=1)):
                hour = timestamp.floor("h")
                if omit is not None and symbol == omit[0] and hour == omit[1]:
                    continue
                offset = int((timestamp - hour).total_seconds() * 1_000)
                records_by_hour.setdefault(hour, []).append(
                    (offset, mid_integer + 1, mid_integer - 1, 1.0, 1.0)
                )

        path = root / f"{symbol}.sqlite"
        metadata = {
            "database_schema_version": "1",
            "parser_version": PARSER_VERSION,
            "provider": "dukascopy",
            "base_url": BASE_URL,
            "symbol": symbol,
            "price_divisor": str(divisor),
        }
        with sqlite3.connect(path) as connection:
            connection.executescript(DATABASE_SQL)
            connection.executemany("INSERT INTO metadata VALUES (?, ?)", metadata.items())
            for hour, records in sorted(records_by_hour.items()):
                ordered = sorted(records)
                raw = b"".join(TICK_RECORD.pack(*record) for record in ordered)
                payload = lzma.compress(raw, format=lzma.FORMAT_ALONE)
                connection.execute(
                    "INSERT INTO hours VALUES (?, 'ok', ?, ?, ?, ?, ?, ?, 200, ?, ?)",
                    (
                        int(hour.timestamp()),
                        payload,
                        hashlib.sha256(payload).hexdigest(),
                        len(payload),
                        len(ordered),
                        ordered[0][0],
                        ordered[-1][0],
                        "2026-01-01T00:00:00+00:00",
                        "https://example.test/hour.bi5",
                    ),
                )
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entry = {
            "file": path.name,
            "bytes": path.stat().st_size,
            "sha256": digest,
            "integrity": "ok",
            "metadata": metadata,
            "counts": {"ok": len(records_by_hour), "no_data": 0},
            "first_hour": min(records_by_hour).isoformat(),
            "last_hour": max(records_by_hour).isoformat(),
        }
        Path(f"{path}.sha256").write_text(f"{digest}  {path.name}\n", encoding="utf-8")
        Path(f"{path}.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "program_version": "1.1.0",
                    "symbol": symbol,
                    **entry,
                }
            ),
            encoding="utf-8",
        )
        manifest_entries[symbol] = entry
    manifest_path = root / "_sqlite_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "program_version": "1.1.0",
                "created_at": "2026-01-02T00:00:00+00:00",
                "parser_version": PARSER_VERSION,
                "databases": manifest_entries,
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_formal_fix_w_sqlite_runner_verifies_once_and_extracts_only_boundaries(
    tmp_path: Path,
) -> None:
    local_date = date(2025, 1, 15)
    calendar = _calendar(local_date)
    database_dir = tmp_path / "databases"
    manifest_path = _write_g9_databases(database_dir, local_date, calendar)

    result = run_fix_w_from_sqlite(
        database_dir,
        [local_date],
        publication_calendar=calendar,
        transfer_manifest_path=manifest_path,
    )

    assert len(result.transfer_audit) == 9
    assert result.transfer_audit["transfer_verified"].all()
    assert len(result.extraction_audit) == 9 * 6
    assert result.extraction_audit["window_complete"].all()
    assert result.extraction_audit["payload_hashes_verified"].sum() > 9 * 6
    assert len(result.leg_experiments) == 9
    assert set(result.leg_experiments["sample_status"]) == {"complete"}
    assert result.leg_experiments["source_window_complete"].all()
    assert len(result.composite_experiments) == 1
    assert result.composite_experiments.iloc[0]["sample_status"] == "complete"
    assert bool(result.composite_experiments.iloc[0]["source_window_complete"])
    assert pd.isna(fix_w_candidate_return_series(result).iloc[0])  # 60-day warmup
    assert pd.notna(
        fix_w_candidate_return_series(result, spread_filtered=False).iloc[0]
    )


def test_fix_w_sqlite_runner_suppresses_incomplete_source_hour(tmp_path: Path) -> None:
    local_date = date(2025, 1, 15)
    calendar = _calendar(local_date)
    tokyo_hour = pd.Timestamp(event_window("tokyo_fix", local_date).center_utc).floor("h")
    database_dir = tmp_path / "databases"
    manifest_path = _write_g9_databases(
        database_dir,
        local_date,
        calendar,
        omit=("USDJPY", tokyo_hour),
    )

    result = run_fix_w_from_sqlite(
        database_dir,
        [local_date],
        publication_calendar=calendar,
        transfer_manifest_path=manifest_path,
    )

    jpy = result.leg_experiments.loc[
        result.leg_experiments["foreign_currency"] == "JPY"
    ].iloc[0]
    composite = result.composite_experiments.iloc[0]
    assert not bool(jpy["source_window_complete"])
    assert jpy["sample_status"] == "incomplete_source_window"
    assert pd.isna(jpy["executable_long_log_return"])
    assert composite["sample_status"] == "incomplete_source_window"
    assert composite["source_incomplete_symbols"] == "USDJPY"
    assert pd.isna(composite["executable_long_log_return"])


def test_fix_w_sqlite_runner_builds_spread_history_across_dates_not_per_date(
    tmp_path: Path,
) -> None:
    local_dates = [date(2025, 1, 15), date(2025, 1, 16)]
    calendar = _calendar_for_dates(local_dates)
    database_dir = tmp_path / "databases"
    manifest_path = _write_g9_databases(database_dir, local_dates, calendar)

    result = run_fix_w_from_sqlite(
        database_dir,
        local_dates,
        publication_calendar=calendar,
        transfer_manifest_path=manifest_path,
    )

    eur = result.leg_experiments.loc[
        result.leg_experiments["foreign_currency"] == "EUR"
    ]
    assert list(eur["event_day_ordinal"]) == [0, 1]
    assert list(eur["pre_tokyo_spread_history_count"]) == [0, 1]
    assert (eur["spread_filter_status"] == "warmup").all()
    assert len(result.composite_experiments) == 2


def test_fix_w_sqlite_runner_does_not_hash_databases_for_closed_event_date(
    tmp_path: Path,
) -> None:
    local_date = date(2025, 1, 15)
    result = run_fix_w_from_sqlite(
        tmp_path,
        [local_date],
        publication_calendar=_calendar(local_date, wmr_published=False),
    )

    assert result.leg_experiments.empty
    assert result.composite_experiments.empty
    assert result.extraction_audit.empty
    assert result.transfer_audit.empty
