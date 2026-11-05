"""
Nexus Trader — API Gateway.

Central HTTP + WebSocket gateway that the dashboard (and external clients)
talk to.  Every other micro-service is reachable only through this gateway
or through Redis Streams.
"""
from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from shared.constants import SERVICE_PORTS

from .deps import config_loader, data_service, redis, ws_manager
from .data_client import DataServiceRejected, DataServiceUnavailable
from .research_backend import NexusResearchBackend
from .routers import (
    broker_settings,
    admin,
    agents,
    audit_progress,
    backtest,
    config,
    ea,
    env,
    intelligence,
    fundamental,
    intermarket,
    market,
    ml,
    news,
    notifications,
    performance,
    positions,
    research_lab,
    regime,
    risk,
    strategies,
    system,
    trades,
)
from .websockets import (
    agents as ws_agents,
    broadcast as ws_broadcast,
    news as ws_news,
    orders as ws_orders,
    positions as ws_positions,
    risk as ws_risk,
    ticks as ws_ticks,
)

from shared import setup_logger as _setup_logger
_setup_logger("nexus-api")
logger = structlog.get_logger(__name__)

_broadcaster_tasks: list[asyncio.Task] = []  # type: ignore[type-arg]


async def _start_ws_broadcasters() -> None:
    from .websockets.ticks import tick_broadcaster
    from .websockets.agents import agent_broadcaster
    from .websockets.positions import position_broadcaster
    from .websockets.orders import order_broadcaster
    from .websockets.news import news_broadcaster
    from .websockets.risk import risk_broadcaster
    from .websockets.broadcast import broadcast_relay

    broadcasters = [
        tick_broadcaster(redis, ws_manager),
        agent_broadcaster(redis, ws_manager),
        position_broadcaster(redis, ws_manager),
        order_broadcaster(redis, ws_manager),
        news_broadcaster(redis, ws_manager),
        risk_broadcaster(redis, ws_manager),
        broadcast_relay(redis, ws_manager),
    ]
    for coro in broadcasters:
        _broadcaster_tasks.append(asyncio.create_task(coro))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _health_refresher
    app.state.ws_manager = ws_manager
    app.state.data_service_available = False
    await redis.connect()
    app.state.nexus_redis = redis.r  # raw async client: scope rate limiter (T-001)
    # Fail-safe startup invariant: autonomous opening is always OFF after a
    # gateway restart and must be explicitly re-enabled with the admin PIN.
    await redis.cache_set("system:auto_trade", False, ttl_sec=10 * 3600 * 24 * 3600)
    try:
        await _probe_dependencies()
    except Exception as exc:
        await logger.awarning(
            "api_gateway.data_service_unavailable",
            error=str(exc),
        )
    config_loader.load_all()
    await _start_ws_broadcasters()
    _health_refresher = asyncio.create_task(_health_refresh_loop())
    await logger.ainfo("api_gateway.started", port=SERVICE_PORTS["nexus-api"])
    yield
    _health_refresher.cancel()
    await asyncio.gather(_health_refresher, return_exceptions=True)
    if _health_probe_task is not None:
        _health_probe_task.cancel()
        await asyncio.gather(_health_probe_task, return_exceptions=True)
    for task in _broadcaster_tasks:
        task.cancel()
    await asyncio.gather(*_broadcaster_tasks, return_exceptions=True)
    _broadcaster_tasks.clear()
    await redis.disconnect()
    await logger.ainfo("api_gateway.stopped")


# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Nexus Trader API Gateway",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)
app.state.research_backend = NexusResearchBackend(data_service)

DASHBOARD_ORIGIN = os.getenv("DASHBOARD_ORIGIN", "http://localhost:3100")


def build_cors_origins(dashboard_origin: str) -> list[str]:
    """N3 closure (T-011): the dashboard is browsed from :3100 (next-server) or
    from :3000 (scripts/port3000_forward.py, a raw TCP forwarder onto :3100 —
    the browser Origin is then http://localhost:3000).

    In the primary flow CORS is never evaluated: next.config.js rewrites keep
    every API call same-origin, and same-origin fetches are exempt. The
    allowlist below only matters for the degraded case a stale browser bundle
    calling nexus-api (:9000) cross-origin — it must keep working (the
    next.config.js comment documents the same contract) instead of dying on a
    blocked preflight. DASHBOARD_ORIGIN stays first so external deployments can
    extend the list via env without touching code. Duplicates are collapsed.
    """
    extras = (
        "http://localhost:3100",
        "http://127.0.0.1:3100",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    )
    seen: dict[str, None] = {dashboard_origin.strip().rstrip("/"): None}
    for origin in extras:
        seen.setdefault(origin, None)
    return list(seen)


