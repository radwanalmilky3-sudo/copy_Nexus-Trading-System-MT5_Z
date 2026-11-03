"""Bounded MT5 remediation. Archive before removing; never invent OHLCV values."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .stored_audit import INTERVALS, MAX_ROWS

MT5_SOURCES = {'mt5', 'mt5_poll', 'mt5_backfill', 'mt5_range'}
ATTEMPTS_SCHEMA = '''CREATE TABLE IF NOT EXISTS quality_repair_attempts (
 attempt_id VARCHAR PRIMARY KEY, symbol VARCHAR, timeframe VARCHAR,
 request_key VARCHAR, status VARCHAR, attempt_number INTEGER,
 started_at TIMESTAMPTZ, retry_after TIMESTAMPTZ, details_json VARCHAR)'''
FIELDS = ('rowid', 'symbol', 'timeframe', 'open', 'high', 'low', 'close',
          'volume', 'timestamp', 'source', 'quality', 'fetched_at', 'available_at', 'revision')


def _digest(rows):
    return hashlib.sha256(json.dumps(rows, default=str, separators=(',', ':')).encode()).hexdigest()


def _valid(values):
    o, h, low, c, v = values
    return (all(isinstance(x, (int, float)) and math.isfinite(x) and x > 0 for x in (o, h, low, c))
            and low <= min(o, c) <= max(o, c) <= h
            and isinstance(v, (int, float)) and math.isfinite(v) and v >= 0)


async def repair_pair(store, provider, symbol, timeframe, *, now=None, invalidate=None, calendar=None):
    now = now or datetime.now(timezone.utc)
    if timeframe not in INTERVALS or now.tzinfo is None:
        raise ValueError('Unsupported timeframe or naive repair time')
    step = timedelta(seconds=INTERVALS[timeframe])
    floor = now - timedelta(days=365)
    sql = 'SELECT ' + ','.join(FIELDS) + ' FROM ohlcv WHERE symbol=? AND timeframe=? ORDER BY rowid'

    def prepare():
        conn = store._conn
        conn.execute((Path(__file__).resolve().parents[1] / 'migrations/research_lineage_001.sql').read_text(encoding='utf-8'))
        conn.execute(ATTEMPTS_SCHEMA)
        count = conn.execute('SELECT COUNT(*) FROM ohlcv WHERE symbol=? AND timeframe=?', (symbol, timeframe)).fetchone()[0]
        if count > MAX_ROWS:
            raise ValueError('Repair selection exceeds bounded row limit')
        rows = conn.execute(sql, (symbol, timeframe)).fetchall()
        pending = conn.execute("SELECT quarantine_id,payload_json FROM quarantine WHERE resolution_status='open' AND reason_code LIKE 'auto_%' AND json_extract_string(payload_json,'$.symbol')=? AND json_extract_string(payload_json,'$.timeframe')=? LIMIT 100000", (symbol,timeframe)).fetchall()
        attempts = conn.execute('SELECT request_key,attempt_number,retry_after FROM quality_repair_attempts WHERE symbol=? AND timeframe=? ORDER BY started_at,attempt_number', (symbol, timeframe)).fetchall()
        return rows, pending, {r[0]: r[1:] for r in attempts}

    rows, pending, attempts = await store._execute_locked(prepare)
    grouped = defaultdict(list)
    removed = {}  # rowid -> reason
    wanted = {}  # timestamp -> (source, previous revision)
    resolve = defaultdict(list)
    resolve_existing = []
    for row in rows:
        if row[9] not in MT5_SOURCES:
            continue
        grouped[row[8]].append(row)
    for stamp, items in grouped.items():
        valid = [r for r in items if _valid(r[3:8]) and stamp + step <= now]
        for row in items:
            if row not in valid:
                removed[row[0]] = 'auto_invalid' if not _valid(row[3:8]) else 'auto_forming'
        signatures = {tuple(r[3:8]) for r in valid}
        if len(signatures) > 1:
            # Conflicting prices are not resolved by arbitrarily selecting a row.
            for row in valid:
                removed[row[0]] = 'auto_conflict'
            valid = []
        elif len(valid) > 1:
            for row in valid[1:]:
                removed[row[0]] = 'auto_duplicate'
        if not valid and stamp + step <= now:
            eligible = [r for r in items if r[9] in MT5_SOURCES]
            if eligible:
                wanted[stamp] = (eligible[0][9], max((r[13] or 0) for r in eligible) + 1)
    for qid, payload in pending:
        item = json.loads(payload)
        if (item.get('symbol'), item.get('timeframe')) != (symbol, timeframe):
            continue
        stamp = datetime.fromisoformat(item['timestamp'])
        if item['source'] not in MT5_SOURCES or stamp + step > now:
            continue
        confirmed = [r for r in grouped.get(stamp, []) if r[0] not in removed and _valid(r[3:8])]
        if confirmed:
            resolve_existing.append(qid)
        else:
            wanted[stamp] = (item['source'], (item.get('revision') or 0) + 1)
            resolve[stamp].append(qid)
    # Detect gaps on the combined MT5 series, not separately per ingestion path.
    stamps = sorted({r[8] for r in rows if r[9] in MT5_SOURCES and floor <= r[8] and r[8] + step <= now})
    gap_added = 0
    for a, b in zip(stamps, stamps[1:]):
        stamp = a + step
        while stamp < b and gap_added < 2000:
            end = min(b-step, stamp+step*499)
            previous = attempts.get(_digest([symbol,timeframe,stamp,end]))
            if not previous or previous[1] <= now:
                cursor = stamp
                while cursor <= end and gap_added < 2000:
                    if cursor not in grouped:
                        from .session_calendar import classify_interval
                        if classify_interval(calendar,start=cursor,end=cursor+step).kind != 'confirmed_closed':
                            wanted.setdefault(cursor, ('mt5_backfill', 0))
                            gap_added += 1
                    cursor += step
            stamp = end + step
    targets = sorted(t for t in wanted if t + step <= now)
    windows = []
    for stamp in targets:
        if windows and stamp == windows[-1][-1] + step and len(windows[-1]) < 500:
            windows[-1].append(stamp)
        else:
            windows.append([stamp])
    replacements, records = {}, []
    if provider is not None and provider.connected:
        for window in windows:
            key = _digest([symbol, timeframe, window[0], window[-1]])
            previous = attempts.get(key)
            if previous and previous[1] > now:
                continue
            if len(records) >= 4:
                break
            number = (previous[0] if previous else 0) + 1
            status, detail = 'empty', ''
            try:
                bars = await asyncio.wait_for(provider.get_ohlcv_range(symbol, timeframe, window[0], window[-1], limit=500), 35)
                requested = set(window)
                candidates = defaultdict(list)
                for bar in bars:
                    if (bar.symbol == symbol and bar.timeframe == timeframe and bar.timestamp in requested
                            and bar.timestamp + step <= now and _valid((bar.open, bar.high, bar.low, bar.close, bar.volume))):
                        candidates[bar.timestamp].append(bar)
                for stamp, items in candidates.items():
                    if len({(b.open,b.high,b.low,b.close,b.volume) for b in items}) == 1:
                        replacements[stamp] = items[0]
                found = sum(t in replacements for t in window)
                status = 'fetched' if found == len(window) else 'partial' if found else 'empty'
                detail = f'{found}/{len(window)} requested timestamps validated'
            except Exception as exc:
                status = 'error'
                detail = type(exc).__name__  # never persist provider credentials/errors verbatim
            delay = 21600 if status in {'empty', 'partial', 'fetched'} else min(21600, 60 * 2 ** min(number, 8))
            records.append((uuid.uuid4().hex, symbol, timeframe, key, status, number, now,
                            now + timedelta(seconds=delay), json.dumps(dict(detail=detail, start=str(window[0]), end=str(window[-1])))))

    def apply():
        conn = store._conn
        if _digest(conn.execute(sql, (symbol, timeframe)).fetchall()) != _digest(rows):
            for record in records:
                conn.execute('INSERT INTO quality_repair_attempts VALUES (?,?,?,?,?,?,?,?,?)', record)
            return dict(quarantined=0, replaced=0, inserted=0, deferred=True)
        conn.execute('BEGIN TRANSACTION')
        applied_at = max(now, datetime.now(timezone.utc))
        result = dict(quarantined=0, replaced=0, inserted=0, deferred=False)
        try:
            for row in rows:
                if row[0] not in removed:
                    continue
                item = {key: str(value) if isinstance(value,float) and not math.isfinite(value) else value
                        for key,value in zip(FIELDS,row)}
                dataset = f'ohlcv:{symbol}:{timeframe}:{row[9]}'
                conn.execute('INSERT INTO datasets(dataset_id,dataset_name,source_system,grain) VALUES (?,?,?,?) ON CONFLICT DO NOTHING', (dataset,dataset,row[9],timeframe))
                qid = 'auto:' + uuid.uuid4().hex
                resolved = removed[row[0]] == 'auto_duplicate'
                conn.execute('INSERT INTO quarantine(quarantine_id,dataset_id,record_key,reason_code,reason_detail,payload_json,resolution_status,resolved_by,resolved_at) VALUES (?,?,?,?,?,?,?,?,?)',
                             (qid,dataset,str(row[8]),removed[row[0]],'Original retained before automatic cleaning; MT5-only replacements',json.dumps(item,default=str,ensure_ascii=False,allow_nan=False),
                              'resolved' if resolved else 'open','nexus-data:auto-repair' if resolved else None,applied_at if resolved else None))
                if not resolved:
                    resolve[row[8]].append(qid)
                conn.execute('DELETE FROM ohlcv WHERE rowid=?', (row[0],))
                result['quarantined'] += 1
            for stamp, bar in replacements.items():
                # Never overwrite another provider or a concurrently preserved valid row.
                if conn.execute('SELECT 1 FROM ohlcv WHERE symbol=? AND timeframe=? AND timestamp=?', (symbol,timeframe,stamp)).fetchone():
                    continue
                source, revision = wanted[stamp]
                conn.execute('INSERT INTO ohlcv(symbol,timeframe,open,high,low,close,volume,timestamp,source,quality,fetched_at,available_at,revision) VALUES (?,?,?,?,?,?,?,?,?,?,?, ?,?)',
                             (symbol,timeframe,bar.open,bar.high,bar.low,bar.close,bar.volume,stamp,source,'ok',applied_at,applied_at,revision))
                result['replaced' if revision else 'inserted'] += 1
                for qid in resolve[stamp]:
                    conn.execute("UPDATE quarantine SET resolution_status='resolved',resolved_by='nexus-data:auto-repair',resolved_at=? WHERE quarantine_id=?", (applied_at,qid))
            for qid in resolve_existing:
                conn.execute("UPDATE quarantine SET resolution_status='resolved',resolved_by='nexus-data:mt5-ingestion-confirmed',resolved_at=? WHERE quarantine_id=?", (applied_at,qid))
            for record in records:
                conn.execute('INSERT INTO quality_repair_attempts VALUES (?,?,?,?,?,?,?,?,?)', record)
            if result['quarantined'] or result['replaced'] or result['inserted']:
                store._refresh_ohlcv_manifest(symbol,timeframe)
            conn.execute('COMMIT')
        except BaseException:
            conn.execute('ROLLBACK')
            raise
        return result

    from .operational import pair_lock
    async with pair_lock(store,symbol,timeframe):
        if invalidate is not None and (removed or replacements or resolve_existing):
            await invalidate(symbol,timeframe)
        return await store._execute_locked(apply)
