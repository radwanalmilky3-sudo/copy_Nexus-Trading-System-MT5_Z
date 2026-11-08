"""Capture MT5 symbol_info metadata snapshots for the correlated asset universe.

Calls GET /api/data/symbols/{symbol}/snapshot on the running nexus-data
service; each response is persisted as an append-only row in the
symbol_property_snapshots table (see NEXUS data dictionary,
broker.symbol_property_snapshots adapted to DuckDB).

Usage:
    python scripts/import_symbol_metadata.py                       # default universe
    python scripts/import_symbol_metadata.py --symbols XAUUSD,BTCUSD
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:  # cp1256-safe output regardless of the calling console
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent

# Correlated asset universe for XAUUSD-centric multi-asset training
# (approved scope): metals + crypto + USD majors + dollar index + indices + energy.
DEFAULT_SYMBOLS = [
    "XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD", "DXY",
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD",
    "US30", "US500", "WTI",
]

SUMMARY_FIELDS = [
    ("digits", "digits"),
    ("spread", "spread_pts"),
    ("trade_contract_size", "contract"),
    ("tick_value", "tick_value"),
    ("volume_min", "vol_min"),
    ("margin_initial", "margin_init"),
]


def load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def capture(symbol: str, secret: str, timeout: float = 30.0) -> dict:
    url = f"http://127.0.0.1:9001/api/data/symbols/{symbol}/snapshot"
    req = urllib.request.Request(url, headers={"X-Nexus-Internal-Secret": secret})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS),
                        help="comma-separated symbols (default: correlated universe)")
    args = parser.parse_args()

    load_env()
    secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "")
    if not secret:
        print("NEXUS_INTERNAL_API_SECRET missing from .env", file=sys.stderr)
        return 2

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    ok: list[dict] = []
    failed: list[tuple[str, str]] = []
    for symbol in symbols:
        try:
            body = capture(symbol, secret)
            snap = body.get("snapshot") or {}
            ok.append(snap)
            print(f"[OK] {symbol}: digits={snap.get('digits')} spread={snap.get('spread')} "
                  f"contract={snap.get('trade_contract_size')} tick_value={snap.get('tick_value')} "
                  f"margin_initial={snap.get('margin_initial')}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
            failed.append((symbol, f"HTTP {exc.code}: {detail}"))
            print(f"[FAIL] {symbol}: HTTP {exc.code} {detail}")
        except Exception as exc:
            failed.append((symbol, str(exc)))
            print(f"[FAIL] {symbol}: {exc}")

    print(f"\ncaptured={len(ok)} failed={len(failed)} total={len(symbols)}")
    if failed:
        print("failures:")
        for symbol, reason in failed:
            print(f"  - {symbol}: {reason}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
