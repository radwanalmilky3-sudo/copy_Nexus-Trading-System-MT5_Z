"""Source-backed evidence for the eight laboratory views."""
import hashlib
import json
from datetime import datetime,timezone
from uuid import uuid4
from shared.research_context_engine import ASSETS,pair_context,point_in_time
from .data_loader import load_research_series
from .research_market import SECONDS,inspect_bars,session_gap_review

def logical(symbol):
    # Only known exact broker aliases; never guess what a bond instrument means.
    return next((a for a in ASSETS if symbol in (a,a+'s')),None)

async def get_research_report(store,owner,account_id,report_id):
    await store.get_account(owner,account_id)
    def read():
        from .broker_settings_store import BrokerNotFound
        conn=store.owner_store._conn
        if not conn.execute("SELECT 1 FROM information_schema.tables WHERE table_name='research_context_reports'").fetchone():raise BrokerNotFound()
        row=conn.execute('SELECT report_json FROM research_context_reports WHERE owner_id=? AND account_id=? AND report_id=?',(owner,account_id,report_id)).fetchone()
        if not row:raise BrokerNotFound()
        return json.loads(row[0])
    return await store.owner_store._execute_locked(read)

async def research_analysis(store,owner,payload):
    account_id=payload['account_id'];tf=payload.get('timeframe','M15')
    if tf not in SECONDS:raise ValueError('Invalid timeframe')
    account,rows=await load_research_series(store,owner,account_id,tf,payload.get('start'),payload.get('end'))
    saved={a['broker_symbol'] for a in account['settings']['assets']}
    rows=[r for r in rows if r['symbol'] in saved]
    grouped={s:[r for r in rows if r['symbol']==s] for s in sorted(saved)}
    stamp=datetime.now(timezone.utc).isoformat()
    fingerprint=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
    context={'account_id':account_id,'server':account['server'],'timeframe':tf,'start':payload.get('start'),'end':payload.get('end'),'as_of':stamp,'settings_version':account['version'],'fingerprint':fingerprint,'engine_version':'cross-asset-observer-1','selected_symbol':payload.get('symbol')}
    report={'context':context,'datasets':[],'cleaning':[],'validation':[],'provenance':[],'strategies':[],'backtests':[],'artifacts':[],'mode':'observe','confidence':None,'trade_permission_changed':False}
    mapped={}
    for s,source in grouped.items():
        bars=[{k:r[k] for k in ('time','open','high','low','close','volume')} for r in source]
        clean,q=inspect_bars(bars,tf)
        session_review=session_gap_review(clean,tf,account,s)
        name=logical(s)
        if name:mapped[name]=clean
        known=sum(r['available_at'] is not None for r in source)
        observations=account['settings'].get('session_observations')
        clock_evidence=(next((o for o in observations if o['broker_symbol']==s and o['server']==account['server']),None)
                        if observations is not None else account['settings'].get('session_observation'))
        report['datasets'].append({'symbol':s,'logical_asset':name or 'خارج مجموعة السياق الستة','data_type':'غير موثق: عائد أم سعر' if name=='US10Y' else 'سعر','rows':len(source),'last_bar':source[-1]['time'] if source else None,'availability_known':known,'status':'stored' if source else 'missing'})
        report['cleaning'].append({'symbol':s,'rows_before':len(bars),'rows_after':len(clean),'invalid':q['rejected'],'duplicates':q['duplicates_removed'],'unclassified_gaps':q['unclassified_gaps'],'action':'فحص نسخة المصدر؛ لم تُكتب أسعار بديلة','fingerprint':q['fingerprint'],'checked_at':stamp})
        checks=[('سلامة الأسعار',q['rejected']==0 and bool(source),f"{q['rejected']} صف غير صالح"),('كفاية العينات',len(clean)>=121,f"{len(clean)} شمعة؛ نافذة 120 عائدًا تحتاج 121 شمعة على الأقل"),('توثيق وقت الإتاحة',bool(source) and known==len(source),f'{known} من {len(source)} موثقة'),('التحويل التاريخي إلى UTC',False,'فرق التوقيت المرصود لا يمثل جدولًا تاريخيًا معتمدًا'),('الفواصل الزمنية',q['unclassified_gaps']==0 and bool(source),f"{q['unclassified_gaps']} فاصل غير مصنف")]
        for check,passed,reason in checks:report['validation'].append({'symbol':s,'check':check,'result':'passed' if passed else 'needs_review','reason':reason,'fingerprint':q['fingerprint'],'checked_at':stamp})
        report['validation'].append({'symbol':s,'check':'ربط جلسات إعدادات الحساب','result':'needs_review',
            'reason':f"حالة الربط: {session_review['state']}؛ نسخة الإعدادات {account['version']}؛ {session_review['weekly_closure_candidates']} فاصل يطابق إغلاق الجدول الأسبوعي استرشاديًا؛ لا اعتماد تاريخي بأثر رجعي",
            'fingerprint':q['fingerprint'],'checked_at':stamp})
        report['validation'].append({'symbol':s,'check':'وقت نشر المصدر','result':'needs_review','reason':'المصدر لم يزوّد publication_time؛ لا يُستبدل بوقت الشمعة أو بوقت الجلب','fingerprint':q['fingerprint'],'checked_at':stamp})
        report['provenance'].append({'symbol':s,'server':account['server'],'timeframe':tf,'first_bar':source[0]['time'] if source else None,'last_bar':source[-1]['time'] if source else None,'publication_time':None,'available_at':max((r['available_at'] for r in source if r['available_at']),default=None),'availability_known':known,'total':len(source),'clock_evidence':clock_evidence,'fingerprint':q['fingerprint']})
    for name in ASSETS:
        if name not in mapped:report['validation'].append({'symbol':name,'check':'توفر الأصل المطلوب','result':'blocked','reason':'لم يُربط أصل محفوظ له بيانات في الفترة والإطار المختارين','checked_at':stamp,'fingerprint':fingerprint})
    gold=mapped.get('XAUUSD',[])
    for asset in ASSETS[1:]:
        other=mapped.get(asset,[])
        if asset=='US10Y':
            report['strategies'].append({'asset':asset,'status':'blocked','reason':'يجب توثيق هل الأداة عائد سندات أم سعر قبل تحديد التحويل الحسابي','confidence':None})
            continue
        result=pair_context(gold,other,SECONDS[tf])
        report['strategies'].append({'asset':asset,'status':'observed' if result['aligned_samples']>=20 else 'insufficient','reason':'ارتباط وأسبقية مرصودة فقط؛ لا إثبات لقدرة تنبؤية','conflict_flag':None,'action':'observe',**result})
    eligible=point_in_time(rows,datetime.fromisoformat(stamp).timestamp())
    report['backtests']=[{'name':'مقارنة فلتر السياق باستراتيجية الأساس','status':'blocked','reason':'يتطلب توثيق إغلاق الشموع تاريخيًا بـUTC، ووقت إتاحتها، وتعريف استراتيجية الأساس وتكاليفها. لا توجد نتيجة ربح أو اعتماد محسوبة لهذه النسخة.','eligible_rows':len(eligible),'data_fingerprint':fingerprint,'strategy_defined':False}]
    def artifacts():
        conn=store.owner_store._conn
        conn.execute('CREATE TABLE IF NOT EXISTS research_context_reports(owner_id VARCHAR,account_id VARCHAR,report_id VARCHAR PRIMARY KEY,timeframe VARCHAR,created_at VARCHAR,report_json VARCHAR)')
        if payload.get('persist'):
            conn.execute('INSERT INTO research_context_reports VALUES(?,?,?,?,?,?)',(owner,account_id,str(uuid4()),tf,stamp,json.dumps(report,ensure_ascii=False)))
        return [{'report_id':rid,'created_at':at,'timeframe':tf,'fingerprint':json.loads(raw)['context']['fingerprint'],'mode':'observe'} for rid,at,raw in conn.execute('SELECT report_id,created_at,report_json FROM research_context_reports WHERE owner_id=? AND account_id=? AND timeframe=? ORDER BY created_at DESC LIMIT 20',(owner,account_id,tf)).fetchall()]
    report['artifacts']=await store.owner_store._execute_locked(artifacts)
    return report
