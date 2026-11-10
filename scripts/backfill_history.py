"""
backfill_history.py - inject historical OHLCV into nexus-data's DuckDB.

Mechanism (development plan Phase 0): while nexus-data holds the DuckDB
write lock and is connected to MT5, each window is POSTed to the explicit
write path /api/data/ingest/range (read-only GET no longer persists), which
journals the window in ingest_jobs and persists via the idempotent
revision-aware upsert. The script walks newest -> oldest in windows small
enough for a single call, then runs extra passes so windows that came back
sparse (MT5 lazy-syncs history: a never-opened window returns a sliver
until the terminal downloads it) are re-fetched and completed.

Usage:
    .\\venv-nexus\\Scripts\\python.exe scripts\\backfill_history.py
    .\\venv-nexus\\Scripts\\python.exe scripts\\backfill_history.py --symbols XAUUSD --timeframes H1 --days 180
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:  # cp1256-safe output regardless of the calling console
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
INGEST_URL = "http://127.0.0.1:9001/api/data/ingest/range"
TICKS_URL = "http://127.0.0.1:9001/api/data/ingest/ticks"
ASK_UNAVAILABLE_URL = "http://127.0.0.1:9001/api/data/ingest/ask-unavailable"
PROV_URL = "http://127.0.0.1:9001/api/data/ohlcv/{symbol}/{tf}/provenance"

TF_SEC = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}
# window length: expected bars stay under the 5000-bars response cap and each
# window completes within the server's own MT5 fetch budget (a never-synced
# chunk is downloaded by the terminal once; later windows are instant).
TF_WINDOW_DAYS = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 90, "H4": 300, "D1": 1200}
FETCH_TIMEOUT_SEC = 240.0


def load_env() -> None:  # values are ASCII; encoding never has to round-trip
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def get_json(url: str, secret: str, timeout: float = 60.0):
    req = Request(url, headers={"X-Nexus-Internal-Secret": secret})
    with urlopen(req, timeout=timeout) as resp:  # nosek身: internal HTTPS port
        return resp.status, resp.read().decode("utf-8")


def bar_window(symbol: str, tf: str, start: datetime, end: datetime, secret: str) -> int:
    """Persist one [start, end) window through the explicit write path.

    POST /api/data/ingest/range journals the window in ingest_jobs and
    persists it with the idempotent revision-aware upsert, so a retry after
    a timeout never duplicates rows. Returns the number of bars the
    provider returned for the window. Transient failures (DuckDB lock-busy
    5xx, client read timeouts while MT5 syncs a cold symbol, connection
    resets) retry with backoff and degrade to 0 bars rather than aborting
    the sweep — later passes revisit the window.
    """
    payload = json.dumps({
        "symbol": symbol,
        "timeframe": tf,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "limit": 5000,
    }).encode("utf-8")
    req = Request(
        INGEST_URL,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "X-Nexus-Internal-Secret": secret},
    )
    attempts = 0
    while attempts < 5:
        attempts += 1
        try:
            with urlopen(req, timeout=FETCH_TIMEOUT_SEC) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            return int(body.get("rows_returned", 0))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
            if exc.code in (404, 405) and "Not Found" in detail:
                # Route missing => nexus-data is running pre-Phase-0 code.
                # Fail loudly instead of silently importing zero bars.
                raise RuntimeError(
                    "POST /api/data/ingest/range not found — restart nexus-data "
                    "so the Phase 0 write path is active"
                )
            print(f"  [window {start:%Y-%m-%d}] HTTP {exc.code}: retrying", flush=True)
            if 500 <= exc.code < 600:
                time.sleep(8.0)  # lock-busy storm: back off, don't abort
                continue
            raise
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            print(f"  [window {start:%Y-%m-%d}] {type(exc).__name__}: retrying", flush=True)
            time.sleep(5.0)
    print(f"  [window {start:%Y-%m-%d}] giving up after {attempts} attempts", flush=True)
    return 0


def store_count(symbol: str, tf: str, secret: str) -> int:
    try:
        _status, body = get_json(PROV_URL.format(symbol=symbol, tf=tf), secret)
    except HTTPError as exc:
        if exc.code == 404:
            return 0  # provenance 404 == nothing persisted yet for this pair
        raise
    except Exception as exc:  # provenance must never abort a sweep
        return -1
    # provenance embeds counts directly; keiner extra requests per window
    for key in ('"bar_count":', '"row_count":', '"count":'):
        i = body.find(key)
        if i != -1:
            j = body.find(",", i)
            try:
                return int(body[i + len(key):j if j != -1 else None].strip("} "))
            except ValueError:
                continue
    return -1  # parser miss; provenance format != expected


def fill(symbol: str, tf: str, days: float, secret: str, passes: int = 2,
         sleep_sec: float = 10.0) -> None:
    step = timedelta(days=TF_WINDOW_DAYS.get(tf, 40))
    tf_sec = TF_SEC[tf]
    end = datetime.now(timezone.utc) - timedelta(seconds=tf_sec)  # drop forming bar
    start_all = end - timedelta(days=days)
    print(f"== {symbol} {tf}: {days:g}d -> {step.days}d windows, {passes} passes", flush=True)

    for pas in range(1, passes + 1):
        cursor = end
        fetched = total = 0
        windows = 0
        while cursor > start_all:
            win_start = max(cursor - step, start_all)
            n = bar_window(symbol, tf, win_start, cursor, secret)
            total += n
            fetched += n
            windows += 1
            cursor = win_start
        print(f"  pass {pas}: {windows} windows, {fetched} bars returned "
              f"(cumulative {total})", flush=True)
        print(f"  store_bars={store_count(symbol, tf, secret)}", flush=True)
        if pas < passes:
            # Always wait between passes — even a 0-bar pair needs the gap so
            # the terminal can finish its background history download.
            print(f"  sleeping {sleep_sec:g}s before pass {pas + 1} (MT5 history sync)", flush=True)
            time.sleep(sleep_sec)


def tick_window(symbol: str, tfs: list[str], start: datetime, end: datetime,
                secret: str) -> dict:
    """Persist raw ticks for one window via POST /api/data/ingest/ticks.

    Same retry discipline as bar_window (Phase 0): transient failures back
    off instead of aborting the sweep, a missing route fails loudly instead
    of silently importing nothing. Returns the JSON body — an empty window
    answers {"ticks_returned": 0, ...}.
    """
    payload = json.dumps({
        "symbol": symbol,
        "timeframes": tfs,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }).encode("utf-8")
    req = Request(
        TICKS_URL,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "X-Nexus-Internal-Secret": secret},
    )
    attempts = 0
    while attempts < 5:
        attempts += 1
        try:
            with urlopen(req, timeout=FETCH_TIMEOUT_SEC) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
            if exc.code in (404, 405) and "Not Found" in detail:
                raise RuntimeError(
                    "POST /api/data/ingest/ticks not found — restart nexus-data "
                    "so the Phase 2 tick write path is active"
                )
            print(f"  [ticks {start:%Y-%m-%d}] HTTP {exc.code}: retrying", flush=True)
            if 500 <= exc.code < 600:
                time.sleep(8.0)  # lock-busy storm: back off, don't abort
                continue
            raise
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            print(f"  [ticks {start:%Y-%m-%d}] {type(exc).__name__}: retrying", flush=True)
            time.sleep(5.0)
    print(f"  [ticks {start:%Y-%m-%d}] giving up after {attempts} attempts", flush=True)
    # A give-up is NOT an answer: callers must not read it as "0 ticks found"
    # (the ask_source='unavailable' mark below requires real empty responses).
    return {"ticks_returned": 0, "ticks_inserted": 0, "aggregates": {},
            "_failed": True}


def mark_ask_unavailable(symbol: str, secret: str) -> dict:
    """Mark a tick-less symbol's bars ask_source='unavailable' (Phase 2).

    Only called after a full-depth tick sweep returned zero ticks from every
    window (plan: symbols with no tick depth carry an explicit marker).
    """
    payload = json.dumps({"symbol": symbol}).encode("utf-8")
    req = Request(
        ASK_UNAVAILABLE_URL,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json",
                 "X-Nexus-Internal-Secret": secret},
    )
    attempts = 0
    while attempts < 5:
        attempts += 1
        try:
            with urlopen(req, timeout=FETCH_TIMEOUT_SEC) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
            if exc.code in (404, 405) and "Not Found" in detail:
                raise RuntimeError(
                    "POST /api/data/ingest/ask-unavailable not found — restart "
                    "nexus-data so the Phase 2 ask marker route is active"
                )
            print(f"  [ask-unavailable {symbol}] HTTP {exc.code}: retrying",
                  flush=True)
            if 500 <= exc.code < 600:
                time.sleep(8.0)
                continue
            raise
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            print(f"  [ask-unavailable {symbol}] {type(exc).__name__}: retrying",
                  flush=True)
            time.sleep(5.0)
    raise RuntimeError(f"ask-unavailable mark failed after {attempts} attempts")


def fill_ticks(symbol: str, tfs: list[str], days: float, secret: str,
               empty_stop: int = 5) -> None:
    """Sweep raw ticks newest -> oldest in day windows (Phase 2).

    Broker tick history is contiguous from the oldest available tick, so the
    sweep stops after `empty_stop` consecutive empty windows instead of
    spawning a worker per empty day for the rest of the range. One window
    fetches the ticks once and rebuilds ask/aggregates for every requested
    timeframe (idempotent — a re-run inserts 0 new ticks).

    When every probed window answers with ZERO ticks (at least 7 consecutive
    empty day-windows = a full week at the stream head, all responses
    successful), the broker provably serves no tick stream for the symbol:
    its ask-less bars are then marked ask_source='unavailable' (plan Phase 2)
    so the readiness check reports a documented source limitation instead of
    a coverage failure. Give-ups (HTTP failures) never count as empties.
    """
    end = datetime.now(timezone.utc)
    start_all = end - timedelta(days=days)
    print(f"== ticks {symbol} ({','.join(tfs)}): {days:g}d day-windows, "
          f"stop after {empty_stop} empty", flush=True)
    cursor = end
    empty = 0
    windows = 0
    got = 0
    failed = 0
    min_probe = 7  # a full week of empty, successful answers proves no stream
    while cursor > start_all and (
        empty < empty_stop
        or (got == 0 and failed == 0 and windows < min_probe)
    ):
        win_start = max(cursor - timedelta(days=1), start_all)
        body = tick_window(symbol, tfs, win_start, cursor, secret)
        n = int(body.get("ticks_returned", 0) or 0)
        ins = int(body.get("ticks_inserted", 0) or 0)
        windows += 1
        if body.get("_failed"):
            failed += 1
        got += n
        print(f"  {win_start:%Y-%m-%d}: {n} ticks ({ins} new)", flush=True)
        empty = 0 if n else empty + 1
        cursor = win_start
    stop = "empty-depth stop" if empty >= empty_stop else "range covered"
    print(f"  done ({stop}): {windows} windows, {got} ticks returned", flush=True)
    if got == 0 and failed == 0 and windows >= min_probe:
        body = mark_ask_unavailable(symbol, secret)
        print(f"  ask_source='unavailable': {body.get('marked', 0)} bars marked "
              f"(job {body.get('job_id')})", flush=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    load_env()
    secret = os.environ.get("NEXUS_INTERNAL_API_SECRET", "")
    if not secret:
        print("NEXUS_INTERNAL_API_SECRET missing from .env", flush=True)
        return 2

    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default="XAUUSD,XAUUSDs,XAUUSDr,BTCUSD,BTCSOL,BTCm,ETHUSD,SOLASH,GBPCAD,EURGBP")
    parser.add_argument("--timeframes", default="M1,M5,M15,M30,H1,H4,D1")
    parser.add_argument("--days", type=float, default=365.0)
    parser.add_argument("--passes", type=int, default=2,
                        help="fetch passes per symbol/timeframe (heals lazy-sync slivers)")
    parser.add_argument("--sleep", type=float, default=10.0,
                        help="seconds to wait between passes (MT5 background download)")
    parser.add_argument("--with-ticks", action="store_true",
                        help="after candle sweeps: ingest raw ticks per symbol "
                             "and rebuild ask/bar_tick_aggregates (Phase 2)")
    parser.add_argument("--tick-empty-stop", type=int, default=5,
                        help="stop a tick sweep after this many consecutive empty day-windows")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    tfs = [t.strip().upper() for t in args.timeframes.split(",") if t.strip()]
    for sym in symbols:
        for tf in tfs:
            try:
                fill(sym, tf, args.days, secret, passes=args.passes, sleep_sec=args.sleep)
            except Exception as exc:  # per-pair failures must not stop the sweep
                print(f"[{sym}/{tf}] FAILED: {type(exc).__name__}: {exc}", flush=True)
        if args.with_ticks:
            try:
                fill_ticks(sym, tfs, args.days, secret, empty_stop=args.tick_empty_stop)
            except Exception as exc:  # per-symbol failures must not stop the sweep
                print(f"[{sym} ticks] FAILED: {type(exc).__name__}: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
