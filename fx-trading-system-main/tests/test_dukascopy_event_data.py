from __future__ import annotations

import hashlib
import json
import lzma
import sqlite3
import struct
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest

from fx_system.dukascopy_event_data import (
    BASE_URL,
    PARSER_VERSION,
    DatabaseContractError,
    HourStatusError,
    PayloadIntegrityError,
    TransferIntegrityError,
    load_tick_window,
    select_first_tick_at_or_after,
    select_last_tick_at_or_before,
    verify_database_transfer,
)

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


def _payload(*records: tuple[int, int, int, float, float]) -> bytes:
    raw = b"".join(TICK_RECORD.pack(*record) for record in records)
    return lzma.compress(raw, format=lzma.FORMAT_ALONE)


def _create_database(path: Path, *, parser_version: str = "dukascopy-bi5-v1") -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(DATABASE_SQL)
        metadata = {
            "database_schema_version": "1",
            "parser_version": parser_version,
            "provider": "dukascopy",
            "base_url": BASE_URL,
            "symbol": "EURUSD",
            "price_divisor": "100000",
        }
        connection.executemany("INSERT INTO metadata VALUES (?, ?)", metadata.items())


def _store_ok(
    path: Path,
    hour: str,
    records: tuple[tuple[int, int, int, float, float], ...],
    *,
    payload_hash: str | None = None,
) -> None:
    payload = _payload(*records)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO hours VALUES (?, 'ok', ?, ?, ?, ?, ?, ?, 200, ?, ?)",
            (
                int(pd.Timestamp(hour).timestamp()),
                payload,
                payload_hash or hashlib.sha256(payload).hexdigest(),
                len(payload),
                len(records),
                records[0][0],
                records[-1][0],
                "2026-01-01T00:00:00+00:00",
                "https://example.test/hour.bi5",
            ),
        )


def _store_no_data(path: Path, hour: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO hours VALUES (?, 'no_data', NULL, NULL, 0, 0, NULL, NULL, "
            "404, ?, ?)",
            (
                int(pd.Timestamp(hour).timestamp()),
                "2026-01-01T00:00:00+00:00",
                "https://example.test/missing.bi5",
            ),
        )


def _write_transfer_contract(path: Path) -> Path:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    metadata = {
        "database_schema_version": "1",
        "parser_version": PARSER_VERSION,
        "provider": "dukascopy",
        "base_url": BASE_URL,
        "symbol": "EURUSD",
        "price_divisor": "100000",
    }
    entry = {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": digest,
        "integrity": "ok",
        "metadata": metadata,
        "counts": {"ok": 1, "no_data": 0},
        "first_hour": "2025-01-06T00:00:00Z",
        "last_hour": "2025-01-06T00:00:00Z",
    }
    Path(f"{path}.sha256").write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    Path(f"{path}.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "program_version": "1.0.0",
                "symbol": "EURUSD",
                **entry,
            }
        ),
        encoding="utf-8",
    )
    manifest_path = path.parent / "_sqlite_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "program_version": "1.0.0",
                "created_at": "2026-01-02T00:00:00+00:00",
                "parser_version": PARSER_VERSION,
                "databases": {"EURUSD": entry},
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_read_only_window_decodes_only_related_hours_and_deduplicates(tmp_path) -> None:
    path = tmp_path / "EURUSD.sqlite"
    _create_database(path)
    _store_ok(
        path,
        "2025-01-06T00:00:00Z",
        (
            (0, 110_002, 110_000, 1.0, 2.0),
            (1_000, 110_004, 110_001, 3.0, 4.0),
            # The last update at a duplicated millisecond is retained.
            (1_000, 110_005, 110_002, 5.0, 6.0),
            (3_599_000, 110_006, 110_003, 7.0, 8.0),
        ),
    )
    _store_ok(
        path,
        "2025-01-06T01:00:00Z",
        (
            (0, 110_007, 110_004, 9.0, 10.0),
            (2_000, 110_008, 110_005, 11.0, 12.0),
        ),
    )
    _store_no_data(path, "2025-01-06T02:00:00Z")
    # A corrupt, out-of-window payload proves extraction does not decode all rows.
    _store_ok(
        path,
        "2025-01-06T03:00:00Z",
        ((0, 110_010, 110_008, 1.0, 1.0),),
        payload_hash="0" * 64,
    )
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    window = load_tick_window(
        path,
        "2025-01-06T00:00:00.500Z",
        "2025-01-06T03:00:00Z",
        symbol="EUR/USD",
        include_sizes=True,
    )

    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert window.complete
    assert window.payload_hashes_verified == 2
    assert window.duplicate_timestamps_removed == 1
    assert window.decoded_hours_utc == (
        pd.Timestamp("2025-01-06T00:00:00Z"),
        pd.Timestamp("2025-01-06T01:00:00Z"),
    )
    assert window.no_data_hours_utc == (pd.Timestamp("2025-01-06T02:00:00Z"),)
    assert not window.missing_hours_utc
    assert list(window.ticks) == ["timestamp", "bid", "ask", "bid_size", "ask_size"]
    assert window.ticks["timestamp"].is_monotonic_increasing
    assert window.ticks["timestamp"].is_unique
    assert (window.ticks["ask"] >= window.ticks["bid"]).all()
    duplicate_result = window.ticks.iloc[0]
    assert duplicate_result["timestamp"] == pd.Timestamp("2025-01-06T00:00:01Z")
    assert duplicate_result["bid"] == pytest.approx(1.10002)
    assert duplicate_result["ask_size"] == pytest.approx(5.0)
    # no_data stays empty; no boundary or forward-filled quote is introduced.
    assert len(window.ticks) == 4
    assert not window.ticks["timestamp"].between(
        pd.Timestamp("2025-01-06T02:00:00Z"),
        pd.Timestamp("2025-01-06T03:00:00Z"),
        inclusive="left",
    ).any()
    assert window.ticks.attrs["forward_filled"] is False
    assert window.ticks.attrs["database_transfer_verified"] is False


