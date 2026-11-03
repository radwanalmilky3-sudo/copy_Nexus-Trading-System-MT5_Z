import httpx
import pytest
from fastapi import FastAPI


@pytest.mark.asyncio
async def test_internal_auth_validation_and_operations(operational_store,monkeypatch):
    from services.nexus_data.broker_settings_router import create_broker_settings_router
    from services.nexus_data.broker_settings_store import BrokerSettingsStore
    monkeypatch.setenv('NEXUS_INTERNAL_API_SECRET','test-only-broker-secret')
    app=FastAPI();app.include_router(create_broker_settings_router(BrokerSettingsStore(operational_store)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://data.test') as c:
        url='/api/data/broker-settings'
        req={'operation':'list_profiles','owner_id':'u1','payload':{}}
        assert (await c.post(url,json=req)).status_code==403
        assert (await c.post(url,json=req,headers={'X-Nexus-Internal-Secret':'wrong'})).status_code==403
        c.headers['X-Nexus-Internal-Secret']='test-only-broker-secret'
        assert (await c.post(url,json=req)).json()=={'result':[]}
        assert (await c.post(url,json={**req,'operation':'arbitrary_sql'})).status_code==422
        assert (await c.post(url,json={**req,'operation':'create_profile','payload':{'name':'x','broker_name':'b','owner_user_id':'other'}})).status_code==422
        created=(await c.post(url,json={**req,'operation':'create_profile','payload':{'name':'mine','broker_name':'OneRoyal'}})).json()['result']
        account=(await c.post(url,json={**req,'operation':'create_account','payload':{'profile_id':created['profile_id'],'label':'Demo A','server':'OneRoyal-Demo','login':'12345678'}})).json()['result']
        assert account['masked_login']!='12345678' and 'login' not in account
        cross={'account_id':account['account_id']}
        for op,payload in [('get_identity',cross),('get_account',cross),('list_events',cross),('save_settings',{**cross,'expected_version':1,'settings':{}})]:
            r=await c.post(url,json={'operation':op,'owner_id':'u2','payload':payload})
            assert r.status_code==404,(op,r.status_code,r.text)
            assert 'OneRoyal' not in r.text and '12345678' not in r.text,'404 must not leak server or login of the other owner'
        assert (await c.post(url,json={'operation':'list_profiles','owner_id':'u2','payload':{}})).json()=={'result':[]}
