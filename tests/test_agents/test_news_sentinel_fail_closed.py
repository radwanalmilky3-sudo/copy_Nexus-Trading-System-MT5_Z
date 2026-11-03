from __future__ import annotations

import pytest

from services.nexus_agents.agents import news_sentinel
from services.nexus_agents.state import initial_state


@pytest.mark.asyncio
async def test_news_sentinel_avoids_trading_when_news_source_fails(monkeypatch):
    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("news service unavailable")

    monkeypatch.setattr(news_sentinel, "fetch_news", unavailable)
    monkeypatch.setattr(news_sentinel, "get_calendar", lambda **_kw: _empty())
    monkeypatch.setattr(
        news_sentinel,
        "get_sentiment",
        lambda *_args, **_kw: _neutral_sentiment(),
    )

    agent = news_sentinel.NewsSentinelAgent()
    llm_calls = []

    def record_llm_call(**_kwargs):
        llm_calls.append(True)
        raise RuntimeError("offline")

    monkeypatch.setattr(agent, "_get_llm", record_llm_call)
    state = initial_state(symbol="XAUUSD")

    result = await agent.invoke(state)

    assert result["messages"][-1]["recommendation"] == "AVOID"
    assert any("news service unavailable" in error for error in result["errors"])
    assert "AVOID" in result["news_assessment"]
    assert result["news_source_unavailable"] is True
    assert llm_calls == []


async def _empty():
    return []


async def _neutral_sentiment():
    return {"symbol": "XAUUSD", "score": 0.0, "label": "neutral", "sources": 0}
