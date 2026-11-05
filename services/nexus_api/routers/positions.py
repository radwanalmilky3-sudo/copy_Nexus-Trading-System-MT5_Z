"""
Positions router — open-position CRUD and close/modify proxying.

Falls back to the executor's live broker positions when Redis/DuckDB are empty
(local dev / MT5 terminal).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx

from ..http_client import new_client
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from shared.constants import SERVICE_PORTS, Verdict
from shared.models import Position
from shared.redis_client import RedisClient

from ..data_client import DataServiceClient, DataServiceRejected, DataServiceUnavailable
from ..deps import get_data_service, get_redis
from ..middleware.auth import CurrentUser
from .admin import _require

logger = structlog.get_logger(__name__)

from shared.rate_limit import rate_limit_scope

router = APIRouter(prefix="/api/positions", tags=["positions"])

EXECUTOR_URL = os.getenv(
    "NEXUS_EXECUTOR_URL",
    f"http://127.0.0.1:{SERVICE_PORTS['nexus-executor']}",
).rstrip("/")


# ── Response / request models ────────────────────────────────────────────────

class ModifyRequest(BaseModel):
    sl: float | None = None
    tp1: float | None = None
    tp2: float | None = None
    tp3: float | None = None


class PositionList(BaseModel):
    positions: list[Position]
    count: int
    nexus_count: int = 0
    external_count: int = 0
    account: dict[str, Any] | None = None
    live_connected: bool = False
    source: str = "cache"


def _parse_opened_at(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _executor_row_to_position(p: dict[str, Any]) -> Position:
    side_raw = str(p.get("side", "BUY")).upper()
    side = Verdict.BUY if side_raw == "BUY" else Verdict.SELL
    opened_at = _parse_opened_at(p.get("opened_at"))
    duration_s = max(0.0, (datetime.now(timezone.utc) - opened_at).total_seconds())
    tp = float(p.get("tp") or 0)
    return Position(
        id=str(p.get("id", "")),
        symbol=str(p.get("symbol", "")),
        side=side,
        entry_price=float(p.get("entry_price", 0)),
        current_price=float(p.get("current_price", 0)),
        sl=float(p.get("sl") or 0),
        tp1=tp,
        tp2=None,
        tp3=None,
        size=float(p.get("size", 0.01)),
        pnl_pips=float(p.get("pnl_pips", 0)),
        pnl_usd=float(p.get("pnl_usd", 0)),
        duration=duration_s,
        status="open",
        opened_at=opened_at,
    )


def _dict_to_position(row: dict[str, Any]) -> Position | None:
    try:
        return Position.model_validate(row)
    except Exception:
        return None


async def _fetch_live_executor_snapshot() -> tuple[
    list[Position], dict[str, Any] | None, bool, int, int,
]:
    internal_secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
    if not internal_secret:
        raise HTTPException(503, "NEXUS_INTERNAL_API_SECRET is not configured")
    url = f"{EXECUTOR_URL}/api/executor/positions"
    async with new_client(timeout=25.0) as client:
        resp = await client.get(
            url, headers={"X-Nexus-Internal-Secret": internal_secret}
        )
        resp.raise_for_status()
        data = resp.json()
    rows = data.get("positions") or []
    account = data.get("account")
    nexus_count = int(data.get("nexus_count", 0))
    external_count = int(data.get("external_count", 0))
    return (
        [_executor_row_to_position(dict(r)) for r in rows],
        account if isinstance(account, dict) else None,
        True,
        nexus_count,
        external_count,
    )


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=PositionList)
async def list_positions(
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
    symbol: str | None = Query(None),
    status_filter: str = Query("open", alias="status"),
    redis: RedisClient = Depends(get_redis),
) -> dict[str, Any]:
    """Return open positions from Redis cache, DuckDB, or live executor (MT5).

    Fails closed with 503 only when BOTH durable sources fail (DuckDB query
    error AND executor snapshot error) and no cache entry exists. Sources
    that legitimately report zero positions still return 200.
    """
    await _require(db, actor, "trading.view")
    source = "cache"
    cache_key = f"positions:{status_filter}"
    cached = await redis.cache_get(cache_key)
    duckdb_failed = False
    if cached and isinstance(cached, list):
        positions_raw: list[Any] = cached
    else:
        source = "duckdb"
        try:
            rows = await db.query("positions_by_status", {"status": status_filter})
            positions_raw = rows
        except (DataServiceUnavailable, DataServiceRejected):
            raise
        except Exception as exc:
            positions_raw = []
            duckdb_failed = True
            await logger.awarning("positions.duckdb_unavailable", error=str(exc))
        else:
            try:
                await redis.cache_set(cache_key, positions_raw, ttl_sec=5)
            except Exception as exc:
                await logger.awarning("positions.cache_write_failed", error=str(exc))

    if symbol:
        positions_raw = [
            p for p in positions_raw
            if isinstance(p, dict) and p.get("symbol") == symbol
        ]

    normalized: list[Position] = []
    for p in positions_raw:
        if isinstance(p, Position):
            normalized.append(p)
        elif isinstance(p, dict):
            pos = _dict_to_position(p)
            if pos is not None:
                normalized.append(pos)

    account: dict[str, Any] | None = None
    live_connected = False
    nexus_count = 0
    external_count = 0
    executor_failed = False

    try:
        (
            exec_positions,
            exec_account,
            exec_connected,
            nexus_count,
            external_count,
        ) = await _fetch_live_executor_snapshot()
        account = exec_account
        live_connected = exec_connected
        if not normalized:
            normalized = exec_positions
            source = "executor"
        if symbol:
            normalized = [p for p in normalized if p.symbol == symbol]
    except Exception as exc:
        executor_failed = True
        await logger.awarning("positions.executor_snapshot_failed", error=str(exc))

    if not normalized and duckdb_failed and executor_failed:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Position sources are temporarily unavailable",
        )

    if not normalized:
        source = "empty"

    return {
        "positions": normalized,
        "count": len(normalized),
        "nexus_count": nexus_count,
        "external_count": external_count,
        "account": account,
        "live_connected": live_connected,
        "source": source,
    }


@router.get("/{position_id}", response_model=Position)
async def get_position(
    position_id: str,
    actor: CurrentUser,
    redis: RedisClient = Depends(get_redis),
    db: DataServiceClient = Depends(get_data_service),
) -> Any:
    await _require(db, actor, "trading.view")
    cached = await redis.cache_get(f"positions:{position_id}")
    if cached:
        return cached

    rows = await db.query("position_by_id", {"position_id": position_id})
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Position not found")
    return rows[0]


@router.post(
    "/{position_id}/close",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[rate_limit_scope("edit_close")],
)
async def close_position(
    position_id: str,
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
) -> dict[str, str]:
    """Proxy close to the executor (DELETE …/api/executor/position/{ticket})."""
    await _require(db, actor, "trading.execute")
    internal_secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
    if not internal_secret:
        raise HTTPException(503, "NEXUS_INTERNAL_API_SECRET is not configured")
    async with new_client(timeout=45.0) as client:
        try:
            resp = await client.delete(
                f"{EXECUTOR_URL}/api/executor/position/{position_id}",
                headers={"X-Nexus-Internal-Secret": internal_secret},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(exc.response.status_code, exc.response.text)
        except httpx.RequestError as exc:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"Executor unreachable: {exc}",
            )
    return {"status": "close_requested", "position_id": position_id}


@router.post(
    "/{position_id}/modify",
    status_code=status.HTTP_200_OK,
    response_model=None,
    dependencies=[rate_limit_scope("edit_close")],
)
async def modify_position(
    position_id: str,
    body: ModifyRequest,
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
) -> dict[str, Any] | JSONResponse:
    """Proxy modify SL/TP to the executor."""
    await _require(db, actor, "trading.execute")
    internal_secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
    if not internal_secret:
        raise HTTPException(503, "NEXUS_INTERNAL_API_SECRET is not configured")
    exec_body: dict[str, float] = {}
    if body.sl is not None:
        exec_body["sl"] = body.sl
    tp_val = body.tp1 if body.tp1 is not None else body.tp2 if body.tp2 is not None else body.tp3
    if tp_val is not None:
        exec_body["tp"] = tp_val

    if not exec_body:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Provide at least one of sl, tp1, tp2, tp3",
        )

    async with new_client(timeout=45.0) as client:
        try:
            resp = await client.put(
                f"{EXECUTOR_URL}/api/executor/position/{position_id}",
                json=exec_body,
                headers={"X-Nexus-Internal-Secret": internal_secret},
            )
            resp.raise_for_status()
            try:
                result = resp.json()
            except ValueError as exc:
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    "Executor returned an invalid modification response",
                ) from exc
            if not isinstance(result, dict):
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    "Executor returned an invalid modification response",
                )
            outcome = str(result.get("status", "")).upper()
            if outcome in {"REJECTED", "ERROR", "CANCELLED"}:
                detail = str(result.get("error") or f"Executor reported {outcome}")
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail)
            if outcome not in {"FILLED", "PARTIAL", "PENDING"}:
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    "Executor returned an unknown modification status",
                )
        except httpx.HTTPStatusError as exc:
            raise HTTPException(exc.response.status_code, exc.response.text)
        except httpx.RequestError as exc:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"Executor unreachable: {exc}",
            )
    payload = {
        **result,
        "position_id": position_id,
        "requested": exec_body,
    }
    if outcome == "PENDING":
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=payload)
    return payload
