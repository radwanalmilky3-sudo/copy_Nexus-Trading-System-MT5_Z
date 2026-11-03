"""Deprecated compatibility facade for the canonical fundamental blackout state.

The old sentinel used a second, independent calendar/news parser and could fail
open when either contract broke.  Safety state now has one owner:
``FundamentalRuntime`` + ``BlackoutEngine``.  This module only mirrors the
canonical Redis state for legacy callers; it never decides whether trading is
safe.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

CANONICAL_BLACKOUT_KEY = "nexus:fundamental:blackout"
LEGACY_BLACKOUT_KEY = "nexus:news:sentinel:blackout"
LEGACY_ALERTS_KEY = "nexus:news:sentinel:alerts"
LEGACY_LAST_SCAN_KEY = "nexus:news:sentinel:last_scan"


def _decode(value: Any) -> Any:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


async def _canonical_blackout(redis: Any) -> dict[str, Any]:
    try:
        raw = await redis.get(CANONICAL_BLACKOUT_KEY)
        state = _decode(raw)
        if isinstance(state, dict):
            return state
    except Exception as exc:
        logger.warning("canonical blackout unavailable: %s", exc)
    return {
        "state": "degraded",
        "active": True,
        "reason_code": "CALENDAR_STATE_UNAVAILABLE",
        "reason_ar": "حالة التقويم الاقتصادي غير متاحة؛ تم الحظر احترازيًا.",
        "events": [],
    }


async def scan_once(redis: Any, fetcher: Any = None, calendar: Any = None) -> dict[str, Any]:
    """Return the canonical blackout state and mirror it to the legacy key.

    ``fetcher`` and ``calendar`` are accepted only for backward compatibility
    and deliberately ignored.  No independent safety calculation is permitted.
    """
    blackout = await _canonical_blackout(redis)
    try:
        payload = json.dumps(blackout, ensure_ascii=False, default=str)
        await redis.set(LEGACY_BLACKOUT_KEY, payload, ex=3600)
    except Exception as exc:
        logger.debug("legacy sentinel mirror failed: %s", exc)
    return {"alerts_added": 0, "blackout": blackout}


async def sentinel_loop(redis: Any, fetcher: Any = None, calendar: Any = None, poll_sec: int = 60) -> None:
    """Legacy mirror loop; it never determines blackout state."""
    logger.warning("legacy news sentinel is deprecated; canonical blackout is authoritative")
    while True:
        try:
            await scan_once(redis, fetcher, calendar)
            await asyncio.sleep(max(10, int(poll_sec)))
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("legacy sentinel mirror failed")
            await asyncio.sleep(60)
