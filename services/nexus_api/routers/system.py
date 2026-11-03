"""
System router — health dashboard, kill-switch, auto-trade toggle, mode switch.
"""
from __future__ import annotations

from typing import Any
import os

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from shared.constants import ServiceName, TradingMode
from shared.models import SystemHealth
from shared.redis_client import RedisClient
from shared.llm_factory import local_health
from shared.safety import live_mode_enabled

from ..deps import get_config, get_redis
from ..middleware.auth import verify_pin
from ..middleware.auth import CurrentUser
from ..data_client import DataServiceClient
from ..deps import get_data_service
from .admin import _require, require_permission

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/system", tags=["system"])
_trading_view = require_permission("trading.view")


# ── Request / response models ────────────────────────────────────────────────

class KillSwitchRequest(BaseModel):
    pin: str
    reason: str = "manual kill-switch"


class ToggleAutoTradeRequest(BaseModel):
    enabled: bool
    pin: str | None = None


class SwitchModeRequest(BaseModel):
    mode: TradingMode
    pin: str | None = None


class ModeResponse(BaseModel):
    mode: TradingMode
    auto_trade: bool
    kill_switch: bool


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/health", response_model=list[SystemHealth], dependencies=[Depends(_trading_view)])
async def system_health(
    redis: RedisClient = Depends(get_redis),
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for svc in ServiceName:
        cached = await redis.cache_get(f"health:{svc}")
        if cached and isinstance(cached, dict):
            results.append(cached)
        else:
            results.append(
                SystemHealth(service_name=svc, status="unknown").model_dump(mode="json"),
            )
    return results


@router.post("/kill-switch", status_code=status.HTTP_200_OK)
async def kill_switch(
    body: KillSwitchRequest,
    actor: CurrentUser,
    redis: RedisClient = Depends(get_redis),
) -> dict[str, str]:
    """EMERGENCY STOP — close all positions, halt all agents."""
    verify_pin(body.pin)
    await redis.cache_set("system:kill_switch", True, ttl_sec=10 * 365 * 24 * 3600)
    await redis.cache_set("system:auto_trade", False, ttl_sec=10 * 365 * 24 * 3600)
    await redis.publish_channel(
        "system:commands",
        {"command": "kill_switch", "reason": body.reason},
    )
    await logger.awarning("KILL_SWITCH activated", reason=body.reason)
    return {"status": "kill_switch_activated", "reason": body.reason}


@router.post("/toggle-auto-trade")
async def toggle_auto_trade(
    body: ToggleAutoTradeRequest,
    actor: CurrentUser,
    redis: RedisClient = Depends(get_redis),
    db: DataServiceClient = Depends(get_data_service),
) -> dict[str, Any]:
    if body.enabled:
        await _require(db, actor, "trading.execute")
        if not body.pin:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "PIN required to enable auto-trade")
        verify_pin(body.pin)
    await redis.cache_set("system:auto_trade", body.enabled, ttl_sec=10 * 365 * 24 * 3600)
    state = "enabled" if body.enabled else "disabled"
    await logger.ainfo("auto_trade.toggled", enabled=body.enabled)
    return {"auto_trade": body.enabled, "message": f"Auto-trade {state}"}


@router.get("/mode", response_model=ModeResponse, dependencies=[Depends(_trading_view)])
async def get_mode(
    redis: RedisClient = Depends(get_redis),
) -> dict[str, Any]:
    mode = TradingMode.LIVE if live_mode_enabled() else TradingMode.PAPER
    auto_trade = await redis.cache_get("system:auto_trade")
    kill_switch = await redis.cache_get("system:kill_switch")
    return {
        "mode": mode,
        "auto_trade": auto_trade is True,
        # Risk/anti-tilt may latch a structured reason rather than literal True.
        # Any non-empty latch value is active and must remain visible to clients.
        "kill_switch": bool(kill_switch),
    }


@router.post("/mode", response_model=ModeResponse)
async def switch_mode(
    body: SwitchModeRequest,
    actor: CurrentUser,
    redis: RedisClient = Depends(get_redis),
) -> dict[str, Any]:
    if body.mode == TradingMode.LIVE:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "LIVE mode cannot be activated from the dashboard. Restart with --live --confirm-live.",
        )
    if live_mode_enabled():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Trading mode is process-level. Restart with --paper to enter PAPER mode; no mode change was applied.",
        )
    # PAPER can always be requested; the process environment remains the executor source of truth.
    session = await redis.cache_get("session:state") or {}
    session = session if isinstance(session, dict) else {}
    session["mode"] = TradingMode.PAPER
    await redis.cache_set("session:state", session, ttl_sec=10 * 365 * 24 * 3600)
    await redis.cache_set("system:auto_trade", False, ttl_sec=10 * 365 * 24 * 3600)
    kill_switch = await redis.cache_get("system:kill_switch")
    await redis.publish_channel("system:commands", {"command": "mode_switch", "mode": "paper"})
    return {"mode": TradingMode.PAPER, "auto_trade": False, "kill_switch": bool(kill_switch)}


@router.get("/local-ai-health", dependencies=[Depends(_trading_view)])
async def local_ai_health() -> dict[str, Any]:
    """Live proof that the configured local Ollama/OpenAI-compatible model is reachable."""
    return await local_health()
