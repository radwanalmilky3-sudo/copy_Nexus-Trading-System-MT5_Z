"""Snapshot-bound combined coverage, shared by reporting and dependency checks."""
import hashlib
import json
import math
from collections import defaultdict
from datetime import timedelta

from .session_calendar import calendar_dependency_hash,classify_interval
from .session_contracts import CalendarStatus

MT5_SOURCES=('mt5','mt5_poll','mt5_backfill','mt5_range')


def current_context(store,symbol,now):
    owner=getattr(store,'_session_calendar_store',None)
    return owner.context_now(symbol,now) if owner else None


def combined_rows(conn,symbol,timeframe):
    rows=conn.execute("SELECT timestamp,source,open,high,low,close,volume,COALESCE(revision,0),available_at,quality FROM ohlcv WHERE symbol=? AND timeframe=? AND source IN ('mt5','mt5_poll','mt5_backfill','mt5_range') ORDER BY timestamp,source,open,high,low,close,volume,COALESCE(revision,0),available_at,quality LIMIT 100001",(symbol,timeframe)).fetchall()
    if len(rows)>100000:
        raise ValueError('Combined coverage exceeds bounded audit limit')
    return rows


def series_hash(rows):
    return hashlib.sha256(json.dumps(rows,default=str,separators=(',',':')).encode()).hexdigest()


def calendar_summary(calendar):
    status=calendar.status if calendar else CalendarStatus(state='not_configured',reason='No session reader configured')
    return status.model_dump(mode='json')


def gap_summary(rows,combined,seconds,calendar,now):
    step=timedelta(seconds=seconds)
    groups=defaultdict(list)
    for row in combined:
        groups[row[0]].append(row)
    def valid(items):
        for r in items:
            o,h,low,c,v=r[2:7]
            if not(all(math.isfinite(x) and x>0 for x in (o,h,low,c)) and low<=min(o,c)<=max(o,c)<=h and math.isfinite(v) and v>=0):
                return False
        return len({tuple(r[2:7]) for r in items})==1
    covered={stamp for stamp,items in groups.items() if stamp+step<=now and valid(items)}
    result=dict(confirmed_closed=0,covered_elsewhere=0,expected_quote_missing=0,unknown=0,details=[],truncated=False)
    checked=0
    stamps=sorted(set(row[0] for row in rows))
    for a,b in zip(stamps,stamps[1:]):
        cursor=a+step
        while cursor<b:
            if checked>=10000:
                result['unknown']+=math.ceil((b-cursor).total_seconds()/seconds)
                result['truncated']=True
                break
            checked+=1
            if cursor in covered:
                result['covered_elsewhere']+=1
            else:
                classified=classify_interval(calendar,start=cursor,end=cursor+step)
                key={'confirmed_closed':'confirmed_closed','expected_quote':'expected_quote_missing','unknown':'unknown'}[classified.kind]
                result[key]+=1
                if len(result['details'])<12:
                    result['details'].append(dict(start=cursor.isoformat(),end=(cursor+step).isoformat(),kind=classified.kind,
                                                 reason=classified.reason,snapshot_id=classified.snapshot_id,exception_ids=list(classified.exception_ids)))
            cursor+=step
    return result
