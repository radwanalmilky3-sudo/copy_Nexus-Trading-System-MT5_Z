"""
Nexus Agents — FastAPI application (Service 5, port 8004).

Exposes REST endpoints for agent status, evaluation triggers, and reasoning
retrieval.  A background task consumes Signal events from Redis Streams
and kicks off the LangGraph agent evaluation cycle.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel

from shared.constants import RedisStream, ServiceName, SUPPORTED_TIMEFRAMES
from shared.events import (
    AgentAnalysisEvent,
    AgentVerdictEvent,
    Event,
    SignalEvent,
)
from shared.redis_client import RedisClient

from .graph import build_graph
from .internal_auth import verify_internal_service_secret
from .research import StrategyResearcher
from .state import AgentState, validate_state
from shared.orchestrator import claim_active_signal, should_defer
from shared.security_headers import SecurityHeadersMiddleware
from .tools.market_tools import get_htf_context
from .tools.risk_tools import get_open_positions

from shared import setup_logger as _setup_logger
_setup_logger("nexus-agents")
logger = structlog.get_logger(__name__)

SERVICE_NAME = ServiceName.AGENTS
SERVICE_PORT = int(os.getenv("NEXUS_SERVICE_PORT", "9004"))
CONSUMER_GROUP = "nexus-agents-cg"
CONSUMER_NAME = f"agent-worker-{uuid.uuid4().hex[:6]}"

# Research scheduler config
RESEARCH_INTERVAL_SEC = int(os.getenv("NEXUS_RESEARCH_INTERVAL_SEC", str(60 * 30)))
RESEARCH_BATCH_SIZE = int(os.getenv("NEXUS_RESEARCH_BATCH", "2"))
RESEARCH_DISABLED = os.getenv("NEXUS_DISABLE_RESEARCH", "").lower() in ("1", "true", "yes")

redis_client = RedisClient()
_agent_graph = None
_consumer_task: asyncio.Task | None = None
_research_task: asyncio.Task | None = None
_heartbeat_task: asyncio.Task | None = None
_researcher: StrategyResearcher | None = None

_cycle_store: dict[str, dict[str, Any]] = {}
_agent_statuses: dict[str, dict[str, Any]] = {}
_cycle_active: bool = False


# ── LLM reachability probe ───────────────────────────────────────────────
# /health must reflect real LLM reachability (local Ollama, or Z.ai cloud when
# NEXUS_LLM_PROVIDER=zai) so the dashboard can show ONLINE/READY vs OFFLINE.
# The probe (via shared.llm_factory.llm_health) is memoised so status polls
# never hammer the backend, and it never blocks startup — it runs lazily on
# the first status request.
LLM_HEALTH_TTL_SEC = float(os.getenv("NEXUS_LLM_HEALTH_TTL_SEC", "20"))
LLM_HEALTH_TIMEOUT_SEC = float(os.getenv("NEXUS_LLM_HEALTH_TIMEOUT_SEC", "2"))
_llm_health_lock = asyncio.Lock()
_llm_health_cache: dict[str, Any] = {"ts": 0.0, "result": None}


async def _get_llm_health() -> dict[str, Any]:
    """Cached reachability check for the configured LLM provider.

    Uses shared.llm_factory.llm_health (provider-aware: local Ollama models
    probe, or a 1-token Z.ai completion when NEXUS_LLM_PROVIDER=zai).
    Result is cached for LLM_HEALTH_TTL_SEC (~20s). Never raises: an
    unreachable backend reports ONLINE=False.
    """
    cached = _llm_health_cache.get("result")
    if cached is not None and (time.monotonic() - float(_llm_health_cache["ts"])) < LLM_HEALTH_TTL_SEC:
        return cached  # type: ignore[return-value]
    async with _llm_health_lock:
        cached = _llm_health_cache.get("result")
        now = time.monotonic()
        if cached is not None and (now - float(_llm_health_cache["ts"])) < LLM_HEALTH_TTL_SEC:
            return cached  # type: ignore[return-value]
        from shared.llm_factory import llm_health, provider_model
        try:
            probe = await llm_health(timeout=max(LLM_HEALTH_TIMEOUT_SEC, 6.0))
        except Exception as exc:
            probe = {"status": "offline", "error": str(exc)}
        online = (
            str(probe.get("status", "offline")).lower() == "healthy"
            and bool(probe.get("model_available", False))
        )
        entry = {
            "status": "ONLINE" if online else "OFFLINE",
            "online": online,
            "url": str(probe.get("endpoint") or ""),
            "model": str(probe.get("required_model") or provider_model()),
            "model_available": bool(probe.get("model_available", False)),
            "latency_ms": probe.get("latency_ms"),
            "error": str(probe.get("error", "") or ""),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        _llm_health_cache["ts"] = time.monotonic()
        _llm_health_cache["result"] = entry
        return entry


# ── Response Models ───────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    service: str
    status: str
    timestamp: datetime
    redis: bool
    # Added fields (backward compatible): real Ollama reachability.
    # `status` keeps the legacy healthy/degraded values on HTTP 200 so the
    # monitor's whitelist keeps working; it is "OFFLINE" on the 503 path.
    state: str = "OFFLINE"          # ONLINE | DEGRADED | OFFLINE
    ready: bool = False
    llm: str = "OFFLINE"            # ONLINE | OFFLINE
    llm_online: bool = False
    llm_url: str = ""
    llm_model: str = ""
    llm_latency_ms: float | None = None
    llm_error: str = ""


class AgentStatusResponse(BaseModel):
    agents: dict[str, Any]
    active_cycles: int
    total_cycles_completed: int
    # Added fields (backward compatible): aggregate pipeline state + LLM.
    status: str = "OFFLINE"         # ONLINE | READY | OFFLINE
    ready: bool = False
    llm: str = "OFFLINE"            # ONLINE | OFFLINE
    llm_online: bool = False
    llm_url: str = ""
    llm_model: str = ""


class EvaluationResponse(BaseModel):
    cycle_id: str
    symbol: str
    status: str
    verdict: str | None = None
    conviction: int | None = None
    reasoning: str | None = None


class ReasoningResponse(BaseModel):
    cycle_id: str
    state: dict[str, Any]
    messages: list[dict[str, Any]]
    errors: list[str]


# ── Signal Consumer ───────────────────────────────────────────────────────────

CYCLE_TIMEOUT_SEC = int(os.getenv("NEXUS_CYCLE_TIMEOUT_SEC", "300"))
AGENT_SIGNAL_COOLDOWN_SEC = int(os.getenv("NEXUS_AGENT_SIGNAL_COOLDOWN_SEC", "120"))
_last_agent_cycle_ts: dict[str, float] = {}


def _resolve_operational_timeframe(
    signal_timeframe: str | None,
    env_timeframe: str,
    dynamic_timeframe: str | None = None,
    cached_timeframe: str | None = None,
) -> str:
    """Keep the signal's timeframe; use runtime settings only as fallback."""
    selected = (
        signal_timeframe
        if signal_timeframe is not None
        else cached_timeframe or dynamic_timeframe or env_timeframe
    )
    operational_tf = str(selected).strip().upper()
    if operational_tf not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"Unsupported signal timeframe: {operational_tf}")
    return operational_tf


