"""
Trades router — proxies to nexus-data which owns the DuckDB write lock.

On Windows, DuckDB enforces an exclusive write lock: the process that opened
the file for writing cannot coexist with a read-only opener in another process.
nexus-data is the sole DuckDB writer, so all trade queries go through it.
"""
from __future__ import annotations

from typing import Any

from ..http_client import new_client
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..data_client import DataServiceClient
from ..deps import get_data_service
from ..middleware.auth import CurrentUser
from .admin import _require
from shared.safety import internal_api_secret

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/trades", tags=["trades"])

import os
_DATA_URL = os.getenv("NEXUS_DATA_URL", "http://127.0.0.1:9001")


async def _proxy_trades(params: dict[str, Any]) -> dict[str, Any]:
    """Forward a trades query to nexus-data and return its JSON response."""
    clean = {k: v for k, v in params.items() if v is not None}
    secret = internal_api_secret()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal data service credential is not configured",
        )
    try:
        async with new_client(timeout=10.0) as client:
            resp = await client.get(
                f"{_DATA_URL}/api/data/trades",
                params=clean,
                headers={"X-Nexus-Internal-Secret": secret},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.warning("trades.proxy.error", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Trade history is temporarily unavailable",
        ) from exc


@router.get("")
async def list_trades(
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
    symbol: str | None = Query(None),
    session: str | None = Query(None),
    side: str | None = Query(None),
    since: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    await _require(db, actor, "trading.view")
    data = await _proxy_trades(
        {"symbol": symbol, "session": session, "since": since,
         "page": page, "page_size": page_size}
    )
    # Apply side filter client-side (nexus-data doesn't support it yet)
    if side and data.get("trades"):
        data["trades"] = [
            t for t in data["trades"]
            if str(t.get("side", "")).upper() == side.upper()
        ]
        data["total"] = len(data["trades"])
    return data


@router.get("/stats")
async def trade_stats(
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
    symbol: str | None = Query(None),
    session: str | None = Query(None),
    since: str | None = Query(None),
) -> dict[str, Any]:
    await _require(db, actor, "trading.view")
    page_size = 5000
    page = 1
    expected_total = 0
    total = 0
    winning = 0
    losing = 0
    total_pnl = 0.0
    total_rr = 0.0
    total_duration = 0.0
    best_trade: float | None = None
    worst_trade: float | None = None

    while True:
        data = await _proxy_trades(
            {"symbol": symbol, "session": session, "since": since,
             "page": page, "page_size": page_size}
        )
        trades = data.get("trades", [])
        if page == 1:
            expected_total = int(data.get("total", len(trades)))
        if not trades:
            break

        for trade in trades:
            pnl = float(trade.get("pnl_usd", 0))
            total += 1
            total_pnl += pnl
            total_rr += float(trade.get("rr_ratio", 0))
            total_duration += float(trade.get("duration_s", 0))
            if pnl > 0:
                winning += 1
            else:
                losing += 1
            best_trade = pnl if best_trade is None else max(best_trade, pnl)
            worst_trade = pnl if worst_trade is None else min(worst_trade, pnl)

        if page * page_size >= expected_total:
            break
        page += 1

    if total == 0:
        return {
            "total_trades": 0, "winning": 0, "losing": 0, "win_rate": 0.0,
            "total_pnl": 0.0, "avg_pnl": 0.0, "avg_rr": 0.0,
            "best_trade": 0.0, "worst_trade": 0.0, "avg_duration_s": 0.0,
        }
    return {
        "total_trades": total,
        "winning": winning,
        "losing": losing,
        "win_rate": round(winning * 100.0 / total, 2),
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(total_pnl / total, 2),
        "avg_rr": round(total_rr / total, 2),
        "best_trade": round(best_trade or 0.0, 2),
        "worst_trade": round(worst_trade or 0.0, 2),
        "avg_duration_s": round(total_duration / total, 1),
    }


@router.get("/{trade_id}")
async def get_trade(
    trade_id: str,
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
) -> dict[str, Any]:
    await _require(db, actor, "trading.view")
    data = await _proxy_trades({"page": 1, "page_size": 200})
    for t in data.get("trades", []):
        if str(t.get("id")) == trade_id:
            return t
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Trade not found")
