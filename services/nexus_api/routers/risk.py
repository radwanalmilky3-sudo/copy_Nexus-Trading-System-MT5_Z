"""
Risk router — current risk state and circuit-breaker status.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from ..http_client import new_client
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from shared.constants import SERVICE_PORTS
from shared.models import CircuitBreaker, RiskState
from shared.redis_client import RedisClient

from ..data_client import DataServiceClient
from ..deps import get_data_service, get_redis
from ..middleware.auth import CurrentUser
from .admin import _require

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/risk", tags=["risk"])

# Fallback must match shared.constants.SERVICE_PORTS["nexus-risk"] and resolve
# to IPv4: run.py injects NEXUS_RISK_URL=http://127.0.0.1:9006, but launchers
# that skip that injection (uvicorn by hand, IDE run configs,
# scripts/start_settings_only.py) rely on this default — the old "localhost:8006"
# pointed at a port nothing listens on, turning every /api/risk/* proxy into a 502.
RISK_BASE = os.getenv(
    "NEXUS_RISK_URL",
    f"http://127.0.0.1:{os.getenv('NEXUS_RISK_PORT', str(SERVICE_PORTS['nexus-risk']))}",
)


async def _risk_proxy(method: str, path: str, body: Any = None) -> Any:
    """Forward a request to the nexus-risk service and return JSON."""
    url = f"{RISK_BASE}{path}"
    internal_secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
    if not internal_secret:
        raise HTTPException(503, "NEXUS_INTERNAL_API_SECRET is not configured")
    headers = {"X-Nexus-Internal-Secret": internal_secret}
    async with new_client(timeout=8.0) as client:
        try:
            kwargs: dict[str, Any] = {}
            kwargs["headers"] = headers
            if body is not None:
                kwargs["json"] = body
            resp = await client.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(exc.response.status_code, exc.response.text)
        except Exception as exc:
            logger.warning("risk.proxy_failed", path=path, error=str(exc))
            raise HTTPException(502, f"nexus-risk unreachable: {exc}")


@router.get("/settings")
async def get_risk_settings(
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
):
    """Proxy: current front-configurable runtime settings + live counters."""
    await _require(db, actor, "risk.view")
    return await _risk_proxy("GET", "/api/risk/settings")


@router.post("/settings")
async def update_risk_settings(
    req: Request,
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
):
    """Proxy: update runtime settings from the dashboard."""
    await _require(db, actor, "risk.modify")
    body = await req.json()
    return await _risk_proxy("POST", "/api/risk/settings", body=body)


@router.post("/reset-day")
async def reset_day(
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
):
    """Proxy: reset the daily risk budget so trading resumes."""
    await _require(db, actor, "risk.modify")
    return await _risk_proxy("POST", "/api/risk/reset-day")


@router.post("/pause")
async def pause_trading(
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
    paused: bool = True,
):
    """Proxy: manually pause/resume trading."""
    await _require(db, actor, "risk.modify")
    return await _risk_proxy("POST", f"/api/risk/pause?paused={str(paused).lower()}")


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/status", response_model=RiskState)
async def risk_status(
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
    redis: RedisClient = Depends(get_redis),
) -> dict[str, Any]:
    """Return the current risk state from Redis."""
    await _require(db, actor, "risk.view")
    cached = await redis.cache_get("risk:state")
    if cached and isinstance(cached, dict):
        return cached
    return RiskState().model_dump()


@router.get("/circuit-breakers", response_model=list[CircuitBreaker])
async def circuit_breakers(
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
    redis: RedisClient = Depends(get_redis),
) -> list[dict[str, Any]]:
    await _require(db, actor, "risk.view")
    try:
        cached = await redis.cache_get("risk:state")
    except Exception as exc:
        logger.warning("risk.cache_failed", error=str(exc))
        raise HTTPException(503, "Risk state unavailable") from exc
    if (
        not isinstance(cached, dict)
        or cached.get("available") is not True
        or not isinstance(cached.get("circuit_breakers"), list)
    ):
        raise HTTPException(503, "Risk state unavailable")
    try:
        state = RiskState.model_validate(cached)
    except ValidationError as exc:
        raise HTTPException(503, "Risk state invalid") from exc
    return [breaker.model_dump(mode="json") for breaker in state.circuit_breakers]
