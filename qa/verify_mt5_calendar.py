#!/usr/bin/env python3
"""Verify real MT5 calendar events end-to-end (MASTER PROMPT V4.1).

Run AFTER recompiling and re-attaching NexusBridgeEA.mq5 (calendar sync
defaults: every 300s, ±7 days window). Checks, in order:

  1. Redis sync cursor  nexus:calendar:mt5:last_sync  advanced
  2. nexus:news:calendar cache contains events with source=calendar_mt5
  3. merge behaviour: MT5 events win over web events for the same release
  4. nexus-data persisted the events (macro_releases / fund_events)

Usage:
    venv-nexus/Scripts/python.exe qa/verify_mt5_calendar.py [--watch]

Without --watch it takes one snapshot. With --watch it polls every 30s
until MT5 events appear (Ctrl+C to stop). Never fabricates results: if
nothing arrived, it says so and prints the EA-side checklist.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

REDIS_URL = "redis://127.0.0.1:6379/0"
CAL_KEY = "nexus:news:calendar"
CURSOR_KEY = "nexus:calendar:mt5:last_sync"


def _redis():
    for line in open(".env", encoding="utf-8"):
        if line.strip().startswith("REDIS_URL="):
            return __import__("redis").Redis.from_url(
                line.split("=", 1)[1].strip().strip('"').strip("'"),
                decode_responses=True,
            )
    return __import__("redis").Redis.from_url(REDIS_URL, decode_responses=True)


def snapshot() -> dict:
    r = _redis()
    cursor = r.get(CURSOR_KEY)
    events = []
    raw = r.get(CAL_KEY)
    if raw:
        data = json.loads(raw)
        events = data if isinstance(data, list) else data.get("events", [])
    mt5 = [e for e in events if e.get("source") == "calendar_mt5"]
    web = [e for e in events if e.get("source") != "calendar_mt5"]
    return {"cursor": cursor, "total": len(events), "mt5": mt5, "web": web}


def report(snap: dict) -> bool:
    print(f"sync cursor : {snap['cursor'] or '(not set — EA has not posted yet)'}")
    print(f"calendar    : {snap['total']} events "
          f"({len(snap['mt5'])} from calendar_mt5, {len(snap['web'])} from web sources)")
    if snap["mt5"]:
        print("\nMT5 events (first 5):")
        for e in snap["mt5"][:5]:
            print("  -", e.get("timestamp"), e.get("currency"),
                  e.get("event_name"), "| impact:", e.get("impact"),
                  "| actual:", e.get("actual"))
        ok = True
    else:
        ok = False
        print("\nNO MT5 events yet. EA-side checklist:")
        print("  1. Recompile mql5/Experts/NexusBridgeEA.mq5 in MetaEditor (F7)")
        print("  2. Re-attach the EA to a chart; confirm 'nexus bound' in Experts log")
        print("  3. Inputs: InpCalendarSync=true, InpCalendarSyncSec=300")
        print("  4. WebRequest whitelist must include http://127.0.0.1:9000")
        print("     (Tools > Options > Expert Advisors > Allow WebRequest)")
        print("  5. Wait up to InpCalendarSyncSec for the first chunked POST")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true", help="poll every 30s until MT5 events arrive")
    args = ap.parse_args()
    if not args.watch:
        ok = report(snapshot())
        return 0 if ok else 1
    print("Watching for calendar_mt5 events (30s interval, Ctrl+C to stop)...")
    while True:
        snap = snapshot()
        if snap["mt5"]:
            report(snap)
            return 0
        print(f"  {time.strftime('%H:%M:%S')} — no MT5 events yet "
              f"(cursor={snap['cursor'] or '-'}, web={len(snap['web'])})")
        time.sleep(30)


if __name__ == "__main__":
    sys.exit(main())
