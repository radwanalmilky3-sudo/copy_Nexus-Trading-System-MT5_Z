from __future__ import annotations

import hashlib
import importlib.util
import json
import lzma
import sqlite3
import struct
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "audit_dukascopy_sqlite.py"
SPEC = importlib.util.spec_from_file_location("audit_dukascopy_sqlite", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
audit = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit
SPEC.loader.exec_module(audit)

DATABASE_SQL = """
CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE hours (
    hour_utc INTEGER PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('ok', 'no_data')),
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


def _payload(*records: tuple[int, int, int, float, float]) -> bytes:
    raw = b"".join(TICK_RECORD.pack(*record) for record in records)
    return lzma.compress(raw, format=lzma.FORMAT_ALONE)


def _create_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(DATABASE_SQL)
        metadata = {
            "database_schema_version": "1",
            "parser_version": "dukascopy-bi5-v1",
            "provider": "dukascopy",
            "base_url": "https://datafeed.dukascopy.com/datafeed",
            "symbol": "EURUSD",
            "price_divisor": "100000",
            "requested_start": "2025-01-06T00:00:00Z",
            "requested_end_exclusive": "2025-01-06T03:00:00Z",
            "expected_hours": "3",
            "completed_hours": "3",
            "ok_hours": "2",
            "no_data_hours": "1",
            "missing_hours": "0",
        }
        connection.executemany("INSERT INTO metadata VALUES (?, ?)", metadata.items())


def _store_ok(
    path: Path,
    hour: str,
    records: tuple[tuple[int, int, int, float, float], ...],
) -> None:
    payload = _payload(*records)
    epoch = int(audit.datetime.fromisoformat(hour.replace("Z", "+00:00")).timestamp())
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO hours VALUES (?, 'ok', ?, ?, ?, ?, ?, ?, 200, ?, ?)",
            (
                epoch,
                payload,
                hashlib.sha256(payload).hexdigest(),
                len(payload),
                len(records),
                records[0][0],
                records[-1][0],
                "2026-01-01T00:00:00+00:00",
                audit._source_url("EURUSD", epoch),
            ),
        )


def _store_no_data(path: Path, hour: str) -> None:
    epoch = int(audit.datetime.fromisoformat(hour.replace("Z", "+00:00")).timestamp())
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO hours VALUES (?, 'no_data', NULL, NULL, 0, 0, NULL, NULL, 404, ?, ?)",
            (
                epoch,
                "2026-01-01T00:00:00+00:00",
                audit._source_url("EURUSD", epoch),
            ),
        )


def _complete_database(path: Path) -> None:
    _create_database(path)
    _store_ok(
        path,
        "2025-01-06T00:00:00Z",
        (
            (0, 110_002, 110_000, 1.0, 2.0),
            (1_000, 110_004, 110_001, 3.0, 4.0),
            (1_000, 110_005, 110_002, 5.0, 6.0),
        ),
    )
    _store_no_data(path, "2025-01-06T01:00:00Z")
    _store_ok(
        path,
        "2025-01-06T02:00:00Z",
        ((0, 110_008, 110_005, 7.0, 8.0),),
    )


def test_audit_streams_valid_database_without_modifying_it(tmp_path) -> None:
    path = tmp_path / "EURUSD.sqlite"
    _complete_database(path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    report = audit.audit_database(path, "EUR/USD", expected_file_sha256=before)
    output = audit.write_report(report, tmp_path / "reports", "EURUSD")

    assert report["result"] == {"passed": True}
    assert report["transport"]["matched"] is True
    assert report["coverage"]["expected_candidate_hours"] == 3
    assert report["coverage"]["ok_hours"] == 2
    assert report["coverage"]["no_data_hours"] == 1
    assert report["coverage"]["missing_hours"] == 0
    assert report["payloads"]["sha256_matches"] == 2
    assert report["payloads"]["lzma_decoded_rows"] == 2
    assert report["ticks"]["duplicate_offset"] == 1
    assert report["market"]["quotes"]["valid_quote_ticks"] == 4
    assert output.is_file()
    assert json.loads(output.read_text(encoding="utf-8"))["result"] == {"passed": True}
    assert (
        audit.main(
            [
                str(path),
                "--symbol",
                "EURUSD",
                "--output-dir",
                str(tmp_path / "cli-reports"),
            ]
        )
        == 0
    )
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_audit_reports_tick_count_mismatch(tmp_path) -> None:
    path = tmp_path / "EURUSD.sqlite"
    _complete_database(path)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE hours SET tick_count = 99 WHERE status = 'ok'")

    report = audit.audit_database(path, "EURUSD")

    assert report["result"] == {"passed": False}
    assert report["payloads"]["tick_count_mismatches"] == 2
    assert report["issues"]["counts_by_code"]["tick_count_mismatch"] == 2
