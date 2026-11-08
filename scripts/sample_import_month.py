"""
sample_import_month.py - one-month OHLCV sample from MT5 into DuckDB.

Must run when nexus-data is STOPPED (the service owns the exclusive DuckDB
write lock). Pulls history through the project MT5 worker's `research_history`
op (10-day chunking + sync retries, forced login guard from .env
MT5_LOGIN/MT5_SERVER), then inserts via the store's own `insert_ohlcv_batch`.

Usage:
    .\\venv-nexus\\Scripts\\python.exe scripts\\sample_import_month.py [--symbol XAUUSD] [--days 30]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TF_SEC = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}
DATA_URL = "http://127.0.0.1:9001"


def load_env() -> None:
    for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def service_running(port: int) -> bool:
    s = socket.socket()
    s.settimeout(2.0)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


async def fetch_bares(symbol: str, tf: str, start: datetime, end: datetime, path: str) -> list[dict]:
    """One timeframe via the project's isolated worker (login-guarded)."""
    from services.nexus_data.mt5_connector import _mt5_worker

    payload = {
        "op": "research_history",
        "use_terminal": True,
        "symbol": symbol,
        "timeframe": tf,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "path": path,
        "expected_login": os.environ["MT5_LOGIN"],
        "expected_server": os.environ["MT5_SERVER"],
    }
    data = await _mt5_worker(payload, timeout_sec=600.0)
    return data.get("bars", [])


async def run(symbol: str, days: int, path: str) -> int:
    from shared.models import OHLCV
    from services.nexus_data.duckdb_store import DataStore

    tf_list = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]
    now = datetime.now(timezone.utc)
    start_all = now - timedelta(days=days)

    store = DataStore(str(ROOT / "data" / "nexus.duckdb"))
    await store.init_tables()
    total = 0
    try:
        for tf in tf_list:
            end = now - timedelta(seconds=TF_SEC[tf])  # drop the forming bar
            bars_raw = await fetch_bares(symbol, tf, start_all, end, path)
            dropped = [b for b in bars_raw
                       if datetime.fromtimestamp(int(b["time"]), tz=timezone.utc) < end]
            into = [
                OHLCV(symbol=symbol, timeframe=tf,
                      open=float(b["open"]), high=float(b["high"]),
                      low=float(b["low"]), close=float(b["close"]),
                      volume=float(b["volume"]),
                      timestamp=datetime.fromtimestamp(int(b["time"]), tz=timezone.utc))
                for b in dropped
            ]
            inserted = await store.insert_ohlcv_batch(into, source="mt5_sample")
            total += inserted
            first = into[0].timestamp.date() if into else None
            last = into[-1].timestamp.date() if into else None
            print(f"[{symbol}/{tf}] fetched={len(bars_raw)} persisted={inserted} "
                  f"range={first}..{last}", flush=True)
    finally:
        await store.aclose()
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()
    load_env()
    path = os.environ["MT5_PATH"]

    if service_running(9001):
        print("nexus-data is RUNNING — stop it first (it owns the DuckDB lock).", flush=True)
        return 2
    if "terminal64.exe" not in path:
        print(f"MT5_PATH does not point to terminal64.exe: {path!r}", flush=True)
        return 2
    total = asyncio.run(run(args.symbol, args.days, path))
    print(f"DONE: {total} bars persisted (sample {args.days}d of {args.symbol})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
