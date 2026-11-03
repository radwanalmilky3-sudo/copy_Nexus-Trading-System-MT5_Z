"""Per-user draft settings. Never invokes a broker or changes runtime policy."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, AwareDatetime, model_validator
from typing import Literal

from shared.broker_settings_models import AccountCreate, ProfileCreate, SaveSettings
from ..data_client import BrokerRequestRejected, DataServiceClient, DataServiceUnavailable
from ..deps import get_data_service
from ..middleware.auth import CurrentUser
from .admin import _require

router=APIRouter(prefix='/api/brokers',tags=['broker settings'])

class ResearchMarketRequest(BaseModel):
    group_id: str | None = Field(default=None,max_length=64)
    mode: Literal['history','live','unified']
    symbol: str = Field(min_length=1,max_length=128)
    timeframe: Literal['M1','M5','M15','M30','H1','H4','D1'] = 'M15'
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None

    @model_validator(mode='after')
    def dates(self):
        if self.mode=='history' and (not self.start or not self.end or self.start>=self.end or (self.end-self.start).days>366):
            raise ValueError('Choose a valid period of at most 366 days')
        return self

@router.post('/accounts/{account_id}/research-market')
async def research_market(account_id:str,payload:ResearchMarketRequest,actor:CurrentUser,db:DataServiceClient=Depends(get_data_service)):
    await _require(db,actor,'source_manager.view')
    if payload.mode in ('history','unified'):await _require(db,actor,'source_manager.edit')
    return await call(db,'research_market',actor,{'account_id':account_id,**payload.model_dump(mode='json',exclude_none=True)})

@router.get('/accounts/{account_id}/research-runs')
async def research_runs(account_id:str,actor:CurrentUser,db:DataServiceClient=Depends(get_data_service)):
    await _require(db,actor,'source_manager.view')
    return await call(db,'research_runs',actor,{'account_id':account_id})

class AnalysisRequest(BaseModel):
    timeframe:Literal['M1','M5','M15','M30','H1','H4','D1']='M15'
    start:int|None=None
    end:int|None=None
    symbol:str|None=Field(default=None,max_length=128)

@router.get('/accounts/{account_id}/research-analysis')
async def analysis(account_id:str,actor:CurrentUser,timeframe:Literal['M1','M5','M15','M30','H1','H4','D1']='M15',start:int|None=None,end:int|None=None,symbol:str|None=Query(default=None,max_length=128),db:DataServiceClient=Depends(get_data_service)):
    await _require(db,actor,'source_manager.view')
    return await call(db,'research_analysis',actor,{'account_id':account_id,'timeframe':timeframe,'start':start,'end':end,'symbol':symbol})

@router.post('/accounts/{account_id}/research-analysis')
async def save_analysis(account_id:str,payload:AnalysisRequest,actor:CurrentUser,db:DataServiceClient=Depends(get_data_service)):
    await _require(db,actor,'source_manager.edit')
    return await call(db,'research_analysis',actor,{'account_id':account_id,**payload.model_dump(),'persist':True})

@router.get('/accounts/{account_id}/research-analysis/{report_id}')
async def saved_analysis(account_id:str,report_id:str,actor:CurrentUser,db:DataServiceClient=Depends(get_data_service)):
    await _require(db,actor,'source_manager.view')
    return await call(db,'research_report',actor,{'account_id':account_id,'report_id':report_id})


async def call(db,op,actor,payload):
    try:
        return await db.broker_settings(op,actor,payload)
    except BrokerRequestRejected as exc:
        messages={404:'Broker account not found',409:'Settings changed or duplicate account; reload before saving',422:'Invalid broker settings',413:'Payload too large'}
        raise HTTPException(exc.status_code,messages[exc.status_code]) from None
    except DataServiceUnavailable:
        raise HTTPException(503,'Broker settings service unavailable') from None


@router.get('/profiles')
async def profiles(actor:CurrentUser,db:DataServiceClient=Depends(get_data_service)):
    await _require(db,actor,'source_manager.view')
    return await call(db,'list_profiles',actor,{})


@router.post('/profiles')
async def create_profile(payload:ProfileCreate,actor:CurrentUser,db:DataServiceClient=Depends(get_data_service)):
    await _require(db,actor,'source_manager.edit')
    return await call(db,'create_profile',actor,payload.model_dump(mode='json'))


@router.post('/accounts')
async def create_account(payload:AccountCreate,actor:CurrentUser,db:DataServiceClient=Depends(get_data_service)):
    await _require(db,actor,'source_manager.edit')
    return await call(db,'create_account',actor,payload.model_dump(mode='json'))


@router.get('/accounts/{account_id}')
async def account(account_id:str,actor:CurrentUser,db:DataServiceClient=Depends(get_data_service)):
    await _require(db,actor,'source_manager.view')
    return await call(db,'get_account',actor,{'account_id':account_id})


@router.get('/accounts/{account_id}/events')
async def events(account_id:str,actor:CurrentUser,db:DataServiceClient=Depends(get_data_service)):
    await _require(db,actor,'source_manager.view')
    return await call(db,'list_events',actor,{'account_id':account_id})

@router.post('/accounts/{account_id}/sessions/sync')
async def sync_sessions(account_id:str,actor:CurrentUser,db:DataServiceClient=Depends(get_data_service)):
    await _require(db,actor,'source_manager.edit')
    identity=await call(db,'get_identity',actor,{'account_id':account_id})
    try:
        await db.mt5_symbols(identity)  # Read-only verification of the open terminal.
    except DataServiceUnavailable:
        raise HTTPException(503,'تعذر التحقق من حساب MT5؛ لم تُغيّر إعدادات الجلسات.') from None
    return await call(db,'sync_sessions',actor,{'account_id':account_id})

@router.get('/accounts/{account_id}/symbols')
async def symbols(account_id:str,actor:CurrentUser,db:DataServiceClient=Depends(get_data_service)):
    await _require(db,actor,'source_manager.view')
    identity=await call(db,'get_identity',actor,{'account_id':account_id})
    try:
        return {'symbols': await db.mt5_symbols(identity)}
    except DataServiceUnavailable:
        raise HTTPException(503,'MT5 symbol service unavailable') from None


@router.put('/accounts/{account_id}/settings')
async def save(account_id:str,payload:SaveSettings,actor:CurrentUser,db:DataServiceClient=Depends(get_data_service)):
    await _require(db,actor,'source_manager.edit')
    old=await call(db,'get_account',actor,{'account_id':account_id})
    old_trade={a['broker_symbol'] for a in old['settings']['assets'] if a['mode']=='trade'}
    new_trade={a.broker_symbol for a in payload.settings.assets if a.mode=='trade'}
    if old_trade!=new_trade:
        await _require(db,actor,'trading.settings')
    return await call(db,'save_settings',actor,{'account_id':account_id,**payload.model_dump(mode='json')})
