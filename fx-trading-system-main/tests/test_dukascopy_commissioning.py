"""Research-only two-symbol commissioning tests."""

from __future__ import annotations

import hashlib
import json
import lzma
import sqlite3
import struct
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

from fx_system.data import DUKASCOPY_PRICE_DIVISORS
from fx_system.dukascopy_commissioning import run_two_symbol_commissioning
from fx_system.dukascopy_event_data import BASE_URL, PARSER_VERSION
from fx_system.intraday_calendar import fx_session_bounds

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


def _hour_range(start: pd.Timestamp, end: pd.Timestamp) -> set[pd.Timestamp]:
    return set(pd.date_range(start.floor("h"), end.ceil("h"), freq="1h", inclusive="left"))


def _write_symbol(root: Path, audit_root: Path, symbol: str) -> None:
    session_bounds = fx_session_bounds(date(2025, 1, 6))
    session_start = pd.Timestamp(session_bounds.start_utc)
    session_end = pd.Timestamp(session_bounds.end_utc)
    hours = _hour_range(session_start, session_end)
    # The New York event probe straddles the session end and needs the next hour.
    hours.add(pd.Timestamp("2025-01-07T22:00:00Z"))
    database = root / f"{symbol}.sqlite"
    divisor = DUKASCOPY_PRICE_DIVISORS[symbol]
    metadata = {
        "database_schema_version": "1",
        "parser_version": PARSER_VERSION,
        "provider": "dukascopy",
        "base_url": BASE_URL,
        "symbol": symbol,
        "price_divisor": str(divisor),
        "requested_start": "2016-01-01T00:00:00Z",
        "requested_end_exclusive": "2025-09-15T00:00:00Z",
    }
    with sqlite3.connect(database) as connection:
        connection.executescript(DATABASE_SQL)
        connection.executemany("INSERT INTO metadata VALUES (?, ?)", metadata.items())
        for sequence, hour in enumerate(sorted(hours)):
            offsets = {1, 3_599_999}
            if hour == pd.Timestamp("2025-01-07T00:00:00Z"):
                offsets.update({3_299_000, 3_301_000})
            base = int((1.10 + sequence * 0.00001) * divisor)
            records = [
                (offset, base + 2, base, 1.0, 1.0)
                for offset in sorted(offsets)
            ]
            raw = b"".join(TICK_RECORD.pack(*record) for record in records)
            payload = lzma.compress(raw, format=lzma.FORMAT_ALONE)
            connection.execute(
                "INSERT INTO hours VALUES (?, 'ok', ?, ?, ?, ?, ?, ?, 200, ?, ?)",
                (
                    int(hour.timestamp()),
                    payload,
                    hashlib.sha256(payload).hexdigest(),
                    len(payload),
                    len(records),
                    records[0][0],
                    records[-1][0],
                    datetime.now(UTC).isoformat(),
                    "https://example.test/hour.bi5",
                ),
            )

    digest = hashlib.sha256(database.read_bytes()).hexdigest()
    info = {
        "schema_version": 1,
        "program_version": "1.0.0",
        "symbol": symbol,
        "file": database.name,
        "bytes": database.stat().st_size,
        "sha256": digest,
        "integrity": "ok",
        "metadata": metadata,
    }
    Path(f"{database}.sha256").write_text(
        f"{digest}  {database.name}\n",
        encoding="utf-8",
    )
    Path(f"{database}.json").write_text(json.dumps(info), encoding="utf-8")
    audit = {
        "result": {"passed": True},
        "transport": {"actual_file_sha256": digest, "matched": True},
        "database": {"bytes": database.stat().st_size, "requested_symbol": symbol},
    }
    (audit_root / f"{symbol}_dukascopy_audit.json").write_text(
        json.dumps(audit),
        encoding="utf-8",
    )


def test_two_symbol_commissioning_checks_real_payload_boundaries_without_outcomes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sqlite"
    audit_root = tmp_path / "audit"
    root.mkdir()
    audit_root.mkdir()
    for symbol in ("EURUSD", "GBPUSD"):
        _write_symbol(root, audit_root, symbol)

    report = run_two_symbol_commissioning(
        root,
        audit_directory=audit_root,
        session_dates=("2025-01-06",),
        event_date="2025-01-07",
    )

    assert report["commissioning_verdict"] == "commissioning_pass_research_only"
    assert report["checks"] == {
        "database_evidence_ok": True,
        "session_boundaries_ok": True,
        "event_boundaries_ok": True,
    }
    assert len(report["session_probes"]) == 2
    assert len(report["event_probes"]) == 6
    assert all(item["boundary_within_5_seconds"] for item in report["session_probes"])
    assert all(item["boundary_ready"] for item in report["event_probes"])
    assert report["formal_research_ready"] is False
    assert report["return_labels_opened"] is False
    assert report["factor_outcome_evaluations_added"] == 0
    assert report["trading_approval"] is False
    assert report["intake"]["full_14_formal_ready"] is False


def test_two_symbol_commissioning_rejects_scope_expansion(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must be exactly"):
        run_two_symbol_commissioning(
            tmp_path,
            symbols=("EURUSD", "USDJPY"),
            session_dates=(date(2025, 1, 6),),
        )
