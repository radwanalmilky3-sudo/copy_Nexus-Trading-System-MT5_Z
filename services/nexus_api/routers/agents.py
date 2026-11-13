"""
Agents router — agent status, reasoning history, and manual evaluation trigger.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from ..http_client import new_client
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from shared.constants import (
    AGENT_COLORS,
    AGENT_NAMES,
    AgentID,
    REDIS_KEY_PREFIX,
    SERVICE_PORTS,
)
from shared.redis_client import RedisClient

from ..data_client import DataServiceClient, DataServiceRejected, DataServiceUnavailable
from ..deps import get_data_service, get_redis
from ..middleware.auth import CurrentUser
from .admin import _require

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/agents", tags=["agents"])

AGENTS_BASE = os.getenv(
    "NEXUS_AGENTS_URL",
    f"http://127.0.0.1:{SERVICE_PORTS['nexus-agents']}",
).rstrip("/")

FRESH_WINDOW_SEC = 300  # align with heartbeat TTL


def _internal_headers() -> dict[str, str]:
    secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
    if not secret:
        raise HTTPException(503, "NEXUS_INTERNAL_API_SECRET is not configured")
    return {"X-Nexus-Internal-Secret": secret}


# ── Response models ──────────────────────────────────────────────────────────

class AgentStatus(BaseModel):
    agent_id: str
    name: str
    color: str
    status: str = "idle"
    last_message: str = ""
    last_active: str | None = None


class AgentsMeta(BaseModel):
    service_online: bool = False
    active_cycles: int = 0
    total_cycles_completed: int = 0
    ready_count: int = 0
    total_agents: int = 13
    pipeline_state: str = "offline"  # offline | ready | evaluating | error


class AgentsStatusPayload(BaseModel):
    agents: list[AgentStatus]
    meta: AgentsMeta
    # Real LLM identity reported by nexus-agents (Ollama tag / Z.ai model).
    # Empty when the agents service is unreachable — never a guessed default.
    llm_model: str = ""
    llm_online: bool = False
    # Endpoint the agents service actually talks to — the dashboard derives
    # local-vs-cloud from it instead of hardcoding a provider name.
    llm_url: str = ""


class EvaluateRequest(BaseModel):
    symbol: str = "EURUSD"
    timeframe: str = "M5"


def _parse_health_age(ts: str | None, now: datetime) -> bool:
    if not ts:
        return False
    try:
        parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        age = (now - parsed).total_seconds()
        return 0 <= age <= FRESH_WINDOW_SEC
    except Exception:
        return False


async def _fetch_agents_service_meta() -> tuple[bool, int, int, str, bool, str]:
    """Ping nexus-agents for cycle counters and the real LLM identity.

    Returns ``(service_online, active_cycles, total_cycles_completed,
    llm_model, llm_online, llm_url)``. ``llm_model`` is whatever the agents service
    reports for the configured provider — the dashboard must render this
    value, not a hardcoded model name.
    """
    try:
        async with new_client(timeout=2.5) as client:
            health = await client.get(f"{AGENTS_BASE}/health")
            if health.status_code != 200:
                return False, 0, 0, "", False, ""
            status_resp = await client.get(
                f"{AGENTS_BASE}/api/agents/status",
                headers=_internal_headers(),
            )
            if status_resp.status_code != 200:
                return True, 0, 0, "", False, ""
            body = status_resp.json()
            return (
                True,
                int(body.get("active_cycles", 0)),
                int(body.get("total_cycles_completed", 0)),
                str(body.get("llm_model") or ""),
                bool(body.get("llm_online", False)),
                str(body.get("llm_url") or ""),
            )
    except Exception:
        return False, 0, 0, "", False, ""


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/status", response_model=AgentsStatusPayload)
async def agents_status(
    actor: CurrentUser,
    redis: RedisClient = Depends(get_redis),
    db: DataServiceClient = Depends(get_data_service),
) -> dict[str, Any]:
    await _require(db, actor, "trading.view")
    now = datetime.now(timezone.utc)
    agent_ids = list(AgentID)

    raw_values: list[Any] = [None] * len(agent_ids)
    try:
        keys = [f"{REDIS_KEY_PREFIX}health:{aid}" for aid in agent_ids]
        raw_values = await redis.r.mget(keys)
    except Exception:
        logger.warning("agents.status.mget_failed")

    results: list[dict[str, Any]] = []
    for aid, raw in zip(agent_ids, raw_values):
        cached: Any = None
        if raw is not None:
            try:
                cached = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
            except Exception:
                cached = None

        status_val = "offline"
        last_active: str | None = None
        if isinstance(cached, dict):
            last_active = cached.get("ts")
            reported = str(cached.get("status") or "").lower()
            if _parse_health_age(last_active, now) and reported:
                status_val = reported if reported in (
                    "online", "processing", "idle", "error",
                ) else "online"

        results.append({
            "agent_id": aid,
            "name": AGENT_NAMES.get(aid, aid),
            "color": AGENT_COLORS.get(aid, "#FFFFFF"),
            "status": status_val,
            "last_message": "",
            "last_active": last_active,
        })

    (
        service_online,
        active_cycles,
        total_cycles,
        llm_model,
        llm_online,
        llm_url,
    ) = await _fetch_agents_service_meta()

    # Service alive but Redis keys missing/stale → show READY (idle), not offline
    if service_online:
        for row in results:
            if row["status"] == "offline":
                row["status"] = "idle"
                row["last_message"] = "awaiting signal"

    ready_count = sum(
        1 for a in results
        if a["status"] in ("idle", "online", "processing")
    )

    if not service_online:
        pipeline_state = "offline"
    elif active_cycles > 0:
        pipeline_state = "evaluating"
    elif any(a["status"] == "error" for a in results):
        pipeline_state = "error"
    else:
        pipeline_state = "ready"

    return {
        "agents": results,
        "meta": {
            "service_online": service_online,
            "active_cycles": active_cycles,
            "total_cycles_completed": total_cycles,
            "ready_count": ready_count,
            "total_agents": len(results),
            "pipeline_state": pipeline_state,
        },
        "llm_model": llm_model,
        "llm_online": llm_online,
        "llm_url": llm_url,
    }


@router.get("/reasoning/{cycle_id}")
async def agent_reasoning(
    cycle_id: str,
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
) -> dict[str, Any]:
    """Return every agent log entry that belongs to *cycle_id*."""
    await _require(db, actor, "trading.view")
    try:
        rows = await db.query("agent_reasoning", {"cycle_id": cycle_id, "cycle_pattern": f"%{cycle_id}%"})
    except (DataServiceUnavailable, DataServiceRejected):
        raise
    except Exception:
        rows = []
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cycle not found")
    return {"cycle_id": cycle_id, "messages": rows, "count": len(rows)}


@router.post("/evaluate", status_code=status.HTTP_202_ACCEPTED)
async def trigger_evaluation(
    body: EvaluateRequest,
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
) -> dict[str, str]:
    """Proxy a manual evaluation request to the agents service."""
    await _require(db, actor, "trading.execute")
    internal_secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
    if not internal_secret:
        raise HTTPException(503, "NEXUS_INTERNAL_API_SECRET is not configured")
    async with new_client(timeout=15) as client:
        try:
            resp = await client.post(
                f"{AGENTS_BASE}/api/agents/evaluate/{body.symbol}",
                json=body.model_dump(),
                headers={"X-Nexus-Internal-Secret": internal_secret},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(exc.response.status_code, exc.response.text)
        except httpx.RequestError as exc:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"Agents service unreachable: {exc}",
            )
    return {"status": "evaluation_triggered", "symbol": body.symbol}


@router.get("/decision/{symbol}")
async def latest_decision(
    symbol: str,
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
) -> dict[str, Any]:
    """Forward the most recent verdict + risk reasoning for a symbol."""
    await _require(db, actor, "trading.view")
    async with new_client(timeout=10) as client:
        try:
            resp = await client.get(
                f"{AGENTS_BASE}/api/agents/decision/{symbol.upper()}",
                headers=_internal_headers(),
            )
        except httpx.RequestError as exc:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"Agents service unreachable: {exc}",
            )
    if resp.status_code == 404:
        # N4 (2026-11-05): polling façade — "no decision yet" is a state,
        # not an error. Bare not-available marker (same unwrapped shape as
        # the normal DTO path; verdict fields are never fabricated) keeps
        # the honesty contracts intact while sparing the browser console
        # the unsuppressible 404 network line. The UI client treats
        # available:false exactly like the old 404 (null).
        return {"symbol": symbol.upper(), "available": False}
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text)
    return resp.json()

@router.get("/brain/budget")
async def brain_budget(
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
) -> dict[str, Any]:
    """Daily LLM cost tracker — remaining budget, token usage."""
    await _require(db, actor, "trading.view")
    async with new_client(timeout=10) as client:
        try:
            resp = await client.get(
                f"{AGENTS_BASE}/api/agents/brain/budget",
                headers=_internal_headers(),
            )
        except httpx.RequestError as exc:
            logger.warning("agents.brain_budget.unreachable", error=str(exc))
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                "Agents service unreachable for budget data",
            ) from exc
    if resp.status_code >= 400:
        logger.warning(
            "agents.brain_budget.failed", status=resp.status_code
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"nexus-agents budget read failed ({resp.status_code})",
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "nexus-agents returned an invalid budget payload",
        ) from exc

@router.get("/shadow-trades/stats")
async def shadow_trade_stats(
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
    limit: int = 500,
) -> dict[str, Any]:
    """What rejected/downgraded signals would have done — validates the
    conflict-lock, ergodic circuit breaker and institutional thresholds
    against real outcomes instead of guessing."""
    await _require(db, actor, "trading.view")
    async with new_client(timeout=10) as client:
        try:
            resp = await client.get(
                f"{AGENTS_BASE}/api/agents/shadow-trades/stats",
                params={"limit": limit},
                headers=_internal_headers(),
            )
        except httpx.RequestError as exc:
            logger.warning("agents.shadow_stats.unreachable", error=str(exc))
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                "Agents service unreachable for shadow-trade stats",
            ) from exc
    if resp.status_code >= 400:
        logger.warning(
            "agents.shadow_stats.failed", status=resp.status_code
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"nexus-agents shadow-trade stats read failed ({resp.status_code})",
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "nexus-agents returned an invalid shadow-trade stats payload",
        ) from exc
