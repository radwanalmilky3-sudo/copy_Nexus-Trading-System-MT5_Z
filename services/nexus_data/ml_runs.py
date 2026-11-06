"""ml.training_runs registry (dictionary: ml.training_runs + ml.model_registry_events).

Written by nexus_ml after every candidate training attempt (promoted OR
rejected) via the internal secret. The sole-writer rule is respected: nexus_ml
reports over HTTP; nexus-data owns the DuckDB connection.
"""
import json
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field

from shared.broker_settings_models import StrictModel
from .trial_registry_router import _authorize


class TrainingRunReport(StrictModel):
    run_id: str = Field(min_length=4, max_length=128)
    symbol: str = Field(min_length=1, max_length=64)
    timeframe: str = Field(min_length=2, max_length=4)
    generation: str | None = Field(default=None, max_length=128)
    decision: Literal['promoted', 'rejected', 'failed']
    reason: str | None = Field(default=None, max_length=250)
    fold_count: int = Field(default=0, ge=0)
    metrics: dict[str, Any] = Field(default_factory=dict)
    data_window: str | None = Field(default=None, max_length=120)
    dataset_id: str | None = Field(default=None, max_length=200)
    label_target_id: str | None = Field(default=None, max_length=200)
    account_id: str | None = Field(default=None, max_length=64)


_DDL=('CREATE TABLE IF NOT EXISTS ml_training_runs(run_id VARCHAR PRIMARY KEY,symbol VARCHAR,timeframe VARCHAR,'
      'generation VARCHAR,decision VARCHAR,reason VARCHAR,fold_count INTEGER,metrics_json VARCHAR,'
      'data_window VARCHAR,dataset_id VARCHAR,label_target_id VARCHAR,account_id VARCHAR,'
      'reported_at VARCHAR,recorded_at VARCHAR)')


def create_ml_runs_router(store) -> APIRouter:
    router=APIRouter(prefix='/api/data/ml',dependencies=[Depends(_authorize)])

    @router.post('/training-run')
    async def record_training_run(report:TrainingRunReport):
        recorded=datetime.now(timezone.utc).isoformat()
        def _persist():
            conn=store.owner_store._conn
            conn.execute(_DDL)
            conn.execute('INSERT INTO ml_training_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET '
                         'generation=excluded.generation,decision=excluded.decision,reason=excluded.reason,fold_count=excluded.fold_count,'
                         'metrics_json=excluded.metrics_json,data_window=excluded.data_window,dataset_id=excluded.dataset_id,'
                         'label_target_id=excluded.label_target_id,account_id=excluded.account_id,reported_at=excluded.reported_at,recorded_at=excluded.recorded_at',
                         (report.run_id,report.symbol,report.timeframe,report.generation,report.decision,report.reason,
                          report.fold_count,json.dumps(report.metrics,sort_keys=True,default=str),report.data_window,
                          report.dataset_id,report.label_target_id,report.account_id,None,recorded))
        await store.owner_store._execute_locked(_persist)
        return {'ok':True,'run_id':report.run_id,'recorded_at':recorded}

    @router.get('/training-runs')
    async def list_training_runs(symbol:str|None=Query(default=None,max_length=64),limit:int=Query(default=100,ge=1,le=500)):
        def _read():
            conn=store.owner_store._conn
            conn.execute(_DDL)
            if symbol:
                return [dict(zip(('run_id','symbol','timeframe','generation','decision','reason','fold_count','metrics','data_window','dataset_id','label_target_id','account_id','reported_at','recorded_at'),r)) for r in conn.execute(
                    'SELECT run_id,symbol,timeframe,generation,decision,reason,fold_count,metrics_json,data_window,dataset_id,label_target_id,account_id,reported_at,recorded_at FROM ml_training_runs WHERE symbol=? ORDER BY recorded_at DESC LIMIT ?',
                    (symbol,limit)).fetchall()]
            return [dict(zip(('run_id','symbol','timeframe','generation','decision','reason','fold_count','metrics','data_window','dataset_id','label_target_id','account_id','reported_at','recorded_at'),r)) for r in conn.execute(
                'SELECT run_id,symbol,timeframe,generation,decision,reason,fold_count,metrics_json,data_window,dataset_id,label_target_id,account_id,reported_at,recorded_at FROM ml_training_runs ORDER BY recorded_at DESC LIMIT ?',
                (limit,)).fetchall()]
        rows=await store.owner_store._execute_locked(_read)
        for r in rows:
            try:r['metrics']=json.loads(r.pop('metrics_json') or '{}')
            except Exception:r['metrics']={}
        return {'rows':rows,'count':len(rows)}

    return router