app.add_middleware(
    CORSMiddleware,
    allow_origins=build_cors_origins(DASHBOARD_ORIGIN),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── REST routers ─────────────────────────────────────────────────────────────

app.include_router(admin.router)
app.include_router(ea.router)
app.include_router(positions.router)
app.include_router(trades.router)
app.include_router(performance.router)
app.include_router(agents.router)
app.include_router(risk.router)
app.include_router(system.router)
app.include_router(news.router)
app.include_router(intermarket.router)
app.include_router(config.router)
app.include_router(market.router)
app.include_router(strategies.router)
app.include_router(ml.router)
app.include_router(regime.router)
app.include_router(intelligence.router)
app.include_router(env.router)
app.include_router(fundamental.router)
app.include_router(notifications.router)
app.include_router(backtest.router)
app.include_router(research_lab.router)
app.include_router(audit_progress.router)
app.include_router(broker_settings.router)

# ── WebSocket routers ────────────────────────────────────────────────────────

app.include_router(ws_ticks.router)
app.include_router(ws_agents.router)
app.include_router(ws_positions.router)
app.include_router(ws_orders.router)
app.include_router(ws_news.router)
app.include_router(ws_risk.router)
app.include_router(ws_broadcast.router)


# ── Health ───────────────────────────────────────────────────────────────────
#
# The dashboard polls this gateway every 15s with a hard 3s deadline, while the
# old handler paid for a Redis PING plus a fresh httpx.AsyncClient TCP handshake
# to nexus-data on every call (~0.7-5s here).  /health now serves a cached
# liveness snapshot: deep dependency checks run on a background timer and on
# demand, and a forced request-path probe is capped at _HEALTH_BUDGET_SEC.

_HEALTH_REFRESH_SEC = 5.0  # background deep-check cadence
_HEALTH_BUDGET_SEC = 0.2  # hard request-path budget for a forced probe
_HEALTH_STALE_SEC = 3 * _HEALTH_REFRESH_SEC

_health_state: dict[str, Any] = {
    "status": "healthy",
    "service": "nexus-api",
    "redis": "unknown",
    "duckdb": "unknown",
    "ready": True,
    "checked_at": 0.0,
}
_health_probe_task: asyncio.Task[None] | None = None  # type: ignore[type-arg]
_health_refresher: asyncio.Task[None] | None = None  # type: ignore[type-arg]


def _data_health_blocking() -> bool:
    """nexus-data hop off-loop: a fresh httpx.AsyncClient connect blocks the
    event loop ~1s on this host, which is what made /health (and every other
    request) stall for 0.7-5s whenever a deep check ran."""
    async def _run() -> bool:
        return bool(await data_service.health())

    return asyncio.run(_run())


async def _probe_dependencies() -> None:
    """One deep check: Redis PING + a single nexus-data /health hop."""
    redis_ok = await redis.health_check()
    try:
        data_ok = await asyncio.to_thread(_data_health_blocking)
    except Exception:
        data_ok = False
    app.state.data_service_available = data_ok
    healthy = redis_ok and data_ok
    _health_state.update(
        {
            "status": "healthy" if healthy else "degraded",
            "redis": "connected" if redis_ok else "disconnected",
            "duckdb": "connected" if data_ok else "unavailable",
            "ready": healthy,
            "checked_at": time.monotonic(),
        }
    )


def _probe_done(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("api_gateway.health_probe_failed", error=str(exc))


def _start_probe() -> asyncio.Task[None]:
    """Single-flight deep probe so concurrent health calls never stack hops."""
    global _health_probe_task
    if _health_probe_task is None or _health_probe_task.done():
        _health_probe_task = asyncio.create_task(_probe_dependencies())
        _health_probe_task.add_done_callback(_probe_done)
    return _health_probe_task


async def _health_refresh_loop() -> None:
    """Deep checks at most every _HEALTH_REFRESH_SEC, off the request path."""
    while True:
        await asyncio.sleep(_HEALTH_REFRESH_SEC)
        await _start_probe()


def _health_payload(now: float) -> dict[str, Any]:
    age_ms = int(max(0.0, now - float(_health_state["checked_at"])) * 1000)
    return {
        "status": _health_state["status"],
        "service": "nexus-api",
        "redis": _health_state["redis"],
        "duckdb": _health_state["duckdb"],
        "ready": _health_state["ready"],
        "age_ms": age_ms,
        "stale": age_ms > _HEALTH_STALE_SEC * 1000,
    }


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, Any]:
    """Liveness from cached state; forced probes never exceed ~200ms."""
    now = time.monotonic()
    cache_fresh = (now - float(_health_state["checked_at"])) < _HEALTH_REFRESH_SEC
    refresher_alive = _health_refresher is not None and not _health_refresher.done()
    if cache_fresh and refresher_alive:
        return _health_payload(now)
    probe = _start_probe()
    try:
        # shield(): a slow probe keeps running in the background while the
        # caller still gets the last good snapshot inside the hard budget.
        await asyncio.wait_for(asyncio.shield(probe), timeout=_HEALTH_BUDGET_SEC)
    except (asyncio.TimeoutError, TimeoutError):
        pass
    except Exception as exc:
        logger.warning("api_gateway.health_probe_failed", error=str(exc))
    return _health_payload(time.monotonic())


@app.get("/health/deep", tags=["health"])
async def health_deep() -> dict[str, Any]:
    """Uncached dependency check (may take up to ~2s); debugging/ops use."""
    await _start_probe()
    return _health_payload(time.monotonic())


# ── Global error handler ────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    await logger.aexception(
        "unhandled_error", path=request.url.path, error=str(exc),
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.exception_handler(DataServiceUnavailable)
async def data_service_unavailable_handler(request: Request, exc: DataServiceUnavailable) -> JSONResponse:
    # D10-a: keep the detail (validation text only, no secrets) so operators and
    # QA see WHY the write was rejected instead of a generic mask.
    return JSONResponse(status_code=503, content={"detail": str(exc) or "Data service unavailable"})


@app.exception_handler(DataServiceRejected)
async def data_service_rejected_handler(request: Request, exc: DataServiceRejected) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": "Data service rejected the request"})
