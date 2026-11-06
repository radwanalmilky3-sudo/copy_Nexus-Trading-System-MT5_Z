"""Account-owned research candles, isolated from execution market data."""
import hashlib
import json
import math
import os
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from .mt5_connector import _mt5_worker

SECONDS={'M1':60,'M5':300,'M15':900,'M30':1800,'H1':3600,'H4':14400,'D1':86400}

def session_gap_review(bars,timeframe,account,symbol):
    """Compare source-clock gaps with saved windows without projecting history.

    A captured weekly schedule is reference evidence, not retrospective closure
    authority. All gaps remain unclassified until dated evidence covers them.
    """
    step=SECONDS[timeframe]
    gaps=[(a['time']+step,b['time']) for a,b in zip(bars,bars[1:])
          if b['time']-a['time']>step]
    result=dict(state='missing',settings_version=account['version'],
                unclassified_gaps=len(gaps),confirmed_closed=0,
                weekly_closure_candidates=0,source='account_settings.session_observation')
    observations=account['settings'].get('session_observations')
    evidence=(next((o for o in observations if o['broker_symbol']==symbol),None)
              if observations is not None else account['settings'].get('session_observation'))
    if not evidence:return result
    result['captured_at_utc']=evidence['captured_at_utc']
    if evidence['server']!=account['server']:
        result['state']='server_mismatch';return result
    if evidence['broker_symbol']!=symbol:
        result['state']='symbol_mismatch';return result
    windows=evidence.get('windows',[])
    if not windows or any(w['start_seconds']==w['end_seconds'] for w in windows):
        result['state']='incomplete';return result
    result['state']='weekly_reference_only'
    for start,end in gaps:
        if end-start>8*86400:continue
        first=datetime.fromtimestamp(start,timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=1)
        cursor=first;opened=False
        while cursor.timestamp()<end:
            day=(cursor.weekday()+1)%7
            for window in windows:
                if window['day']!=day:continue
                a=cursor.timestamp()+window['start_seconds']
                b=cursor.timestamp()+window['end_seconds']
                if b<a:b+=86400
                if a<end and start<b:opened=True
            cursor+=timedelta(days=1)
        if not opened:result['weekly_closure_candidates']+=1
    return result

def settings_clock(account,tick,captured):
    observations=account['settings'].get('session_observations')
    evidence=(max((o for o in observations if o['server']==account['server']),key=lambda o:o['captured_at_utc'],default=None)
              if observations is not None else account['settings'].get('session_observation'))
    context={'source':'account_settings.session_observation','settings_version':account['version'],'offset_seconds':None,'observed_at':None,'tick_utc':None,'state':'missing'}
    if not evidence or evidence.get('server')!=account['server']:return context
    context.update(offset_seconds=evidence['observed_offset_seconds'],observed_at=evidence['captured_at_utc'],state='observed')
    if tick and captured:
        now=datetime.fromisoformat(captured.replace('Z','+00:00')).timestamp()
        observed=datetime.fromisoformat(evidence['captured_at_utc'].replace('Z','+00:00')).timestamp()
        converted=tick['time']-evidence['observed_offset_seconds']
        if 0<=now-observed<=86400 and -60<=now-converted<=300:
            context.update(tick_utc=datetime.fromtimestamp(converted,timezone.utc).isoformat(),state='current_quote_verified')
        else:context['state']='needs_refresh'
    return context

def _reject_reason(bar):
    """Return the quarantine reason for a raw bar, or None when it is clean.

    Mirrors the original inspect predicates; also tolerates non-numeric or
    missing fields (previously a crash) so every bad raw row can be preserved
    with a reason instead of vanishing.
    """
    try:
        prices=[bar[k] for k in ('open','high','low','close')]
        volume=bar['volume']
    except (KeyError,TypeError):
        return 'invalid_record: missing or unusable OHLCV field'
    if not all(isinstance(x,(int,float)) and math.isfinite(x) and x>0 for x in prices):
        return 'invalid_record: non-positive or non-finite price'
    if bar['high']<max(prices) or bar['low']>min(prices):
        return 'invalid_record: broken OHLC envelope'
    if not isinstance(volume,(int,float)) or not math.isfinite(volume) or volume<0:
        return 'invalid_record: invalid volume'
    return None


