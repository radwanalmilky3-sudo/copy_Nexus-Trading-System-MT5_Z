from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.nexus_risk import main as risk_main
from shared.events import AgentVerdictEvent, TradeCloseEvent
from shared.constants import RedisStream


@pytest.mark.asyncio
async def test_invalid_proposal_is_acknowledged_after_intentional_drop(monkeypatch):
    acknowledged = []
    event = AgentVerdictEvent(symbol="EURUSD", verdict="BUY", conviction=0.8)
    delivery = SimpleNamespace(
        event=event,
        ack=AsyncMock(side_effect=lambda: acknowledged.append("ack")),
    )

    class FakeRedis:
        async def connect(self):
            return None

        async def cache_get(self, _key):
            return None

        async def subscribe_deliveries(self, *args, **kwargs):
            yield delivery
            raise asyncio.CancelledError

    monkeypatch.setattr(risk_main, "redis", FakeRedis())

    with pytest.raises(asyncio.CancelledError):
        await risk_main._risk_stream_consumer()

    assert acknowledged == ["ack"]


@pytest.mark.asyncio
async def test_risk_evaluation_failure_leaves_proposal_unacknowledged(monkeypatch):
    acknowledged = []
    event = AgentVerdictEvent(
        symbol="EURUSD",
        verdict="BUY",
        conviction=0.8,
        data={"entry": 1.1, "sl": 1.09, "tp1": 1.12},
    )
    delivery = SimpleNamespace(
        event=event,
        message_id="1728910000000-0",
        ack=AsyncMock(side_effect=lambda: acknowledged.append("ack")),
    )

    class FakeRedis:
        async def connect(self):
            return None

        async def cache_get(self, _key):
            return None

        async def subscribe_deliveries(self, *args, **kwargs):
            yield delivery
            raise asyncio.CancelledError

    async def fail_evaluation(*args, **kwargs):
        raise RuntimeError("simulated risk evaluation failure")

    monkeypatch.setattr(risk_main, "redis", FakeRedis())
    monkeypatch.setattr(risk_main, "_evaluate_proposal", fail_evaluation)

    with pytest.raises(asyncio.CancelledError):
        await risk_main._risk_stream_consumer()

    assert acknowledged == []


@pytest.mark.asyncio
async def test_trade_close_processing_failure_leaves_delivery_unacknowledged(monkeypatch):
    acknowledged = []
    event = TradeCloseEvent(
        trade_id="trade-1",
        symbol="EURUSD",
        side="BUY",
        pnl_usd=-5.0,
        data={"source": "nexus:test"},
    )
    delivery = SimpleNamespace(
        event=event,
        message_id="1728910000000-0",
        ack=AsyncMock(side_effect=lambda: acknowledged.append("ack")),
    )

    class FakeRedis:
        async def connect(self):
            return None

        async def subscribe_stream(self, *args, **kwargs):
            try:
                yield event
            finally:
                acknowledged.append("legacy-auto-ack")
            raise asyncio.CancelledError

        async def subscribe_deliveries(self, *args, **kwargs):
            yield delivery
            raise asyncio.CancelledError

    async def fail_daily_pnl(_pnl):
        raise RuntimeError("simulated persistence failure")

    monkeypatch.setattr(risk_main, "redis", FakeRedis())
    monkeypatch.setattr(risk_main, "_add_nexus_daily_pnl", fail_daily_pnl)

    with pytest.raises(asyncio.CancelledError):
        await risk_main._trade_close_consumer()

    assert acknowledged == []


@pytest.mark.asyncio
async def test_daily_pnl_persistence_error_is_not_silently_swallowed(monkeypatch):
    class FailingRedisCommands:
        async def get(self, _key):
            return risk_main.datetime.now(risk_main.timezone.utc).strftime("%Y-%m-%d")

        async def incrbyfloat(self, *_args):
            raise RuntimeError("simulated Redis write failure")

    monkeypatch.setattr(risk_main, "redis", SimpleNamespace(r=FailingRedisCommands()))

    with pytest.raises(RuntimeError, match="simulated Redis write failure"):
        await risk_main._add_nexus_daily_pnl(-5.0)


@pytest.mark.asyncio
async def test_direction_streak_persistence_error_is_not_silently_swallowed(monkeypatch):
    class FailingRedisCommands:
        async def incr(self, _key):
            raise RuntimeError("simulated streak write failure")

    monkeypatch.setattr(risk_main, "redis", SimpleNamespace(r=FailingRedisCommands()))

    with pytest.raises(RuntimeError, match="simulated streak write failure"):
        await risk_main._update_direction_streak("EURUSD", "BUY", -5.0)


@pytest.mark.asyncio
async def test_recent_results_write_failure_leaves_trade_close_unacknowledged(monkeypatch):
    acknowledged = []
    delivery = SimpleNamespace(
        event=TradeCloseEvent(
            trade_id="trade-2",
            symbol="EURUSD",
            side="BUY",
            pnl_usd=-5.0,
            data={"source": "nexus:test"},
        ),
        message_id="1728910000001-0",
        ack=AsyncMock(side_effect=lambda: acknowledged.append("ack")),
    )

    class FailingRedisCommands:
        async def lpush(self, *_args):
            raise RuntimeError("simulated recent-results write failure")

    class FakeRedis:
        r = FailingRedisCommands()

        async def connect(self):
            return None

        async def cache_set(self, *_args, **_kwargs):
            return None

        async def subscribe_deliveries(self, *args, **kwargs):
            yield delivery
            raise asyncio.CancelledError

    anti_tilt = SimpleNamespace(
        update=lambda _result: risk_main.TiltStatus.NORMAL,
        get_state_dict=lambda: {"consecutive_losses": 1},
        persist_to_redis=AsyncMock(),
    )
    monkeypatch.setattr(risk_main, "redis", FakeRedis())
    monkeypatch.setattr(risk_main, "_add_nexus_daily_pnl", AsyncMock())
    monkeypatch.setattr(risk_main, "anti_tilt", anti_tilt)
    monkeypatch.setattr(risk_main, "_update_direction_streak", AsyncMock())
    monkeypatch.setattr(risk_main, "_cache_risk_state", AsyncMock())

    with pytest.raises(asyncio.CancelledError):
        await risk_main._trade_close_consumer()

    assert acknowledged == []
