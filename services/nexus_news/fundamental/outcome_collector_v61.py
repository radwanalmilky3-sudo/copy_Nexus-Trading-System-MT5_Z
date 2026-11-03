from __future__ import annotations

"""Point-in-time asset outcome collector for 5m/15m/60m/4h horizons.

The collector requests historical M1 bars with explicit start/end bounds. That
intentionally disables nexus-data's synthetic fallback, so missing market data is
reported as missing rather than fabricated.
"""

import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import httpx

UTC = timezone.utc
_HORIZONS = {"5m": timedelta(minutes=5), "15m": timedelta(minutes=15), "60m": timedelta(minutes=60), "4h": timedelta(hours=4)}


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if value is None:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d.astimezone(UTC) if d.tzinfo else d.replace(tzinfo=UTC)
    except Exception:
        return None


def _stable_id(*parts: Any) -> str:
    return hashlib.sha256("|".join(str(x) for x in parts).encode("utf-8")).hexdigest()[:32]


def _return(entry: float | None, price: float | None) -> float | None:
    if entry is None or price is None or entry == 0:
        return None
    return (price / entry - 1.0) * 100.0


def _direction(ret: float | None) -> str | None:
    if ret is None:
        return None
    if ret > 0:
        return "bullish"
    if ret < 0:
        return "bearish"
    return "neutral"


class AssetOutcomeCollector:
    version = "1.0.0-v6.1"

    def __init__(self, client: httpx.AsyncClient, data_url: str, persist: Callable[[str, dict[str, Any]], Awaitable[bool]]) -> None:
        self.client = client
        self.data_url = data_url.rstrip("/")
        self.persist = persist

    async def collect_recent(self, now: datetime | None = None, limit: int = 250) -> dict[str, Any]:
        current = now or datetime.now(UTC)
        try:
            impacts = await self._recent_impacts(limit)
        except Exception:
            # Never report "ready" when the impacts feed itself failed — the
            # collector state must surface unavailability, not empty success.
            return {"state": "unavailable", "anchors": 0, "written": 0, "missing_market_data": 0, "collector_version": self.version}
        # One canonical outcome row per event/asset snapshot: the 5m impact is
        # the anchor and stores realized returns for all four horizons.
        anchors = [x for x in impacts if str(x.get("horizon")) == "5m"]
        written = 0
        missing_market_data = 0
        for impact in anchors:
            ts = _dt(impact.get("known_at") or impact.get("calculated_at"))
            asset = str(impact.get("asset_id") or "").upper()
            if not ts or asset not in {"XAUUSD", "BTCUSD"}:
                continue
            # Do not keep scanning ancient impacts in the live collector.
            if current - ts > timedelta(hours=8):
                continue
            bars = await self._bars(asset, ts - timedelta(minutes=2), min(current, ts + timedelta(hours=4, minutes=2)))
            if not bars:
                missing_market_data += 1
                continue
            row = self.build_outcome(impact, bars, current)
            if await self.persist("asset_event_outcomes", row):
                written += 1
        return {"state": "ready", "anchors": len(anchors), "written": written, "missing_market_data": missing_market_data, "collector_version": self.version}

    async def _recent_impacts(self, limit: int) -> list[dict[str, Any]]:
        internal_secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
        if not internal_secret:
            raise RuntimeError("NEXUS_INTERNAL_API_SECRET not configured; outcomes cannot be collected")
        resp = await self.client.get(
            self.data_url + "/api/data/fundamental/latest/event_asset_impacts",
            params={"order_col": "calculated_at", "limit": max(1, min(limit, 500))},
            headers={"X-Nexus-Internal-Secret": internal_secret},
        )
        resp.raise_for_status()
        payload = resp.json()
        rows = payload.get("rows", []) if isinstance(payload, dict) else []
        return rows if isinstance(rows, list) else []

    async def _bars(self, asset: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        try:
            resp = await self.client.get(
                f"{self.data_url}/api/data/ohlcv/{asset}/M1",
                params={"start": start.isoformat(), "end": end.isoformat(), "limit": 5000},
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            rows = resp.json()
            if not isinstance(rows, list):
                return []
            return sorted((x for x in rows if isinstance(x, dict)), key=lambda x: str(x.get("timestamp") or ""))
        except Exception:
            return []

    @staticmethod
    def build_outcome(impact: dict[str, Any], bars: list[dict[str, Any]], captured_at: datetime) -> dict[str, Any]:
        prediction_ts = _dt(impact.get("known_at") or impact.get("calculated_at")) or captured_at
        parsed: list[tuple[datetime, float, float, float]] = []
        for bar in bars:
            ts = _dt(bar.get("timestamp"))
            try:
                close = float(bar.get("close"))
                high = float(bar.get("high", close))
                low = float(bar.get("low", close))
            except (TypeError, ValueError):
                continue
            if ts:
                parsed.append((ts, close, high, low))
        parsed.sort(key=lambda x: x[0])

        def near(target: datetime, *, prefer_after: bool = True) -> float | None:
            eligible = [x for x in parsed if x[0] >= target] if prefer_after else [x for x in parsed if x[0] <= target]
            if eligible:
                row = min(eligible, key=lambda x: abs((x[0] - target).total_seconds()))
                if abs((row[0] - target).total_seconds()) <= 120:
                    return row[1]
            return None

        entry = near(prediction_ts, prefer_after=False) or near(prediction_ts, prefer_after=True)
        prices: dict[str, float | None] = {}
        returns: dict[str, float | None] = {}
        for label, delta in _HORIZONS.items():
            target = prediction_ts + delta
            price = near(target, prefer_after=True) if captured_at >= target else None
            prices[label] = price
            returns[label] = _return(entry, price)

        window = [x for x in parsed if prediction_ts <= x[0] <= min(captured_at, prediction_ts + timedelta(hours=4))]
        mfe = mae = None
        if entry and window:
            mfe = max((x[2] / entry - 1.0) * 100.0 for x in window)
            mae = min((x[3] / entry - 1.0) * 100.0 for x in window)
        complete = prices["4h"] is not None
        any_realized = any(v is not None for v in prices.values())
        quality = "complete" if complete else "partial" if any_realized else "pending"
        impact_id = str(impact.get("impact_id") or "")
        asset = str(impact.get("asset_id") or "")
        return {
            "outcome_id": _stable_id("asset-outcome", impact_id, asset),
            "impact_id": impact_id,
            "asset_id": asset,
            "event_id": impact.get("event_id"),
            "market_timestamp": prediction_ts,
            "price_at_prediction": entry,
            "price_5m": prices["5m"], "price_15m": prices["15m"], "price_60m": prices["60m"], "price_4h": prices["4h"],
            "return_5m": returns["5m"], "return_15m": returns["15m"], "return_60m": returns["60m"], "return_4h": returns["4h"],
            "mfe": mfe, "mae": mae,
            "actual_direction_5m": _direction(returns["5m"]),
            "actual_direction_15m": _direction(returns["15m"]),
            "actual_direction_60m": _direction(returns["60m"]),
            "actual_direction_4h": _direction(returns["4h"]),
            "quality": quality,
            "captured_at": captured_at,
        }
