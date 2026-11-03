"""
Nexus Trader — Redis Stream event schemas.

Every message published to a Redis Stream is wrapped in one of these
typed event classes so consumers can deserialise safely.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import StrEnum, unique
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .constants import RedisStream, RiskDecision, SessionName, Verdict


_STREAM_LIST_PREFIX = "__nexus_list_v1__:"
_STREAM_STRING_PREFIX = "__nexus_string_v1__:"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Event Base ───────────────────────────────────────────────────────────────

class Event(BaseModel):
    """Base envelope for every Redis-Stream message."""

    event_type: str
    source: str = ""
    correlation_id: str = ""
    timestamp: datetime = Field(default_factory=_utcnow)
    data: dict[str, Any] = Field(default_factory=dict)

    def to_stream_dict(self) -> dict[str, str]:
        """Flatten to ``{str: str}`` pairs suitable for ``XADD``."""
        payload = self.model_dump(mode="json")
        encoded: dict[str, str] = {}
        for key, value in _flatten(payload).items():
            if isinstance(value, list):
                encoded[key] = _STREAM_LIST_PREFIX + json.dumps(
                    value, ensure_ascii=False, separators=(",", ":"),
                )
            elif isinstance(value, str):
                encoded[key] = (
                    _STREAM_STRING_PREFIX + value
                    if value.startswith((_STREAM_LIST_PREFIX, _STREAM_STRING_PREFIX))
                    else value
                )
            else:
                encoded[key] = str(value)
        return encoded


def _flatten(d: dict[str, Any], parent: str = "", sep: str = ".") -> dict[str, Any]:
    items: list[tuple[str, Any]] = []
    for k, v in d.items():
        key = f"{parent}{sep}{k}" if parent else k
        if isinstance(v, dict):
            items.extend(_flatten(v, key, sep).items())
        else:
            items.append((key, v))
    return dict(items)


def _unflatten(d: dict[str, Any], sep: str = ".") -> dict[str, Any]:
    """Reconstruct nested event fields flattened for Redis Streams."""
    out: dict[str, Any] = {}
    for key, value in d.items():
        if sep not in key:
            out[key] = value
            continue
        parts = key.split(sep)
        current = out
        for part in parts[:-1]:
            nested = current.setdefault(part, {})
            if not isinstance(nested, dict):
                nested = {}
                current[part] = nested
            current = nested
        current[parts[-1]] = value
    return out


# ── Market-Data Events ───────────────────────────────────────────────────────

class TickEvent(Event):
    event_type: str = "tick"
    symbol: str = ""
    bid: float = 0.0
    ask: float = 0.0
    spread: float = 0.0


class OHLCVEvent(Event):
    event_type: str = "ohlcv"
    symbol: str = ""
    timeframe: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0


class SignalEvent(Event):
    event_type: str = "signal"
    symbol: str = ""
    timeframe: str = ""
    direction: Verdict | str = ""
    confidence: float = 0.0
    features: dict[str, float] = Field(default_factory=dict)
    ml_scores: dict[str, float] = Field(default_factory=dict)
    # Optional signal risk fields — None/"" means "not provided" (backward compatible).
    atr: float | None = None
    stop_atr: float | None = None
    target_atr: float | None = None
    max_holding_hours: float | None = None
    group_id: str | None = None
    reason: str = ""

    @field_validator("atr", "stop_atr", "target_atr", "max_holding_hours", "group_id", mode="before")
    @classmethod
    def _coerce_optional_risk_field(cls, v: Any) -> Any:
        # Redis-stream round-trip stringifies None as "None" — normalise back.
        if isinstance(v, str) and v.strip() in {"", "None"}:
            return None
        return v


class FeatureEvent(Event):
    event_type: str = "feature"
    symbol: str = ""
    timeframe: str = ""
    bar_timestamp: str = ""
    features: dict[str, float | str] = Field(default_factory=dict)


# ── Agent Events ─────────────────────────────────────────────────────────────

class AgentAnalysisEvent(Event):
    event_type: str = "agent_analysis"
    agent_id: str = ""
    agent_name: str = ""
    symbol: str = ""
    analysis: str = ""
    confidence: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentVerdictEvent(Event):
    event_type: str = "agent_verdict"
    agent_id: str = ""
    agent_name: str = ""
    symbol: str = ""
    verdict: Verdict | str = ""
    conviction: float = 0.0
    reasoning: str = ""


# ── Risk Events ──────────────────────────────────────────────────────────────

class RiskDecisionEvent(Event):
    event_type: str = "risk_decision"
    proposal_id: str = ""
    decision: RiskDecision | str = ""
    original_size: float = 0.0
    approved_size: float = 0.0
    reason: str = ""


# ── Execution Events ─────────────────────────────────────────────────────────

class OrderEvent(Event):
    event_type: str = "order"
    order_id: str = ""
    symbol: str = ""
    side: str = ""
    order_type: str = "market"
    price: float = 0.0
    size: float = 0.0
    status: str = "pending"


class PositionUpdateEvent(Event):
    event_type: str = "position_update"
    position_id: str = ""
    symbol: str = ""
    current_price: float = 0.0
    pnl_pips: float = 0.0
    pnl_usd: float = 0.0
    status: str = "open"


class TradeCloseEvent(Event):
    event_type: str = "trade_close"
    trade_id: str = ""
    symbol: str = ""
    side: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    pnl_pips: float = 0.0
    pnl_usd: float = 0.0
    rr_ratio: float = 0.0
    reason: str = ""
    opened_at: str = ""
    session: str = ""
    conviction: float = 0.0
    size: float = 0.0
    atr: float = 0.0
    regime: str = ""


# ── System Events ────────────────────────────────────────────────────────────

class SessionChangeEvent(Event):
    event_type: str = "session_change"
    previous_session: SessionName | str = ""
    new_session: SessionName | str = ""
    active_agents: list[str] = Field(default_factory=list)
    eligible_pairs: list[str] = Field(default_factory=list)


class SystemHealthEvent(Event):
    event_type: str = "system_health"
    service_name: str = ""
    status: str = "healthy"
    latency_ms: float = 0.0
    cpu_pct: float = 0.0
    ram_pct: float = 0.0


class NewsAlertEvent(Event):
    event_type: str = "news_alert"
    headline: str = ""
    source_name: str = ""
    impact: str = "low"
    sentiment: str = "neutral"
    affected_currencies: list[str] = Field(default_factory=list)
    finbert_score: float = 0.0


# ── Event-Type Registry ─────────────────────────────────────────────────────

@unique
class EventType(StrEnum):
    TICK             = "tick"
    OHLCV            = "ohlcv"
    SIGNAL           = "signal"
    FEATURE          = "feature"
    AGENT_ANALYSIS   = "agent_analysis"
    AGENT_VERDICT    = "agent_verdict"
    RISK_DECISION    = "risk_decision"
    ORDER            = "order"
    POSITION_UPDATE  = "position_update"
    TRADE_CLOSE      = "trade_close"
    SESSION_CHANGE   = "session_change"
    SYSTEM_HEALTH    = "system_health"
    NEWS_ALERT       = "news_alert"


EVENT_CLASS_MAP: dict[str, type[Event]] = {
    EventType.TICK:            TickEvent,
    EventType.OHLCV:           OHLCVEvent,
    EventType.SIGNAL:          SignalEvent,
    EventType.FEATURE:         FeatureEvent,
    EventType.AGENT_ANALYSIS:  AgentAnalysisEvent,
    EventType.AGENT_VERDICT:   AgentVerdictEvent,
    EventType.RISK_DECISION:   RiskDecisionEvent,
    EventType.ORDER:           OrderEvent,
    EventType.POSITION_UPDATE: PositionUpdateEvent,
    EventType.TRADE_CLOSE:     TradeCloseEvent,
    EventType.SESSION_CHANGE:  SessionChangeEvent,
    EventType.SYSTEM_HEALTH:   SystemHealthEvent,
    EventType.NEWS_ALERT:      NewsAlertEvent,
}

STREAM_FOR_EVENT: dict[str, RedisStream] = {
    EventType.TICK:            RedisStream.TICK_STREAM,
    EventType.OHLCV:           RedisStream.OHLCV_STREAM,
    EventType.SIGNAL:          RedisStream.SIGNAL_STREAM,
    EventType.FEATURE:         RedisStream.FEATURE_STREAM,
    EventType.AGENT_ANALYSIS:  RedisStream.AGENT_ANALYSIS,
    EventType.AGENT_VERDICT:   RedisStream.AGENT_VERDICT,
    EventType.RISK_DECISION:   RedisStream.RISK_DECISION,
    EventType.ORDER:           RedisStream.ORDER_STREAM,
    EventType.POSITION_UPDATE: RedisStream.POSITION_UPDATE,
    EventType.TRADE_CLOSE:     RedisStream.TRADE_CLOSE,
    EventType.SESSION_CHANGE:  RedisStream.SESSION_CHANGE,
    EventType.SYSTEM_HEALTH:   RedisStream.SYSTEM_HEALTH_STREAM,
    EventType.NEWS_ALERT:      RedisStream.NEWS_ALERT,
}


def parse_event(raw: dict[str, str]) -> Event:
    """Reconstruct a typed Event from a flat Redis-Stream entry."""
    decoded: dict[str, Any] = {}
    for key, value in raw.items():
        if value.startswith(_STREAM_LIST_PREFIX):
            decoded[key] = json.loads(value[len(_STREAM_LIST_PREFIX):])
        elif value.startswith(_STREAM_STRING_PREFIX):
            decoded[key] = value[len(_STREAM_STRING_PREFIX):]
        else:
            decoded[key] = value
    payload = _unflatten(decoded)
    event_type = str(payload.get("event_type", ""))
    cls = EVENT_CLASS_MAP.get(event_type, Event)
    return cls.model_validate(payload)
