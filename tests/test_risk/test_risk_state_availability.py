from __future__ import annotations

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from services.nexus_risk import main as risk_main
from shared.models import TradeProposal, Verdict
from shared.constants import RiskDecision


@pytest.mark.asyncio
async def test_risk_state_cache_distinguishes_missing_sync_from_live_zero(monkeypatch):
    writes = []

    async def cache_set(key, value, **kwargs):
        writes.append((key, value))

    monkeypatch.setattr(risk_main, "redis", type("Redis", (), {"cache_set": staticmethod(cache_set)})())
    monkeypatch.setitem(risk_main._current_state, "available", False)
    await risk_main._cache_risk_state()
    assert writes[-1][1]["available"] is False

    monkeypatch.setitem(risk_main._current_state, "available", True)
    await risk_main._cache_risk_state()
    assert writes[-1][1]["available"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [
    {"available": False, "balance": 10_000, "equity": 10_000, "daily_loss_pct": 0},
    {"available": True, "balance": float("nan"), "equity": 10_000, "daily_loss_pct": 0},
    {"available": True, "balance": 0, "equity": 0, "daily_loss_pct": 0},
])
async def test_unsynced_or_invalid_account_cannot_authorize_exposure(monkeypatch, state):
    monkeypatch.setattr(risk_main, "_current_state", state)
    cache_get = AsyncMock()
    monkeypatch.setattr(risk_main, "redis", SimpleNamespace(cache_get=cache_get))
    proposal = TradeProposal(
        symbol="XAUUSD", direction=Verdict.BUY, entry=2500,
        sl=2490, tp1=2520, conviction=0.8,
    )
    result = await risk_main._evaluate_proposal(proposal, {
        "available": True, "balance": 1_000_000,
    })
    assert result["decision"] == RiskDecision.REJECT
    assert result["approved_size"] == 0
    assert result["violations"][0]["rule"] == "account_state_unavailable"
    cache_get.assert_not_awaited()


@pytest.mark.asyncio
async def test_daily_pnl_read_failure_is_not_reported_as_zero_loss(monkeypatch):
    monkeypatch.setattr(risk_main, "redis", SimpleNamespace(
        r=SimpleNamespace(get=AsyncMock(side_effect=ConnectionError("offline"))),
    ))
    with pytest.raises(ConnectionError):
        await risk_main._get_nexus_daily_pnl()
