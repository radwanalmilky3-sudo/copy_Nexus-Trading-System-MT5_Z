"""
Nexus Agents — AgentState definition.

TypedDict for LangGraph + Pydantic model for runtime validation at boundaries.
"""
from __future__ import annotations

from typing import Any, Literal, Optional, TypedDict

from pydantic import BaseModel, Field

# ── State-write idempotency ──────────────────────────────────────────────────

STATE_WRITE_STREAM = "nexus:agents:state_writes"
STATE_WRITE_GROUP = "state-writer"
_STATE_WRITE_TTL_SEC = 30 * 24 * 3600


async def mark_state_write_once(
    redis_client: Any,
    *,
    cycle_id: str,
    source_message_id: str = "",
) -> bool:
    """True only the first time a state write for this (cycle, message) runs.

    Guards LangGraph state publication against stream redeliveries: a
    duplicate delivery of the same source message must not publish a second
    cycle result. Uses the shared Redis client's SETNX idempotency helper.
    """
    if redis_client is None:
        return True
    key = f"{cycle_id}:{source_message_id or 'no-message'}"
    try:
        first = await redis_client.mark_processed(
            STATE_WRITE_STREAM, STATE_WRITE_GROUP, key, ttl_sec=_STATE_WRITE_TTL_SEC,
        )
    except Exception:
        # Redis outage: state writes are not broker-affecting; proceed.
        return True
    return bool(first)


class AgentState(TypedDict):
    symbol: str
    timeframe: str
    session: str
    ml_signal: dict
    features: dict
    htf_context: dict
    regime_analysis: dict
    technical_analysis: str
    news_assessment: str
    news_source_unavailable: bool
    intermarket_score: float
    flow_score: float
    bull_case: str
    bull_conviction: int
    bear_case: str
    bear_conviction: int
    verdict: Literal["BUY", "SELL", "NO_TRADE", "WATCH"]
    verdict_conviction: int
    verdict_reasoning: str
    risk_decision: Literal["APPROVE", "REJECT", "MODIFY"]
    position_size: float
    risk_reasoning: str
    open_positions: list
    order: Optional[dict]
    messages: list
    cycle_id: str
    errors: list
    trade_memory: dict


class AgentStateModel(BaseModel):
    """Pydantic mirror — validate at graph entry/exit."""

    symbol: str = "XAUUSD"
    timeframe: str = "M5"
    session: str = "OFF_HOURS"
    ml_signal: dict[str, Any] = Field(default_factory=dict)
    features: dict[str, Any] = Field(default_factory=dict)
    htf_context: dict[str, Any] = Field(default_factory=dict)
    regime_analysis: dict[str, Any] = Field(default_factory=dict)
    technical_analysis: str = ""
    news_assessment: str = ""
    news_source_unavailable: bool = False
    intermarket_score: float = 0.0
    flow_score: float = 0.0
    bull_case: str = ""
    bull_conviction: int = 0
    bear_case: str = ""
    bear_conviction: int = 0
    verdict: Literal["BUY", "SELL", "NO_TRADE", "WATCH"] = "NO_TRADE"
    verdict_conviction: int = 0
    verdict_reasoning: str = ""
    risk_decision: Literal["APPROVE", "REJECT", "MODIFY"] = "REJECT"
    position_size: float = 0.0
    risk_reasoning: str = ""
    open_positions: list[Any] = Field(default_factory=list)
    order: Optional[dict[str, Any]] = None
    messages: list[Any] = Field(default_factory=list)
    cycle_id: str = ""
    errors: list[str] = Field(default_factory=list)
    trade_memory: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


def validate_state(state: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize agent state dict."""
    return AgentStateModel.model_validate(state).model_dump()


def initial_state(**kwargs: Any) -> AgentState:
    base = AgentStateModel(**kwargs).model_dump()
    return base  # type: ignore[return-value]
