import httpx
import pytest
from fastapi import FastAPI,Request
from tests.test_data.conftest import operational_store


@pytest.mark.asyncio
async def test_broker_transport_ownership_permissions_and_versions(operational_store,monkeypatch):
    from services.nexus_api.routers.broker_settings import router
    from services.nexus_api.data_client import DataServiceClient
    from services.nexus_api.deps import get_data_service
    from services.nexus_api.middleware.auth import create_token
    from services.nexus_data.broker_settings_router import create_broker_settings_router
    from services.nexus_data.broker_settings_store import BrokerSettingsStore
    monkeypatch.setenv('NEXUS_JWT_SECRET','broker-test-jwt-secret-only-0123456789abcdef')
    monkeypatch.setenv('NEXUS_INTERNAL_API_SECRET','broker-test-internal-secret')
    data=FastAPI();data.include_router(create_broker_settings_router(BrokerSettingsStore(operational_store)))
    perms={u:{'source_manager.view','source_manager.edit'} for u in ['u1','u2']}
    perms['reader']={'source_manager.view'}
    @data.post('/api/data/query')
    async def permissions(req:Request):
        body=await req.json()
        assert body['operation']=='user_permissions'
        return {'rows':[{'permission_code':p} for p in perms.get(body['params']['user_id'],set())]}
    db=DataServiceClient(base_url='http://data.test',secret='broker-test-internal-secret',transport=httpx.ASGITransport(app=data))
    app=FastAPI();app.include_router(router);app.dependency_overrides[get_data_service]=lambda:db
    def auth(user):return {'Authorization':'Bearer '+create_token(user)}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://gateway.test') as c:
        assert (await c.get('/api/brokers/profiles')).status_code==401
        assert (await c.post('/api/brokers/profiles',headers=auth('reader'),json={'name':'x','broker_name':'b'})).status_code==403
        assert (await c.post('/api/brokers/profiles',headers=auth('u1'),json={'name':'x','broker_name':'b','owner_id':'u2'})).status_code==422
        p=(await c.post('/api/brokers/profiles',headers=auth('u1'),json={'name':'mine','broker_name':'OneRoyal'})).json()
        body={'profile_id':p['profile_id'],'label':'Demo','server':'OneRoyal-Demo','login':'123456','account_kind':'demo'}
        assert (await c.post('/api/brokers/accounts',headers=auth('u2'),json=body)).status_code==404
        created=await c.post('/api/brokers/accounts',headers=auth('u1'),json=body)
        assert created.status_code==200,created.text
        a=created.json();url='/api/brokers/accounts/'+a['account_id']
        assert (await c.get(url,headers=auth('u2'))).status_code==404
        assert (await c.get(url+'/events',headers=auth('u2'))).status_code==404
        assert (await c.post(url+'/sessions/sync',headers=auth('reader'))).status_code==403
        assert (await c.post(url+'/sessions/sync',headers=auth('u2'))).status_code==404
        req={'expected_version':1,'settings':a['settings']}
        req['settings']['transition'].update(session_start_date='2026-11-02',effective_at_utc='2026-11-02T00:15:00Z',next_open_utc='2026-11-02T01:00:00Z',evidence_received_at='2026-10-19T20:00:00Z')
        assert (await c.put(url+'/settings',headers=auth('u2'),json=req)).status_code==404
        req['settings']['assets']=[{'broker_symbol':'XAUUSD','mode':'trade'}]
        assert (await c.put(url+'/settings',headers=auth('u1'),json=req)).status_code==403
        perms['u1'].add('trading.settings')
        saved=await c.put(url+'/settings',headers=auth('u1'),json=req)
        assert saved.status_code==200,saved.text
        assert saved.json()['version']==2 and saved.json()['runtime_effective'] is False
        assert saved.json()['persistence']=='durable' and saved.json()['connection_state']=='unconnected'
        assert saved.json()['settings']['transition']['session_start_date']=='2026-11-02'
        assert (await c.put(url+'/settings',headers=auth('u1'),json=req)).status_code==409
        perms['u1'].remove('trading.settings')
        req['expected_version']=2;req['settings']['assets']=[]
        assert (await c.put(url+'/settings',headers=auth('u1'),json=req)).status_code==403
        assert len((await c.get(url+'/events',headers=auth('u1'))).json())==2
        assert (await c.get('/api/brokers/profiles',headers=auth('u2'))).json()==[]
