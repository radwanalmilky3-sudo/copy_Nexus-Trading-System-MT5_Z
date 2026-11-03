"""
Regime Router — exposes current HMM + rule-based regime data to the dashboard.
"""
from __future__ import annotations

import json
import logging
import os

import redis.asyncio as aioredis
from fastapi import APIRouter
from fastapi import Depends, HTTPException
from .admin import require_permission

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

_redis: aioredis.Redis | None = None


async def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(REDIS_URL, decode_responses=True, max_connections=5)
    return _redis


router = APIRouter(prefix="/api/regime", tags=["Regime"])
_trading_view = require_permission("trading.view")


@router.get("/current", dependencies=[Depends(_trading_view)])
async def get_current_regime():
    """Current market regime from HMM + rule-based classifier.

    A Redis outage returns 503 instead of a fabricated UNKNOWN 200 payload.
    """
    try:
        r = await _get_redis()
        raw = await r.get("nexus:regime:current")
    except Exception as exc:
        logger.warning("regime/current unavailable", exc_info=True)
        raise HTTPException(
            status_code=503, detail="regime state unavailable"
        ) from exc
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=503, detail="regime state invalid"
            ) from exc
    return {
        "regime": "UNKNOWN",
        "hmm_regime": "UNKNOWN",
        "rule_regime": "UNKNOWN",
        "hmm_confidence": 0.0,
        "source": "none",
        "is_transition": False,
        "volatility_regime": "MEDIUM",
    }


@router.get("/history", dependencies=[Depends(_trading_view)])
async def get_regime_history(limit: int = 20):
    """Recent regime transitions (last N)."""
    try:
        r = await _get_redis()
        raw_list = await r.lrange("nexus:regime:history", 0, limit - 1)
        return {"transitions": [json.loads(x) for x in raw_list]}
    except Exception as exc:
        logger.warning("regime/history unavailable", exc_info=True)
        raise HTTPException(status_code=503, detail="regime history unavailable") from exc


@router.get("/thresholds", dependencies=[Depends(_trading_view)])
async def get_dynamic_thresholds():
    """Current dynamic thresholds derived from TradeMemory.

    A Redis outage returns 503 instead of a misleading 200 error dict.
    """
    try:
        r = await _get_redis()
        raw = await r.get("nexus:trade_memory:thresholds")
    except Exception as exc:
        logger.warning("regime/thresholds unavailable", exc_info=True)
        raise HTTPException(
            status_code=503, detail="dynamic thresholds unavailable"
        ) from exc
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=503, detail="dynamic thresholds invalid"
            ) from exc
    return {"error": "no thresholds computed yet", "total_trades": 0}
