"""
backfill_history.py - inject historical OHLCV into nexus-data's DuckDB.

Mechanism: while nexus-data holds the DuckDB write lock and is connected to
MT5, a range query on /api/data/ohlcv moves bars from MT5 into the store
(_persist_closed_ohlcv -> insert_ohlcv_batch). This script walks newest ->
oldest in windows small enough for a single call, then runs a second pass so
windows that came back sparse on the first try (MT5 lazy-syncs history: a
never-opened window returns a sliver until the terminal downloads it) are
re-fetched and completed.

Usage:
    .\\venv-nexus\\Scripts\\python.exe scripts\\backfill_history.py
    .\\venv-nexus\\Scripts\\python.exe scripts\\backfill_history.py --symbols XAUUSD --timeframes H1 --days 180
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:  # cp1256-safe output regardless of the calling console
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
DATA_URL = "http://127.0.0.1:9001/api/data/ohlcv"
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
    """Fetch one [start, end) window; every response is persisted server-side.

    Returns the number of bars contained in the response body.
    """
    q = urlencode({
        "start": start.isoformat(),
        "end": end.isoformat(),
        "limit": "5000",
    })
    url = f"{DATA_URL}/{symbol}/{tf}?{q}"
    req = Request(url, headers={"X-Nexus-Internal-Secret": secret})
    for attempt in range(2):  # 404 => window still empty (weekend or lazy-sync)
        try:
            with urlopen(req, timeout=FETCH_TIMEOUT_SEC) as resp:
                body = resp.read().decode("utf-8")
            return body.count('"timestamp"')
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:200]
            if exc.code == 404 and attempt == 0:
                continue
            print(f"  [window {start:%Y-%m-%d}] HTTP {exc.code}: {body}", flush=True)
            if exc.code == 404:
                return 0
            raise
        except URLError as exc:
            print(f"  [window {start:%Y-%m-%d}] network error: {exc}; retrying", flush=True)
            time.sleep(3.0)
    return 0


def store_count(symbol: str, tf: str, secret: str) -> int:
    _status, body = get_json(PROV_URL.format(symbol=symbol, tf=tf), secret)
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


def fill(symbol: str, tf: str, days: float, secret: str, passes: int = 2) -> None:
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
        if pas < passes and total:
            print(f"  sleeping 10s before pass {pas + 1} (MT5 history sync)", flush=True)
            time.sleep(10.0)


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
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    tfs = [t.strip().upper() for t in args.timeframes.split(",") if t.strip()]
    for sym in symbols:
        for tf in tfs:
            try:
                fill(sym, tf, args.days, secret)
            except Exception as exc:  # per-pair failures must not stop the sweep
                print(f"[{sym}/{tf}] FAILED: {type(exc).__name__}: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