async def _handle_signal_event(message_id: str, event: Event) -> bool:
    """Claim and run one signal event. True = safe to ACK.

    Claiming uses the stream idempotency marker so a redelivery of an already
    processed message is skipped. On failure the claim is released and False
    is returned so the delivery stays pending for reclaim/retry.
    """
    stream = RedisStream.SIGNAL_STREAM
    claimed = True
    if message_id:
        try:
            claimed = bool(await redis_client.mark_processed(
                stream, CONSUMER_GROUP, message_id,
            ))
        except Exception:
            await logger.awarning(
                "consumer.idem_claim_failed", message_id=message_id, exc_info=True,
            )
            claimed = True
    if not claimed:
        await logger.ainfo("consumer.duplicate_delivery_skipped", message_id=message_id)
        return True

    cycle_id: str | None = None
    try:
        signal_ev: SignalEvent = event  # type: ignore[assignment]

        # Throttle: one LangGraph cycle per symbol per cooldown window
        now = time.monotonic()
        sym_key = signal_ev.symbol.upper()
        last_ts = _last_agent_cycle_ts.get(sym_key, 0.0)
        if last_ts and (now - last_ts) < AGENT_SIGNAL_COOLDOWN_SEC:
            return True
        _last_agent_cycle_ts[sym_key] = now

        cycle_id = uuid.uuid4().hex[:12]
        # Additive risk fields from the signal — evaluators tolerate absence.
        _atr = getattr(signal_ev, "atr", None)
        _stop_atr = getattr(signal_ev, "stop_atr", None)
        _target_atr = getattr(signal_ev, "target_atr", None)
        _max_hold = getattr(signal_ev, "max_holding_hours", None)
        _group_id = getattr(signal_ev, "group_id", None)
        _reason = getattr(signal_ev, "reason", "") or ""
        await logger.ainfo(
            "consumer.signal_received",
            symbol=signal_ev.symbol,
            cycle_id=cycle_id,
            message_id=message_id,
        )
        await asyncio.wait_for(
            _run_evaluation_cycle(
                symbol=signal_ev.symbol,
                ml_signal={
                    "direction": str(signal_ev.direction),
                    "confidence": signal_ev.confidence,
                    "ml_scores": signal_ev.ml_scores,
                    "atr": _atr,
                    "stop_atr": _stop_atr,
                    "target_atr": _target_atr,
                    "max_holding_hours": _max_hold,
                    "group_id": _group_id,
                    "reason": _reason,
                },
                features=signal_ev.features,
                timeframe=signal_ev.timeframe or None,
                cycle_id=cycle_id,
                source_message_id=message_id,
            ),
            timeout=CYCLE_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        if cycle_id and cycle_id in _cycle_store:
            _cycle_store[cycle_id]["status"] = "error"
            _cycle_store[cycle_id]["error"] = f"Timeout after {CYCLE_TIMEOUT_SEC}s"
        await logger.awarning(
            "consumer.cycle_timeout",
            cycle_id=cycle_id,
            timeout_sec=CYCLE_TIMEOUT_SEC,
        )
        await _release_claim(message_id)
        return False
    except Exception:
        await logger.aexception("consumer.evaluation_error", message_id=message_id)
        await _release_claim(message_id)
        return False
    return True


async def _release_claim(message_id: str) -> None:
    """Drop the idempotency claim so a reclaim retry can re-process the entry."""
    if not message_id:
        return
    try:
        await redis_client.cache_delete(
            redis_client.idempotency_key(RedisStream.SIGNAL_STREAM, CONSUMER_GROUP, message_id),
            prefix=False,
        )
    except Exception:
        pass


async def _consume_signals() -> None:
    """Background loop: read Signal events and trigger agent evaluation.

    Uses explicit-ack deliveries: a delivery is ACKed only after the cycle
    completes (or is deliberately skipped). The message id is claimed with
    mark_processed before any work so a redelivered signal can never run a
    second full cycle; on failure the claim is released so a later reclaim
    retry can still process it.
    """
    await logger.ainfo("consumer.starting", group=CONSUMER_GROUP)
    await redis_client.connect()
    stream = RedisStream.SIGNAL_STREAM
    dlq_stream = str(RedisStream.SIGNAL_STREAM) + ":dlq"
    reclaim_every_sec = 30
    last_reclaim = time.monotonic()
    async for delivery in redis_client.subscribe_deliveries(
        stream,
        CONSUMER_GROUP,
        CONSUMER_NAME,
        dlq_stream=dlq_stream,
    ):
        # Periodically reclaim stale pending entries so failed deliveries retry.
        now_mono = time.monotonic()
        if now_mono - last_reclaim >= reclaim_every_sec:
            last_reclaim = now_mono
            try:
                reclaimed = await redis_client.reclaim_pending(
                    stream,
                    CONSUMER_GROUP,
                    CONSUMER_NAME,
                    min_idle_ms=CYCLE_TIMEOUT_SEC * 1000,
                    max_attempts=3,
                    dlq_stream=dlq_stream,
                )
            except Exception:
                await logger.awarning("consumer.reclaim_failed", exc_info=True)
                reclaimed = []
            for msg_id, fields in reclaimed or []:
                try:
                    from shared.events import parse_event
                    reclaimed_event = parse_event(dict(fields))
                except Exception:
                    await logger.awarning(
                        "consumer.reclaimed_parse_failed", message_id=msg_id,
                    )
                    continue
                if getattr(reclaimed_event, "event_type", "") != "signal":
                    await redis_client.r.xack(str(stream), CONSUMER_GROUP, msg_id)
                    continue
                if await _handle_signal_event(str(msg_id), reclaimed_event):
                    await redis_client.r.xack(str(stream), CONSUMER_GROUP, msg_id)

        event = delivery.event
        if event.event_type != "signal":
            await delivery.ack()
            continue

        message_id = str(getattr(delivery, "message_id", "") or "")
        if await _handle_signal_event(message_id, event):
            await delivery.ack()


async def _run_evaluation_cycle(
    symbol: str,
    ml_signal: dict | None = None,
    features: dict | None = None,
    timeframe: str | None = None,
    cycle_id: str | None = None,
    source_message_id: str = "",
) -> AgentState:
    """Execute the full LangGraph agent pipeline for one symbol."""
    global _agent_graph

    cycle_id = cycle_id or uuid.uuid4().hex[:12]

    # Idempotency for state writes: a redelivered stream message must not
    # publish a second cycle result for the same (cycle, message) pair.
    from .state import mark_state_write_once
    if not await mark_state_write_once(
        redis_client, cycle_id=cycle_id, source_message_id=source_message_id,
    ):
        await logger.awarning(
            "cycle.duplicate_state_write_skipped",
            symbol=symbol,
            cycle_id=cycle_id,
            source_message_id=source_message_id,
        )
        return validate_state({
            "symbol": symbol,
            "verdict": "NO_TRADE",
            "verdict_conviction": 0,
            "verdict_reasoning": "Duplicate state write for this cycle/message — skipped.",
            "cycle_id": cycle_id,
            "errors": [],
            "messages": [],
        })

    # ── Kill switch check ─────────────────────────────────────
    kill_switch = await redis_client.cache_get("system:kill_switch")
    if kill_switch:
        await logger.awarning(
            "cycle.kill_switch_active",
            symbol=symbol,
            cycle_id=cycle_id,
        )
        return {
            "symbol": symbol,
            "verdict": "NO_TRADE",
            "verdict_conviction": 0,
            "verdict_reasoning": "Kill switch is active — skipping evaluation.",
            "cycle_id": cycle_id,
            "errors": [],
            "messages": [],
        }

    session_state = await redis_client.cache_get("session:state")
    current_session = session_state.get("name", "UNKNOWN") if session_state else "UNKNOWN"

    try:
        symbol_positions = await get_open_positions(symbol)
    except Exception:
        symbol_positions = []

    # Fetch higher-timeframe context relative to operational timeframe.
    # Respect the current trading mode (M5 for scalping, M15 for swing).
    # Use env var as primary source — set by the trading mode switch API;
    # avoids cross-service import that breaks when services run in
    # separate processes.
    env_tf = os.getenv("NEXUS_OPERATIONAL_TF", "M5")
    dynamic_tf = None
    cached_tf = None
    if timeframe is None:
        try:
            dyn_raw = await redis_client.r.get("nexus:dynamic:tf")
            if dyn_raw:
                dynamic_tf = json.loads(dyn_raw).get("operational_tf")
        except Exception:
            pass
        try:
            from shared import runtime_settings as _rs
            cached_tf = _rs.get_cached_settings().get("operational_tf")
        except Exception:
            pass
    operational_tf = _resolve_operational_timeframe(
        timeframe, env_tf, dynamic_tf, cached_tf,
    )
    try:
        htf_ctx = await get_htf_context(symbol, operational_tf)
    except Exception:
        htf_ctx = {"bias": "NEUTRAL", "alignment_score": 0, "htf_details": {},
                    "operational_tf": operational_tf, "htf_list": []}

    # Orchestrator: defer if ML autonomous has priority lock
    defer, defer_reason = await should_defer(redis_client.r, symbol, "genai_agents")
    if defer:
        await logger.ainfo("cycle.deferred", symbol=symbol, reason=defer_reason, cycle_id=cycle_id)
        return validate_state({
            "symbol": symbol,
            "verdict": "NO_TRADE",
            "verdict_conviction": 0,
            "verdict_reasoning": defer_reason,
            "cycle_id": cycle_id,
            "errors": [],
            "messages": [],
        })

    # Fetch trade memory snapshot for agents to reference
    trade_memory_snapshot: dict = {}
    try:
        raw_str = await redis_client.r.get("nexus:trade_memory:metrics")
        if raw_str:
            trade_memory_snapshot = json.loads(raw_str)
    except Exception:
        pass

    initial_state: AgentState = validate_state({
        "symbol": symbol,
        "timeframe": operational_tf,
        "session": current_session,
        "ml_signal": ml_signal or {},
        "features": features or {},
        "htf_context": htf_ctx,
        "regime_analysis": {},
        "technical_analysis": "",
        "news_assessment": "",
        "intermarket_score": 0.0,
        "flow_score": 0.0,
        "bull_case": "",
        "bull_conviction": 0,
        "bear_case": "",
        "bear_conviction": 0,
        "verdict": "NO_TRADE",
        "verdict_conviction": 0,
        "verdict_reasoning": "",
        "risk_decision": "REJECT",
        "position_size": 0.0,
        "risk_reasoning": "",
        "open_positions": symbol_positions,
        "order": None,
        "messages": [],
        "cycle_id": cycle_id,
        "errors": [],
        "trade_memory": trade_memory_snapshot,
    })

    global _cycle_active

    HEALTH_TTL = 180  # survive long LLM calls without expiring

    _cycle_store[cycle_id] = {
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "state": initial_state,
    }

    _cycle_active = True
    now_iso = datetime.now(timezone.utc).isoformat()
    for aid in ("A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10", "A11", "A12"):
        await redis_client.cache_set(
            f"health:{aid}",
            {"status": "processing", "ts": now_iso, "cycle_id": cycle_id},
            ttl_sec=CYCLE_TIMEOUT_SEC,
        )

    try:
        final_state = validate_state(await _agent_graph.ainvoke(initial_state))

        if final_state.get("verdict") in ("BUY", "SELL") and final_state.get("risk_decision") == "APPROVE":
            await claim_active_signal(
                redis_client.r,
                symbol,
                "genai_agents",
                {
                    "direction": final_state.get("verdict"),
                    "confidence": final_state.get("verdict_conviction", 0) / 100.0,
                },
            )

        _cycle_store[cycle_id]["status"] = "completed"
        _cycle_store[cycle_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
        _cycle_store[cycle_id]["state"] = final_state

        await _publish_results(final_state, cycle_id)

        now_iso = datetime.now(timezone.utc).isoformat()
        for aid in ("A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10", "A11", "A12"):
            await redis_client.cache_set(
                f"health:{aid}",
                {"status": "online", "ts": now_iso, "cycle_id": cycle_id},
                ttl_sec=HEALTH_TTL,
            )

        await logger.ainfo(
            "cycle.completed",
            cycle_id=cycle_id,
            symbol=symbol,
            verdict=final_state.get("verdict"),
            conviction=final_state.get("verdict_conviction"),
        )
        return final_state

    except Exception as exc:
        _cycle_store[cycle_id]["status"] = "error"
        _cycle_store[cycle_id]["error"] = str(exc)
        now_iso = datetime.now(timezone.utc).isoformat()
        for aid in ("A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10", "A11", "A12"):
            await redis_client.cache_set(
                f"health:{aid}",
                {"status": "error", "ts": now_iso, "cycle_id": cycle_id},
                ttl_sec=HEALTH_TTL,
            )
        await logger.aexception("cycle.error", cycle_id=cycle_id)
        raise
    finally:
        _cycle_active = False


async def _publish_results(state: AgentState, cycle_id: str) -> None:
    """Publish agent analysis and verdict events to Redis Streams."""
    analysis_event = AgentAnalysisEvent(
        source=str(SERVICE_NAME),
        correlation_id=cycle_id,
        agent_id="A7",
        agent_name="Arbitrator",
        symbol=state["symbol"],
        analysis=state.get("verdict_reasoning", ""),
        confidence=state.get("verdict_conviction", 0) / 100.0,
        metadata={
            "technical_analysis": state.get("technical_analysis", "")[:200],
            "news_assessment": state.get("news_assessment", "")[:200],
            "intermarket_score": state.get("intermarket_score", 0.0),
            "flow_score": state.get("flow_score", 0.0),
        },
    )
    await redis_client.publish_event(RedisStream.AGENT_ANALYSIS, analysis_event)

    # Pull entry/SL/TP from the order computed by A9 (Trade Executor)
    # so the downstream risk service can evaluate real prices instead
    # of dropping the verdict due to entry==0 or sl==0.
    order = state.get("order") or {}
    verdict_data: dict[str, Any] = {}
    verdict_data["timeframe"] = state.get("timeframe", "")
    if order:
        verdict_data["entry"] = order.get("entry", 0)
        verdict_data["sl"] = order.get("sl", 0)
        verdict_data["tp1"] = order.get("tp1", 0)
        verdict_data["tp2"] = order.get("tp2", 0)
        verdict_data["tp3"] = order.get("tp3", 0)
        verdict_data["tp"] = order.get("tp1", 0)
        verdict_data["size"] = order.get("size", 0)
        verdict_data["order_type"] = order.get("order_type", "market")
        verdict_data["trailing_stop"] = order.get("trailing_stop", 0)
        verdict_data["bid"] = order.get("bid", 0)
        verdict_data["ask"] = order.get("ask", 0)
        verdict_data["comment"] = order.get("comment", "")
        verdict_data["strategy"] = order.get("strategy", "genai")

    verdict_event = AgentVerdictEvent(
        source=str(SERVICE_NAME),
        correlation_id=cycle_id,
        agent_id="A7",
        agent_name="Arbitrator",
        symbol=state["symbol"],
        verdict=state.get("verdict", "NO_TRADE"),
        conviction=state.get("verdict_conviction", 0) / 100.0,
        reasoning=state.get("verdict_reasoning", ""),
        data=verdict_data,
    )
    await redis_client.publish_event(RedisStream.AGENT_VERDICT, verdict_event)

    # Mark active signal so the autonomous ML pipeline defers for this symbol
    if state.get("verdict") in ("BUY", "SELL"):
        try:
            import json as _json
            await redis_client.r.set(
                f"nexus:active_signal:{state['symbol']}",
                _json.dumps({
                    "source": "genai_agents",
                    "direction": state.get("verdict"),
                    "conviction": state.get("verdict_conviction", 0),
                    "cycle_id": cycle_id,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }),
                ex=120,
            )
        except Exception:
            pass

    # Cache the latest decision so the dashboard can render a live panel
    # without having to subscribe to the Redis stream itself.
    if _researcher is not None:
        try:
            await _researcher.registry.publish_live_decision(
                state["symbol"],
                {
                    "cycle_id": cycle_id,
                    "verdict": state.get("verdict", "NO_TRADE"),
                    "conviction": state.get("verdict_conviction", 0),
                    "reasoning": state.get("verdict_reasoning", "")[:600],
                    "session": state.get("session", "UNKNOWN"),
                    "risk_decision": state.get("risk_decision", "REJECT"),
                    "risk_reasoning": state.get("risk_reasoning", "")[:400],
                    "position_size": state.get("position_size", 0.0),
                    "ml_signal": state.get("ml_signal", {}),
                    "regime_analysis": state.get("regime_analysis", {}),
                    "htf_bias": state.get("htf_context", {}).get("bias", "NEUTRAL"),
                    "htf_alignment": state.get("htf_context", {}).get("alignment_score", 0),
                    "entry": order.get("entry", 0),
                    "sl": order.get("sl", 0),
                    "tp1": order.get("tp1", 0),
                    "ts": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception:
            await logger.awarning("decision.cache_failed", symbol=state["symbol"])


# ── Strategy research scheduler ──────────────────────────────────────────────

async def _research_loop() -> None:
    """Periodically propose, evaluate and persist new strategies."""
    if _researcher is None:
        return
    try:
        await _researcher.ensure_seed()
    except Exception:
        await logger.aexception("research.seed_failed")

    if RESEARCH_DISABLED:
        await logger.ainfo("research.disabled_via_env")
        return

    cycle_count = 0
    while True:
        cycle_count += 1
        # Re-evaluating the whole registry is CPU-heavy (Python-loop backtests).
        # Do it only every 3rd cycle so the agents service stays responsive
        # (heartbeats / health) the rest of the time.
        if cycle_count % 3 == 1:
            try:
                n_refreshed = await _researcher.re_evaluate_all()
                await logger.ainfo("research.refreshed_existing", count=n_refreshed)
            except Exception:
                await logger.aexception("research.refresh_failed")

        # Default cadence; shortened automatically when we still lack a
        # tradeable strategy for the current regime (reduce dead time).
        next_sleep = RESEARCH_INTERVAL_SEC
        try:
            from shared import runtime_settings
            settings = await runtime_settings.get_settings(_researcher.redis)
            base_interval = int(settings.get("research_interval_sec", RESEARCH_INTERVAL_SEC))

            # Emergency research trigger: if trade memory shows a losing streak ≥ 5,
            # run research immediately so the LLM can design for the current failure mode.
            try:
                _tm_raw = await redis_client.r.get("nexus:trade_memory:metrics")
                if _tm_raw:
                    _tm = json.loads(_tm_raw)
                    _streak = _tm.get("recent_streak", {})
                    if _streak.get("type") == "loss" and _streak.get("count", 0) >= 5:
                        await logger.awarning(
                            "research.emergency_trigger",
                            streak=_streak["count"],
                            reason="losing streak >= 5 — running immediate research cycle",
                        )
            except Exception:
                pass

            summary = await _researcher.run_adaptive_cycle()
            searched = bool(summary.get("searched"))
            has_active_fit = summary.get("had_fitting_active") or len(summary.get("accepted", [])) > 0
            await logger.ainfo(
                "research.cycle_done",
                cycle=cycle_count,
                regime=summary.get("regime"),
                accepted=len(summary.get("accepted", [])),
                rejected=len(summary.get("rejected", [])),
                proposed=summary.get("proposed", 0),
                rounds=summary.get("rounds_used", 1),
                searched=searched,
                improved=len(summary.get("improved", [])),
            )
            # If we still have nothing tradeable for this regime, hunt sooner —
            # but keep a healthy floor so research never hogs the CPU continuously
            # (which would freeze heartbeats and make agents render OFFLINE).
            next_sleep = base_interval if has_active_fit else max(600, base_interval // 3)
        except asyncio.CancelledError:
            raise
        except Exception:
            await logger.aexception("research.cycle_failed")

        try:
            await asyncio.sleep(next_sleep)
        except asyncio.CancelledError:
            raise


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _agent_graph, _consumer_task, _research_task, _heartbeat_task, _researcher

    tasks: list[asyncio.Task] = []

    HEARTBEAT_TTL = 300
    HEARTBEAT_INTERVAL = 15
    _AGENT_IDS = ("A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10", "A11", "A12")

    async def _agent_heartbeat():
        while True:
            try:
                now_iso = datetime.now(timezone.utc).isoformat()
                for aid in _AGENT_IDS:
                    if _cycle_active:
                        existing = await redis_client.cache_get(f"health:{aid}")
                        if isinstance(existing, dict) and existing.get("status") == "processing":
                            continue
                    await redis_client.cache_set(
                        f"health:{aid}",
                        {
                            "status": "processing" if _cycle_active else "idle",
                            "ts": now_iso,
                            "service": "nexus-agents",
                        },
                        ttl_sec=HEARTBEAT_TTL,
                    )
            except Exception as exc:
                await logger.awarning("heartbeat.failed", error=str(exc))
            await asyncio.sleep(HEARTBEAT_INTERVAL)

    # Shadow trade resolver (Fase 4) — every 5 min, resolve any hypothetical
    # trades whose 60-minute window has elapsed so gate tuning (conflict-lock,
    # ergodic circuit breaker, institutional thresholds) can be validated
    # against what rejected signals would actually have done.
    async def _shadow_trade_resolver_loop():
        from .shadow_trades import resolve_due_shadow_trades
        from .tools.market_tools import get_price as _get_price_dict

        async def _mid_price(symbol: str) -> float | None:
            try:
                tick = await _get_price_dict(symbol)
                bid, ask = tick.get("bid", 0), tick.get("ask", 0)
                if bid and ask:
                    return (bid + ask) / 2
                return bid or ask or None
            except Exception:
                return None

        await asyncio.sleep(90)
        while True:
            try:
                n = await resolve_due_shadow_trades(redis_client, _mid_price)
                if n:
                    await logger.ainfo("shadow_trades.resolved", count=n)
            except Exception:
                await logger.awarning("shadow_trades.resolve_loop_error", exc_info=True)
            await asyncio.sleep(300)

    try:
        await redis_client.connect()
        _agent_graph = build_graph(redis_client)
        _researcher = StrategyResearcher(redis_client)

        _consumer_task = asyncio.create_task(_consume_signals())
        tasks.append(_consumer_task)
        _research_task = asyncio.create_task(_research_loop())
        tasks.append(_research_task)

        # Daily brief service (Fase 4)
        from .daily_brief import daily_brief_loop as _daily_brief_loop
        _symbols = os.getenv("STREAM_SYMBOLS", "XAUUSD").split(",")
        _daily_brief_task = asyncio.create_task(_daily_brief_loop(redis_client.r, _symbols))
        tasks.append(_daily_brief_task)

        _heartbeat_task = asyncio.create_task(_agent_heartbeat())
        tasks.append(_heartbeat_task)
        _shadow_task = asyncio.create_task(_shadow_trade_resolver_loop())
        tasks.append(_shadow_task)

        await logger.ainfo("service.started", service=str(SERVICE_NAME), port=SERVICE_PORT)

        yield
    finally:
        try:
            for task in tasks:
                if not task.done():
                    task.cancel()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for task, result in zip(tasks, results):
                if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                    await logger.awarning("service.task_failed", task=task.get_name(), error=str(result))
        finally:
            await redis_client.disconnect()
        await logger.ainfo("service.stopped", service=str(SERVICE_NAME))


# ── FastAPI App ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Nexus Agents — Multi-Agent Layer",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(SecurityHeadersMiddleware)


@app.get("/health", response_model=HealthResponse)
async def health(response: Response):
    redis_ok = await redis_client.health_check()
    llm = await _get_llm_health()
    llm_online = bool(llm.get("online"))
    if not llm_online:
        # Ollama unreachable → report OFFLINE (HTTP 503 so the dashboard
        # health probe and nexus-api pipeline both surface it as offline).
        response.status_code = 503
        status_str, state_str, ready = "OFFLINE", "OFFLINE", False
    elif redis_ok:
        status_str, state_str, ready = "healthy", "ONLINE", True
    else:
        status_str, state_str, ready = "degraded", "DEGRADED", False
    return HealthResponse(
        service=str(SERVICE_NAME),
        status=status_str,
        timestamp=datetime.now(timezone.utc),
        redis=redis_ok,
        state=state_str,
        ready=ready,
        llm=str(llm.get("status", "OFFLINE")),
        llm_online=llm_online,
        llm_url=str(llm.get("url", "")),
        llm_model=str(llm.get("model", "")),
        llm_latency_ms=llm.get("latency_ms"),
        llm_error=str(llm.get("error", "")),
    )


@app.get("/api/agents/brain/budget")
async def get_brain_budget(
    x_nexus_internal_secret: str | None = Header(default=None),
):
    verify_internal_service_secret(x_nexus_internal_secret)
    """Local-AI token/resource budget status."""
    from .brain_budget import budget_status
    try:
        return await budget_status(redis_client.r)
    except Exception as e:
        return {"error": str(e), "allowed": False, "provider": "local"}


@app.get("/api/agents/shadow-trades/stats")
async def get_shadow_trade_stats(
    limit: int = 500,
    x_nexus_internal_secret: str | None = Header(default=None),
):
    verify_internal_service_secret(x_nexus_internal_secret)
    """What rejected/downgraded signals would have done — validates whether
    the conflict-lock, ergodic circuit breaker and institutional thresholds
    are filtering noise or costing real edge."""
    from .shadow_trades import get_shadow_stats
    try:
        return await get_shadow_stats(redis_client, limit=limit)
    except Exception as e:
        return {"error": str(e), "total": 0}


@app.get("/api/agents/status", response_model=AgentStatusResponse)
async def get_agent_status(
    x_nexus_internal_secret: str | None = Header(default=None),
):
    verify_internal_service_secret(x_nexus_internal_secret)
    active = sum(1 for c in _cycle_store.values() if c["status"] == "running")
    completed = sum(1 for c in _cycle_store.values() if c["status"] == "completed")
    llm = await _get_llm_health()
    llm_online = bool(llm.get("online"))
    if not llm_online:
        status_str = "OFFLINE"
    elif active > 0:
        status_str = "ONLINE"
    else:
        status_str = "READY"
    return AgentStatusResponse(
        agents=_agent_statuses,
        active_cycles=active,
        total_cycles_completed=completed,
        status=status_str,
        ready=llm_online,
        llm=str(llm.get("status", "OFFLINE")),
        llm_online=llm_online,
        llm_url=str(llm.get("url", "")),
        llm_model=str(llm.get("model", "")),
    )


@app.post("/api/agents/evaluate/{symbol}", response_model=EvaluationResponse)
async def evaluate_symbol(
    symbol: str,
    x_nexus_internal_secret: str | None = Header(default=None),
):
    verify_internal_service_secret(x_nexus_internal_secret)
    cycle_id = uuid.uuid4().hex[:12]
    try:
        final_state = await _run_evaluation_cycle(
            symbol=symbol,
            cycle_id=cycle_id,
        )
        return EvaluationResponse(
            cycle_id=cycle_id,
            symbol=symbol,
            status="completed",
            verdict=final_state.get("verdict"),
            conviction=final_state.get("verdict_conviction"),
            reasoning=final_state.get("verdict_reasoning"),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {exc}")


# ── Strategy Lab endpoints ──────────────────────────────────────────────────


class StrategyResponse(BaseModel):
    id: str
    name: str
    short_name: str
    type: str
    description: str
    status: str
    pairs: list[str]
    timeframes: list[str]
    agents: list[str]
    entry_logic: str
    exit_logic: str
    color: str
    win_rate: float
    profit_factor: float
    sharpe: float
    max_dd_pct: float
    total_trades: int
    avg_rr: float
    net_pnl_pct: float
    recent_results: list[bool]
    promotion_reasons: list[str]
    proposed_by: str
    created_at: float
    updated_at: float
    mql5_signal_code: str = ""


def _serialise_strategy(rec: Any) -> dict[str, Any]:
    if hasattr(rec, "to_dict"):
        return rec.to_dict()
    return dict(rec)


@app.get("/api/strategies")
async def list_strategies(
    status: str | None = None,
    x_nexus_internal_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_internal_service_secret(x_nexus_internal_secret)
    if _researcher is None:
        raise HTTPException(503, "Research subsystem not initialised")
    records = await _researcher.registry.list(status=status)
    items = [_serialise_strategy(r) for r in records]
    return {
        "items": items,
        "count": len(items),
        "rules": _researcher.registry.rules.__dict__,
    }


@app.get("/api/strategies/{strategy_id}")
async def get_strategy(
    strategy_id: str,
    x_nexus_internal_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_internal_service_secret(x_nexus_internal_secret)
    if _researcher is None:
        raise HTTPException(503, "Research subsystem not initialised")
    rec = await _researcher.registry.get(strategy_id)
    if rec is None:
        raise HTTPException(404, "Strategy not found")
    return _serialise_strategy(rec)


class ResearchTriggerRequest(BaseModel):
    n: int = 2


@app.post("/api/strategies/research")
async def trigger_research(
    body: ResearchTriggerRequest | None = None,
    x_nexus_internal_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_internal_service_secret(x_nexus_internal_secret)
    if _researcher is None:
        raise HTTPException(503, "Research subsystem not initialised")
    n = max(1, min(5, (body.n if body else 2)))
    return await _researcher.run_cycle(n=n)


@app.post("/api/strategies/{strategy_id}/reevaluate")
async def reevaluate_strategy(
    strategy_id: str,
    x_nexus_internal_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_internal_service_secret(x_nexus_internal_secret)
    if _researcher is None:
        raise HTTPException(503, "Research subsystem not initialised")
    rec = await _researcher.registry.get(strategy_id)
    if rec is None:
        raise HTTPException(404, "Strategy not found")
    saved = await _researcher._evaluate_and_save(rec)
    if saved is None:
        raise HTTPException(500, "Re-evaluation failed")
    return _serialise_strategy(saved)


class StatusUpdateRequest(BaseModel):
    status: str


@app.put("/api/strategies/{strategy_id}/status")
async def update_strategy_status(
    strategy_id: str, body: StatusUpdateRequest,
    x_nexus_internal_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_internal_service_secret(x_nexus_internal_secret)
    if _researcher is None:
        raise HTTPException(503, "Research subsystem not initialised")
    rec = await _researcher.registry.set_status(strategy_id, body.status)
    if rec is None:
        raise HTTPException(404, "Strategy not found")
    return _serialise_strategy(rec)


@app.get("/api/strategies/research/log")
async def research_log(
    limit: int = 25,
    x_nexus_internal_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_internal_service_secret(x_nexus_internal_secret)
    if _researcher is None:
        raise HTTPException(503, "Research subsystem not initialised")
    runs = await _researcher.registry.get_research_log(limit=limit)
    return {"runs": runs, "count": len(runs)}


@app.get("/api/agents/decision/{symbol}")
async def latest_decision(
    symbol: str,
    x_nexus_internal_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_internal_service_secret(x_nexus_internal_secret)
    if _researcher is None:
        raise HTTPException(503, "Research subsystem not initialised")
    payload = await _researcher.registry.get_live_decision(symbol.upper())
    if payload is None:
        raise HTTPException(404, "No decision yet for this symbol")
    return payload


@app.post("/api/agents/brief/generate")
async def trigger_brief_generation(
    symbol: str = "XAUUSD",
    x_nexus_internal_secret: str | None = Header(default=None),
):
    """Manually trigger a daily brief generation (bypasses schedule)."""
    verify_internal_service_secret(x_nexus_internal_secret)
    try:
        from .daily_brief import generate_brief
        result = await generate_brief(redis_client.r, symbol=symbol)
        return {"status": "ok", "symbol": symbol, "brief": result}
    except Exception as exc:
        logger.exception("brief/generate failed")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/agents/reasoning/{cycle_id}", response_model=ReasoningResponse)
async def get_reasoning(
    cycle_id: str,
    x_nexus_internal_secret: str | None = Header(default=None),
):
    verify_internal_service_secret(x_nexus_internal_secret)
    cycle = _cycle_store.get(cycle_id)
    if not cycle:
        raise HTTPException(status_code=404, detail=f"Cycle {cycle_id} not found")
    state = cycle.get("state", {})
    return ReasoningResponse(
        cycle_id=cycle_id,
        state={
            k: v for k, v in state.items()
            if k not in ("messages",)
        },
        messages=[
            m if isinstance(m, dict) else {"content": str(m)}
            for m in state.get("messages", [])
        ],
        errors=state.get("errors", []),
    )
