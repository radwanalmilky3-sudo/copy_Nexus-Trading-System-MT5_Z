"""MT5 native economic calendar bridge — parse, normalize, merge.

The MetaTrader5 Python package exposes no calendar API, so the economic
calendar is fetched inside the terminal by NexusBridgeEA (MQL5
CalendarValueHistory / CalendarEventById / CalendarCountryById) and POSTed to
nexus-api /api/ea/calendar, which forwards here.

Contract notes (do not break — the EA depends on them):
  * MQL5 calendar times are in TRADE SERVER time.  Each batch carries
    ``server_offset_sec`` (TimeTradeServer() - TimeGMT()); UTC event time =
    event_time - server_offset_sec.
  * Unset MqlCalendarValue numbers arrive as ``null`` (the EA maps
    EMPTY_VALUE/±DBL_MAX to null) — absence is never coerced to zero.
  * Importance maps 0..3 → none/low/medium/high; "none" degrades to "low"
    downstream because CalendarEvent.impact has no "none" tier.
  * Dedup/upsert: fund_events/macro_releases key on event_id built from
    (source, event_name, currency, timestamp) — re-releases with a fresh
    Actual overwrite the canonical row while data_vintages records history.
"""
from __future__ import annotations

import structlog
from datetime import datetime, timedelta, timezone
from typing import Any

from shared.models import CalendarEvent

log = structlog.get_logger("nexus_news.mt5_calendar")

SOURCE_ID = "calendar_mt5"
IMPORTANCE_MAP = {0: "low", 1: "low", 2: "medium", 3: "high"}
# MQL5 EMPTY_VALUE is DBL_MAX; anything at/above this magnitude is "unset".
_EMPTY_SENTINEL = 1e300
# Two events are the same release when currency, normalized name and the
# timestamp agree within this window (broker feeds differ by seconds).
_MERGE_WINDOW_SEC = 120


def _clean_number(value: Any) -> str | None:
    """Normalize an MQL5 numeric field to a compact string, or None."""
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        text = str(value).strip()
        return text or None
    if abs(num) >= _EMPTY_SENTINEL:
        return None
    if num == int(num) and abs(num) < 1e15:
        return str(int(num))
    return repr(num)


def _normalize_name(name: Any) -> str:
    return " ".join(str(name or "").lower().split())


def parse_mt5_calendar_payload(payload: dict[str, Any]) -> list[CalendarEvent]:
    """Validate + convert one EA calendar batch into CalendarEvent objects.

    Raises ValueError on structurally invalid payloads (auth is already
    enforced upstream; this guards the ingestion contract).
    """
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    events_raw = payload.get("events")
    if not isinstance(events_raw, list):
        raise ValueError("payload.events must be an array")
    try:
        offset = int(payload.get("server_offset_sec") or 0)
    except (TypeError, ValueError):
        raise ValueError("server_offset_sec must be an integer") from None
    if not -14 * 3600 <= offset <= 14 * 3600:
        raise ValueError(f"server_offset_sec out of range: {offset}")

    parsed: list[CalendarEvent] = []
    for idx, raw in enumerate(events_raw):
        if not isinstance(raw, dict):
            raise ValueError(f"events[{idx}] must be an object")
        name = str(raw.get("name") or "").strip()
        currency = str(raw.get("currency") or "").strip().upper()
        event_time = raw.get("time")
        if not name or not currency or event_time is None:
            # Incomplete event: skip it honestly rather than fabricating fields.
            log.warning("mt5_calendar.incomplete_event_skipped",
                        index=idx, has_name=bool(name), has_currency=bool(currency))
            continue
        try:
            server_ts = datetime.fromtimestamp(int(event_time), tz=timezone.utc)
        except (TypeError, ValueError, OSError, OverflowError):
            raise ValueError(f"events[{idx}].time is not a unix timestamp") from None
        utc_ts = server_ts - timedelta(seconds=offset)
        importance = raw.get("importance")
        try:
            impact = IMPORTANCE_MAP.get(int(importance or 0), "low")
        except (TypeError, ValueError):
            impact = "low"
        parsed.append(CalendarEvent(
            event_name=name,
            currency=currency,
            impact=impact,
            forecast=_clean_number(raw.get("forecast")),
            previous=_clean_number(raw.get("previous")),
            actual=_clean_number(raw.get("actual")),
            timestamp=utc_ts,
            source=SOURCE_ID,
        ))
    return parsed


def merge_mt5_primary(
    mt5_events: list[CalendarEvent],
    web_events: list[CalendarEvent],
) -> list[CalendarEvent]:
    """Merge MT5 (primary) with web-fallback events.

    MT5 wins for the same release (currency + normalized name + time within
    the merge window); web events without an MT5 counterpart are kept so an
    MT5 outage never empties the calendar (absence of MT5 data is NOT
    evidence of absence of events).
    """
    merged: list[CalendarEvent] = list(mt5_events)
    for web in web_events:
        duplicate = any(
            w.currency == web.currency
            and _normalize_name(w.event_name) == _normalize_name(web.event_name)
            and abs((w.timestamp - web.timestamp).total_seconds()) <= _MERGE_WINDOW_SEC
            for w in mt5_events
        )
        if not duplicate:
            merged.append(web)
    return sorted(merged, key=lambda e: e.timestamp)


def sync_cursor_key() -> str:
    """Redis key holding the last successful MT5 sync boundary (unix seconds)."""
    return "nexus:calendar:mt5:last_sync"


def resume_window(now: datetime, stored_last_sync: float | None,
                  lookback_sec: int) -> tuple[datetime, datetime]:
    """Compute the fetch window for one sync cycle.

    With no stored cursor (first sync / Redis lost) fall back to the full
    lookback window; otherwise resume from the last successful boundary minus
    a small overlap so an event released mid-sync is never lost.
    """
    end = now + timedelta(days=7)
    if stored_last_sync is None:
        start = now - timedelta(seconds=lookback_sec)
    else:
        start = datetime.fromtimestamp(stored_last_sync, tz=timezone.utc) - timedelta(minutes=10)
        if (now - start).total_seconds() > lookback_sec:
            start = now - timedelta(seconds=lookback_sec)
    return start, end
