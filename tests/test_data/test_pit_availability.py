from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from shared.models import OHLCV
from services.nexus_data.duckdb_store import DataStore

BAR_TS_1 = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
BAR_TS_2 = datetime(2026, 1, 5, 10, 15, tzinfo=timezone.utc)
T_JUNE = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
T_JULY = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)


def _bar(ts: datetime, *, close: float = 102, volume: float = 10) -> OHLCV:
    return OHLCV(
        symbol="XAUUSD", timeframe="M15", open=100, high=105,
        low=99, close=close, volume=volume, timestamp=ts,
    )


async def _insert_legacy_null_quality_row(store: DataStore, ts: datetime) -> None:
    """Simulate a pre-migration row: NULL quality AND NULL available_at."""
    # Fresh test DBs create quality NOT NULL; production legacy DBs got the
    # column via nullable ALTER. Drop the index, relax, recreate.
    await store._run("DROP INDEX IF EXISTS idx_ohlcv_symbol_tf_ts")
    await store._run("ALTER TABLE ohlcv ALTER COLUMN quality DROP NOT NULL")
    await store._run(
        "CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_tf_ts "
        "ON ohlcv (symbol, timeframe, timestamp DESC)"
    )
    await store._run(
        "INSERT INTO ohlcv "
        "(symbol, timeframe, open, high, low, close, volume, timestamp, source, quality) "
        "VALUES ('XAUUSD', 'M15', 100, 105, 99, 102, 10, ?, 'mt5', NULL)",
        (ts,),
    )


@pytest.mark.asyncio
async def test_pit_query_excludes_legacy_rows_with_null_available_at(tmp_path, monkeypatch):
    monkeypatch.delenv("NEXUS_QUALITY_GATE", raising=False)
    store = DataStore(db_path=str(tmp_path / "pit-legacy.duckdb"))
    await store.init_tables()

    try:
        await _insert_legacy_null_quality_row(store, BAR_TS_1)
        await store.insert_ohlcv_batch([_bar(BAR_TS_2)])

        # No PIT params: legacy row still visible (pre-change behavior).
        all_rows = await store.query_ohlcv("XAUUSD", "M15", limit=10)
        assert [r.timestamp for r in all_rows] == [BAR_TS_2, BAR_TS_1]

        horizon = datetime.now(timezone.utc) + timedelta(seconds=5)
        pit_rows = await store.query_ohlcv(
            "XAUUSD", "M15", limit=10, available_through=horizon,
        )
        assert [r.timestamp for r in pit_rows] == [BAR_TS_2]
    finally:
        store.close()


@pytest.mark.asyncio
async def test_row_arriving_after_cutoff_is_excluded_then_included(tmp_path, monkeypatch):
    monkeypatch.delenv("NEXUS_QUALITY_GATE", raising=False)
    store = DataStore(db_path=str(tmp_path / "pit-future.duckdb"))
    await store.init_tables()

    try:
        before_insert = datetime.now(timezone.utc)
        await store.insert_ohlcv_batch([_bar(BAR_TS_1)])
        after_insert = datetime.now(timezone.utc)

        early = await store.query_ohlcv(
            "XAUUSD", "M15", limit=10,
            available_through=before_insert - timedelta(seconds=1),
        )
        assert early == []

        late = await store.query_ohlcv(
            "XAUUSD", "M15", limit=10,
            available_through=after_insert + timedelta(seconds=1),
        )
        assert [r.timestamp for r in late] == [BAR_TS_1]
    finally:
        store.close()


@pytest.mark.asyncio
async def test_max_staleness_s_filters_late_available_at_and_null_rows(tmp_path, monkeypatch):
    monkeypatch.delenv("NEXUS_QUALITY_GATE", raising=False)
    store = DataStore(db_path=str(tmp_path / "pit-staleness.duckdb"))
    await store.init_tables()

    try:
        await _insert_legacy_null_quality_row(store, BAR_TS_1)
        available_at = BAR_TS_2 + timedelta(seconds=100)
        await store.insert_ohlcv_batch([_bar(BAR_TS_2)], available_at=available_at)

        # Bar became available 100s after its open: TTL 50s hides it,
        # TTL 200s shows it; the NULL-available_at legacy row never shows.
        toostrict = await store.query_ohlcv(
            "XAUUSD", "M15", limit=10, max_staleness_s=50,
        )
        assert toostrict == []

        relaxed = await store.query_ohlcv(
            "XAUUSD", "M15", limit=10, max_staleness_s=200,
        )
        assert [r.timestamp for r in relaxed] == [BAR_TS_2]
    finally:
        store.close()


