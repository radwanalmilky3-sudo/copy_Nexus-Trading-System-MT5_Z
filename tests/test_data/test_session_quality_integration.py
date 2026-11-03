from datetime import datetime,timedelta,timezone

import pytest

from tests.test_data.test_session_calendar import context
from tests.test_data.test_session_contracts import export_payload
from tests.test_data.test_quality_repair import Provider,put


@pytest.mark.asyncio
async def test_confirmed_closure_skips_gap_fetch_but_unknown_still_fetches(operational_store):
    from services.nexus_data.quality.repair import repair_pair
    now=datetime(2026,10,19,10,20,tzinfo=timezone.utc)
    await put(operational_store,now-timedelta(minutes=20))
    await put(operational_store,now-timedelta(minutes=10))
    provider=Provider([])
    await repair_pair(operational_store,provider,'XAUUSD','M5',now=now,calendar=context())
    assert provider.calls == []
    await repair_pair(operational_store,provider,'XAUUSD','M5',now=now,calendar=None)
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_calendar_and_combined_series_changes_invalidate_certificate(operational_store):
    from services.nexus_data.quality.stored_audit import audit_stored_ohlcv,latest_quality
    from services.nexus_data.quality.session_store import SessionEvidenceStore
    from tests.test_data.test_session_store import policy
    now=datetime.now(timezone.utc)
    await put(operational_store,now-timedelta(minutes=20))
    await put(operational_store,now-timedelta(minutes=10))
    report=await audit_stored_ohlcv(operational_store,'XAUUSD','M5','mt5_poll',now=now)
    assert report['gap_summary']['unknown'] == 1
    assert (await latest_quality(operational_store,'XAUUSD','M5','mt5_poll'))['snapshot_current'] is True
    await put(operational_store,now-timedelta(minutes=15),source='mt5_backfill')
    assert (await latest_quality(operational_store,'XAUUSD','M5','mt5_poll'))['snapshot_current'] is False
    report=await audit_stored_ohlcv(operational_store,'XAUUSD','M5','mt5_poll',now=now)
    assert report['gap_summary']['covered_elsewhere'] == 1
    assert report['checks']['continuous_observed_intervals'] is True
    # Attaching even a not-yet-configured calendar adds a dependency; no stale pass.
    SessionEvidenceStore(operational_store,None,policy())
    assert (await latest_quality(operational_store,'XAUUSD','M5','mt5_poll'))['snapshot_current'] is False
