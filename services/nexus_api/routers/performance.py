"""
Performance router — proxies to nexus-data (DuckDB owner).
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from ..http_client import new_client
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from shared.safety import internal_api_secret

from ..data_client import DataServiceClient
from ..deps import get_data_service
from ..middleware.auth import CurrentUser
from .admin import _require

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/performance", tags=["performance"])

_DATA_URL = os.getenv("NEXUS_DATA_URL", "http://127.0.0.1:9001")

_EMPTY_PERF = {
    "total_pnl": 0.0, "win_rate": 0.0, "profit_factor": 0.0,
    "sharpe_ratio": 0.0, "max_drawdown": 0.0, "total_trades": 0,
    "avg_win": 0.0, "avg_loss": 0.0,
}


async def _get(path: str, params: dict | None = None) -> Any:
    """Fetch a performance slice from nexus-data.

    ``None`` means the data owner reported no data (HTTP 404). Upstream
    outage or misconfigured credentials fail closed with 502/503 — never a
    fabricated empty/zero 200 payload.
    """
    secret = internal_api_secret()
    if not secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Internal data service credential is not configured",
        )
    try:
        async with new_client(timeout=10.0) as client:
            resp = await client.get(
                f"{_DATA_URL}{path}",
                params=params or {},
                headers={"X-Nexus-Internal-Secret": secret},
            )
    except httpx.HTTPError as exc:
        logger.warning("performance.proxy.error", path=path, error=str(exc))
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "nexus-data unreachable for performance data",
        ) from exc
    if resp.status_code == 404:
        return None
    if resp.status_code >= 400:
        logger.warning("performance.proxy.error", path=path, status=resp.status_code)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"nexus-data performance read failed ({resp.status_code})",
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "nexus-data returned an invalid performance payload",
        ) from exc


@router.get("")
async def overall_performance(
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
) -> dict[str, Any]:
    await _require(db, actor, "trading.view")
    data = await _get("/api/data/performance")
    return data if data else _EMPTY_PERF


@router.get("/equity-curve")
async def equity_curve(
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
    limit: int = Query(200, ge=1, le=2000),
) -> list[dict[str, Any]]:
    await _require(db, actor, "trading.view")
    data = await _get("/api/data/performance/equity-curve", {"limit": limit})
    return data if data else []


@router.get("/daily")
async def daily_pnl(
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
    since: str | None = Query(None),
) -> list[dict[str, Any]]:
    await _require(db, actor, "trading.view")
    params = {"since": since} if since else {}
    data = await _get("/api/data/performance/daily", params)
    return data if data else []


@router.get("/by-session")
async def performance_by_session(
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
) -> list[dict[str, Any]]:
    await _require(db, actor, "trading.view")
    data = await _get("/api/data/performance/by-session")
    return data if data else []


@router.get("/by-symbol")
async def performance_by_symbol(
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
) -> list[dict[str, Any]]:
    await _require(db, actor, "trading.view")
    data = await _get("/api/data/performance/by-symbol")
    return data if data else []
