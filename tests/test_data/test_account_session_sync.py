import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from shared.broker_settings_models import AccountCreate, AccountSettings, ProfileCreate
from services.nexus_data.broker_settings_store import BrokerSettingsStore, BrokerNotFound
from services.nexus_data.account_session_sync import sync_account_sessions
from services.nexus_data.research_market import session_gap_review
from tests.test_data.conftest import operational_store


@pytest.mark.asyncio
async def test_sync_is_account_scoped_durable_idempotent_and_rejects_errors(operational_store,tmp_path):
    store=BrokerSettingsStore(operational_store)
    profile=await store.create_profile('u1',ProfileCreate(name='broker',broker_name='broker'))
    account=await store.create_account('u1',AccountCreate(profile_id=profile['profile_id'],label='real',server='real',login='123'))
    settings=AccountSettings.model_validate_json(json.dumps({'assets':[{'broker_symbol':s,'mode':'analysis'} for s in ['AUDUSDs','XAUUSDs']]}))
    await store.save_settings('u1',account['account_id'],1,settings)
    stamp=datetime.now(timezone.utc).isoformat()
    def symbol(name,error=False):
        return dict(broker_symbol=name,days=[dict(day=d,quote_status='error' if error else 'ok' if d in range(1,6) else 'no_sessions',trade_status='no_sessions',quote_error=1 if error else 0,trade_error=0,quote_sessions=[dict(start_seconds=180,end_seconds=86340)] if d in range(1,6) and not error else [],trade_sessions=[]) for d in range(7)])
    raw=dict(schema_version=1,server='real',company='broker',captured_at_utc=stamp,connected=True,observed_server_offset_seconds=10800,symbols=[symbol('AUDUSDs'),symbol('XAUUSDs'),symbol('OTHER')])
    path=tmp_path/'sessions.json';path.write_text(json.dumps(raw),encoding='utf8')
    operational_store._session_calendar_store=SimpleNamespace(export_path=path)
    with pytest.raises(BrokerNotFound):await sync_account_sessions(store,'u2',account['account_id'])
    result=await sync_account_sessions(store,'u1',account['account_id'])
    assert result['imported']==['AUDUSDs','XAUUSDs']
    stored=await store.get_account('u1',account['account_id'])
    assert len(stored['settings']['session_observations'])==2
    assert stored['settings']['assets']==settings.model_dump()['assets']
    assert session_gap_review([], 'M15',stored,'AUDUSDs')['state']=='weekly_reference_only'
    assert (await sync_account_sessions(store,'u1',account['account_id']))['account']['version']==stored['version']
    raw['symbols']=[symbol('AUDUSDs',True),symbol('XAUUSDs')]
    path.write_text(json.dumps(raw),encoding='utf8')
    result=await sync_account_sessions(store,'u1',account['account_id'])
    assert result['skipped']==['AUDUSDs']
    assert [s['broker_symbol'] for s in result['account']['settings']['session_observations']]==['XAUUSDs']
    raw['server']='demo';path.write_text(json.dumps(raw),encoding='utf8')
    with pytest.raises(ValueError):await sync_account_sessions(store,'u1',account['account_id'])
