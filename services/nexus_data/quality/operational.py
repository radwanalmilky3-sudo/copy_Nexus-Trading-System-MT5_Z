"""Safety projection shared by persisted and live candle consumers."""
from datetime import datetime, timedelta, timezone

from .repair import _valid
from .stored_audit import INTERVALS


def usable_bars(bars, now=None):
    now = now or datetime.now(timezone.utc)
    grouped = {}
    conflicts = set()
    for bar in bars:
        seconds = INTERVALS.get(bar.timeframe)
        if (not seconds or bar.timestamp + timedelta(seconds=seconds) > now
                or not _valid((bar.open,bar.high,bar.low,bar.close,bar.volume))):
            continue
        key = (bar.symbol,bar.timeframe,bar.timestamp)
        old = grouped.get(key)
        if old and (old.open,old.high,old.low,old.close,old.volume) != (bar.open,bar.high,bar.low,bar.close,bar.volume):
            conflicts.add(key)
        grouped[key] = bar
    return sorted((bar for key,bar in grouped.items() if key not in conflicts), key=lambda b:b.timestamp)


def blocked_on_connection(conn, symbol, timeframe):
    if not conn.execute("SELECT 1 FROM information_schema.tables WHERE table_name='quarantine' AND table_schema='main'").fetchone():
        return False
    return bool(conn.execute("SELECT 1 FROM quarantine WHERE resolution_status='open' AND reason_code LIKE 'auto_%' AND json_extract_string(payload_json,'$.symbol')=? AND json_extract_string(payload_json,'$.timeframe')=? LIMIT 1", (symbol,timeframe)).fetchone())


def pair_lock(store, symbol, timeframe):
    import asyncio
    return store._quality_pair_locks.setdefault((symbol,timeframe),asyncio.Lock())


async def pair_blocked(store, symbol, timeframe):
    return await store._execute_locked(lambda: blocked_on_connection(store._conn,symbol,timeframe))
