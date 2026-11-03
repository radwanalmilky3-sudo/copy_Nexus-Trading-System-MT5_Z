"""
A2 — El Periodista: News Sentinel agent.

Fetches latest news, calendar events, and social sentiment.
Classifies impact and checks for news blackouts.
Returns a news_assessment with recommendation:
  TRADE_FREELY / CAUTION / AVOID / HEDGE
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import structlog
import yaml

from shared.redis_client import RedisClient

from ..state import AgentState
from ..tools.news_tools import fetch_news, finbert_score, get_calendar, get_sentiment
from .base_agent import BaseAgent

logger = structlog.get_logger(__name__)

RISK_RULES_PATH = Path(__file__).resolve().parents[3] / "config" / "risk_rules.yaml"
# Mirrors services/nexus_risk/rules_engine.py _HARDCODED_MIN["news_blackout_minutes"]:
# the central risk engine never runs a blackout window tighter than this floor.
_NEWS_BLACKOUT_FLOOR_MIN = 5


def _blackout_minutes() -> int:
    """Effective news blackout window (minutes) from config/risk_rules.yaml.

    Matches the central risk engine: calendar.news_blackout_minutes, floored at
    the same minimum nexus_risk enforces (so the agent never advertises a
    narrower window than risk will apply). NEXUS_AGGRESSIVE_TRADING disables
    the window, exactly as rules_engine does.
    """
    configured = 0
    try:
        with open(RISK_RULES_PATH) as f:
            rules = yaml.safe_load(f) or {}
        configured = int(rules.get("calendar", {}).get("news_blackout_minutes", 0) or 0)
    except Exception:
        configured = 0
    if os.getenv("NEXUS_AGGRESSIVE_TRADING", "false").lower() == "true":
        return configured
    return max(configured, _NEWS_BLACKOUT_FLOOR_MIN)


NEWS_BLACKOUT_MINUTES = _blackout_minutes()


class NewsSentinelAgent(BaseAgent):
    def __init__(self, *, redis_client: RedisClient | None = None) -> None:
        super().__init__("A2", "News Sentinel", redis_client=redis_client)

    async def invoke(self, state: AgentState) -> AgentState:
        symbol = state["symbol"]

        news_items: list = []
        calendar_events: list = []
        sentiment_data: dict = {}
        finbert_scores: list = []
        source_unavailable = False

        try:
            news_items = await fetch_news(symbol)
        except Exception as exc:
            source_unavailable = True
            state["errors"].append(f"A2: fetch_news failed: {exc}")

        try:
            calendar_events = await get_calendar(hours=24)
        except Exception as exc:
            source_unavailable = True
            state["errors"].append(f"A2: get_calendar failed: {exc}")

        try:
            sentiment_data = await get_sentiment(symbol)
        except Exception as exc:
            source_unavailable = True
            state["errors"].append(f"A2: get_sentiment failed: {exc}")

        for item in news_items[:5]:
            try:
                headline = item.get("headline", "") if isinstance(item, dict) else str(item)
                score = await finbert_score(headline)
                finbert_scores.append({"headline": headline[:100], "score": score})
            except Exception:
                pass

        blackout_active = False
        high_impact_events = []
        for evt in calendar_events:
            impact = evt.get("impact", "low") if isinstance(evt, dict) else "low"
            if impact in ("high", "critical"):
                high_impact_events.append(evt)
                evt_time = evt.get("timestamp")
                if evt_time:
                    try:
                        from datetime import timedelta
                        evt_dt = datetime.fromisoformat(str(evt_time).replace("Z", "+00:00"))
                        now = datetime.now(timezone.utc)
                        diff = abs((evt_dt - now).total_seconds()) / 60
                        if diff <= NEWS_BLACKOUT_MINUTES:
                            blackout_active = True
                    except Exception:
                        pass

        if blackout_active:
            recommendation = "AVOID"
        elif source_unavailable:
            recommendation = "AVOID"
        elif high_impact_events:
            recommendation = "CAUTION"
        elif sentiment_data.get("score", 0) < -0.5:
            recommendation = "HEDGE"
        else:
            recommendation = "TRADE_FREELY"

        # Carry source health as structured state so arbitration does not rely
        # on an LLM honoring a warning embedded in prose.
        state["news_source_unavailable"] = source_unavailable

        context_block = (
            f"Symbol: {symbol}\n"
            f"News blackout window (from config/risk_rules.yaml, enforced by nexus-risk): "
            f"{NEWS_BLACKOUT_MINUTES} minutes\n"
            f"Recent news ({len(news_items)} items): {json.dumps(news_items[:5], default=str)}\n"
            f"Calendar events (next 24h): {json.dumps(calendar_events[:10], default=str)}\n"
            f"Sentiment: {json.dumps(sentiment_data, default=str)}\n"
            f"FinBERT scores: {json.dumps(finbert_scores, default=str)}\n"
            f"Blackout active: {blackout_active}\n"
            f"High-impact events: {json.dumps(high_impact_events, default=str)}\n"
            f"Source unavailable: {source_unavailable}\n"
            f"Initial recommendation: {recommendation}\n"
            f"NOTE: Your assessment is advisory — the central nexus-risk service "
            f"enforces blackouts and the final decision independently."
        )

        if source_unavailable:
            assessment = (
                "[News data unavailable — fail-closed assessment]\n"
                "At least one required news/calendar/sentiment source failed. "
                "Do not interpret missing data as no risk.\n"
                "RECOMMENDATION: AVOID — news risk could not be verified."
            )
        else:
            try:
                llm = self._get_llm(fast=True)
                prompt = self._load_prompt("news_sentinel")
                chain = prompt | llm
                response = await self._invoke_with_budget(chain, {"input": context_block}, cycle_id=str(state.get("cycle_id", "")))
                assessment = response.content if hasattr(response, "content") else str(response)
            except Exception as exc:
                assessment = (
                    f"[LLM unavailable — raw assessment]\n"
                    f"Recommendation: {recommendation}\n"
                    f"Blackout: {blackout_active}\n"
                    f"High-impact events: {len(high_impact_events)}\n"
                    f"Sentiment score: {sentiment_data.get('score', 'N/A')}"
                )
                state["errors"].append(f"A2: LLM call failed: {exc}")

        state["news_assessment"] = assessment
        state["messages"].append({
            "agent_id": self.agent_id,
            "agent_name": self.name,
            "type": "analysis",
            "content": assessment[:500],
            "recommendation": recommendation,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        await self._publish_message(assessment[:500], metadata={
            "recommendation": recommendation,
            "blackout": blackout_active,
            "high_impact_count": len(high_impact_events),
        }, state=state)
        await self._log_reasoning(assessment, state=state)

        return state