def test_whole_database_transfer_receipt_is_reused_by_narrow_event_windows(tmp_path) -> None:
    path = tmp_path / "EURUSD.sqlite"
    _create_database(path)
    _store_ok(
        path,
        "2025-01-06T00:00:00Z",
        ((0, 110_002, 110_000, 1.0, 2.0),),
    )
    manifest_path = _write_transfer_contract(path)

    receipt = verify_database_transfer(path, manifest_path, symbol="EUR/USD")
    window = load_tick_window(
        path,
        "2025-01-06T00:00:00Z",
        "2025-01-06T00:01:00Z",
        symbol="EURUSD",
        transfer_verification=receipt,
        require_transfer_verification=True,
    )

    assert receipt.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert window.transfer_verification is receipt
    assert window.ticks.attrs["database_transfer_verified"] is True
    assert window.ticks.attrs["database_sha256"] == receipt.sha256


def test_formal_event_window_requires_receipt_and_rejects_post_verification_change(
    tmp_path,
) -> None:
    path = tmp_path / "EURUSD.sqlite"
    _create_database(path)
    _store_no_data(path, "2025-01-06T00:00:00Z")
    manifest_path = _write_transfer_contract(path)
    receipt = verify_database_transfer(path, manifest_path)

    with pytest.raises(TransferIntegrityError, match="receipt is required"):
        load_tick_window(
            path,
            "2025-01-06T00:00:00Z",
            "2025-01-06T00:01:00Z",
            require_transfer_verification=True,
        )

    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO metadata VALUES ('post_verify_change', '1')")
    with pytest.raises(TransferIntegrityError, match="changed after"):
        load_tick_window(
            path,
            "2025-01-06T00:00:00Z",
            "2025-01-06T00:01:00Z",
            transfer_verification=receipt,
            require_transfer_verification=True,
        )


def test_transfer_verification_requires_manifest_and_both_matching_sidecars(tmp_path) -> None:
    path = tmp_path / "EURUSD.sqlite"
    _create_database(path)
    _store_no_data(path, "2025-01-06T00:00:00Z")
    manifest_path = _write_transfer_contract(path)
    Path(f"{path}.sha256").write_text(f"{'0' * 64}  {path.name}\n", encoding="utf-8")

    with pytest.raises(TransferIntegrityError, match="sidecar disagrees"):
        verify_database_transfer(path, manifest_path)


def test_missing_hour_marks_incomplete_and_blocks_quote_acceptance(tmp_path) -> None:
    path = tmp_path / "EURUSD.sqlite"
    _create_database(path)
    _store_ok(
        path,
        "2025-01-06T00:00:00Z",
        ((3_599_000, 110_002, 110_000, 1.0, 2.0),),
    )
    _store_ok(
        path,
        "2025-01-06T02:00:00Z",
        ((1_000, 110_004, 110_001, 3.0, 4.0),),
    )

    window = load_tick_window(
        path, "2025-01-06T00:59:00Z", "2025-01-06T02:01:01Z"
    )

    assert not window.complete
    assert window.missing_hours_utc == (pd.Timestamp("2025-01-06T01:00:00Z"),)
    assert len(window.ticks) == 2  # the missing hour is not forward-filled
    selected = select_last_tick_at_or_before(
        window,
        "2025-01-06T01:00:00Z",
        maximum_quote_age="2s",
    )
    assert selected.quote_timestamp == pd.Timestamp("2025-01-06T00:59:59Z")
    assert selected.quote_age == timedelta(seconds=1)
    assert not selected.accepted
    assert selected.rejection_reason == "incomplete_window"


