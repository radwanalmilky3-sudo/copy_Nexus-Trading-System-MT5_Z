from datetime import datetime, timedelta, timezone

import pytest

from services.nexus_data.duckdb_store import DataStore
from services.nexus_data.fundamental_store import FundamentalStore


@pytest.fixture
def at():
    return datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


async def insert_raw(store, at, *, high=12, available=True):
    await store._run(
        'INSERT INTO ohlcv(symbol,timeframe,open,high,low,close,volume,timestamp,source,quality,available_at) '
        "VALUES ('XAUUSD','M5',10,?,9,11,5,?,'mt5_poll','ok',?)",
        (high, at, at + timedelta(minutes=5) if available else None))


@pytest.mark.asyncio
async def test_audit_persists_snapshot_checks_without_changing_bars(tmp_path, at):
    from services.nexus_data.quality.stored_audit import audit_stored_ohlcv
    store = DataStore(str(tmp_path / 'audit.duckdb'))
    await store.init_tables()
    try:
        await insert_raw(store, at - timedelta(minutes=10))
        await insert_raw(store, at - timedelta(minutes=5))
        before = await store._fetch('SELECT * FROM ohlcv ORDER BY timestamp')
        result = await audit_stored_ohlcv(store, 'XAUUSD', 'M5', 'mt5_poll', now=at)
        assert result['status'] == 'passed'
        assert result['rows_checked'] == 2
        assert len(result['content_hash']) == 64
        assert result['checks']['ohlc_invariants'] is True
        assert await store._fetch('SELECT * FROM ohlcv ORDER BY timestamp') == before
        runs, = await FundamentalStore(store).query_named('research_collection', dict(resource='quality_runs', limit=50, offset=0, query=None))
        item, = runs['items']
        assert item['status'] == 'passed'
        assert item['content_hash'] == result['content_hash']
        assert item['rows_checked'] == 2
        datasets, = await FundamentalStore(store).query_named('research_collection', dict(resource='datasets', limit=50, offset=0, query=None))
        quality = datasets['items'][0]['quality_summary']
        assert quality['snapshot_current'] is True
        assert datetime.fromisoformat(quality['snapshot_verified_at']).tzinfo is not None
        assert quality['checked_at'] == result['checked_at']
        await insert_raw(store, at)
        datasets, = await FundamentalStore(store).query_named('research_collection', dict(resource='datasets', limit=50, offset=0, query=None))
        assert datasets['items'][0]['quality_summary']['snapshot_current'] is False
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_invalid_ohlc_duplicate_and_forming_bar_fail_without_repairing_data(tmp_path, at):
    from services.nexus_data.quality.stored_audit import audit_stored_ohlcv
    store = DataStore(str(tmp_path / 'invalid.duckdb'))
    await store.init_tables()
    try:
        await insert_raw(store, at, high=8)
        await insert_raw(store, at, high=8)
        result = await audit_stored_ohlcv(store, 'XAUUSD', 'M5', 'mt5_poll', now=at)
        assert result['status'] == 'failed'
        assert result['checks']['ohlc_invariants'] is False
        assert result['checks']['unique_timestamps'] is False
        assert result['checks']['closed_bars'] is False
        assert len(result['issues']) >= 3
        assert await store._fetch('SELECT COUNT(*) FROM ohlcv') == [(2,)]
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_unclassified_gaps_old_data_and_missing_availability_are_warnings(tmp_path, at):
    from services.nexus_data.quality.stored_audit import audit_stored_ohlcv
    store = DataStore(str(tmp_path / 'warning.duckdb'))
    await store.init_tables()
    try:
        await insert_raw(store, at - timedelta(days=3), available=False)
        await insert_raw(store, at - timedelta(days=1), available=False)
        result = await audit_stored_ohlcv(store, 'XAUUSD', 'M5', 'mt5_poll', now=at)
        assert result['status'] == 'warning'
        assert result['issues'] == []
        assert len(result['warnings']) >= 3
        assert result['metrics']['unclassified_gaps'] == 1
        assert result['checks']['availability_recorded'] is False
        # No assertion that weekend/holiday closures are missing market data.
        assert result['scope'] == 'stored_ohlcv_basic_v1'
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_empty_selection_does_not_generate_a_success_run(tmp_path, at):
    from services.nexus_data.quality.stored_audit import audit_stored_ohlcv
    store = DataStore(str(tmp_path / 'empty.duckdb'))
    await store.init_tables()
    try:
        with pytest.raises(ValueError, match='No stored bars'):
            await audit_stored_ohlcv(store, 'XAUUSD', 'M5', 'mt5_poll', now=at)
    finally:
        await store.aclose()
