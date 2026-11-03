from datetime import datetime, timedelta, timezone

import pytest

from services.nexus_data.duckdb_store import DataStore
from shared.models import OHLCV


async def put(store, stamp, high=12, source='mt5_poll'):
    await store._run("INSERT INTO ohlcv(symbol,timeframe,open,high,low,close,volume,timestamp,source,quality,available_at) VALUES ('XAUUSD','M5',10,?,9,11,5,?,?,'ok',?)", (high, stamp, source, stamp + timedelta(minutes=5)))


class Provider:
    connected = True

    def __init__(self, bars):
        self.bars = bars
        self.calls = []

    async def get_ohlcv_range(self, symbol, tf, start, end, limit):
        self.calls.append((symbol, tf, start, end, limit))
        return [b for b in self.bars if start <= b.timestamp <= end]


@pytest.mark.asyncio
async def test_repairs_corruption_and_missing_bar_archiving_original(tmp_path):
    from services.nexus_data.quality.repair import repair_pair
    store = DataStore(str(tmp_path / 'repair.duckdb'))
    await store.init_tables()
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    stamps = [now-timedelta(minutes=m) for m in (20, 15, 10)]
    provider = Provider([OHLCV(symbol='XAUUSD', timeframe='M5', timestamp=t, open=10, high=12, low=9, close=11, volume=5) for t in stamps])
    try:
        await put(store, stamps[0], high=8)
        await put(store, stamps[2])
        result = await repair_pair(store, provider, 'XAUUSD', 'M5', now=now)
        assert result['replaced'] == 1
        assert result['inserted'] == 1
        assert await store._fetch('SELECT high FROM ohlcv ORDER BY timestamp') == [(12.0,), (12.0,), (12.0,)]
        archived = await store._fetch('SELECT payload_json FROM quarantine')
        assert len(archived) == 1
        import json
        assert json.loads(archived[0][0])['high'] == 8
        assert await store._fetch('SELECT revision FROM ohlcv WHERE timestamp=?', (stamps[0],)) == [(1,)]
        await repair_pair(store, provider, 'XAUUSD', 'M5', now=now)
        assert await store._fetch('SELECT COUNT(*) FROM quarantine') == [(1,)]
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_cleaner_isolates_invalid_and_deduplicates_without_provider(tmp_path):
    from services.nexus_data.quality.repair import repair_pair
    store = DataStore(str(tmp_path / 'isolate.duckdb'))
    await store.init_tables()
    now = datetime.now(timezone.utc)
    provider = Provider([])
    provider.connected = False
    try:
        await put(store, now-timedelta(minutes=15))
        await put(store, now-timedelta(minutes=15))
        await put(store, now-timedelta(minutes=10), high=8)
        await put(store, now)  # retain original in quarantine, not active bars
        result = await repair_pair(store, provider, 'XAUUSD', 'M5', now=now)
        assert result['quarantined'] == 3
        assert await store._fetch('SELECT COUNT(*) FROM ohlcv') == [(1,)]
        assert await store._fetch('SELECT COUNT(*) FROM quarantine') == [(3,)]
        assert provider.calls == []
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_empty_provider_response_is_persisted_and_backed_off(tmp_path):
    from services.nexus_data.quality.repair import repair_pair
    store = DataStore(str(tmp_path / 'retry.duckdb'))
    await store.init_tables()
    now = datetime.now(timezone.utc)
    provider = Provider([])
    try:
        await put(store, now-timedelta(minutes=20))
        await put(store, now-timedelta(minutes=10))
        await repair_pair(store, provider, 'XAUUSD', 'M5', now=now)
        assert len(provider.calls) == 1
        await repair_pair(store, provider, 'XAUUSD', 'M5', now=now+timedelta(seconds=60))
        assert len(provider.calls) == 1
        assert await store._fetch('SELECT status FROM quality_repair_attempts') == [('empty',)]
        assert await store._fetch('SELECT COUNT(*) FROM ohlcv') == [(2,)]
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_worker_reaudits_after_repair_and_keeps_unresolved_quarantine_failed(tmp_path):
    from services.nexus_data.quality.automation import QualityAutomation
    store = DataStore(str(tmp_path / 'worker.duckdb'))
    await store.init_tables()
    now = datetime.now(timezone.utc)
    try:
        await put(store, now-timedelta(minutes=20), high=8)
        await put(store, now-timedelta(minutes=15))
        await put(store, now-timedelta(minutes=10))
        worker = QualityAutomation(store, provider=Provider([]))
        await worker.cycle()
        assert worker.state['quarantined'] == 1
        assert worker.state['failed'] == 1
        from services.nexus_data.quality.stored_audit import latest_quality
        report = await latest_quality(store, 'XAUUSD','M5','mt5_poll')
        assert report['status'] == 'failed'
        assert report['snapshot_current'] is True
        assert await store._fetch('SELECT COUNT(*) FROM ohlcv') == [(2,)]
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_no_cross_provider_cleaning_or_replacement(tmp_path):
    from services.nexus_data.quality.repair import repair_pair
    store = DataStore(str(tmp_path / 'providers.duckdb'))
    await store.init_tables()
    now = datetime.now(timezone.utc)
    try:
        await put(store, now-timedelta(minutes=15), source='csv')
        await put(store, now-timedelta(minutes=15), source='mt5_poll', high=13)
        before = await store._fetch('SELECT * FROM ohlcv ORDER BY source')
        await repair_pair(store, Provider([]), 'XAUUSD', 'M5', now=now)
        assert await store._fetch('SELECT * FROM ohlcv ORDER BY source') == before
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_operational_reads_reject_invalid_forming_and_unresolved_quarantine(tmp_path):
    from services.nexus_data.quality.repair import repair_pair
    store = DataStore(str(tmp_path / 'safe-read.duckdb'))
    await store.init_tables()
    now = datetime.now(timezone.utc)
    try:
        await put(store, now-timedelta(minutes=20))
        await put(store, now-timedelta(minutes=15), high=8)
        await put(store, now)
        assert len(await store.query_ohlcv('XAUUSD','M5')) == 1
        await repair_pair(store, Provider([]), 'XAUUSD','M5', now=now)
        assert await store.query_ohlcv('XAUUSD','M5') == []
        # Original evidence remains available outside the operational projection.
        assert await store._fetch('SELECT COUNT(*) FROM quarantine') == [(2,)]
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_concurrent_ingestion_defers_repair_without_losing_new_rows(tmp_path):
    from services.nexus_data.quality.repair import repair_pair
    store = DataStore(str(tmp_path / 'race.duckdb'))
    await store.init_tables()
    now = datetime.now(timezone.utc)
    class ConcurrentProvider(Provider):
        async def get_ohlcv_range(self, *args, **kwargs):
            await put(store, now-timedelta(minutes=5))
            return []
    try:
        await put(store, now-timedelta(minutes=20))
        await put(store, now-timedelta(minutes=10))
        result = await repair_pair(store, ConcurrentProvider([]), 'XAUUSD','M5', now=now)
        assert result['deferred'] is True
        assert await store._fetch('SELECT COUNT(*) FROM ohlcv') == [(3,)]
        assert await store._fetch('SELECT COUNT(*) FROM quarantine') == [(0,)]
        assert await store._fetch('SELECT COUNT(*) FROM quality_repair_attempts') == [(1,)]
    finally:
        await store.aclose()


