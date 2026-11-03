from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.nexus_risk import main as risk_main
from shared.constants import RiskDecision
from shared.models import TradeProposal, Verdict


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "blackout",
    [
        None,
        [],
        "clear",
        {},
        {"state": "unexpected", "active": False},
        {"state": "clear", "active": "false"},
        {"state": "degraded", "active": False},
        {"state": "unknown", "active": False},
        {"state": "active", "active": True},
    ],
)
async def test_risk_rejects_missing_or_unsafe_fundamental_blackout(
    monkeypatch, blackout
):
    class FakeRedis:
        async def cache_get(self, key):
            if key == "system:auto_trade":
                return True
            if key == "fundamental:blackout":
                return blackout
            raise AssertionError(f"unexpected Redis key read: {key}")

    monkeypatch.setattr(risk_main, "redis", SimpleNamespace(cache_get=FakeRedis().cache_get))
    monkeypatch.setattr(risk_main, "_current_state", {
        "available": True, "balance": 10_000.0,
        "equity": 10_000.0, "daily_loss_pct": 0.0,
    })
    proposal = TradeProposal(
        id="fundamental-fail-closed",
        symbol="XAUUSD",
        direction=Verdict.BUY,
        entry=2500.0,
        sl=2490.0,
        tp1=2520.0,
        conviction=0.8,
    )

    result = await risk_main._evaluate_proposal(proposal, {})

    assert result["decision"] == RiskDecision.REJECT
    assert result["approved_size"] == 0.0
    assert result["violations"][0]["rule"] in {
        "fundamental_state_unavailable",
        "NEWS_BLACKOUT",
    }