def inspect_bars(bars,timeframe):
    """Clean a raw fetch while preserving every dropped row + its reason.

    Returns (clean_bars, quality) where quality['rejected_bars'] is the raw
    evidence list: invalid bars (reason 'invalid_record: ...') and conflicting
    duplicates that were superseded (reason 'duplicate: ...'). Identical
    duplicates are plain refetches and are counted, not archived.
    """
    valid=[];rejected_bars=[]
    for bar in bars:
        reason=_reject_reason(bar)
        if reason is None:valid.append(bar)
        else:rejected_bars.append({'bar':bar,'reason':reason})
    unique={}
    for b in valid:
        kept=unique.get(b['time'])
        if kept is not None and kept!=b:
            rejected_bars.append({'bar':kept,'reason':'duplicate: superseded by a differing bar at the same timestamp'})
        unique[b['time']]=b
    clean=sorted(unique.values(),key=lambda b:b['time'])
    invalid=sum(1 for e in rejected_bars if e['reason'].startswith('invalid_record'))
    gaps=sum(1 for a,b in zip(clean,clean[1:]) if b['time']-a['time']>SECONDS[timeframe])
    return clean,{'rejected':invalid,'duplicates_removed':len(valid)-len(clean),'unclassified_gaps':gaps,
                  'status':'needs_review' if gaps or invalid else 'basic_checks_passed',
                  'fingerprint':hashlib.sha256(json.dumps(clean,sort_keys=True).encode()).hexdigest(),
                  'rejected_bars':rejected_bars}


async def _archive_rejected(store,owner,account_id,symbol,timeframe,rejected_bars):
    """Write raw rejected bars to quarantine (raw payload + reason, idempotent)."""
    if not rejected_bars:return 0
    from .quality.quarantine import QuarantineRecord,QuarantineReason
    dataset_id=f'research_rejected:{account_id}:{symbol}:{timeframe}'
    records=[]
    for entry in rejected_bars:
        bar=entry['bar'];detail=entry['reason']
        reason=QuarantineReason.DUPLICATE if detail.startswith('duplicate') else QuarantineReason.INVALID_RECORD
        record_key=json.dumps({'owner_id':owner,'account_id':account_id,'symbol':symbol,'timeframe':timeframe,
                               'time':bar.get('time') if isinstance(bar,dict) else None},sort_keys=True,default=str)
        identity=json.dumps({'dataset_id':dataset_id,'reason':reason.value,'key':record_key},sort_keys=True)
        records.append(QuarantineRecord(
            quarantine_id=hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24],
            dataset_id=dataset_id,reason_code=reason,record_key=record_key,
            payload=dict(bar),detail=detail))
    await store.owner_store._write_quarantine(records)
    return len(records)


def _evidence_quality(quality):
    """Copy of a quality dict sized for the run ledger (full rows capped at 10)."""
    q=dict(quality)
    rows=q.pop('rejected_bars',None) or []
    if rows:
        q['rejected_bars']=rows[:10]
        q['rejected_bars_total']=len(rows)
    return q


def _input_binding(owner,account,payload):
    """sha256 over the request + account settings versions that produced it."""
    material=json.dumps({'owner':owner,'account_id':payload['account_id'],'symbol':payload['symbol'],
                         'timeframe':payload['timeframe'],'mode':payload['mode'],
                         'start':payload.get('start'),'end':payload.get('end'),
                         'server':account['server'],'settings_version':account['version']},
                        sort_keys=True,default=str)
    return hashlib.sha256(material.encode('utf-8')).hexdigest()

