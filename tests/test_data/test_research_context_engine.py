import math
import pytest
from shared.research_context_engine import pair_context,point_in_time,pearson
from services.nexus_data.research_analysis import research_analysis,get_research_report
from services.nexus_data.research_market import research_market
from services.nexus_data.broker_settings_store import BrokerSettingsStore,BrokerNotFound
from shared.broker_settings_models import ProfileCreate,AccountCreate,AccountSettings
from tests.test_data.conftest import operational_store

def test_rolling_and_explicit_lag_do_not_fill_gaps():
    changes=[math.sin(i*1.731)+math.cos(i*0.313) for i in range(180)]
    other=[{'time':i*60,'close':math.exp(sum(changes[:i+1])/100)} for i in range(180)]
    gold=[{'time':i*60,'close':math.exp(sum(changes[:max(0,i-2)])/100)} for i in range(180)]
    result=pair_context(gold,other,60)
    assert result['rolling']['120']['samples']==120
    assert result['lead_lag']['lag_bars']==3
    assert result['lead_lag']['correlation']==pytest.approx(1.)
    assert result['predictive_validated'] is False and result['confidence'] is None
    assert pair_context(gold[:10],other[:10],60)['rolling']['20']['value'] is None
    assert pearson([(1,1)]*20) is None

def test_point_in_time_excludes_future_and_unknown_availability():
    rows=[{'id':1,'available_at_epoch':10,'close_utc_epoch':9},{'id':2,'available_at_epoch':30,'close_utc_epoch':9},{'id':3,'available_at_epoch':10,'close_utc_epoch':40},{'id':4}]
    assert [r['id'] for r in point_in_time(rows,20)]==[1]

@pytest.mark.asyncio
async def test_snapshot_uses_real_account_data_and_persists_evidence(operational_store,monkeypatch):
    store=BrokerSettingsStore(operational_store)
    p=await store.create_profile('u1',ProfileCreate(name='test',broker_name='test'))
    a=await store.create_account('u1',AccountCreate(profile_id=p['profile_id'],label='test',login='123',server='test'))
    settings=AccountSettings.model_validate_json('{"assets":[{"broker_symbol":"XAUUSDs","mode":"analysis"},{"broker_symbol":"XAGUSDs","mode":"analysis"}]}')
    await store.save_settings('u1',a['account_id'],1,settings)
    async def worker(payload,**kwargs):
        return {'bars':[dict(time=i*60,open=100.+i,high=102.+i,low=99.+i,close=101.+i,volume=1.) for i in range(150)],'tick':None,'captured_at':'2026-10-20T14:00:00Z'}
    monkeypatch.setattr('services.nexus_data.research_market._mt5_worker',worker)
    for s in ['XAUUSDs','XAGUSDs']:
        await research_market(store,'u1',dict(account_id=a['account_id'],symbol=s,timeframe='M1',mode='history',start='2026-10-01T00:00:00Z',end='2026-10-20T00:00:00Z'))
    payload=dict(account_id=a['account_id'],timeframe='M1',persist=True)
    report=await research_analysis(store,'u1',payload)
    assert len(report['datasets'])==2
    assert all(r['availability_known']==150 for r in report['datasets'])
    assert report['strategies'][0]['rolling']['120']['value']==pytest.approx(1.)
    assert report['backtests'][0]['status']=='blocked'
    assert len(report['artifacts'])==1
    stored=await get_research_report(store,'u1',a['account_id'],report['artifacts'][0]['report_id'])
    assert stored['context']['fingerprint']==report['context']['fingerprint']
    with pytest.raises(BrokerNotFound):await get_research_report(store,'u2',a['account_id'],report['artifacts'][0]['report_id'])
    assert report['trade_permission_changed'] is False
    with pytest.raises(BrokerNotFound):await research_analysis(store,'u2',payload)
