import json
import re

import pytest
from tests.test_data.conftest import operational_store
from services.nexus_data.research_market import inspect_bars,research_market,settings_clock,list_research_runs
from services.nexus_data.broker_settings_store import BrokerSettingsStore,BrokerNotFound
from shared.broker_settings_models import ProfileCreate,AccountCreate

def bar(t):return dict(time=t,open=10.,high=12.,low=9.,close=11.,volume=1.)

HEX64=re.compile(r'^[0-9a-f]{64}$')

def test_clock_uses_saved_account_offset_and_rejects_wrong_server():
    from datetime import datetime
    now='2026-10-20T14:00:00+00:00'
    epoch=int(datetime.fromisoformat(now).timestamp())
    account={'version':6,'server':'real','settings':{'session_observation':{'server':'real','captured_at_utc':'2026-10-20T13:00:00+00:00','observed_offset_seconds':10800}}}
    result=settings_clock(account,{'time':epoch+10800},now)
    assert result['tick_utc']==now and result['settings_version']==6
    account['settings']['session_observation']['observed_offset_seconds']=7200
    assert settings_clock(account,{'time':epoch+10800},now)['tick_utc'] is None
    account['settings']['session_observation']['server']='demo'
    assert settings_clock(account,{'time':epoch+10800},now)['state']=='missing'

def test_basic_checks_deduplicate_reject_and_flag_gaps():
    rows,q=inspect_bars([bar(0),bar(0),bar(180),{**bar(60),'high':1.}], 'M1')
    assert [b['time'] for b in rows]==[0,180]
    assert q['rejected']==1 and q['duplicates_removed']==1 and q['unclassified_gaps']==1

@pytest.mark.asyncio
async def test_account_archive_deduplicates_merge_and_isolates_owners(operational_store,monkeypatch):
    store=BrokerSettingsStore(operational_store)
    p=await store.create_profile('u1',ProfileCreate(name='test',broker_name='test'))
    a=await store.create_account('u1',AccountCreate(profile_id=p['profile_id'],label='test',login='123',server='test'))
    calls=[]
    async def worker(payload,**kwargs):
        calls.append(payload)
        return {'bars':[bar(60),bar(120)],'tick':None,'captured_at':'2026-10-20T00:00:00Z'}
    monkeypatch.setattr('services.nexus_data.research_market._mt5_worker',worker)
    payload=dict(account_id=a['account_id'],symbol='XAUUSDs',timeframe='M1',mode='history',start='2026-10-19T00:00:00Z',end='2026-10-20T00:00:00Z')
    assert (await research_market(store,'u1',payload))['count']==2
    result=await research_market(store,'u1',{**payload,'mode':'unified'})
    assert result['count']==2 and result['coverage_complete'] is False
    assert calls[0]['expected_login']=='123'
    with pytest.raises(BrokerNotFound):await research_market(store,'u2',payload)
    assert len(calls)==2
    runs=await list_research_runs(store,'u1',a['account_id'])
    assert len(runs)==2 and all(r['status']=='completed' for r in runs)
    assert sorted(r['added'] for r in runs)==[0,2]
    assert next(r for r in runs if r['mode']=='unified')['existing']==2
    async def failed(*args,**kwargs):raise RuntimeError('terminal down')
    monkeypatch.setattr('services.nexus_data.research_market._mt5_worker',failed)
    with pytest.raises(RuntimeError):await research_market(store,'u1',payload)
    latest=await list_research_runs(store,'u1',a['account_id'])
    assert latest[0]['status']=='failed' and latest[0]['finished_at']
    with pytest.raises(BrokerNotFound):await list_research_runs(store,'u2',a['account_id'])


async def _account(store,owner='u1'):
    p=await store.create_profile(owner,ProfileCreate(name='test',broker_name='test'))
    a=await store.create_account(owner,AccountCreate(profile_id=p['profile_id'],label='test',login='123',server='test'))
    return a


def test_inspect_bars_preserves_rejected_raw_rows_with_reason():
    bad_envelope={**bar(60),'high':1.}
    kept_conflict={**bar(0),'close':12.}
    rows,q=inspect_bars([bar(0),kept_conflict,bad_envelope,bar(120)],'M1')
    assert [b['time'] for b in rows]==[0,120]
    assert rows[0]==kept_conflict
    assert q['rejected']==1 and q['duplicates_removed']==1
    entries=q['rejected_bars']
    assert len(entries)==2, 'both the invalid bar and the superseded duplicate must be kept raw'
    by_reason={e['reason'].split(':')[0]:e for e in entries}
    assert by_reason['invalid_record']['bar']==bad_envelope
    assert by_reason['duplicate']['bar']==bar(0), 'the superseded (dropped) raw bar must be preserved'
    for e in entries:
        assert isinstance(e['bar'],dict) and e['reason']
    # Identical duplicates are plain refetches: counted, not archived as raw evidence.
    _,q2=inspect_bars([bar(0),bar(0)],'M1')
    assert q2['duplicates_removed']==1 and q2['rejected_bars']==[]