def test_pre_and_post_decision_selectors_expose_age_and_delay_limits(tmp_path) -> None:
    path = tmp_path / "EURUSD.sqlite"
    _create_database(path)
    _store_ok(
        path,
        "2025-01-06T12:00:00Z",
        (
            (8_000, 110_002, 110_000, 1.0, 2.0),
            (13_000, 110_004, 110_001, 3.0, 4.0),
        ),
    )
    window = load_tick_window(
        path, "2025-01-06T12:00:00Z", "2025-01-06T12:01:00Z", include_sizes=False
    )
    decision = "2025-01-06T12:00:10Z"

    pre = select_last_tick_at_or_before(window, decision, maximum_quote_age="2s")
    assert pre.accepted
    assert pre.quote_timestamp == pd.Timestamp("2025-01-06T12:00:08Z")
    assert pre.quote_age == timedelta(seconds=2)
    assert pre.maximum_quote_age == timedelta(seconds=2)
    assert pre.execution_delay is None
    assert pre.bid_size is None

    stale = select_last_tick_at_or_before(window, decision, maximum_quote_age="1999ms")
    assert not stale.accepted
    assert stale.rejection_reason == "maximum_quote_age_exceeded"
    assert stale.quote_timestamp == pre.quote_timestamp

    post = select_first_tick_at_or_after(
        window, decision, maximum_execution_delay="3s"
    )
    assert post.accepted
    assert post.quote_timestamp == pd.Timestamp("2025-01-06T12:00:13Z")
    assert post.execution_delay == timedelta(seconds=3)
    assert post.maximum_execution_delay == timedelta(seconds=3)
    assert post.quote_age is None

    delayed = select_first_tick_at_or_after(
        window, decision, maximum_execution_delay="2999ms"
    )
    assert not delayed.accepted
    assert delayed.rejection_reason == "maximum_execution_delay_exceeded"


def test_rejects_parser_schema_hash_and_hour_status_contract_violations(tmp_path) -> None:
    bad_parser = tmp_path / "bad-parser.sqlite"
    _create_database(bad_parser, parser_version="unknown-parser")
    with pytest.raises(DatabaseContractError, match="parser_version"):
        load_tick_window(
            bad_parser, "2025-01-06T00:00:00Z", "2025-01-06T00:01:00Z"
        )

    bad_schema = tmp_path / "bad-schema.sqlite"
    with sqlite3.connect(bad_schema) as connection:
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("CREATE TABLE hours (hour_utc INTEGER PRIMARY KEY)")
    with pytest.raises(DatabaseContractError, match="hours schema"):
        load_tick_window(
            bad_schema, "2025-01-06T00:00:00Z", "2025-01-06T00:01:00Z"
        )

    bad_hash = tmp_path / "bad-hash.sqlite"
    _create_database(bad_hash)
    _store_ok(
        bad_hash,
        "2025-01-06T00:00:00Z",
        ((0, 110_002, 110_000, 1.0, 2.0),),
        payload_hash="f" * 64,
    )
    with pytest.raises(PayloadIntegrityError, match="SHA-256"):
        load_tick_window(
            bad_hash, "2025-01-06T00:00:00Z", "2025-01-06T00:01:00Z"
        )

    bad_status = tmp_path / "bad-status.sqlite"
    _create_database(bad_status)
    payload = _payload((0, 110_002, 110_000, 1.0, 2.0))
    with sqlite3.connect(bad_status) as connection:
        connection.execute(
            "INSERT INTO hours VALUES (?, 'no_data', ?, NULL, ?, 0, NULL, NULL, "
            "404, ?, ?)",
            (
                int(pd.Timestamp("2025-01-06T00:00:00Z").timestamp()),
                payload,
                len(payload),
                "2026-01-01T00:00:00+00:00",
                "https://example.test/missing.bi5",
            ),
        )
    with pytest.raises(HourStatusError, match="no_data"):
        load_tick_window(
            bad_status, "2025-01-06T00:00:00Z", "2025-01-06T00:01:00Z"
        )


def test_empty_complete_no_data_window_does_not_invent_a_quote(tmp_path) -> None:
    path = tmp_path / "EURUSD.sqlite"
    _create_database(path)
    _store_no_data(path, "2025-01-06T00:00:00Z")
    window = load_tick_window(
        path, "2025-01-06T00:00:00Z", "2025-01-06T00:30:00Z"
    )

    assert window.complete
    assert window.ticks.empty
    pre = select_last_tick_at_or_before(
        window, "2025-01-06T00:15:00Z", maximum_quote_age="1min"
    )
    post = select_first_tick_at_or_after(
        window, "2025-01-06T00:15:00Z", maximum_execution_delay="1min"
    )
    assert not pre.accepted and pre.rejection_reason == "no_tick_at_or_before_decision"
    assert not post.accepted and post.rejection_reason == "no_tick_at_or_after_decision"
