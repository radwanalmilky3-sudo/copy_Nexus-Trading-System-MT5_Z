import json
from datetime import timedelta

import pytest

from tests.test_data.test_session_contracts import export_payload, NOW


def policy_payload():
    return dict(expected_server='Demo',symbol_map={'XAUUSD':'XAUUSD'},clock_evidence=dict(
        evidence_id='clock-1',source_uri='https://broker.example/clock',published_at='2026-10-18T00:00:00Z',
        effective_from='2026-10-19T00:00:00Z',effective_to='2026-10-20T00:00:00Z',utc_offset_seconds=0),exceptions=[])


def policy():
    from services.nexus_data.quality.session_contracts import CalendarPolicy
    return CalendarPolicy.model_validate_json(json.dumps(policy_payload()))


@pytest.mark.asyncio
async def test_import_is_idempotent_and_missing_file_is_not_ready(tmp_path,operational_store):
    from services.nexus_data.quality.session_store import SessionEvidenceStore
    path=tmp_path/'sessions.json';path.write_text(json.dumps(export_payload()),encoding='utf-8')
    importer=SessionEvidenceStore(operational_store,path,policy())
    assert (await importer.refresh(NOW)).state == 'ready'
    assert (await importer.refresh(NOW)).state == 'ready'
    assert await operational_store._fetch('SELECT COUNT(*) FROM market_session_snapshots') == [(1,)]
    path.unlink()
    assert (await importer.refresh(NOW)).state == 'unavailable'
    assert (await importer.context('XAUUSD',NOW)).export is None


@pytest.mark.asyncio
async def test_identity_staleness_clock_and_unconfigured_states(tmp_path,operational_store):
    from services.nexus_data.quality.session_store import SessionEvidenceStore
    from services.nexus_data.quality.session_contracts import CalendarPolicy
    path=tmp_path/'sessions.json';payload=export_payload();payload['server']='Wrong'
    path.write_text(json.dumps(payload),encoding='utf-8')
    importer=SessionEvidenceStore(operational_store,path,policy())
    assert (await importer.refresh(NOW)).state == 'identity_mismatch'
    path.write_text(json.dumps(export_payload()),encoding='utf-8')
    assert (await importer.refresh(NOW+timedelta(hours=25))).state == 'stale'
    unverified=SessionEvidenceStore(operational_store,path,CalendarPolicy.model_validate_json(json.dumps(dict(expected_server='Demo',symbol_map={'XAUUSD':'XAUUSD'}))))
    assert (await unverified.refresh(NOW)).state == 'clock_unverified'
    assert (await SessionEvidenceStore(operational_store,None,policy()).refresh(NOW)).state == 'not_configured'


@pytest.mark.asyncio
async def test_partial_file_and_provider_failure_never_mean_closed(tmp_path,operational_store):
    from services.nexus_data.quality.session_store import SessionEvidenceStore
    path=tmp_path/'sessions.json';path.write_text('{',encoding='utf-8')
    importer=SessionEvidenceStore(operational_store,path,policy())
    assert (await importer.refresh(NOW)).state == 'invalid'
    payload=export_payload();payload['connected']=False
    path.write_text(json.dumps(payload),encoding='utf-8')
    assert (await importer.refresh(NOW)).state == 'unavailable'


@pytest.mark.asyncio
async def test_empty_week_is_not_proof_of_permanent_market_closure(tmp_path,operational_store):
    from services.nexus_data.quality.session_store import SessionEvidenceStore
    payload=export_payload()
    for day in payload['symbols'][0]['days']:
        day.update(quote_status='no_sessions',quote_sessions=[])
    path=tmp_path/'empty.json';path.write_text(json.dumps(payload),encoding='utf-8')
    importer=SessionEvidenceStore(operational_store,path,policy())
    assert (await importer.refresh(NOW)).state == 'invalid'


def holiday_policy():
    from services.nexus_data.quality.session_contracts import CalendarPolicy
    payload=policy_payload()
    payload['exceptions']=[dict(evidence_id='gold-holiday',source_uri='https://broker.example/holiday',
        published_at='2026-10-18T00:00:00Z',effective_from='2026-10-19T09:00:00Z',effective_to='2026-10-19T10:00:00Z',
        server='Demo',broker_symbols=['XAUUSD'],kind='closed',quote_windows_utc=[])]
    return CalendarPolicy.model_validate_json(json.dumps(payload))


@pytest.mark.asyncio
async def test_unmapped_symbol_never_inherits_gold_exception(operational_store):
    from services.nexus_data.quality.session_store import SessionEvidenceStore
    from services.nexus_data.quality.session_calendar import classify_interval
    importer=SessionEvidenceStore(operational_store,None,holiday_policy())
    start=NOW+timedelta(hours=1)
    gold=await importer.context('XAUUSD',NOW)
    bitcoin=await importer.context('BTCUSD',NOW)
    assert classify_interval(gold,start=start,end=start+timedelta(minutes=5)).kind=='confirmed_closed'
    assert classify_interval(bitcoin,start=start,end=start+timedelta(minutes=5)).kind=='unknown'


@pytest.mark.asyncio
async def test_failed_policy_reload_withdraws_old_exception(tmp_path,operational_store):
    from services.nexus_data.quality.session_store import SessionEvidenceStore
    from services.nexus_data.quality.session_calendar import classify_interval
    file=tmp_path/'sessions.json';file.write_text(json.dumps(export_payload()),encoding='utf-8')
    rules=tmp_path/'policy.json';rules.write_text(holiday_policy().model_dump_json(),encoding='utf-8')
    importer=SessionEvidenceStore(operational_store,file,policy(),policy_path=rules)
    await importer.refresh(NOW)
    start=NOW+timedelta(hours=1)
    assert classify_interval(await importer.context('XAUUSD',NOW),start=start,end=start+timedelta(minutes=5)).kind=='confirmed_closed'
    rules.unlink()
    await importer.refresh(NOW)
    assert classify_interval(await importer.context('XAUUSD',NOW),start=start,end=start+timedelta(minutes=5)).kind=='unknown'