@pytest.mark.asyncio
async def test_research_fetch_rejected_bars_are_archived_with_raw_payload(operational_store,monkeypatch):
    store=BrokerSettingsStore(operational_store)
    a=await _account(store)
    bad={**bar(120),'high':1.}
    async def worker(payload,**kwargs):
        return {'bars':[bar(60),bad],'tick':None,'captured_at':'2026-10-20T00:00:00Z'}
    monkeypatch.setattr('services.nexus_data.research_market._mt5_worker',worker)
    payload=dict(account_id=a['account_id'],symbol='XAUUSDs',timeframe='M1',mode='history',
                 start='2026-10-19T00:00:00Z',end='2026-10-20T00:00:00Z')
    result=await research_market(store,'u1',payload)
    assert result['fetch_rejected']==1
    assert result['archived_rejected']>=1
    rows=await operational_store._fetch(
        'SELECT dataset_id,reason_code,reason_detail,payload_json FROM quarantine')
    assert rows, 'a fetch-rejected bar must leave a quarantine evidence row'
    dataset_id,reason,detail,payload_json=rows[-1]
    assert dataset_id==f"research_rejected:{a['account_id']}:XAUUSDs:M1"
    assert reason=='invalid_record' and detail
    assert json.loads(payload_json)==bad, 'raw rejected values must be preserved verbatim'
    stored=await operational_store._fetch(
        'SELECT COUNT(*) FROM research_account_candles WHERE owner_id=? AND account_id=?',('u1',a['account_id']))
    assert stored[0][0]==1, 'only the valid bar may be stored'


@pytest.mark.asyncio
async def test_research_run_binds_input_output_hashes_and_lineage(operational_store,monkeypatch):
    store=BrokerSettingsStore(operational_store)
    a=await _account(store)
    account=await store.get_account('u1',a['account_id'])
    async def worker(payload,**kwargs):
        return {'bars':[bar(60),bar(120)],'tick':None,'captured_at':'2026-10-20T00:00:00Z'}
    monkeypatch.setattr('services.nexus_data.research_market._mt5_worker',worker)
    payload=dict(account_id=a['account_id'],symbol='XAUUSDs',timeframe='M1',mode='history',
                 start='2026-10-19T00:00:00Z',end='2026-10-20T00:00:00Z')
    result=await research_market(store,'u1',payload)
    runs=await list_research_runs(store,'u1',a['account_id'])
    record=runs[0]
    assert record['status']=='completed'
    assert HEX64.match(record['input_hash']), 'every run must bind an input hash'
    assert HEX64.match(record['output_hash']), 'every run must bind an output hash'
    assert record['settings_version']==account['version']
    assert record['output_hash']==result['quality']['fingerprint'], (
        'output_hash must equal the stored-series fingerprint it certifies')
    assert result['input_hash']==record['input_hash']

    datasets={r[0] for r in await operational_store._fetch('SELECT dataset_id FROM datasets')}
    clean_id=f"research:{a['account_id']}:XAUUSDs:M1"
    raw_id=f"research_raw:{a['account_id']}:XAUUSDs:M1"
    assert {clean_id,raw_id}<=datasets, 'research series must be registered as datasets'

    lineage=await operational_store._fetch(
        'SELECT upstream_dataset_id,downstream_dataset_id,transformation_name,metadata_json FROM lineage')
    assert len(lineage)==1, 'exactly one lineage edge per completed run'
    upstream,downstream,transformation,metadata_json=lineage[0]
    assert (upstream,downstream)==(raw_id,clean_id)
    assert transformation
    metadata=json.loads(metadata_json)
    assert metadata['run_id']==record['run_id']
    assert metadata['input_hash']==record['input_hash']
    assert metadata['output_hash']==record['output_hash']
    assert metadata['settings_version']==account['version']

    certs=await operational_store._fetch(
        'SELECT dataset_id,contract_version,status,summary_json FROM quality_runs')
    assert len(certs)==1, 'exactly one quality certificate per completed run'
    cert_dataset,contract,status,summary_json=certs[0]
    assert cert_dataset==clean_id and contract=='research_market_v1'
    assert status in ('passed','warning')
    summary=json.loads(summary_json)
    assert summary['input_hash']==record['input_hash']
    assert summary['output_hash']==record['output_hash']
    assert summary['run_id']==record['run_id']


@pytest.mark.asyncio
async def test_failed_research_run_records_input_binding_without_output_or_lineage(operational_store,monkeypatch):
    store=BrokerSettingsStore(operational_store)
    a=await _account(store)
    async def failed(*args,**kwargs):raise RuntimeError('terminal down')
    monkeypatch.setattr('services.nexus_data.research_market._mt5_worker',failed)
    payload=dict(account_id=a['account_id'],symbol='XAUUSDs',timeframe='M1',mode='history',
                 start='2026-10-19T00:00:00Z',end='2026-10-20T00:00:00Z')
    with pytest.raises(RuntimeError):
        await research_market(store,'u1',payload)
    record=(await list_research_runs(store,'u1',a['account_id']))[0]
    assert record['status']=='failed'
    assert HEX64.match(record['input_hash']), 'failed runs keep the input binding as evidence'
    assert 'output_hash' not in record, 'a failed run must not claim an output binding'
    tables={r[0] for r in await operational_store._fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main'")}
    assert 'lineage' not in tables or not await operational_store._fetch('SELECT 1 FROM lineage'), (
        'a failed run must not fabricate a lineage edge')
