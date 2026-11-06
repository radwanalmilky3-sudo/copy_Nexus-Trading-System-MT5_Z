"""Secret-authenticated metadata operations on the sole database owner."""
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, ValidationError

from shared.broker_settings_models import AccountCreate, AccountSettings, Name, ProfileCreate, SaveSettings, StrictModel
from .broker_settings_store import BrokerConflict, BrokerNotFound
from .trial_registry_router import _authorize


class Operation(StrictModel):
    operation: Literal['list_profiles','create_profile','create_account','get_account','get_identity','save_settings','list_events','research_market','research_runs','research_batch_certificate','research_analysis','research_report','sync_sessions']
    owner_id: Name
    payload: dict[str, Any] = Field(default_factory=dict)


class AccountLookup(StrictModel):
    account_id: Name


class BatchCertificateLookup(StrictModel):
    account_id: Name
    group_id: Name


class SaveAccount(SaveSettings):
    account_id: Name


def create_broker_settings_router(store) -> APIRouter:
    router=APIRouter(prefix='/api/data/broker-settings',dependencies=[Depends(_authorize)])

    @router.post('')
    async def execute(request:Operation):
        if len(json.dumps(request.payload).encode())>131072:
            raise HTTPException(413,'Broker settings payload too large')
        op,owner,payload=request.operation,request.owner_id,request.payload
        try:
            if op=='list_profiles':
                StrictModel.model_validate(payload)
                result=await store.list_profiles(owner)
            elif op=='research_market':
                from .research_market import research_market
                result=await research_market(store,owner,payload)
            elif op=='sync_sessions':
                from .account_session_sync import sync_account_sessions
                lookup=AccountLookup.model_validate(payload)
                result=await sync_account_sessions(store,owner,lookup.account_id)
            elif op=='research_runs':
                from .research_market import list_research_runs
                lookup=AccountLookup.model_validate(payload)
                result=await list_research_runs(store,owner,lookup.account_id)
            elif op=='research_batch_certificate':
                from .research_market import batch_certificate
                lookup=BatchCertificateLookup.model_validate(payload)
                result=await batch_certificate(store,owner,lookup.account_id,lookup.group_id)
            elif op=='research_analysis':
                from .research_analysis import research_analysis
                result=await research_analysis(store,owner,payload)
            elif op=='research_report':
                from .research_analysis import get_research_report
                result=await get_research_report(store,owner,payload['account_id'],payload['report_id'])
            elif op=='create_profile':
                result=await store.create_profile(owner,ProfileCreate.model_validate_json(json.dumps(payload)))
            elif op=='create_account':
                result=await store.create_account(owner,AccountCreate.model_validate_json(json.dumps(payload)))
            elif op=='save_settings':
                save=SaveAccount.model_validate_json(json.dumps(payload))
                result=await store.save_settings(owner,save.account_id,save.expected_version,save.settings)
            else:
                lookup=AccountLookup.model_validate(payload)
                if op=='get_identity':
                    result=await store.get_identity(owner,lookup.account_id)
                else:
                    result=await (store.get_account(owner,lookup.account_id) if op=='get_account' else store.list_events(owner,lookup.account_id))
            return {'result':result}
        except ValidationError:
            raise HTTPException(422,'Invalid broker settings') from None
        except BrokerNotFound:
            raise HTTPException(404,'Broker account not found') from None
        except BrokerConflict:
            raise HTTPException(409,'Duplicate account or settings changed; reload before saving') from None
        except Exception:
            raise HTTPException(503,'Broker settings storage unavailable') from None
    return router
