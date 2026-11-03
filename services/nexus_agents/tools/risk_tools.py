"""
Risk management tools used by the Risk Manager (A8) and other agents.

Provides equity-aware position sizing, trade counting, and cooldown tracking.
"""
from __future__ import annotations

import math
import os
import time
from typing import Any

import httpx
from shared.http_client import new_client
import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger(__name__)

RISK_SERVICE_URL = os.getenv("NEXUS_RISK_URL", "http://127.0.0.1:9006")
EXECUTOR_SERVICE_URL = os.getenv("NEXUS_EXECUTOR_URL", "http://127.0.0.1:9007")
ACCOUNT_BALANCE = float(os.getenv("NEXUS_ACCOUNT_BALANCE", "200"))
_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
_REDIS_COUNT_KEY = "nexus:risk:daily_trade_count"
_REDIS_COUNT_DAY_KEY = "nexus:risk:daily_count_day"

_cached_equity: float | None = None
_equity_fetch_time: float = 0.0
_last_trade_ts: float = 0.0


def _executor_internal_headers() -> dict[str, str]:
    secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
    if not secret:
        raise RuntimeError("NEXUS_INTERNAL_API_SECRET is not configured")
    return {"X-Nexus-Internal-Secret": secret}

_redis_rt: aioredis.Redis | None = None


async def _get_redis_rt() -> aioredis.Redis:
    global _redis_rt
    if _redis_rt is None:
        _redis_rt = aioredis.from_url(_REDIS_URL, decode_responses=True, max_connections=3)
    return _redis_rt


async def _get_account_equity() -> float:
    """Fetch real account equity from the executor service (cached 60s)."""
    global _cached_equity, _equity_fetch_time
    now = time.time()
    if _cached_equity is not None and (now - _equity_fetch_time) < 60:
        return _cached_equity
    try:
        async with new_client(timeout=3.0) as client:
            resp = await client.get(
                f"{EXECUTOR_SERVICE_URL}/api/executor/positions",
                headers=_executor_internal_headers(),
            )
            if resp.status_code == 200:
                data = resp.json()
                equity = float(data.get("account", {}).get("equity", 0))
                if equity > 0:
                    _cached_equity = equity
                    _equity_fetch_time = now
                    return equity
    except Exception as exc:
        await logger.awarning(
            "tools.equity_fetch_failed",
            error=str(exc),
            url=EXECUTOR_SERVICE_URL,
        )
    if _cached_equity is not None:
        return _cached_equity
    await logger.awarning(
        "tools.equity_fallback_static",
        fallback_balance=ACCOUNT_BALANCE,
        reason="executor unreachable and no cached equity — using configured fallback",
    )
    return ACCOUNT_BALANCE


def dynamic_lot_cap(equity: float) -> float:
    """Calculate max lot size based on account equity.

    Scales linearly: $200 → 0.04, $500 → 0.10, $1000 → 0.20, $5000 → 1.0.
    Min 0.01, max 2.0.
    """
    if equity <= 0:
        return 0.01
    cap = equity / 5000.0
    return max(0.01, min(round(cap, 2), 2.0))


def dynamic_daily_limit(equity: float) -> int:
    """Calculate max trades per day based on equity.

    $100 → 3, $200 → 4, $500 → 5, $1000 → 8, $5000 → 12, $10000+ → 15.
    """
    if equity <= 0:
        return 3
    limit = 3 + math.log2(max(1, equity / 100))
    return max(3, min(int(limit), 15))


async def record_trade() -> None:
    """Record that a trade was executed (persisted in Redis to survive restarts)."""
    global _last_trade_ts
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _last_trade_ts = time.time()
    try:
        r = await _get_redis_rt()
        stored_day = await r.get(_REDIS_COUNT_DAY_KEY) or ""
        if stored_day != today:
            await r.set(_REDIS_COUNT_DAY_KEY, today, ex=172_800)
            await r.set(_REDIS_COUNT_KEY, 1, ex=172_800)
        else:
            await r.incr(_REDIS_COUNT_KEY)
            await r.expire(_REDIS_COUNT_KEY, 172_800)
    except Exception as exc:
        logger.warning("risk_tools.record_trade redis failed", error=str(exc))


async def get_trade_count_today() -> int:
    """Get number of trades executed today (reads from Redis first)."""
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        r = await _get_redis_rt()
        stored_day = await r.get(_REDIS_COUNT_DAY_KEY) or ""
        if stored_day != today:
            return 0
        val = await r.get(_REDIS_COUNT_KEY)
        return int(val) if val else 0
    except Exception as exc:
        logger.warning("risk_tools.get_trade_count redis failed", error=str(exc))
        return 0


