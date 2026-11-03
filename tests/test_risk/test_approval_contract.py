from __future__ import annotations

import pytest
from fastapi import HTTPException
import time

from services.nexus_risk import main as risk_main
from shared.constants import RiskDecision
from shared.models import TradeProposal, Verdict
from shared.safety import verify_approval_signature


@pytest.mark.asyncio
@pytest.mark.parametrize("provided_secret", [None, "wrong-secret"])
async def test_risk_rest_evaluation_requires_internal_service_secret(monkeypatch, provided_secret):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "configured-risk-secret")

    async def unexpected_evaluate(*_args):
        pytest.fail("risk evaluation must not run without a valid internal credential")

    monkeypatch.setattr(risk_main, "_evaluate_proposal", unexpected_evaluate)
    proposal = TradeProposal(
        id="unauthorized-risk-eval",
        symbol="XAUUSD",
        direction=Verdict.BUY,
        entry=2500.0,
        sl=2490.0,
        tp1=2520.0,
        conviction=0.8,
    )

    with pytest.raises(HTTPException) as raised:
        await risk_main.evaluate_trade(
            risk_main.EvaluateRequest(proposal=proposal),
            x_nexus_internal_secret=provided_secret,
        )

    assert raised.value.status_code == 403


@pytest.mark.asyncio
async def test_risk_evaluate_ignores_client_supplied_safety_state(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "configured-risk-secret")
    received_state = []

    async def fake_evaluate(_proposal, state):
        received_state.append(state)
        return {
            "decision": RiskDecision.REJECT,
            "approved_size": 0.0,
            "violations": [{"rule": "max_daily_loss"}],
            "sizing": {},
            "tilt": {},
        }

    async def fake_cache():
        return None

    monkeypatch.setattr(risk_main, "_evaluate_proposal", fake_evaluate)
    monkeypatch.setattr(risk_main, "_cache_risk_state", fake_cache)
    proposal = TradeProposal(
        id="client-state-spoof",
        symbol="XAUUSD",
        direction=Verdict.BUY,
        entry=2500.0,
        sl=2490.0,
        tp1=2520.0,
        conviction=0.8,
    )
    response = await risk_main.evaluate_trade(risk_main.EvaluateRequest(
        proposal=proposal,
        state={"daily_loss_pct": 0.0, "open_positions_count": 0, "balance": 1_000_000},
    ), x_nexus_internal_secret="configured-risk-secret")

    assert received_state == [risk_main._current_state]
    assert response.decision == "REJECT"
    assert response.approved_size == 0.0


@pytest.mark.asyncio
async def test_risk_rest_approval_signs_the_policy_adjusted_proposal(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-risk-approval-secret")
    monkeypatch.setenv("NEXUS_RISK_APPROVAL_SECRET", "separate-risk-approval-key-for-tests")
    evaluated_symbols = []

    async def fake_evaluate(proposal, _state):
        evaluated_symbols.append(proposal.symbol)
        return {
            "decision": RiskDecision.APPROVE,
            "approved_size": 0.05,
            "violations": [],
            "sizing": {"lots": 0.05, "raw_lots": 0.06, "risk_pct_used": 0.5},
            "tilt": {},
        }

    async def fake_cache():
        return None

    monkeypatch.setattr(risk_main, "_evaluate_proposal", fake_evaluate)
    monkeypatch.setattr(risk_main, "_cache_risk_state", fake_cache)
    proposal = TradeProposal(
        id="contract-proposal",
        symbol=" xauusd ",
        direction=Verdict.BUY,
        entry=2500.0,
        sl=2490.0,
        tp1=2520.0,
        conviction=0.8,
    )

    response = await risk_main.evaluate_trade(
        risk_main.EvaluateRequest(proposal=proposal, size_multiplier=0.8),
        x_nexus_internal_secret="test-risk-approval-secret",
    )

    assert response.decision == "APPROVE"
    assert response.approved_size == 0.04
    assert response.sizing["lots"] == 0.04
    assert response.sizing["raw_lots"] == 0.06
    assert response.sizing["risk_pct_used"] == pytest.approx(0.4)
    assert evaluated_symbols == ["XAUUSD"]
    assert {key: value for key, value in response.approval_payload.items() if key != "signal_timestamp"} == {
        "version": 1,
        "proposal_id": "contract-proposal",
        "expires_at": response.approval_expires_at,
        "symbol": "XAUUSD",
        "side": "BUY",
        "order_type": "MARKET",
        "entry": 2500.0,
        "price": 0.0,
        "sl": 2490.0,
        "tp": 2520.0,
        "size": 0.04,
        "slippage": 10,
    }
    assert abs(response.approval_payload["signal_timestamp"] - time.time()) < 5
    assert verify_approval_signature(response.approval_payload, response.approval_signature)


@pytest.mark.asyncio
async def test_risk_rejects_limit_price_different_from_evaluated_entry(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-risk-approval-secret")
    monkeypatch.setenv("NEXUS_RISK_APPROVAL_SECRET", "separate-risk-approval-key-for-tests")

    async def fake_evaluate(_proposal, _state):
        return {
            "decision": RiskDecision.APPROVE,
            "approved_size": 0.05,
            "violations": [],
            "sizing": {},
            "tilt": {},
        }

    async def fake_cache():
        return None

    monkeypatch.setattr(risk_main, "_evaluate_proposal", fake_evaluate)
    monkeypatch.setattr(risk_main, "_cache_risk_state", fake_cache)
    proposal = TradeProposal(
        id="limit-price-contract",
        symbol="XAUUSD",
        direction=Verdict.BUY,
        entry=2500.0,
        sl=2490.0,
        tp1=2520.0,
        conviction=0.8,
    )

    with pytest.raises(HTTPException) as raised:
        await risk_main.evaluate_trade(
            risk_main.EvaluateRequest(
                proposal=proposal,
                order_type="LIMIT",
                order_price=2490.0,
            ),
            x_nexus_internal_secret="test-risk-approval-secret",
        )

    assert raised.value.status_code == 422


@pytest.mark.asyncio
async def test_risk_rejects_when_policy_reduction_falls_below_minimum_lot(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-risk-approval-secret")
    monkeypatch.setenv("NEXUS_RISK_APPROVAL_SECRET", "separate-risk-approval-key-for-tests")

    async def fake_evaluate(_proposal, _state):
        return {
            "decision": RiskDecision.APPROVE,
            "approved_size": 0.01,
            "violations": [],
            "sizing": {},
            "tilt": {},
        }

    async def fake_cache():
        return None

    monkeypatch.setattr(risk_main, "_evaluate_proposal", fake_evaluate)
    monkeypatch.setattr(risk_main, "_cache_risk_state", fake_cache)
    proposal = TradeProposal(
        id="minimum-lot-policy-contract",
        symbol="XAUUSD",
        direction=Verdict.BUY,
        entry=2500.0,
        sl=2490.0,
        tp1=2520.0,
        conviction=0.8,
    )

    response = await risk_main.evaluate_trade(
        risk_main.EvaluateRequest(proposal=proposal, size_multiplier=0.8),
        x_nexus_internal_secret="test-risk-approval-secret",
    )

    assert response.decision == "REJECT"
    assert response.approved_size == 0.0
    assert response.approval_signature == ""
    assert response.violations[0]["rule"] == "policy_size_below_minimum_lot"
