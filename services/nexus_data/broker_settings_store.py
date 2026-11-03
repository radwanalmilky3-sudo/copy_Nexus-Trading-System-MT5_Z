"""Durable account-local drafts. No MT5 calls, credentials, or policy activation."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import duckdb

from shared.broker_settings_models import AccountCreate, AccountSettings, ProfileCreate


class BrokerNotFound(Exception):
    pass


class BrokerConflict(Exception):
    pass


class BrokerSettingsStore:
    def __init__(self, owner_store):
        self.owner_store = owner_store

    async def _run(self, operation):
        def execute():
            conn = self.owner_store._conn
            conn.execute((Path(__file__).parent/'migrations/broker_settings_001.sql').read_text(encoding='utf-8'))
            conn.execute('BEGIN TRANSACTION')
            try:
                result = operation(conn)
                conn.execute('COMMIT')
                return result
            except BaseException:
                conn.execute('ROLLBACK')
                raise
        return await self.owner_store._execute_locked(execute)

    @staticmethod
    def _event(conn, owner, profile, account, action, version, payload):
        conn.execute('INSERT INTO broker_account_events VALUES (?,?,?,?,?,?,?,?)',
                     (str(uuid4()),owner,profile,account,action,version,json.dumps(payload,ensure_ascii=False),datetime.now(timezone.utc).isoformat()))

    @staticmethod
    def _account(conn, owner, account_id):
        row=conn.execute('''SELECT a.account_id,a.profile_id,a.label,a.server,a.login,a.account_kind,
                           s.version,s.settings_json,s.updated_at FROM broker_accounts a
                           JOIN broker_account_settings s ON a.owner_user_id=s.owner_user_id AND a.account_id=s.account_id
                           WHERE a.owner_user_id=? AND a.account_id=?''',(owner,account_id)).fetchone()
        if row is None:
            raise BrokerNotFound()
        return dict(account_id=row[0],profile_id=row[1],label=row[2],server=row[3],
                    masked_login=('•'*4 + row[4][-4:] if len(row[4])>4 else '•'*4),account_kind=row[5],
                    version=row[6],settings=json.loads(row[7]),updated_at=row[8],
                    persistence='durable',runtime_effective=False,connection_state='unconnected')

    async def list_profiles(self, owner_id: str) -> list[dict]:
        def operation(conn):
            rows=conn.execute('SELECT profile_id,name,broker_name,created_at FROM broker_profiles WHERE owner_user_id=? ORDER BY created_at,profile_id',(owner_id,)).fetchall()
            result=[]
            for row in rows:
                ids=conn.execute('SELECT account_id FROM broker_accounts WHERE owner_user_id=? AND profile_id=? ORDER BY created_at,account_id',(owner_id,row[0])).fetchall()
                result.append(dict(profile_id=row[0],name=row[1],broker_name=row[2],created_at=row[3],accounts=[self._account(conn,owner_id,x[0]) for x in ids]))
            return result
        return await self._run(operation)

    async def create_profile(self, owner_id: str, payload: ProfileCreate) -> dict:
        def operation(conn):
            pid=str(uuid4()); now=datetime.now(timezone.utc).isoformat()
            conn.execute('INSERT INTO broker_profiles VALUES (?,?,?,?,?)',(owner_id,pid,payload.name,payload.broker_name,now))
            self._event(conn,owner_id,pid,None,'profile.created',1,payload.model_dump())
            return dict(profile_id=pid,name=payload.name,broker_name=payload.broker_name,created_at=now,accounts=[])
        return await self._run(operation)

    async def create_account(self, owner_id: str, payload: AccountCreate) -> dict:
        def operation(conn):
            if not conn.execute('SELECT 1 FROM broker_profiles WHERE owner_user_id=? AND profile_id=?',(owner_id,payload.profile_id)).fetchone():
                raise BrokerNotFound()
            aid=str(uuid4());now=datetime.now(timezone.utc).isoformat()
            try:
                conn.execute('INSERT INTO broker_accounts VALUES (?,?,?,?,?,?,?,?)',(owner_id,aid,payload.profile_id,payload.label,payload.server,payload.login,payload.account_kind,now))
            except duckdb.ConstraintException:
                raise BrokerConflict() from None
            conn.execute('INSERT INTO broker_account_settings VALUES (?,?,?,?,?)',(owner_id,aid,1,AccountSettings().model_dump_json(),now))
            self._event(conn,owner_id,payload.profile_id,aid,'account.created',1,{})
            return self._account(conn,owner_id,aid)
        return await self._run(operation)

    async def get_account(self, owner_id: str, account_id: str) -> dict:
        return await self._run(lambda conn:self._account(conn,owner_id,account_id))

    async def get_identity(self, owner_id: str, account_id: str) -> dict:
        def operation(conn):
            self._account(conn,owner_id,account_id)
            row=conn.execute('SELECT login,server FROM broker_accounts WHERE owner_user_id=? AND account_id=?',(owner_id,account_id)).fetchone()
            return {'login':row[0],'server':row[1]}
        return await self._run(operation)

    async def save_settings(self, owner_id: str, account_id: str, expected_version: int, payload: AccountSettings) -> dict:
        def operation(conn):
            current=self._account(conn,owner_id,account_id)
            if current['version']!=expected_version:
                raise BrokerConflict()
            version=expected_version+1
            conn.execute('UPDATE broker_account_settings SET version=?,settings_json=?,updated_at=? WHERE owner_user_id=? AND account_id=?',
                         (version,payload.model_dump_json(),datetime.now(timezone.utc).isoformat(),owner_id,account_id))
            self._event(conn,owner_id,current['profile_id'],account_id,'settings.saved',version,payload.model_dump(mode='json'))
            return self._account(conn,owner_id,account_id)
        return await self._run(operation)

    async def list_events(self, owner_id: str, account_id: str) -> list[dict]:
        def operation(conn):
            self._account(conn,owner_id,account_id)
            rows=conn.execute('SELECT event_id,action,version,payload_json,created_at FROM broker_account_events WHERE owner_user_id=? AND account_id=? ORDER BY version DESC,created_at DESC LIMIT 100',(owner_id,account_id)).fetchall()
            return [dict(event_id=r[0],action=r[1],version=r[2],payload=json.loads(r[3]),created_at=r[4]) for r in rows]
        return await self._run(operation)