async def _research_market(store,owner,payload):
    from .broker_settings_router import AccountLookup
    account_id=AccountLookup.model_validate({'account_id':payload['account_id']}).account_id
    identity=await store.get_identity(owner,account_id)
    account=await store.get_account(owner,account_id)
    symbol=payload['symbol'];tf=payload['timeframe'];mode=payload['mode']
    if tf not in SECONDS or not isinstance(symbol,str) or not 1<=len(symbol)<=128 or mode not in ('history','live','unified'):
        raise ValueError('Invalid research request')
    added=0;existing=0
    def db_run(write=None):
        nonlocal added,existing
        conn=store.owner_store._conn
        conn.execute('CREATE TABLE IF NOT EXISTS research_account_candles(owner_id VARCHAR,account_id VARCHAR,symbol VARCHAR,timeframe VARCHAR,bar_time BIGINT,bar_json VARCHAR,origin VARCHAR,PRIMARY KEY(owner_id,account_id,symbol,timeframe,bar_time))')
        conn.execute('CREATE TABLE IF NOT EXISTS research_candle_availability(owner_id VARCHAR,account_id VARCHAR,symbol VARCHAR,timeframe VARCHAR,bar_time BIGINT,available_at VARCHAR,PRIMARY KEY(owner_id,account_id,symbol,timeframe,bar_time))')
        args=(owner,account_id,symbol,tf)
        if write is not None:
            conn.execute('BEGIN TRANSACTION')
            try:
                before=conn.execute('SELECT COUNT(*) FROM research_account_candles WHERE owner_id=? AND account_id=? AND symbol=? AND timeframe=?',args).fetchone()[0]
                for bar in write:
                    conn.execute('INSERT INTO research_account_candles VALUES(?,?,?,?,?,?,?) ON CONFLICT DO NOTHING',(*args,bar['time'],json.dumps(bar),mode))
                    conn.execute('INSERT INTO research_candle_availability VALUES(?,?,?,?,?,?) ON CONFLICT DO NOTHING',(*args,bar['time'],datetime.now(timezone.utc).isoformat()))
                after=conn.execute('SELECT COUNT(*) FROM research_account_candles WHERE owner_id=? AND account_id=? AND symbol=? AND timeframe=?',args).fetchone()[0]
                added=after-before;existing=len(write)-added
                conn.execute('COMMIT')
            except BaseException:
                conn.execute('ROLLBACK');raise
        return [json.loads(r[0]) for r in conn.execute('SELECT bar_json FROM research_account_candles WHERE owner_id=? AND account_id=? AND symbol=? AND timeframe=? ORDER BY bar_time',args).fetchall()]
    tick=None;captured=None;received=0;fetch_rejected=0;fetch_duplicates=0;archived=0
    if mode in ('history','live'):
        data=await _mt5_worker({'op':'research_'+mode,'use_terminal':True,'path':os.getenv('MT5_PATH',''),'expected_login':identity['login'],'expected_server':identity['server'],'symbol':symbol,'broker_symbol':symbol,'timeframe':tf,**({k:payload[k] for k in ('start','end')} if mode=='history' else {})},timeout_sec=25)
        clean,quality=inspect_bars(data['bars'],tf);received=len(clean);fetch_rejected=quality['rejected'];fetch_duplicates=quality['duplicates_removed']
        archived+=await _archive_rejected(store,owner,account_id,symbol,tf,quality['rejected_bars'])
        if mode=='history':bars=await store.owner_store._execute_locked(lambda:db_run(clean))
        else:bars=clean
        tick=data['tick'];captured=data['captured_at']
    else:
        bars=await store.owner_store._execute_locked(db_run)
        try:
            data=await _mt5_worker({'op':'research_live','use_terminal':True,'path':os.getenv('MT5_PATH',''),'expected_login':identity['login'],'expected_server':identity['server'],'symbol':symbol,'broker_symbol':symbol,'timeframe':tf},timeout_sec=25)
            clean,scan=inspect_bars(data['bars'],tf);fetch_rejected=scan['rejected'];fetch_duplicates=scan['duplicates_removed']
            archived+=await _archive_rejected(store,owner,account_id,symbol,tf,scan['rejected_bars'])
            bars=await store.owner_store._execute_locked(lambda:db_run(clean))
            tick=data['tick'];captured=data['captured_at'];received=len(clean)
        except (RuntimeError,TimeoutError):
            captured=None
    bars,quality=inspect_bars(bars,tf)
    archived+=await _archive_rejected(store,owner,account_id,symbol,tf,quality['rejected_bars'])
    quality['session_review']=session_gap_review(bars,tf,account,symbol)
    last=bars[-1]['time'] if bars else None
    return {'account_id':account_id,'server':identity['server'],'symbol':symbol,'timeframe':tf,'mode':mode,'count':len(bars),'received':received,'added':added,'existing':existing,'fetch_rejected':fetch_rejected,'fetch_duplicates':fetch_duplicates,'archived_rejected':archived,'first':bars[0]['time'] if bars else None,'last':last,'tick':tick,'captured_at':captured,'quality':quality,'bars':bars[-200:],'status':'empty' if not bars else 'needs_review' if quality['unclassified_gaps'] else 'stored','coverage_complete':False,'clock':settings_clock(account,tick,captured)}


