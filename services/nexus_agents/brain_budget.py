"""Local-AI resource budget for nexus-agents.

No cloud-price accounting is used. The budget is expressed in daily tokens and
is intended to protect the local Ollama/OpenAI-compatible runtime from runaway
agent loops. Local model health/availability is checked separately by
``shared.llm_factory.local_health``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_REDIS_KEY = "nexus:brain:usage"
_REDIS_TTL = 172_800

# ── Runtime guards (in-process, single asyncio event loop) ───────────────────
# These protect the local LLM runtime from retry storms and runaway per-cycle
# agent loops. They are deliberately process-local (no Redis) so they cannot
# add latency to the hot path, and they are pruned to stay bounded.

_MAX_TRACKED_CYCLES = 32
_MAX_TRACKED_CALLS_PER_CYCLE_CAP = 64


def max_attempts() -> int:
    """Upper bound on sequential LLM attempts for a single logical call."""
    try:
        raw = int(os.getenv("NEXUS_LLM_MAX_ATTEMPTS", "2"))
    except ValueError:
        raw = 2
    return min(4, max(1, raw))


def backoff_delay(attempt: int) -> float:
    """Bounded, jittered backoff for sequential retry attempts (seconds).

    ``attempt`` is 1-based (1 = first retry). Caps at ~8s so a failing local
    model cannot stall a trading cycle for minutes.
    """
    base = min(2 ** max(1, attempt), 8.0)
    jitter = random.uniform(0.0, 0.5)
    return max(0.1, min(base + jitter, 10.0))


# ── D6: provider-quota spacing (owner decision 2026-11-05) ──────────────────

_RATE_LIMIT_MARKERS = ("429", "rate limit", "ratelimit", "too many requests", "quota")


def min_interval_sec() -> float:
    """Minimum spacing between consecutive LLM call starts, process-wide.

    ``NEXUS_LLM_MIN_INTERVAL_SEC`` (default 1.0s). This is the D6 fix for the
    429→NO_TRADE cascade: the parallel agent fan-out used to fire all its
    provider calls at once; pacing call starts prevents the burst that trips
    the cloud provider's rate/quota limit in the first place.
    """
    try:
        raw = float(os.getenv("NEXUS_LLM_MIN_INTERVAL_SEC", "1.0"))
    except ValueError:
        raw = 1.0
    return max(0.0, min(raw, 60.0))


def is_rate_limit_error(error: str) -> bool:
    """True when an exception looks like a provider rate/quota rejection."""
    message = str(error or "").lower()
    return any(marker in message for marker in _RATE_LIMIT_MARKERS)


def rate_limit_backoff(attempt: int, *, error: str = "") -> float:
    """Backoff for a retry, longer and calmer when the provider said 429.

    Plain failures keep the standard ``backoff_delay`` cadence; rate-limit
    rejections wait 4× longer per attempt (capped ~30s) with wider jitter so
    the provider's window actually has time to recover instead of burning
    both retry attempts into the same closed window.
    """
    if is_rate_limit_error(error):
        base = min(2 ** max(1, attempt) * 4.0, 30.0)
        return max(1.0, min(base + random.uniform(0.0, 2.0), 32.0))
    return backoff_delay(attempt)


_last_call_ts: float = 0.0
_pace_lock = asyncio.Lock()


async def pace_llm_call() -> float:
    """Space out LLM call starts process-wide; returns the seconds slept.

    Holding the lock across the sleep serializes call *starts* at least
    ``min_interval_sec()`` apart — a pacer, not a limiter (calls are never
    dropped, only slowed). With 4 parallel agents and the default 1s
    interval the 4th call starts ~3s late, which is cheap insurance against
    a 429 storm that would otherwise fail the whole cycle closed.
    """
    global _last_call_ts
    interval = min_interval_sec()
    if interval <= 0.0:
        return 0.0
    async with _pace_lock:
        now = time.monotonic()
        wait = _last_call_ts + interval - now
        if wait > 0:
            await asyncio.sleep(wait)
            now = time.monotonic()
        _last_call_ts = now
        return max(0.0, wait)


def max_calls_per_cycle() -> int:
    try:
        raw = int(os.getenv("NEXUS_MAX_LLM_CALLS_PER_CYCLE", "16"))
    except ValueError:
        raw = 16
    return min(_MAX_TRACKED_CALLS_PER_CYCLE_CAP, max(1, raw))


def _circuit_failure_threshold() -> int:
    try:
        raw = int(os.getenv("NEXUS_LLM_CIRCUIT_FAILURES", "3"))
    except ValueError:
        raw = 3
    return max(1, min(10, raw))


def _circuit_open_sec() -> float:
    try:
        raw = float(os.getenv("NEXUS_LLM_CIRCUIT_OPEN_SEC", "120"))
    except ValueError:
        raw = 120.0
    return max(5.0, min(900.0, raw))


_cycle_calls: dict[str, int] = {}
_circuit: dict[str, Any] = {
    "failures": 0,
    "open_until": 0.0,
    "last_error": "",
}


def _prune_cycle_calls(current: str | None) -> None:
    if len(_cycle_calls) <= _MAX_TRACKED_CYCLES:
        return
    for key in [k for k in _cycle_calls if k != current][: len(_cycle_calls) - _MAX_TRACKED_CYCLES]:
        _cycle_calls.pop(key, None)


async def reserve_llm_call(cycle_id: str) -> bool:
    """Consume one per-cycle LLM call slot. False means the cap is exhausted."""
    key = cycle_id or "_default"
    used = _cycle_calls.get(key, 0)
    if used >= max_calls_per_cycle():
        logger.warning(
            "brain_budget.cycle_cap_exhausted cycle=%s used=%d cap=%d",
            key, used, max_calls_per_cycle(),
        )
        return False
    _cycle_calls[key] = used + 1
    _prune_cycle_calls(key)
    return True


def provider_circuit_open() -> bool:
    """True while the local provider circuit breaker is open (cooling down)."""
    return time.monotonic() < float(_circuit.get("open_until", 0.0))


def note_provider_failure(error: str = "") -> None:
    """Record a failed provider call; open the circuit at the failure threshold."""
    _circuit["failures"] = int(_circuit.get("failures", 0)) + 1
    _circuit["last_error"] = str(error)[:300]
    if _circuit["failures"] >= _circuit_failure_threshold():
        _circuit["open_until"] = time.monotonic() + _circuit_open_sec()
        logger.warning(
            "brain_budget.circuit_open failures=%s open_sec=%.0f last_error=%s",
            _circuit["failures"], _circuit_open_sec(), _circuit.get("last_error", ""),
        )


def note_provider_success() -> None:
    """Reset the circuit breaker after a successful provider call."""
    _circuit["failures"] = 0
    _circuit["open_until"] = 0.0
    _circuit["last_error"] = ""


def reset_runtime_state() -> None:
    """Clear all in-process runtime guard state (tests / manual recovery)."""
    global _last_call_ts
    _cycle_calls.clear()
    _circuit["failures"] = 0
    _circuit["open_until"] = 0.0
    _circuit["last_error"] = ""
    _last_call_ts = 0.0


def daily_token_budget() -> int:
    return max(10_000, int(os.getenv("NEXUS_LOCAL_DAILY_TOKEN_BUDGET", "2000000")))


def warn_pct() -> float:
    return min(0.99, max(0.10, float(os.getenv("NEXUS_BRAIN_WARN_PCT", "0.80"))))


async def get_usage(redis_client: Any) -> dict[str, Any]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        raw = await redis_client.get(_REDIS_KEY)
        if raw:
            data = json.loads(raw)
            if data.get("date") == today:
                return data
    except Exception:
        logger.debug("brain_budget.read_failed", exc_info=True)
    return {"date": today, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


async def record_usage(redis_client: Any, input_tokens: int, output_tokens: int) -> int:
    """Add local token counts and return the new daily total."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        usage = await get_usage(redis_client)
        usage["input_tokens"] = int(usage.get("input_tokens", 0)) + max(0, int(input_tokens))
        usage["output_tokens"] = int(usage.get("output_tokens", 0)) + max(0, int(output_tokens))
        usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
        usage["date"] = today
        await redis_client.set(_REDIS_KEY, json.dumps(usage), ex=_REDIS_TTL)
        return int(usage["total_tokens"])
    except Exception:
        logger.debug("brain_budget.record_failed", exc_info=True)
        return 0


