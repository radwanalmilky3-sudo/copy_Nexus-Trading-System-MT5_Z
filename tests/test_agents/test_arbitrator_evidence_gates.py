from types import SimpleNamespace

import pytest

from services.nexus_agents.agents.arbitrator import ArbitratorAgent
from services.nexus_agents.state import initial_state


class _Prompt:
    def __or__(self, _llm):
        return object()


@pytest.mark.asyncio
async def test_missing_news_evidence_cannot_be_overridden_by_arbitrator(monkeypatch):
    agent = ArbitratorAgent()
    monkeypatch.setattr(agent, "_get_llm", lambda **_kwargs: object())
    monkeypatch.setattr(agent, "_load_prompt", lambda *_args: _Prompt())

    async def llm_response(*_args, **_kwargs):
        return SimpleNamespace(
            content="VERDICT: BUY\nCONVICTION: 95\nREASONING: bullish setup"
        )

    monkeypatch.setattr(agent, "_invoke_with_budget", llm_response)
    state = initial_state(
        symbol="XAUUSD",
        session="LONDON",
        news_source_unavailable=True,
        bull_conviction=90,
        bear_conviction=30,
    )

    result = await agent.invoke(state)

    assert result["verdict"] == "NO_TRADE"
    assert result["verdict_conviction"] == 0
    assert "evidence is unavailable" in result["verdict_reasoning"]


@pytest.mark.asyncio
async def test_ml_fallback_cannot_undo_genuine_conflict_lock(monkeypatch):
    agent = ArbitratorAgent()
    monkeypatch.setattr(agent, "_get_llm", lambda **_kwargs: object())
    monkeypatch.setattr(agent, "_load_prompt", lambda *_args: _Prompt())

    async def llm_response(*_args, **_kwargs):
        return SimpleNamespace(
            content="VERDICT: NO_TRADE\nCONVICTION: 50\nREASONING: conflicting debate"
        )

    monkeypatch.setattr(agent, "_invoke_with_budget", llm_response)
    state = initial_state(
        symbol="XAUUSD",
        session="LONDON",
        bull_conviction=95,
        bear_conviction=94,
        ml_signal={"direction": "BUY", "confidence": 0.99},
    )

    result = await agent.invoke(state)

    assert result["verdict"] == "NO_TRADE"
    assert "Genuine conflict" in result["verdict_reasoning"]