def test_live_projection_excludes_forming_invalid_and_conflicting_bars():
    from services.nexus_data.quality.operational import usable_bars
    now = datetime.now(timezone.utc)
    good = OHLCV(symbol='XAUUSD',timeframe='M5',open=10,high=12,low=9,close=11,volume=5,timestamp=now-timedelta(minutes=10))
    forming = good.model_copy(update={'timestamp':now})
    invalid = good.model_copy(update={'timestamp':now-timedelta(minutes=15),'high':8})
    conflict = good.model_copy(update={'high':13})
    assert usable_bars([good,good,forming,invalid],now) == [good]
    assert usable_bars([good,conflict],now) == []


@pytest.mark.asyncio
async def test_api_does_not_bypass_quarantine_with_live_fallback(tmp_path,monkeypatch):
    from services.nexus_data import main
    from services.nexus_data.quality.repair import repair_pair
    from fastapi import HTTPException
    store = DataStore(str(tmp_path / 'api-gate.duckdb'))
    await store.init_tables()
    now = datetime.now(timezone.utc)
    provider = Provider([])
    provider.connected = False
    try:
        await put(store,now-timedelta(minutes=10),high=8)
        await repair_pair(store,provider,'XAUUSD','M5',now=now)
        provider.connected = True
        monkeypatch.setattr(main,'data_store',store)
        monkeypatch.setattr(main,'mt5',provider)
        with pytest.raises(HTTPException) as exc:
            await main.get_ohlcv('XAUUSD','M5',limit=10,start=None,end=None)
        assert exc.value.status_code == 503
        assert provider.calls == []
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_regular_mt5_ingestion_resolves_previously_isolated_timestamp(tmp_path):
    from services.nexus_data.quality.repair import repair_pair
    from services.nexus_data.quality.operational import pair_blocked
    store = DataStore(str(tmp_path / 'recover.duckdb'))
    await store.init_tables()
    now = datetime.now(timezone.utc)
    provider = Provider([])
    provider.connected = False
    try:
        stamp = now-timedelta(minutes=10)
        await put(store,stamp,high=8)
        await repair_pair(store,provider,'XAUUSD','M5',now=now)
        assert await pair_blocked(store,'XAUUSD','M5') is True
        await put(store,stamp)  # recovered via the regular same-provider poll
        await repair_pair(store,provider,'XAUUSD','M5',now=now)
        assert await pair_blocked(store,'XAUUSD','M5') is False
        assert await store._fetch('SELECT COUNT(*) FROM quarantine') == [(1,)]
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_quarantine_only_change_invalidates_old_pass(tmp_path):
    from services.nexus_data.quality.repair import repair_pair
    from services.nexus_data.quality.stored_audit import audit_stored_ohlcv, latest_quality
    store = DataStore(str(tmp_path / 'quarantine-cert.duckdb'))
    await store.init_tables()
    now = datetime.now(timezone.utc)
    provider = Provider([])
    provider.connected = False
    try:
        for minutes in (15,10):
            await put(store,now-timedelta(minutes=minutes))
        await audit_stored_ohlcv(store,'XAUUSD','M5','mt5_poll',now=now)
        assert (await latest_quality(store,'XAUUSD','M5','mt5_poll'))['status'] == 'passed'
        await put(store,now-timedelta(minutes=10),high=8)
        await repair_pair(store,provider,'XAUUSD','M5',now=now)
        assert (await latest_quality(store,'XAUUSD','M5','mt5_poll'))['snapshot_current'] is False
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_stored_operational_projection_rejects_cross_source_conflicts(tmp_path):
    store = DataStore(str(tmp_path / 'conflicts.duckdb'))
    await store.init_tables()
    now = datetime.now(timezone.utc)
    try:
        await put(store,now-timedelta(minutes=15))
        await put(store,now-timedelta(minutes=15))
        await put(store,now-timedelta(minutes=10))
        await put(store,now-timedelta(minutes=10),high=13,source='csv')
        rows = await store.query_ohlcv('XAUUSD','M5',limit=1)
        assert len(rows) == 1
        assert rows[0].timestamp == now-timedelta(minutes=15)
        assert await store._fetch('SELECT COUNT(*) FROM ohlcv') == [(4,)]
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_cooling_old_quarantine_does_not_starve_later_requests(tmp_path):
    from services.nexus_data.quality.repair import repair_pair
    store = DataStore(str(tmp_path / 'fair-retry.duckdb'))
    await store.init_tables()
    now = datetime.now(timezone.utc)
    provider = Provider([])
    try:
        def seed():
            store._conn.execute('BEGIN TRANSACTION')
            store._conn.executemany("INSERT INTO ohlcv(symbol,timeframe,open,high,low,close,volume,timestamp,source,quality,available_at) VALUES ('XAUUSD','M5',10,8,9,11,5,?,'mt5_poll','ok',?)", [(now-timedelta(minutes=5*n),now) for n in range(1,2002)])
            store._conn.execute('COMMIT')
        await store._execute_locked(seed)
        await repair_pair(store,provider,'XAUUSD','M5',now=now)
        assert len(provider.calls) == 4
        await repair_pair(store,provider,'XAUUSD','M5',now=now+timedelta(seconds=60))
        assert len(provider.calls) == 5
        assert await store._fetch('SELECT COUNT(*) FROM quality_repair_attempts') == [(5,)]
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_other_provider_collision_never_falsely_resolves_replacement(tmp_path):
    from services.nexus_data.quality.repair import repair_pair
    store = DataStore(str(tmp_path / 'collision.duckdb'))
    await store.init_tables()
    now = datetime.now(timezone.utc)
    stamp = now-timedelta(minutes=10)
    provider = Provider([OHLCV(symbol='XAUUSD',timeframe='M5',open=10,high=12,low=9,close=11,volume=5,timestamp=stamp)])
    try:
        await put(store,stamp,high=8)
        await put(store,stamp,source='csv')
        result = await repair_pair(store,provider,'XAUUSD','M5',now=now)
        assert result['replaced'] == 0
        assert await store._fetch('SELECT source,high FROM ohlcv') == [('csv',12.0)]
        assert await store._fetch('SELECT resolution_status FROM quarantine') == [('open',)]
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_worker_records_failure_even_when_all_rows_are_isolated(tmp_path):
    from services.nexus_data.quality.automation import QualityAutomation
    store = DataStore(str(tmp_path / 'all-isolated.duckdb'))
    await store.init_tables()
    now = datetime.now(timezone.utc)
    provider = Provider([])
    provider.connected = False
    try:
        await put(store,now-timedelta(minutes=10),high=8)
        worker = QualityAutomation(store,provider=provider)
        await worker.cycle()
        assert worker.state['failed'] == 1
        assert worker.state['blocked_pairs'] == 1
        assert await store._fetch('SELECT status FROM quality_runs') == [('failed',)]
        assert await store._fetch('SELECT COUNT(*) FROM ohlcv') == [(0,)]
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_nonfinite_original_is_archived_as_strict_json(tmp_path):
    import json
    from services.nexus_data.quality.repair import repair_pair
    store = DataStore(str(tmp_path / 'nonfinite.duckdb'))
    await store.init_tables()
    now = datetime.now(timezone.utc)
    provider = Provider([])
    provider.connected = False
    try:
        await put(store,now-timedelta(minutes=10),high=float('nan'))
        await repair_pair(store,provider,'XAUUSD','M5',now=now)
        payload, = (await store._fetch('SELECT payload_json FROM quarantine'))[0]
        def reject_constant(value):
            raise AssertionError(f'Nonstandard JSON constant: {value}')
        assert json.loads(payload,parse_constant=reject_constant)['high'] == 'nan'
    finally:
        await store.aclose()
