"""Idea 6 — label generator (dictionary: ml.prediction_targets + ml.prediction_evaluations inputs).

Generates supervised labels from stored research candles, fully derived from
persisted bars (nothing synthetic). Two honest label kinds:
- direction: sign of close[t+h] - close[t] (+1 / -1 / 0 on exact equality)
- barrier: which barrier is hit first within h bars, using ATR(14) multiples
  for TP and SL ('tp_first' / 'sl_first' / 'timeout')
Labels are stored per target so any training run can cite the exact target.
"""
import json
from datetime import datetime, timezone

_TARGETS_DDL='CREATE TABLE IF NOT EXISTS label_targets(target_id VARCHAR PRIMARY KEY,owner_id VARCHAR,account_id VARCHAR,symbol VARCHAR,timeframe VARCHAR,kind VARCHAR,horizon_bars INTEGER,name VARCHAR,generated_at VARCHAR,bars_total INTEGER,labeled INTEGER,positives INTEGER,negatives INTEGER,timeouts INTEGER,status VARCHAR,metadata_json VARCHAR)'
_VALUES_DDL='CREATE TABLE IF NOT EXISTS label_values(target_id VARCHAR,bar_time BIGINT,label VARCHAR,PRIMARY KEY(target_id,bar_time))'


def _atr14(bars):
    trs=[]
    for i in range(1,len(bars)):
        h=float(bars[i]['high']);l=float(bars[i]['low']);pc=float(bars[i-1]['close'])
        trs.append(max(h-l,abs(h-pc),abs(l-pc)))
    if not trs:return None
    return sum(trs)/len(trs)


def _gen_direction(bars,h):
    out=[];pos=neg=flat=0
    for i in range(len(bars)-h):
        c0=float(bars[i]['close']);c1=float(bars[i+h]['close'])
        label='up' if c1>c0 else ('down' if c1<c0 else 'flat')
        pos+=label=='up';neg+=label=='down';flat+=label=='flat'
        out.append((bars[i]['time'],label))
    return out,pos,neg,flat


def _gen_barrier(bars,h,tp_mult,sl_mult):
    atr=_atr14(bars)
    if not atr or atr<=0:raise ValueError('تعذر حساب ATR من الشموع المخزنة — البيانات غير كافية للحاجز.')
    out=[];tp_first=sl_first=timeout=0
    for i in range(len(bars)-h):
        c0=float(bars[i]['close']);tp=c0+tp_mult*atr;sl=c0-sl_mult*atr
        label='timeout'
        for j in range(1,h+1):
            hi=float(bars[i+j]['high']);lo=float(bars[i+j]['low'])
            hit_tp=hi>=tp;hit_sl=lo<=sl
            if hit_tp and hit_sl:label='ambiguous';break  # كلا الحاجزين في نفس الشمعة — غير قابل للحسم
            if hit_tp:label='tp_first';break
            if hit_sl:label='sl_first';break
        tp_first+=label=='tp_first';sl_first+=label=='sl_first';timeout+=label=='timeout'
        out.append((bars[i]['time'],label))
    return out,tp_first,sl_first,timeout,round(atr,6)


