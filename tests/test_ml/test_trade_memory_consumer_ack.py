from __future__ import annotations

import asyncio

import pytest

from services.nexus_ml.traders import trade_memory


@pytest.mark.asyncio
@pytest.mark.parametrize("record_fails", [True, False])
async def test_trade_memory_acknowledges_only_after_record_succeeds(monkeypatch, record_fails):
    acknowledgements = []
    reads = 0

    class FakeRedis:
        async def xgroup_create(self, *args, **kwargs):
            return None

        async def xreadgroup(self, **kwargs):
            nonlocal reads
            reads += 1
            if reads == 1:
                return [("stream:trade_close", [("1-0", {
                    "trade_id": "",
                    "symbol": "XAUUSD",
                    "side": "BUY",
                    "pnl_pips": "10",
                })])]
            raise asyncio.CancelledError

        async def xack(self, *args):
            acknowledgements.append(args)

    class FakeMemory:
        async def _get_redis(self):
            return FakeRedis()

        async def record_trade(self, **kwargs):
            if record_fails:
                raise RuntimeError("simulated trade-memory persistence failure")

    await trade_memory._trade_close_listener(FakeMemory())

    if record_fails:
        assert acknowledgements == []
    else:
        assert acknowledgements == [("stream:trades:close", "trade-memory-cg", "1-0")]


@pytest.mark.asyncio
async def test_trade_record_propagates_redis_persistence_failure_and_rolls_back():
    class FailingPipeline:
        def set(self, *args, **kwargs):
            return self

        async def execute(self):
            raise RuntimeError("simulated Redis persistence failure")

    class FakeRedis:
        async def get(self, _key):
            return None

        def pipeline(self):
            return FailingPipeline()

    memory = trade_memory.TradeMemory(redis_conn=FakeRedis())

    with pytest.raises(RuntimeError, match="simulated Redis persistence failure"):
        await memory.record_trade(
            trade_id="trade-failed",
            symbol="XAUUSD",
            side="BUY",
            pnl_pips=10,
        )

    assert memory._trades == []


@pytest.mark.asyncio
async def test_listener_leaves_delivery_pending_on_real_redis_pipeline_failure():
    acknowledgements = []
    reads = 0

    class FailingPipeline:
        def set(self, *args, **kwargs):
            return self

        async def execute(self):
            raise RuntimeError("simulated Redis persistence failure")

    class FakeRedis:
        async def xgroup_create(self, *args, **kwargs):
            return None

        async def get(self, _key):
            return None

        def pipeline(self):
            return FailingPipeline()

        async def xreadgroup(self, **kwargs):
            nonlocal reads
            reads += 1
            if reads == 1:
                return [("stream:trades:close", [("2-0", {
                    "trade_id": "trade-failed",
                    "symbol": "XAUUSD",
                    "side": "BUY",
                    "pnl_pips": "10",
                })])]
            raise asyncio.CancelledError

        async def xack(self, *args):
            acknowledgements.append(args)

    memory = trade_memory.TradeMemory(redis_conn=FakeRedis())
    await trade_memory._trade_close_listener(memory)

    assert acknowledgements == []
    assert memory._trades == []
