import json

import pytest

from shared.broker_settings_models import AccountCreate, AccountSettings, ProfileCreate


async def account(store, owner, login='123'):
    p=await store.create_profile(owner, ProfileCreate(name='My broker',broker_name='OneRoyal'))
    return await store.create_account(owner, AccountCreate(profile_id=p['profile_id'],label='Demo',server='OneRoyal-Demo',login=login))


@pytest.mark.asyncio
async def test_owner_isolation_and_conflicts(operational_store):
    from services.nexus_data.broker_settings_store import BrokerSettingsStore,BrokerNotFound,BrokerConflict
    s=BrokerSettingsStore(operational_store)
    a=await account(s,'u1');b=await account(s,'u2')
    await account(s,'u1','456');await account(s,'u2','456')
    assert len(await s.list_profiles('u1'))==2
    assert len(await s.list_profiles('u2'))==2
    assert 'login' not in a and a['masked_login']!='123'
    for other in [a,b]:
        owner='u2' if other==a else 'u1'
        with pytest.raises(BrokerNotFound): await s.get_account(owner,other['account_id'])
        with pytest.raises(BrokerNotFound): await s.list_events(owner,other['account_id'])
        with pytest.raises(BrokerNotFound): await s.get_identity(owner,other['account_id'])
        with pytest.raises(BrokerNotFound): await s.save_settings(owner,other['account_id'],1,AccountSettings())
        with pytest.raises(BrokerNotFound): await s.create_account(owner,AccountCreate(profile_id=other['profile_id'],label='X',server='Demo',login='999'))
    settings=AccountSettings.model_validate_json(json.dumps({'transition':{'during_market_closure':'yes','session_start_date':'2026-11-02'}}))
    saved=await s.save_settings('u1',a['account_id'],1,settings)
    assert saved['version']==2 and saved['persistence']=='durable'
    assert saved['runtime_effective'] is False and saved['connection_state']=='unconnected'
    assert saved['settings']['transition']['effective_at_utc'] is None
    with pytest.raises(BrokerConflict): await s.save_settings('u1',a['account_id'],1,AccountSettings())
    assert (await s.get_account('u1',a['account_id']))['version']==2
    assert len(await s.list_events('u1',a['account_id']))==2
    assert (await s.get_account('u2',b['account_id']))['version']==1


@pytest.mark.asyncio
async def test_reopen_persists_and_duplicate_is_atomic(tmp_path):
    from services.nexus_data.duckdb_store import DataStore
    from services.nexus_data.broker_settings_store import BrokerSettingsStore,BrokerConflict
    path=str(tmp_path/'broker.duckdb')
    owner=DataStore(path);await owner.init_tables()
    try:
        s=BrokerSettingsStore(owner);a=await account(s,'u1')
        with pytest.raises(BrokerConflict):
            await s.create_account('u1',AccountCreate(profile_id=a['profile_id'],label='Again',server='OneRoyal-Demo',login='123'))
        assert len(await s.list_events('u1',a['account_id']))==1
    finally: await owner.aclose()
    reopened=DataStore(path);await reopened.init_tables()
    try:
        result=await BrokerSettingsStore(reopened).get_account('u1',a['account_id'])
        assert result['settings']['assets']==[] and result['version']==1
    finally: await reopened.aclose()