def seconds_since_last_trade() -> float:
    """Seconds elapsed since the last trade was recorded."""
    if _last_trade_ts == 0:
        return float("inf")
    return time.time() - _last_trade_ts


async def check_exposure() -> dict[str, Any]:
    """Get current portfolio exposure from the risk service."""
    try:
        async with new_client(timeout=5.0) as client:
            resp = await client.get(
                f"{RISK_SERVICE_URL}/api/exposure",
                headers=_executor_internal_headers(),
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    required = (
                        "daily_loss_pct",
                        "weekly_dd_pct",
                        "open_positions",
                        "consecutive_losses",
                    )
                    if data.get("available") is False or any(key not in data for key in required):
                        return {**data, "available": False}
                    normalized: dict[str, float | int] = {}
                    for key in required:
                        value = data[key]
                        if isinstance(value, bool):
                            return {**data, "available": False}
                        number = float(value)
                        if not math.isfinite(number):
                            return {**data, "available": False}
                        if key in {"open_positions", "consecutive_losses"}:
                            if number < 0 or not number.is_integer():
                                return {**data, "available": False}
                            normalized[key] = int(number)
                        else:
                            normalized[key] = number
                    return {**data, **normalized, "available": True}
    except Exception as exc:
        await logger.awarning("tools.check_exposure_failed", error=str(exc))

    return {
        "available": False,
        "daily_loss_pct": 0.0,
        "weekly_dd_pct": 0.0,
        "open_positions": 0,
        "positions": [],
        "consecutive_losses": 0,
        "tilt_status": "normal",
        "daily_pnl": 0.0,
        "correlation_exposure": 0.0,
    }


async def calculate_size(
    entry: float,
    sl: float,
    risk_pct: float,
    symbol: str = "XAUUSD",
) -> float:
    """Calculate position size in lots using actual account equity and asset specs."""
    from shared.asset_specs import get_contract_size

    equity = await _get_account_equity()

    try:
        async with new_client(timeout=3.0) as client:
            resp = await client.post(
                f"{RISK_SERVICE_URL}/api/size",
                json={"entry": entry, "sl": sl, "risk_pct": risk_pct, "balance": equity},
                headers=_executor_internal_headers(),
            )
            if resp.status_code == 200:
                return resp.json().get("size", 0.01)
    except Exception:
        pass

    if entry == 0 or sl == 0 or entry == sl:
        return 0.01

    risk_amount = equity * (risk_pct / 100.0)
    sl_distance = abs(entry - sl)

    if sl_distance > 0:
        contract_size = get_contract_size(symbol)
        size = risk_amount / (sl_distance * contract_size)
        cap = dynamic_lot_cap(equity)
        return max(0.01, min(round(size, 2), cap))

    return 0.01


async def get_open_positions(symbol: str | None = None) -> list[dict[str, Any]]:
    """Fetch Nexus-tagged open positions (external MT5 trades are ignored for risk)."""
    try:
        async with new_client(timeout=3.0) as client:
            resp = await client.get(
                f"{EXECUTOR_SERVICE_URL}/api/executor/positions",
                params={"nexus_only": "true"},
                headers=_executor_internal_headers(),
            )
            if resp.status_code == 200:
                data = resp.json()
                positions = data.get("nexus_positions", data.get("positions", []))
                if symbol:
                    positions = [
                        p for p in positions
                        if p.get("symbol", "").upper() == symbol.upper()
                    ]
                return positions
    except Exception:
        pass

    try:
        exposure = await check_exposure()
        positions = exposure.get("positions", [])
        if symbol:
            positions = [
                p for p in positions
                if p.get("symbol", "").upper() == symbol.upper()
            ]
        return positions
    except Exception:
        pass

    return []


async def check_correlation(
    symbol: str,
    positions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check if adding a position in `symbol` would violate correlation limits.

    Fail-closed: if the central risk service is unreachable, the result is
    ``available=False`` with ``violation=True`` so callers treat an unverified
    correlation check as a block rather than silently passing.
    """
    try:
        async with new_client(timeout=3.0) as client:
            resp = await client.post(
                f"{RISK_SERVICE_URL}/api/correlation",
                json={"symbol": symbol, "positions": positions},
                headers=_executor_internal_headers(),
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    return {**data, "available": True}
    except Exception as exc:
        await logger.awarning("tools.check_correlation_failed", error=str(exc))

    return {
        "available": False,
        "symbol": symbol,
        "violation": True,
        "correlated_positions": [],
        "max_correlation": None,
        "reason": "correlation check unavailable — fail-closed block",
    }
