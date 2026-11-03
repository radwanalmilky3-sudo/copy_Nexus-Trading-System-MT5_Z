from __future__ import annotations

import hashlib
import importlib.util
import lzma
import sqlite3
import struct
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "compare_dukascopy_fred_spot.py"
SPEC = importlib.util.spec_from_file_location("compare_dukascopy_fred_spot", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
comparison = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = comparison
SPEC.loader.exec_module(comparison)

TICK_RECORD = struct.Struct(">iiiff")


def _payload(bid: int, ask: int) -> bytes:
    return lzma.compress(
        TICK_RECORD.pack(100, ask, bid, 1.0, 2.0),
        format=lzma.FORMAT_ALONE,
    )


def _database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
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
            """
        )
        metadata = {
            "provider": "dukascopy",
            "parser_version": "dukascopy-bi5-v1",
            "symbol": "GBPUSD",
            "price_divisor": "100000",
            "requested_start": "2025-01-06T00:00:00Z",
            "requested_end_exclusive": "2025-01-08T00:00:00Z",
        }
        connection.executemany("INSERT INTO metadata VALUES (?, ?)", metadata.items())
        for hour, bid, ask in (
            ("2025-01-06T12:00:00+00:00", 124_990, 125_010),
            ("2025-01-07T12:00:00+00:00", 125_990, 126_010),
        ):
            payload = _payload(bid, ask)
            epoch = int(comparison.datetime.fromisoformat(hour).timestamp())
            connection.execute(
                "INSERT INTO hours VALUES (?, 'ok', ?, ?, ?, 1, 100, 100, 200, ?, ?)",
                (
                    epoch,
                    payload,
                    hashlib.sha256(payload).hexdigest(),
                    len(payload),
                    "2026-01-01T00:00:00+00:00",
                    "https://example.test/ticks.bi5",
                ),
            )


def test_compare_matches_reference_without_modifying_database(tmp_path: Path) -> None:
    database = tmp_path / "GBPUSD.sqlite"
    reference = tmp_path / "DEXUSUK.csv"
    _database(database)
    reference.write_text(
        "observation_date,DEXUSUK\n2025-01-06,1.2500\n2025-01-07,1.2600\n",
        encoding="utf-8",
    )
    before = hashlib.sha256(database.read_bytes()).hexdigest()

    report = comparison.compare(
        database,
        reference,
        symbol="GBP/USD",
        series_id="DEXUSUK",
        timezone_name="UTC",
        reference_hour=12,
        maximum_delay_seconds=1.0,
    )

    assert report["matched_observations"] == 2
    assert report["unmatched"] == {}
    assert report["level_correlation"] == 1.0
    assert report["absolute_difference_bps"]["maximum"] == 0.0
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
