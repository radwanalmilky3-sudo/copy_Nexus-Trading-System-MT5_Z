"""
bootstrap_ensemble.py — seed the ML ensemble with enough training data to generate
real ML signals instead of falling back to rule-based.

Workflow:
  1. Check nexus:features:history:XAUUSD in Redis for existing feature records.
  2. If >= MIN_SAMPLES records exist: trigger training via POST /api/ml/train.
  3. If not enough: fetch H1 historical candles from nexus-data, compute OHLCV-derived
     features, push them into nexus:features:history:XAUUSD, then trigger training.

Usage:
    python bootstrap_ensemble.py [--symbol XAUUSD] [--min-samples 500] [--dry-run]

Requires the full stack to be running (nexus-data + nexus-api + Redis).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

import httpx
import pandas as pd
import redis.asyncio as aioredis

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from services.nexus_features.indicators import calculate_all  # noqa: E402
from services.nexus_ml.labeling import label_next_bar_direction  # noqa: E402

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
API_URL = os.getenv("NEXUS_API_URL", "http://localhost:9000")
ML_URL = os.getenv("NEXUS_ML_URL", "http://localhost:9003")
DATA_URL = os.getenv("NEXUS_DATA_URL", "http://localhost:9001")

_HISTORY_KEY_TPL = "nexus:features:history:{symbol}"
_MIN_SAMPLES_DEFAULT = 500
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_env() -> None:
    """Load .env (NEXUS_INTERNAL_API_SECRET etc.) — run.py does this for the
    fleet, but this script is usually invoked from a bare console."""
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _internal_headers() -> dict[str, str]:
    """nexus-ml mutating endpoints require the service-to-service secret."""
    secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
    return {"X-Nexus-Internal-Secret": secret} if secret else {}


# ── Feature computation from OHLCV ───────────────────────────────────────────
# Uses the SAME indicator engine nexus-features runs live (calculate_all), so
# backfilled training data and live inference features share one schema.
# Hand-rolling a parallel indicator set here previously trained a model on
# columns live inference could never reproduce (predict() 500'd on every call).

_NON_FEATURE_COLS = {"open", "high", "low", "close", "volume", "timestamp", "symbol", "timeframe"}


def compute_features(candles: list[dict]) -> list[dict]:
    """Return list of {features: {...}, label: int, timestamp: str} records."""
    if len(candles) < 210:
        return []

    df = pd.DataFrame(candles)
    df = calculate_all(df)
    df = df.reset_index(drop=True)

    numeric_cols = set(df.select_dtypes(include="number").columns)
    feature_cols = [c for c in df.columns if c not in _NON_FEATURE_COLS and c in numeric_cols]

    # Shared helper: rows lacking a valid next close are excluded so the final
    # bar never becomes a fabricated DOWN label.
    labeled = label_next_bar_direction(df, close_column="close", target_column="target")
    valid_rows = set(labeled.index)

    records = []
    for i in range(210, len(df)):
        if i not in valid_rows:
            continue
        label = int(labeled.at[i, "target"])
        row = df.iloc[i]
        features = {col: float(row[col]) for col in feature_cols if pd.notna(row[col])}

        records.append({
            "features": features,
            "label": label,
            "ohlcv": {
                "open": float(row["open"]), "high": float(row["high"]),
                "low": float(row["low"]), "close": float(row["close"]),
                "volume": float(row.get("volume", 0) or 0),
            },
            "timestamp": candles[i].get("timestamp", datetime.now(timezone.utc).isoformat()),
        })

    return records


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(symbol: str, min_samples: int, dry_run: bool) -> None:
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    history_key = _HISTORY_KEY_TPL.format(symbol=symbol)

    try:
        existing = await r.llen(history_key)
        print(f"[bootstrap] Redis feature history: {existing} records for {symbol}")

        if existing >= min_samples:
            print(f"[bootstrap] Sufficient data ({existing} >= {min_samples}). Triggering training...")
        else:
            needed = min_samples - existing
            print(f"[bootstrap] Only {existing} records — fetching {needed + 200} candles to bootstrap...")

            # /api/v2/market/candles caps `count` at 5000 server-side (matches
            # nexus-data's own ceiling) — requesting more fails the call
            # outright instead of clamping, so cap here too.
            candle_count = min(5000, needed + 400)

            async with httpx.AsyncClient(timeout=30.0) as client:
                url = f"{API_URL}/api/v2/market/candles"
                resp = await client.get(url, params={
                    "symbol": symbol, "timeframe": "H1",
                    "count": candle_count,
                })
                if not resp.is_success:
                    # Try nexus-data directly — live route is /api/data/ohlcv
                    # (returns a bare OHLCV list, capped by `limit`).
                    resp = await client.get(
                        f"{DATA_URL}/api/data/ohlcv/{symbol}/H1",
                        params={"limit": candle_count},
                    )
                if not resp.is_success:
                    print(f"[bootstrap] ERROR: could not fetch candles (HTTP {resp.status_code})")
                    print(f"[bootstrap] Make sure nexus-data ({DATA_URL}) is running.")
                    await r.aclose()
                    sys.exit(1)

                candles_raw = resp.json()
                if isinstance(candles_raw, dict):
                    candles_raw = candles_raw.get("candles", candles_raw.get("data", candles_raw.get("bars", [])))

            if not candles_raw:
                print("[bootstrap] No candles returned — cannot bootstrap")
                await r.aclose()
                sys.exit(1)

            print(f"[bootstrap] Fetched {len(candles_raw)} candles")
            records = compute_features(candles_raw)
            print(f"[bootstrap] Computed {len(records)} feature records")

            if not records:
                print("[bootstrap] Not enough candles to compute features (need >= 210)")
                await r.aclose()
                sys.exit(1)

            if dry_run:
                print("[bootstrap] DRY RUN — would push", len(records), "records to Redis")
            else:
                pipe = r.pipeline()
                for rec in records:
                    pipe.rpush(history_key, json.dumps(rec))
                pipe.ltrim(history_key, -10000, -1)
                await pipe.execute()
                print(f"[bootstrap] Pushed {len(records)} records to {history_key}")

        if dry_run:
            print("[bootstrap] DRY RUN — skipping training call")
            await r.aclose()
            return

        # Trigger training. train_months/val_months must fit inside the actual
        # calendar span available — a window wider than the data causes every
        # walk-forward fold to be skipped silently, which is exactly the
        # failure mode this script exists to avoid. H1 history currently
        # spans ~10 months (5000-candle ceiling on nexus-data).
        async with httpx.AsyncClient(timeout=60.0) as client:
            train_url = f"{ML_URL}/api/ml/train"
            resp = await client.post(train_url, headers=_internal_headers(), json={
                "symbols": [symbol],
                "train_months": 4,
                "val_months": 1,
                "step_months": 1,
            })
            if resp.is_success:
                data = resp.json()
                print(f"[bootstrap] Training started: task_id={data.get('task_id')} status={data.get('status')}")
                print(f"[bootstrap] This runs in the background. Check /api/ml/models/status to monitor progress.")
            else:
                print(f"[bootstrap] WARNING: Training request failed (HTTP {resp.status_code}): {resp.text[:200]}")
                print(f"[bootstrap] You can trigger training manually: POST {train_url}")

    finally:
        await r.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bootstrap Nexus ML Ensemble")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--min-samples", type=int, default=_MIN_SAMPLES_DEFAULT,
                        help="Minimum feature records before triggering training")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be done without writing to Redis")
    args = parser.parse_args()
    _load_env()
    asyncio.run(main(args.symbol, args.min_samples, args.dry_run))
