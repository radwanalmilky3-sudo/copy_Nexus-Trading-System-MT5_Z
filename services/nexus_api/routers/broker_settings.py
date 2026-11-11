"""Per-user draft settings. Never invokes a broker or changes runtime policy."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, AwareDatetime, model_validator
from typing import Literal

from shared.broker_settings_models import AccountCreate, ProfileCreate, SaveSettings
from ..data_client import BrokerRequestRejected, DataServiceClient, DataServiceUnavailable
from ..deps import get_data_service
from ..middleware.auth import CurrentUser
from .admin import _require
from .env import _env_path, _parse_env_text, _read_env_text

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

@router.get('/accounts/{account_id}/research-certificate')
async def research_batch_certificate(account_id:str,actor:CurrentUser,group_id:str=Query(min_length=8,max_length=64),db:DataServiceClient=Depends(get_data_service)):
    """Batch-level quality certificate + pack alignment (derived from persisted run records only)."""
    await _require(db,actor,'source_manager.view')
    return await call(db,'research_batch_certificate',actor,{'account_id':account_id,'group_id':group_id})

class TrainDatasetRequest(BaseModel):
    group_id:str=Field(min_length=8,max_length=64)
    name:str=Field(min_length=1,max_length=128)

@router.post('/accounts/{account_id}/research-train-dataset')
async def create_train_dataset(account_id:str,payload:TrainDatasetRequest,actor:CurrentUser,db:DataServiceClient=Depends(get_data_service)):
    """Bind a certified batch to a versioned training dataset (rejected if the certificate is invalid)."""
    await _require(db,actor,'source_manager.edit')
    return await call(db,'research_train_dataset',actor,{'account_id':account_id,'group_id':payload.group_id,'name':payload.name})

class LabelGenerateRequest(BaseModel):
    symbol:str=Field(min_length=1,max_length=128)
    timeframe:Literal['M1','M5','M15','M30','H1','H4','D1']='M1'
    kind:Literal['direction','barrier']='direction'
    horizon_bars:int=Field(ge=1,le=500)
    name:str=Field(min_length=1,max_length=128)
    tp_atr:float=Field(default=1.5,gt=0)
    sl_atr:float=Field(default=1.0,gt=0)

@router.post('/accounts/{account_id}/research-labels')
async def generate_labels(account_id:str,payload:LabelGenerateRequest,actor:CurrentUser,db:DataServiceClient=Depends(get_data_service)):
    """Generate supervised labels (direction / barrier) from stored research candles."""
    await _require(db,actor,'source_manager.edit')
    return await call(db,'research_labels_generate',actor,{'account_id':account_id,**payload.model_dump()})

@router.get('/accounts/{account_id}/research-labels')
async def list_labels(account_id:str,actor:CurrentUser,db:DataServiceClient=Depends(get_data_service)):
    await _require(db,actor,'source_manager.view')
    return await call(db,'research_labels_list',actor,{'account_id':account_id})

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


@router.get('/mt5-check')
async def mt5_check(actor:CurrentUser,db:DataServiceClient=Depends(get_data_service)):
    """System-level read-only MT5 check straight from the platform env card.

    Owner request (2026-11-11): ``MT5_LOGIN``/``MT5_SERVER`` ARE the single
    account record of this deployment — there is nothing to pick — so the
    dashboard's connection table (الحساب/الخادم/حالة الاتصال/آخر تحقق UTC)
    verifies those two values directly, without any per-account record.

    A failed probe returns ``ok: false`` (still 200) so every table column can
    still fill in; only an unreadable/absent ``.env`` raises an HTTP error.
    Never places an order or changes any setting.
    """
    await _require(db,actor,'source_manager.view')
    path=_env_path()
    parsed=_parse_env_text(_read_env_text(path)) if path.exists() else {}
    login=(parsed.get('MT5_LOGIN') or '').strip()
    server=(parsed.get('MT5_SERVER') or '').strip()
    if not login or not server:
        raise HTTPException(409,'MT5_LOGIN و MT5_SERVER غير مضبوطين في بطاقة اتصال المنصة')
    try:
        rows=await db.mt5_symbols({'login':login,'server':server})
    except DataServiceUnavailable:
        return {'login':login,'server':server,'ok':False,'symbol_count':0,'symbols':[]}
    return {'login':login,'server':server,'ok':True,'symbol_count':len(rows),'symbols':rows}


@router.put('/accounts/{account_id}/settings')
async def save(account_id:str,payload:SaveSettings,actor:CurrentUser,db:DataServiceClient=Depends(get_data_service)):
    await _require(db,actor,'source_manager.edit')
    old=await call(db,'get_account',actor,{'account_id':account_id})
    old_trade={a['broker_symbol'] for a in old['settings']['assets'] if a['mode']=='trade'}
    new_trade={a.broker_symbol for a in payload.settings.assets if a.mode=='trade'}
    if old_trade!=new_trade:
        await _require(db,actor,'trading.settings')
    return await call(db,'save_settings',actor,{'account_id':account_id,**payload.model_dump(mode='json')})
