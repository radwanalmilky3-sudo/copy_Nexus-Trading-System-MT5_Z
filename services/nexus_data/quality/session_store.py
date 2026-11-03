"""Bounded local-file ingestion; the market-data owner is the only DB writer."""
from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import datetime, timedelta
from pathlib import Path

from .session_contracts import (MAX_EXPORT_BYTES, CalendarContext, CalendarPolicy, CalendarStatus,
                                load_calendar_policy, parse_session_export)


def read_export(path: Path) -> bytes:
    with path.open('rb') as handle:
        before=os.fstat(handle.fileno())
        raw=handle.read(MAX_EXPORT_BYTES+1)
        after=os.fstat(handle.fileno())
    current=path.stat()
    if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino) or (after.st_size,after.st_mtime_ns,after.st_ino)!=(current.st_size,current.st_mtime_ns,current.st_ino):
        raise ValueError('Export changed during read')
    return raw


def evaluate_export(export,policy,now,content_hash):
    base=dict(snapshot_id='sessions:'+content_hash,content_hash=content_hash,captured_at=export.captured_at_utc,
              expires_at=export.captured_at_utc+timedelta(hours=24))
    def status(state,reason):
        return CalendarStatus(state=state,reason=reason,**base)
    if not policy.expected_server or not policy.symbol_map:
        return status('not_configured','Broker identity policy is not configured')
    if export.server != policy.expected_server or not set(policy.symbol_map.values()).issubset({s.broker_symbol for s in export.symbols}):
        return status('identity_mismatch','Export server/symbols do not match configured broker identity')
    if not export.connected:
        return status('unavailable','Terminal disconnected at capture')
    if now >= base['expires_at']:
        return status('stale','Session snapshot expired')
    clock=policy.clock_evidence
    if clock is None or not clock.effective_from <= now < clock.effective_to or clock.published_at > now:
        return status('clock_unverified','No effective broker clock evidence')
    if any(d.quote_status in ('error','truncated') for s in export.symbols if s.broker_symbol in policy.symbol_map.values() for d in s.days):
        return status('invalid','Quote-session collection incomplete; absence is not closure')
    if any(not any(d.quote_status=='ok' and d.quote_sessions for d in s.days)
           for s in export.symbols if s.broker_symbol in policy.symbol_map.values()):
        return status('invalid','Entire quote week empty; no positive session evidence')
    return status('ready','Fresh matched snapshot; interval coverage still requires classification')


class SessionEvidenceStore:
    def __init__(self,store,export_path: Path | None,policy: CalendarPolicy, *, policy_path: Path | None=None):
        self.store=store;self.export_path=export_path;self.policy=policy;self.policy_path=policy_path
        self.export=None
        self.status=CalendarStatus(state='not_configured',reason='Session reader is not configured')
        store._session_calendar_store=self

    async def refresh(self,now: datetime) -> CalendarStatus:
        self.export=None
        policy_loaded=self.policy_path is None
        try:
            if self.policy_path is not None:
                self.policy=await asyncio.to_thread(load_calendar_policy,self.policy_path)
                policy_loaded=True
            if self.export_path is None:
                self.status=CalendarStatus(state='not_configured',reason='No session export path configured')
                return self.status
            raw=await asyncio.to_thread(read_export,self.export_path)
            export=parse_session_export(raw,now=now)
            digest=hashlib.sha256(raw).hexdigest()
            status=evaluate_export(export,self.policy,now,digest)
            if status.state == 'identity_mismatch':
                self.status=status
                return status
            def persist():
                conn=self.store._conn
                conn.execute((Path(__file__).resolve().parents[1]/'migrations/market_sessions_001.sql').read_text(encoding='utf-8'))
                conn.execute('BEGIN TRANSACTION')
                try:
                    conn.execute('INSERT INTO market_session_snapshots VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(content_hash) DO NOTHING',
                                 (status.snapshot_id,digest,raw.decode('utf-8-sig'),export.server,export.captured_at_utc,now,status.expires_at,status.state,status.reason))
                    imported=conn.execute('SELECT imported_at FROM market_session_snapshots WHERE content_hash=?',(digest,)).fetchone()[0]
                    conn.execute('COMMIT')
                    return imported
                except BaseException:
                    conn.execute('ROLLBACK');raise
            imported=await self.store._execute_locked(persist)
            self.export=export
            self.status=status.model_copy(update={'imported_at':imported})
        except (OSError,ValueError,UnicodeError):
            if not policy_loaded:
                # A withdrawn/broken policy must not retain old closure authority.
                self.policy=CalendarPolicy()
            self.status=CalendarStatus(state='unavailable' if self.export_path is not None and not self.export_path.exists() else 'invalid',
                                       reason='Session export/policy unavailable or invalid; no closure inferred')
        return self.status

    async def context(self,symbol: str,now: datetime) -> CalendarContext:
        return self.context_now(symbol,now)

    def context_now(self,symbol: str,now: datetime) -> CalendarContext:
        policy=self.policy
        if symbol not in policy.symbol_map:
            status=self.status if not policy.symbol_map else self.status.model_copy(update={
                'state':'identity_mismatch','reason':'Logical symbol not mapped'})
            return CalendarContext(None,policy.model_copy(update={'symbol_map':{}}),status)
        if symbol in policy.symbol_map:
            policy=policy.model_copy(update={'symbol_map':{symbol:policy.symbol_map[symbol]}})
        if self.export is None:
            return CalendarContext(None,policy,self.status)
        export=self.export.model_copy(update={'symbols':tuple(s for s in self.export.symbols if s.broker_symbol in policy.symbol_map.values())})
        status=evaluate_export(export,policy,now,self.status.content_hash)
        status=status.model_copy(update={'imported_at':self.status.imported_at})
        if symbol not in self.policy.symbol_map:
            status=status.model_copy(update={'state':'identity_mismatch','reason':'Logical symbol not mapped'})
        return CalendarContext(export,policy,status)
