from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.nexus_executor import main as executor_main
from shared.events import RiskDecisionEvent


@pytest.mark.asyncio
async def test_rejected_risk_decision_is_explicitly_acknowledged(monkeypatch):
    acknowledged = []
    event = RiskDecisionEvent(decision="REJECT", proposal_id="proposal-1")
    delivery = SimpleNamespace(
        event=event,
        ack=AsyncMock(side_effect=lambda: acknowledged.append("ack")),
    )

    class FakeRedis:
        async def connect(self):
            return None

        async def subscribe_deliveries(self, *args, **kwargs):
            yield delivery
            raise asyncio.CancelledError

    monkeypatch.setattr(executor_main, "redis", FakeRedis())

    with pytest.raises(asyncio.CancelledError):
        await executor_main._execution_stream_consumer()

    assert acknowledged == ["ack"]


@pytest.mark.asyncio
async def test_approved_decision_is_not_acknowledged_when_guard_fails(monkeypatch):
    acknowledged = []
    event = RiskDecisionEvent(
        decision="APPROVE",
        proposal_id="proposal-2",
        approved_size=0.01,
        data={"symbol": "XAUUSD", "entry": 2500, "sl": 2490},
    )
    delivery = SimpleNamespace(
        event=event,
        ack=AsyncMock(side_effect=lambda: acknowledged.append("ack")),
    )

    class FakeRedis:
        async def connect(self):
            return None

        async def subscribe_deliveries(self, *args, **kwargs):
            yield delivery
            raise asyncio.CancelledError

    async def fail_guard(*args, **kwargs):
        raise RuntimeError("simulated risk-approval verification outage")

    monkeypatch.setattr(executor_main, "redis", FakeRedis())
    monkeypatch.setattr(executor_main, "evaluate_executor_guard", fail_guard)

    with pytest.raises(asyncio.CancelledError):
        await executor_main._execution_stream_consumer()

    assert acknowledged == []
