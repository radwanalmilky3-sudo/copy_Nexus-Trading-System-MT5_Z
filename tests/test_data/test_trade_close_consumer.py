from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from services.nexus_data import main as data_main


@pytest.mark.asyncio
@pytest.mark.parametrize("write_fails", [True, False])
async def test_trade_close_is_acknowledged_only_after_successful_persistence(monkeypatch, write_fails):
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
                    "trade_id": "trade-1",
                    "symbol": "XAUUSD",
                    "side": "BUY",
                    "entry_price": "100",
                    "exit_price": "101",
                    "pnl_pips": "10",
                    "pnl_usd": "5",
                    "rr_ratio": "1",
                    "conviction": "0.8",
                })])]
            raise asyncio.CancelledError

        async def xack(self, *args):
            acknowledgements.append(args)

    class FakeLog:
        async def ainfo(self, *args, **kwargs):
            return None

        async def aexception(self, *args, **kwargs):
            return None

    async def fail_insert(**kwargs):
        if write_fails:
            raise RuntimeError("simulated DuckDB write failure")

    monkeypatch.setattr(data_main, "redis_client", SimpleNamespace(r=FakeRedis()))
    monkeypatch.setattr(data_main, "data_store", SimpleNamespace(insert_trade=fail_insert))
    monkeypatch.setattr(data_main, "log", FakeLog())
    monkeypatch.setattr(data_main.asyncio, "sleep", lambda *_args, **_kwargs: _noop())

    await data_main._trade_close_consumer()

    if write_fails:
        assert acknowledgements == []
    else:
        assert len(acknowledgements) == 1


async def _noop():
    return None


@pytest.mark.asyncio
async def test_duckdb_startup_failure_releases_redis_and_store(monkeypatch):
    from types import SimpleNamespace

    calls = []

    class FakeRedis:
        async def connect(self):
            calls.append("redis.connect")

        async def disconnect(self):
            calls.append("redis.disconnect")

    class FakeStore:
        async def init_tables(self):
            calls.append("store.init")
            raise RuntimeError("simulated DuckDB initialization failure")

        def close(self):
            calls.append("store.close")

    class FakeLog:
        async def ainfo(self, *args, **kwargs):
            return None

        async def aexception(self, *args, **kwargs):
            return None

    monkeypatch.setattr(data_main, "redis_client", FakeRedis())
    monkeypatch.setattr(data_main, "data_store", FakeStore())
    monkeypatch.setattr(data_main, "fundamental_store", SimpleNamespace(init_schema=_noop))
    monkeypatch.setattr(data_main, "log", FakeLog())

    with pytest.raises(RuntimeError, match="simulated DuckDB initialization failure"):
        async with data_main.lifespan(SimpleNamespace()):
            pytest.fail("lifespan must not yield when DuckDB initialization fails")

    assert calls == ["redis.connect", "store.init", "store.close", "redis.disconnect"]
