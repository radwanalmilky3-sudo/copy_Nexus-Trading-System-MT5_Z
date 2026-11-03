"""Pure evidence-backed quote-window classification. Unknown never means closed."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
from typing import Literal
from zoneinfo import ZoneInfo

from .session_contracts import CalendarContext


def calendar_dependency_hash(context: CalendarContext | None) -> str:
    data=None if context is None else dict(snapshot=context.status.content_hash,state=context.status.state,
        policy=context.policy.model_dump(mode='json'),capture=str(context.status.captured_at),expires=str(context.status.expires_at))
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()


@dataclass(frozen=True)
class IntervalClassification:
    kind: Literal['confirmed_closed','expected_quote','unknown']
    reason: str
    snapshot_id: str | None
    calendar_hash: str
    exception_ids: tuple[str,...] = ()


def _to_utc(local: datetime,zone) -> datetime:
    first=local.replace(tzinfo=zone,fold=0);second=local.replace(tzinfo=zone,fold=1)
    if first.utcoffset()!=second.utcoffset() or first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)!=local:
        raise ValueError('Ambiguous or nonexistent broker wall time')
    return first.astimezone(timezone.utc)


def candidate_gap_windows(start,end,step,calendar, *, max_bars=500,max_windows=4):
    """Inclusive broker fetch ranges, split around fully evidenced closures."""
    if step.total_seconds()<=0 or start>end:
        return []
    windows=[];cursor=start;checked=0;count=0
    while cursor<=end and checked<10000:
        checked+=1
        if classify_interval(calendar,start=cursor,end=cursor+step).kind!='confirmed_closed':
            if windows and cursor==windows[-1][1]+step and count<max_bars:
                windows[-1]=(windows[-1][0],cursor);count+=1
            elif len(windows)<max_windows:
                windows.append((cursor,cursor));count=1
            else:
                break
        else:
            count=max_bars
        cursor+=step
    return windows


def classify_interval(context: CalendarContext | None, *, start: datetime,end: datetime) -> IntervalClassification:
    digest=calendar_dependency_hash(context)
    def result(kind,reason,ids=()):
        return IntervalClassification(kind,reason,context.status.snapshot_id if context else None,digest,ids)
    if start.tzinfo is None or end.tzinfo is None or start>=end or end-start>timedelta(days=8):
        return result('unknown','Invalid or oversized interval')
    if context is None or len(context.policy.symbol_map)!=1:
        return result('unknown','No unambiguous symbol calendar')
    policy=context.policy;broker=next(iter(policy.symbol_map.values()))
    if context.status.state in ('identity_mismatch','conflict'):
        return result('unknown','Calendar identity/conflict invalid')
    exceptions=[e for e in policy.exceptions if e.server==policy.expected_server and broker in e.broker_symbols
                and e.effective_from<end and start<e.effective_to]
    if exceptions:
        if len(exceptions)!=1:
            return result('unknown','Overlapping exception evidence conflicts')
        exception=exceptions[0]
        if not(exception.effective_from<=start and end<=exception.effective_to) or exception.published_at>start:
            return result('unknown','Exception does not cover the complete interval or was not yet published')
        opened=any(w.start<end and start<w.end for w in exception.quote_windows_utc)
        return result('expected_quote' if opened else 'confirmed_closed','Broker-attested UTC exception',(exception.evidence_id,))
    if context.export is None or context.status.state!='ready':
        return result('unknown','No ready session snapshot')
    clock=policy.clock_evidence;capture=context.export.captured_at_utc;expires=context.status.expires_at
    if clock is None or not(capture<=start and end<=expires and clock.effective_from<=start and end<=clock.effective_to and clock.published_at<=start):
        return result('unknown','Snapshot/clock does not cover interval; no historical projection')
    try:
        zone=ZoneInfo(clock.timezone_name) if clock.timezone_name else timezone(timedelta(seconds=clock.utc_offset_seconds))
        symbol=next(s for s in context.export.symbols if s.broker_symbol==broker)
        days={d.day:d for d in symbol.days}
        local_start=start.astimezone(zone).replace(tzinfo=None,hour=0,minute=0,second=0,microsecond=0)-timedelta(days=1)
        local_end=end.astimezone(zone).replace(tzinfo=None,hour=0,minute=0,second=0,microsecond=0)
        cursor=local_start;windows=[]
        while cursor<=local_end:
            day=days[(cursor.weekday()+1)%7]
            if day.quote_status not in ('ok','no_sessions') or day.quote_error:
                return result('unknown','Quote-session enumeration incomplete')
            for window in day.quote_sessions:
                a=cursor+timedelta(seconds=window.start_seconds)
                b=cursor+timedelta(seconds=window.end_seconds)
                if b<a:
                    b+=timedelta(days=1)
                windows.append((_to_utc(a,zone),_to_utc(b,zone)))
            cursor+=timedelta(days=1)
        opened=any(a<end and start<b for a,b in windows)
        return result('expected_quote' if opened else 'confirmed_closed','Verified broker quote-session schedule')
    except (ValueError,KeyError,StopIteration):
        return result('unknown','Unresolvable calendar wall time or symbol')