async def budget_status(redis_client: Any) -> dict[str, Any]:
    limit = daily_token_budget()
    usage = await get_usage(redis_client)
    used = int(usage.get("total_tokens", int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))))
    pct = used / limit if limit > 0 else 0.0
    return {
        "provider": "local",
        "allowed": pct < 1.0,
        "throttled": warn_pct() <= pct < 1.0,
        "remaining_tokens": max(0, limit - used),
        "pct_used": round(pct, 4),
        "total_tokens": used,
        "daily_limit_tokens": limit,
        "input_tokens": int(usage.get("input_tokens", 0)),
        "output_tokens": int(usage.get("output_tokens", 0)),
        "max_parallel_generations": max(1, int(os.getenv("NEXUS_LOCAL_MAX_PARALLEL", "2"))),
        "request_timeout_sec": max(5, int(os.getenv("NEXUS_LOCAL_LLM_TIMEOUT_SEC", "120"))),
    }


async def adjusted_max_tokens(redis_client: Any, requested: int) -> int:
    status = await budget_status(redis_client)
    if not status["allowed"]:
        return 0
    if status["throttled"]:
        reduced = max(200, requested // 2)
        logger.info("brain_budget.throttled pct=%.0f%% tokens %d→%d", status["pct_used"] * 100, requested, reduced)
        return reduced
    return requested