async def generate_labels(store,owner,account_id,symbol,timeframe,kind,horizon,name,tp_atr=1.5,sl_atr=1.0):
    if kind not in ('direction','barrier'):raise ValueError('نوع التسمية غير مدعوم')
    if not isinstance(horizon,int) or horizon<1 or horizon>500:raise ValueError('الأفق يجب أن يكون بين 1 و500 شمعة')
    if kind=='barrier' and (tp_atr<=0 or sl_atr<=0):raise ValueError('مضاعفات ATR يجب أن تكون موجبة')
    await store.get_account(owner,account_id)
    def read():
        conn=store.owner_store._conn
        conn.execute(_TARGETS_DDL);conn.execute(_VALUES_DDL)
        return conn.execute('SELECT bar_json FROM research_account_candles WHERE owner_id=? AND account_id=? AND symbol=? AND timeframe=? ORDER BY bar_time ASC',
                            (owner,account_id,symbol,timeframe)).fetchall()
    rows=await store.owner_store._execute_locked(read)
    bars=[json.loads(r[0]) for r in rows]
    if len(bars)<horizon+30:
        raise ValueError(f'الشموع المخزنة ({len(bars)}) أقل من المطلوب للتسمية ({horizon+30} على الأقل). استورد بيانات أولاً.')
    if kind=='direction':
        labels,pos,neg,extra=_gen_direction(bars,horizon)
        counts={'positives':pos,'negatives':neg,'flat':extra};timeouts=0;atr=None
    else:
        labels,tp_first,sl_first,timeout,atr=_gen_barrier(bars,horizon,float(tp_atr),float(sl_atr))
        counts={'tp_first':tp_first,'sl_first':sl_first,'timeout':timeout};timeouts=timeout
    target_id=f'labeltarget:{account_id}:{symbol}:{timeframe}:{kind}:h{horizon}'
    generated=datetime.now(timezone.utc).isoformat()
    metadata={'name':name,'account_id':account_id,'symbol':symbol,'timeframe':timeframe,'kind':kind,
              'horizon_bars':horizon,'tp_atr':tp_atr if kind=='barrier' else None,
              'sl_atr':sl_atr if kind=='barrier' else None,'atr_at_generation':atr,
              'bars_total':len(bars),'first_bar':bars[0]['time'],'last_bar':bars[-1]['time'],
              'created_by':owner}
    status='ok' if labels else 'empty'
    def _persist():
        conn=store.owner_store._conn
        conn.execute('BEGIN TRANSACTION')
        try:
            conn.execute(_TARGETS_DDL);conn.execute(_VALUES_DDL)
            conn.execute('DELETE FROM label_values WHERE target_id=?',(target_id,))
            conn.executemany('INSERT INTO label_values VALUES(?,?,?)',[(target_id,t,l) for t,l in labels])
            conn.execute('INSERT INTO label_targets VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(target_id) DO UPDATE SET generated_at=excluded.generated_at,bars_total=excluded.bars_total,labeled=excluded.labeled,positives=excluded.positives,negatives=excluded.negatives,timeouts=excluded.timeouts,status=excluded.status,metadata_json=excluded.metadata_json',
                         (target_id,owner,account_id,symbol,timeframe,kind,horizon,name,generated,len(bars),len(labels),
                          counts.get('positives',counts.get('tp_first',0)),counts.get('negatives',counts.get('sl_first',0)),
                          timeouts,status,json.dumps(metadata,ensure_ascii=False,sort_keys=True,default=str)))
            conn.execute('COMMIT')
        except BaseException:
            conn.execute('ROLLBACK');raise
    await store.owner_store._execute_locked(_persist)
    return {'target_id':target_id,'name':name,'symbol':symbol,'timeframe':timeframe,'kind':kind,
            'horizon_bars':horizon,'labeled':len(labels),'bars_total':len(bars),**counts,
            'status':status,'generated_at':generated,
            'note':'تسميات مشتقة من الشموع المخزنة فقط. آخر h شموع بلا تسمية بحكم التعريف (لا مستقبل لها). تخضع لنفس شهادة جودة الدفعة المصدر.'}


async def list_label_targets(store,owner,account_id):
    await store.get_account(owner,account_id)
    def read():
        conn=store.owner_store._conn
        conn.execute(_TARGETS_DDL)
        return [dict(zip(('target_id','symbol','timeframe','kind','horizon_bars','name','generated_at','labeled','status'),r)) for r in conn.execute(
            'SELECT target_id,symbol,timeframe,kind,horizon_bars,name,generated_at,labeled,status FROM label_targets WHERE owner_id=? AND account_id=? ORDER BY generated_at DESC LIMIT 100',
            (owner,account_id)).fetchall()]
    return await store.owner_store._execute_locked(read)