def _ledger(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS research_account_runs(owner_id VARCHAR,account_id VARCHAR,run_id VARCHAR PRIMARY KEY,started_at VARCHAR,record_json VARCHAR)')


async def list_research_runs(store,owner,account_id):
    await store.get_account(owner,account_id)
    def read():
        conn=store.owner_store._conn;_ledger(conn)
        return [json.loads(r[0]) for r in conn.execute('SELECT record_json FROM research_account_runs WHERE owner_id=? AND account_id=? ORDER BY started_at DESC,run_id DESC LIMIT 200',(owner,account_id)).fetchall()]
    return await store.owner_store._execute_locked(read)


async def research_market(store,owner,payload):
    account=await store.get_account(owner,payload['account_id'])
    record={'run_id':str(uuid4()),'group_id':payload.get('group_id') or str(uuid4()),'account_id':payload['account_id'],'symbol':payload['symbol'],'timeframe':payload['timeframe'],'mode':payload['mode'],'requested_start':payload.get('start'),'requested_end':payload.get('end'),'started_at':datetime.now(timezone.utc).isoformat(),'finished_at':None,'status':'running','server':account['server'],'settings_version':account['version'],'input_hash':_input_binding(owner,account,payload)}
    def persist(insert=False):
        conn=store.owner_store._conn;_ledger(conn)
        if insert:conn.execute('INSERT INTO research_account_runs VALUES(?,?,?,?,?)',(owner,payload['account_id'],record['run_id'],record['started_at'],json.dumps(record,default=str)))
        else:conn.execute('UPDATE research_account_runs SET record_json=? WHERE owner_id=? AND account_id=? AND run_id=?',(json.dumps(record,default=str),owner,payload['account_id'],record['run_id']))
    await store.owner_store._execute_locked(lambda:persist(True))
    try:
        result=await _research_market(store,owner,payload)
        record.update({k:result[k] for k in ('count','received','added','existing','fetch_rejected','fetch_duplicates','archived_rejected','first','last','coverage_complete','captured_at')})
        record['quality']=_evidence_quality(result['quality'])
        record['output_hash']=result['quality'].get('fingerprint')
        record['status']='completed' if result['received'] and result['captured_at'] else 'partial'
        record['finished_at']=datetime.now(timezone.utc).isoformat()
        await _complete_evidence(store,owner,record)
        result['run_id']=record['run_id']
        result['input_hash']=record['input_hash']
        result['output_hash']=record['output_hash']
        return result
    except Exception:
        record.update(status='failed',finished_at=datetime.now(timezone.utc).isoformat(),error='تعذر إتمام الجلب أو الحفظ؛ تحقق من اتصال الحساب وتوفر البيانات.')
        await store.owner_store._execute_locked(persist)
        raise


async def _complete_evidence(store,owner,record):
    """Bind a completed run to datasets, a quality certificate, and lineage.

    Runs on the owner connection under the store lock inside one transaction:
    ledger UPDATE + dataset registrations (clean + raw fetch envelope) +
    quality_runs certificate carrying input_hash/output_hash/settings_version
    + a raw->clean lineage edge. Failed runs never reach this, so they cannot
    fabricate output bindings.
    """
    await store.owner_store.ensure_lineage_schema()
    account_id=record['account_id'];symbol=record['symbol'];tf=record['timeframe']
    clean_id=f'research:{account_id}:{symbol}:{tf}'
    raw_id=f'research_raw:{account_id}:{symbol}:{tf}'
    rejected_id=f'research_rejected:{account_id}:{symbol}:{tf}'
    archived=int(record.get('archived_rejected') or 0)
    quality=record.get('quality') or {}
    checks={'bars_stored':int(record.get('count') or 0)>0,
            'fetch_clean':int(record.get('fetch_rejected') or 0)==0,
            'no_unclassified_gaps':int(quality.get('unclassified_gaps') or 0)==0,
            'fetch_captured':bool(record.get('captured_at'))}
    passed=sum(1 for ok in checks.values() if ok);total=len(checks)
    summary={'run_id':record['run_id'],'owner_id':owner,'account_id':account_id,'symbol':symbol,
             'timeframe':tf,'mode':record.get('mode'),'server':record.get('server'),
             'input_hash':record.get('input_hash'),'output_hash':record.get('output_hash'),
             'settings_version':record.get('settings_version'),
             'fingerprint':quality.get('fingerprint'),'checks':checks,
             'counts':{k:record.get(k) for k in ('count','received','added','existing',
                                                 'fetch_rejected','fetch_duplicates','archived_rejected')}}
    started=datetime.fromisoformat(record['started_at'])
    finished=datetime.fromisoformat(record['finished_at']) if record.get('finished_at') else started
    quality_run_id='researchqr:'+record['run_id']
    lineage_id='researchlin:'+hashlib.sha256(record['run_id'].encode('utf-8')).hexdigest()[:20]
    metadata=json.dumps({**summary,'quality_run_id':quality_run_id},ensure_ascii=False,sort_keys=True,default=str)
    def _persist():
        conn=store.owner_store._conn
        conn.execute('BEGIN TRANSACTION')
        try:
            conn.execute('UPDATE research_account_runs SET record_json=? WHERE owner_id=? AND account_id=? AND run_id=?',
                         (json.dumps(record,ensure_ascii=False,default=str),owner,account_id,record['run_id']))
            conn.execute('INSERT INTO datasets(dataset_id,dataset_name,owner,source_system,storage_uri,grain,sensitivity,metadata_json) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(dataset_id) DO NOTHING',
                         (clean_id,clean_id,owner,'research_account_candles',f'table:research_account_candles#{account_id}',tf,'account',
                          json.dumps({'account_id':account_id,'symbol':symbol,'timeframe':tf,'server':record.get('server'),
                                      'settings_version':record.get('settings_version')},sort_keys=True,default=str)))
            conn.execute('INSERT INTO datasets(dataset_id,dataset_name,owner,source_system,storage_uri,grain,sensitivity,metadata_json) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(dataset_id) DO NOTHING',
                         (raw_id,raw_id,owner,'mt5_research_fetch',f'quarantine:{rejected_id}' if archived else None,tf,'account',
                          json.dumps({'mode':record.get('mode'),'received':record.get('received'),
                                      'archived_rejected':archived,'materialized':bool(archived)},sort_keys=True,default=str)))
            conn.execute('INSERT INTO quality_runs(quality_run_id,dataset_id,contract_version,status,checks_total,checks_passed,checks_failed,started_at,finished_at,summary_json) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(quality_run_id) DO NOTHING',
                         (quality_run_id,clean_id,'research_market_v1',
                          'passed' if passed==total else 'warning',total,passed,total-passed,
                          started,finished,json.dumps(summary,ensure_ascii=False,sort_keys=True,default=str)))
            conn.execute('INSERT INTO lineage(lineage_id,upstream_dataset_id,downstream_dataset_id,transformation_name,transformation_version,run_started_at,run_finished_at,metadata_json) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(lineage_id) DO NOTHING',
                         (lineage_id,raw_id,clean_id,'inspect_bars_fetch_merge','v1',started,finished,metadata))
            conn.execute('COMMIT')
        except BaseException:
            conn.execute('ROLLBACK');raise
    await store.owner_store._execute_locked(_persist)


_TF_SECONDS={'M1':60,'M5':300,'M15':900,'M30':1800,'H1':3600,'H4':14400,'D1':86400}
BASE_SYMBOL='XAUUSD'


async def batch_certificate(store,owner,account_id,group_id):
    """Batch-level quality certificate (dictionary: quality.data_certificates +
    context.cross_asset_observations). Aggregates the runs sharing group_id:
    totals, per-symbol coverage, and pack alignment vs the base symbol. Honest
    by construction — derived only from persisted run records, nothing invented."""
    if not group_id or len(group_id)>64:
        raise ValueError('group_id required')
    await store.get_account(owner,account_id)
    def read():
        conn=store.owner_store._conn;_ledger(conn)
        return [json.loads(r[0]) for r in conn.execute(
            'SELECT record_json FROM research_account_runs WHERE owner_id=? AND account_id=? AND record_json LIKE ? ORDER BY started_at ASC',
            (owner,account_id,'%'+group_id+'%')).fetchall()]
    runs=await store.owner_store._execute_locked(read)
    runs=[r for r in runs if r.get('group_id')==group_id]
    if not runs:
        raise ValueError('No runs found for this group_id')
    totals={'runs':len(runs),
            'completed':sum(1 for r in runs if r.get('status')=='completed'),
            'partial':sum(1 for r in runs if r.get('status')=='partial'),
            'failed':sum(1 for r in runs if r.get('status')=='failed'),
            'bars':sum(int(r.get('count') or 0) for r in runs),
            'fetch_rejected':sum(int(r.get('fetch_rejected') or 0) for r in runs),
            'archived_rejected':sum(int(r.get('archived_rejected') or 0) for r in runs)}
    gaps=sum(int((r.get('quality') or {}).get('unclassified_gaps') or 0) for r in runs)
    totals['unclassified_gaps']=gaps
    # محاذاة الحزمة: أول/آخر شمعة لكل رمز مقابل الرمز الأساس
    by_symbol={}
    for r in runs:
        if not r.get('first') or not r.get('last'):continue
        cur=by_symbol.get(r['symbol'])
        if cur is None:by_symbol[r['symbol']]={'first':r['first'],'last':r['last'],'tf':r.get('timeframe'),
                                               'requested_start':r.get('requested_start'),'requested_end':r.get('requested_end')}
        else:
            cur['first']=min(cur['first'],r['first']);cur['last']=max(cur['last'],r['last'])
    base=by_symbol.get(BASE_SYMBOL) or next(iter(by_symbol.values()),None)
    alignment=[]
    for sym,info in sorted(by_symbol.items()):
        entry={'symbol':sym,'timeframe':info['tf'],
               'first':datetime.fromtimestamp(info['first'],tz=timezone.utc).isoformat(),
               'last':datetime.fromtimestamp(info['last'],tz=timezone.utc).isoformat()}
        if base and info is not base:
            entry['last_offset_vs_base_seconds']=int(info['last']-base['last'])
            tf_sec=_TF_SECONDS.get(info['tf'] or '',900)
            entry['aligned']=abs(info['last']-base['last'])<=tf_sec*2
        else:
            entry['last_offset_vs_base_seconds']=0;entry['aligned']=True;entry['is_base']=info is base
        if info['requested_start'] and info['requested_end']:
            span=max(1,int((datetime.fromisoformat(str(info['requested_end']).replace('Z','+00:00'))-datetime.fromisoformat(str(info['requested_start']).replace('Z','+00:00'))).total_seconds()))
            entry['coverage_pct']=round(min(100.0,(info['last']-info['first'])/span*100),2)
        alignment.append(entry)
    misaligned=[a['symbol'] for a in alignment if not a.get('aligned',True)]
    low_coverage=[a['symbol'] for a in alignment if a.get('coverage_pct') is not None and a['coverage_pct']<95.0]
    checks={'all_runs_completed':totals['failed']==0 and totals['partial']==0,
            'no_fetch_rejected':totals['fetch_rejected']==0,
            'no_unclassified_gaps':gaps==0,
            'pack_aligned':not misaligned,
            'coverage_complete':not low_coverage}
    passed=sum(1 for ok in checks.values() if ok)
    cert={'group_id':group_id,'account_id':account_id,'owner_id':owner,
          'issued_at':datetime.now(timezone.utc).isoformat(),
          'status':'valid' if passed==len(checks) else ('warning' if passed>=len(checks)-2 else 'invalid'),
          'checks':checks,'checks_passed':passed,'checks_total':len(checks),
          'totals':totals,'alignment':alignment,
          'misaligned_symbols':misaligned,'low_coverage_symbols':low_coverage,
          'fingerprints':[r.get('output_hash') for r in runs if r.get('output_hash')][:32],
          'note':'شهادة مستنتجة من سجلات العمليات المحفوظة فقط — لا افتراض ولا تعبئة. لا تغطي شيئاً لم يُستورد.'}
    return cert


async def create_train_dataset(store,owner,account_id,group_id,name):
    """Idea 4 — bind an imported batch to a versioned training dataset.

    Requires the batch certificate to exist and not be invalid: an invalid
    batch never becomes a training set. Registers one dataset row for the
    group and lineage edges from every clean per-symbol dataset into it, so
    any future training run can cite exactly which certified inputs it used."""
    import re as _re
    name=(name or '').strip()
    if not name or len(name)>128 or not _re.fullmatch(r'[\w\u0600-\u06FF][\w\u0600-\u06FF \-_.]{0,127}',name):
        raise ValueError('اسم مجموعة التدريب مطلوب (حتى 128 حرفاً دون رموز خاصة)')
    cert=await batch_certificate(store,owner,account_id,group_id)
    if cert['status']=='invalid':
        raise ValueError('رفض الإنشاء: شهادة الدفعة غير صالحة. أصلح الفحوص الفاشلة ثم أعد الاستيراد.')
    dataset_id='trainset:'+account_id+':'+group_id
    symbols=sorted({a['symbol'] for a in cert.get('alignment',[])})
    timeframes=sorted({a.get('timeframe') for a in cert.get('alignment',[]) if a.get('timeframe')})
    def read_window():
        conn=store.owner_store._conn;_ledger(conn)
        row=conn.execute('SELECT MIN(started_at),MAX(started_at) FROM research_account_runs WHERE owner_id=? AND account_id=? AND record_json LIKE ?',(owner,account_id,'%'+group_id+'%')).fetchone()
        return row
    lo,hi=await store.owner_store._execute_locked(read_window)
    metadata={'group_id':group_id,'account_id':account_id,'kind':'training_group',
              'symbols':symbols,'timeframes':timeframes,'runs_window_utc':[lo,hi],
              'certificate':{'status':cert['status'],'checks':cert['checks'],'issued_at':cert['issued_at'],
                             'fingerprints':cert.get('fingerprints',[])[:16]},
              'created_by':owner,'server_time_utc':datetime.now(timezone.utc).isoformat()}
    def _persist():
        conn=store.owner_store._conn
        conn.execute('BEGIN TRANSACTION')
        try:
            conn.execute('INSERT INTO datasets(dataset_id,dataset_name,owner,source_system,storage_uri,grain,sensitivity,metadata_json) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(dataset_id) DO NOTHING',
                         (dataset_id,name,owner,'research_train_group',f'group:{group_id}','multi','account',
                          json.dumps(metadata,ensure_ascii=False,sort_keys=True,default=str)))
            existing=conn.execute('SELECT dataset_id FROM datasets WHERE dataset_id=?',(dataset_id,)).fetchone()
            edges=0
            if existing:
                for a in cert.get('alignment',[]):
                    sym=a['symbol'];tf=a.get('timeframe') or 'M15'
                    upstream=f'research:{account_id}:{sym}:{tf}'
                    edge_id='trainlin:'+hashlib.sha256((dataset_id+upstream).encode('utf-8')).hexdigest()[:20]
                    cur=conn.execute('SELECT 1 FROM lineage WHERE lineage_id=?',(edge_id,)).fetchone()
                    if not cur:
                        conn.execute('INSERT INTO lineage(lineage_id,upstream_dataset_id,downstream_dataset_id,transformation_name,transformation_version,run_started_at,run_finished_at,metadata_json) VALUES(?,?,?,?,?,?,?,?)',
                                     (edge_id,upstream,dataset_id,'train_group_binding','v1',lo,hi,json.dumps({'group_id':group_id,'symbol':sym,'timeframe':tf},ensure_ascii=False,sort_keys=True,default=str)))
                        edges+=1
            conn.execute('COMMIT')
            return edges
        except BaseException:
            conn.execute('ROLLBACK');raise
    edges=await store.owner_store._execute_locked(_persist)
    row=await store.owner_store._execute_locked(lambda:(lambda c:(c.execute('SELECT dataset_id,dataset_name,owner,source_system,storage_uri,grain,sensitivity,metadata_json FROM datasets WHERE dataset_id=?',(dataset_id,)).fetchone()))(store.owner_store._conn))
    return {'dataset_id':dataset_id,'name':name,'symbols':symbols,'timeframes':timeframes,
            'certificate_status':cert['status'],'lineage_edges_added':edges,
            'metadata':metadata,'registered':row is not None,
            'note':'مجموعة تدريب مرتبطة بشهادة الدفعة؛ التنفيذ والتدريب يتمان في nexus_ml عند جدولة التدريب.'}
