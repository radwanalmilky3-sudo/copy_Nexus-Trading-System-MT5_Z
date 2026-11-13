"""Build next-bar-labelled training history from DuckDB OHLCV bars.

The bridge the system was missing: the 6.2 GB DuckDB holds months of real
M15 bars, but the DL/RL trainers only read `nexus:features:history:v2:*`
— a Redis list that grows one sample per live bar (161 samples after days
of running). This script replays the SAME feature engine the live pipeline
uses (services.nexus_features indicators + session tags, 300-bar window)
over the stored history, labels every bar with the next close direction,
and merges the result into the Redis history list.

Sample contract (must match services/nexus_ml/main.py::_handle_feature_event):
    {"timestamp": iso, "timeframe": tf, "features": {numeric only},
     "ohlcv": {open, high, low, close, volume}, "label": 0|1}

Usage:
    python scripts/build_training_history.py --symbol XAUUSD --timeframe M15
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from services.nexus_features.indicators import calculate_all
from services.nexus_features.ohlcv import chronological_bars
from services.nexus_features.session_tagger import tag_dataframe
from shared.redis_client import RedisClient

WINDOW = 300  # matches nexus_features._fetch_ohlcv_from_api default
HISTORY_PREFIX = "nexus:features:history:v2:"
SKIP_COLS = {"open", "high", "low", "close", "volume", "timestamp", "symbol", "timeframe"}


def load_env() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def fetch_bars(symbol: str, timeframe: str) -> list[dict]:
    """Read every stored bar through the data service (the DB is write-locked)."""
    import urllib.request
    from urllib.parse import quote

    secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
    if not secret:
        raise SystemExit("NEXUS_INTERNAL_API_SECRET missing — check .env")
    base = os.getenv("NEXUS_DATA_URL", "http://127.0.0.1:9001").rstrip("/")
    bars: list[dict] = []
    end: str | None = None
    while True:
        url = f"{base}/api/data/ohlcv/{symbol}/{timeframe}?limit=5000"
        if end:
            url += f"&end={quote(end, safe='')}"  # '+03:00' would decode as a space
        req = urllib.request.Request(url, headers={"X-Nexus-Internal-Secret": secret})
        with urllib.request.urlopen(req, timeout=60) as resp:
            page = json.loads(resp.read())
        if not page:
            break
        bars.extend(page)
        oldest = min(str(b.get("timestamp", "")) for b in page)
        if len(page) < 5000 or oldest in {str(b.get("timestamp", "")) for b in bars[:-len(page)]}:
            break
        end = oldest
    # Dedup + chronological order
    seen: dict[str, dict] = {}
    for b in bars:
        seen[str(b.get("timestamp"))] = b
    out = sorted(seen.values(), key=lambda b: str(b.get("timestamp")))
    return out


def features_for_window(window: list[dict]) -> dict[str, float] | None:
    """Run the live feature engine over one bar window; return numeric dict."""
    df = pd.DataFrame(chronological_bars(window))
    if df.empty or not {"open", "high", "low", "close"}.issubset(df.columns):
        return None
    df = tag_dataframe(calculate_all(df))
    last = df.iloc[-1]
    feats: dict[str, float] = {}
    for col in df.columns:
        if col in SKIP_COLS:
            continue
        val = last[col]
        if isinstance(val, (int, float, np.integer, np.floating)) and np.isfinite(float(val)):
            feats[col] = float(val)
    return feats or None


def build_samples(bars: list[dict], timeframe: str) -> list[dict]:
    samples: list[dict] = []
    skipped_nan = 0
    for i in range(WINDOW - 1, len(bars) - 1):
        cur, nxt = bars[i], bars[i + 1]
        feats = features_for_window(bars[i - WINDOW + 1 : i + 1])
        if feats is None:
            skipped_nan += 1
            continue
        try:
            ts = str(cur.get("timestamp"))
            ts_iso = (
                datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
                if "T" in ts
                else datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc).isoformat()
            )
        except (ValueError, TypeError):
            continue
        close = float(cur.get("close", 0) or 0)
        next_close = float(nxt.get("close", 0) or 0)
        if close <= 0 or next_close <= 0:
            continue
        samples.append({
            "timestamp": ts_iso,
            "timeframe": timeframe,
            "features": feats,
            "ohlcv": {
                "open": float(cur.get("open", 0) or 0),
                "high": float(cur.get("high", 0) or 0),
                "low": float(cur.get("low", 0) or 0),
                "close": close,
                "volume": float(cur.get("volume", 0) or 0),
            },
            "label": int(next_close > close),
        })
    if skipped_nan:
        print(f"  skipped {skipped_nan} windows with no finite features")
    return samples


async def merge_into_redis(symbol: str, timeframe: str, samples: list[dict]) -> tuple[int, int]:
    """Merge generated samples with the live-collected list (dedup by timestamp)."""
    r = RedisClient()
    await r.connect()
    key = f"{HISTORY_PREFIX}{symbol.upper()}:{timeframe.upper()}"
    existing_raw = await r.r.lrange(key, 0, -1)
    merged: dict[str, str] = {}
    for raw in existing_raw:
        try:
            rec = json.loads(raw)
            merged[str(rec.get("timestamp"))] = raw
        except json.JSONDecodeError:
            continue
    live_count = len(merged)
    for rec in samples:
        merged[str(rec["timestamp"])] = json.dumps(rec, separators=(",", ":"))
    ordered = sorted(merged.items(), key=lambda kv: kv[0])
    await r.r.delete(key)
    batch: list[str] = []
    for _, raw in ordered:
        batch.append(raw)
        if len(batch) >= 500:
            await r.r.rpush(key, *batch)
            batch = []
    if batch:
        await r.r.rpush(key, *batch)
    return live_count, len(ordered)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M15")
    args = parser.parse_args()

    load_env()
    print(f"Fetching stored {args.timeframe} bars for {args.symbol} ...")
    bars = fetch_bars(args.symbol, args.timeframe)
    if bars:
        print(f"  {len(bars):,} bars "
              f"({bars[0]['timestamp']} -> {bars[-1]['timestamp']})")
    else:
        print("  NO BARS")
    if len(bars) < WINDOW + 10:
        print("Not enough bars for a 300-bar feature window — nothing to do")
        return 1

    print("Computing features per bar (same engine as live) ...")
    samples = build_samples(bars, args.timeframe)
    if not samples:
        print("No samples generated")
        return 1
    labels = [s["label"] for s in samples]
    up = sum(labels)
    print(f"  {len(samples):,} samples | label=1 (up): {up:,} ({up/len(labels):.1%}) "
          f"| features/sample: {len(samples[0]['features'])}")

    live, total = await merge_into_redis(args.symbol, args.timeframe, samples)
    print(f"Redis history: kept {live} live samples, merged total now {total:,} "
          f"-> nexus:features:history:v2:{args.symbol.upper()}:{args.timeframe.upper()}")
    print("Done — the trainers can now see the full labelled history.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
