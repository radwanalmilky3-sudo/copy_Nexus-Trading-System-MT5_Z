"""
Intermarket router — correlation matrix, intermarket score, divergences.

A Redis outage returns 503; a healthy store with no cached data yet returns
the empty/default payload with 200.
"""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from shared.redis_client import RedisClient

from ..deps import get_redis
from .admin import require_permission

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/intermarket", tags=["intermarket"])
_trading_view = require_permission("trading.view")


# ── Response models ──────────────────────────────────────────────────────────

class CorrelationEntry(BaseModel):
    pair_a: str
    pair_b: str
    correlation: float
    timeframe: str = "H1"


class IntermarketScore(BaseModel):
    symbol: str
    score: float
    components: dict[str, float]
    bias: str


class Divergence(BaseModel):
    symbol: str
    related_asset: str
    divergence_type: str
    severity: str
    detected_at: str


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _cache_get_or_fail(redis: RedisClient, key: str) -> Any:
    """Fetch a cache key; an unreachable store fails closed with 503."""
    try:
        return await redis.cache_get(key)
    except Exception as exc:
        logger.warning("intermarket.cache_get_failed", key=key, error=str(exc))
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Intermarket store is temporarily unavailable",
        ) from exc


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/matrix", response_model=list[CorrelationEntry], dependencies=[Depends(_trading_view)])
async def correlation_matrix(
    redis: RedisClient = Depends(get_redis),
) -> list[dict[str, Any]]:
    cached = await _cache_get_or_fail(redis, "intermarket:matrix")
    if cached and isinstance(cached, list):
        return cached
    return []


@router.get("/score/{symbol}", response_model=IntermarketScore, dependencies=[Depends(_trading_view)])
async def intermarket_score(
    symbol: str,
    redis: RedisClient = Depends(get_redis),
) -> dict[str, Any]:
    cached = await _cache_get_or_fail(redis, f"intermarket:score:{symbol.upper()}")
    if cached and isinstance(cached, dict):
        return cached
    return {
        "symbol": symbol.upper(),
        "score": 0.0,
        "components": {},
        "bias": "neutral",
    }


@router.get("/divergences", response_model=list[Divergence], dependencies=[Depends(_trading_view)])
async def active_divergences(
    redis: RedisClient = Depends(get_redis),
) -> list[dict[str, Any]]:
    cached = await _cache_get_or_fail(redis, "intermarket:divergences")
    if cached and isinstance(cached, list):
        return cached
    return []
