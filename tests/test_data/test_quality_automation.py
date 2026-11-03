from datetime import datetime, timedelta, timezone

import pytest

from services.nexus_data.duckdb_store import DataStore


@pytest.mark.asyncio
async def test_automatic_cycle_certifies_changed_snapshots_and_skips_current(tmp_path):
    from services.nexus_data.quality.automation import QualityAutomation
    store = DataStore(str(tmp_path / 'auto.duckdb'))
    await store.init_tables()
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    try:
        for minutes in (15, 10):
            await store._run("INSERT INTO ohlcv(symbol,timeframe,open,high,low,close,volume,timestamp,source,quality,available_at) VALUES ('XAUUSD','M5',10,12,9,11,5,?,'mt5_poll','ok',?)", (now-timedelta(minutes=minutes), now))
        worker = QualityAutomation(store)
        await worker.cycle()
        assert worker.state['audited'] == 1
        assert await store._fetch('SELECT status FROM quality_runs') == [('passed',)]
        await worker.cycle()
        assert worker.state['audited'] == 0
        assert await store._fetch('SELECT COUNT(*) FROM quality_runs') == [(1,)]
        await store._run("UPDATE ohlcv SET high=8 WHERE symbol='XAUUSD'")
        await worker.cycle()
        assert worker.state['failed'] == 1
        assert await store._fetch('SELECT COUNT(*) FROM quality_runs') == [(2,)]
        assert await store._fetch('SELECT DISTINCT high FROM ohlcv') == [(8.0,)]
    finally:
        await store.aclose()
