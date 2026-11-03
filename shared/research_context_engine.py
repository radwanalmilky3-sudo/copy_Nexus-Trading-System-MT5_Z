"""Deterministic observation-only cross-asset calculations."""
import math
from statistics import mean

ASSETS=('XAUUSD','XAGUSD','WTI','DXY','US10Y','VIX')

def pearson(pairs):
    if len(pairs)<3:return None
    x,y=zip(*pairs);mx,my=mean(x),mean(y)
    xx=sum((v-mx)**2 for v in x);yy=sum((v-my)**2 for v in y)
    if xx<=0 or yy<=0:return None
    return max(-1.,min(1.,sum((a-mx)*(b-my) for a,b in pairs)/math.sqrt(xx*yy)))

def returns(rows,step,kind='price'):
    out={}
    rows=sorted(rows,key=lambda r:r['time'])
    for a,b in zip(rows,rows[1:]):
        if b['time']-a['time']!=step:continue
        if a['close']>0 and b['close']>0:
            out[b['time']]=b['close']-a['close'] if kind=='yield' else math.log(b['close']/a['close'])
    return out

def point_in_time(rows,as_of):
    """Unknown availability or UTC close cannot be used in historical tests."""
    return [r for r in rows if r.get('available_at_epoch') is not None and r.get('close_utc_epoch') is not None and r['available_at_epoch']<=as_of and r['close_utc_epoch']<=as_of]

def pair_context(gold,other,step,kind='price'):
    g=returns(gold,step);o=returns(other,step,kind)
    times=sorted(g.keys()&o.keys());result={'rolling':{},'aligned_samples':len(times),'lead_lag':None,'confidence':None,'predictive_validated':False}
    for window in (20,60,120):
        selected=times[-window:]
        result['rolling'][str(window)]={'value':pearson([(o[t],g[t]) for t in selected]) if len(selected)==window else None,'samples':len(selected),'required':window}
    candidates=[]
    for lag in range(-10,11):
        pairs=[(o[t-lag*step],g[t]) for t in sorted(g) if t-lag*step in o][-120:]
        value=pearson(pairs) if len(pairs)>=30 else None
        if value is not None:candidates.append({'lag_bars':lag,'correlation':value,'samples':len(pairs)})
    if candidates:result['lead_lag']=max(candidates,key=lambda v:abs(v['correlation']))
    return result