@pytest.mark.asyncio
async def test_fingerprint_ohlcv_deterministic_and_pit_sensitive(tmp_path, monkeypatch):
    monkeypatch.delenv("NEXUS_QUALITY_GATE", raising=False)
    store = DataStore(db_path=str(tmp_path / "pit-fingerprint.duckdb"))
    await store.init_tables()

    try:
        empty = await store.fingerprint_ohlcv("XAUUSD", "M15", T_JULY)
        assert empty["row_count"] == 0
        assert empty["content_hash"] == hashlib.sha256(b"").hexdigest()

        await store.insert_ohlcv_batch([_bar(BAR_TS_1)], available_at=T_JUNE)

        first = await store.fingerprint_ohlcv("XAUUSD", "M15", T_JUNE)
        assert first["row_count"] == 1
        assert first["symbol"] == "XAUUSD"
        assert first["timeframe"] == "M15"
        assert first["available_through"] == T_JUNE.isoformat()

        again = await store.fingerprint_ohlcv("XAUUSD", "M15", T_JUNE)
        assert again == first

        await store.insert_ohlcv_batch([_bar(BAR_TS_2, close=103)], available_at=T_JULY)

        still_at_june = await store.fingerprint_ohlcv("XAUUSD", "M15", T_JUNE)
        assert still_at_june == first

        at_july = await store.fingerprint_ohlcv("XAUUSD", "M15", T_JULY)
        assert at_july["row_count"] == 2
        assert at_july["content_hash"] != first["content_hash"]
    finally:
        store.close()


@pytest.mark.asyncio
async def test_revision_policy_identical_skip_then_correct_in_place(tmp_path, monkeypatch):
    monkeypatch.delenv("NEXUS_QUALITY_GATE", raising=False)
    store = DataStore(db_path=str(tmp_path / "pit-revision.duckdb"))
    await store.init_tables()

    try:
        batch = [_bar(BAR_TS_1), _bar(BAR_TS_2, close=103, volume=12)]
        submitted = await store.insert_ohlcv_batch(batch)
        assert submitted == 2

        # Identical re-insert: idempotent, revision stays NULL.
        await store.insert_ohlcv_batch(batch)
        rows = await store._fetch(
            "SELECT close, revision FROM ohlcv ORDER BY timestamp"
        )
        assert rows == [(102.0, None), (103.0, None)]

        # Same key, different close: in-place UPDATE, revision 1, no duplicate.
        await store.insert_ohlcv_batch([_bar(BAR_TS_1, close=101)])
        rows = await store._fetch(
            "SELECT close, revision FROM ohlcv ORDER BY timestamp"
        )
        assert rows == [(101.0, 1), (103.0, None)]
        count = await store._fetch("SELECT COUNT(*) FROM ohlcv")
        assert count[0][0] == 2
    finally:
        store.close()


@pytest.mark.asyncio
async def test_manifest_refreshed_after_batch_insert(tmp_path, monkeypatch):
    monkeypatch.delenv("NEXUS_QUALITY_GATE", raising=False)
    store = DataStore(db_path=str(tmp_path / "pit-manifest.duckdb"))
    await store.init_tables()

    try:
        await store.insert_ohlcv_batch([_bar(BAR_TS_1), _bar(BAR_TS_2, close=103)])

        rows = await store._fetch(
            "SELECT symbol, timeframe, row_count, content_hash, available_through "
            "FROM ohlcv_manifests"
        )
        assert len(rows) == 1
        symbol, timeframe, row_count, content_hash, available_through = rows[0]
        assert (symbol, timeframe, row_count) == ("XAUUSD", "M15", 2)
        assert content_hash
        assert available_through is not None

        # Manifest hash matches the PIT fingerprint over the same horizon.
        fp = await store.fingerprint_ohlcv("XAUUSD", "M15", available_through)
        assert fp["row_count"] == 2
        assert fp["content_hash"] == content_hash
    finally:
        store.close()


@pytest.mark.asyncio
async def test_legacy_null_quality_rows_stay_null_after_init_tables(tmp_path, monkeypatch):
    monkeypatch.delenv("NEXUS_QUALITY_GATE", raising=False)
    db_path = str(tmp_path / "legacy-quality.duckdb")
    store = DataStore(db_path=db_path)
    await store.init_tables()

    try:
        await _insert_legacy_null_quality_row(store, BAR_TS_1)
    finally:
        store.close()

    reopened = DataStore(db_path=db_path)
    await reopened.init_tables()
    try:
        rows = await reopened._fetch(
            "SELECT quality FROM ohlcv WHERE symbol = 'XAUUSD'"
        )
        assert rows == [(None,)]
    finally:
        reopened.close()
