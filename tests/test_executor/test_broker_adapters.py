"""Tests for nexus_executor service — broker adapters."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


EXEC_SVC = Path(__file__).resolve().parents[2] / "services" / "nexus_executor"


class TestExecutorServiceFiles:
    REQUIRED = [
        "__init__.py", "main.py", "broker_adapter.py",
        "mt5_executor.py", "ibkr_executor.py",
        "ccxt_executor.py", "smart_routing.py",
    ]

    @pytest.mark.parametrize("filename", REQUIRED)
    def test_file_exists(self, filename: str):
        assert (EXEC_SVC / filename).exists(), f"Missing executor file: {filename}"


class TestBrokerAdapterImport:
    def test_importable(self):
        import importlib
        mod = importlib.import_module("services.nexus_executor.broker_adapter")
        assert mod is not None


class TestSmartRoutingImport:
    def test_importable(self):
        import importlib
        mod = importlib.import_module("services.nexus_executor.smart_routing")
        assert mod is not None


@pytest.mark.asyncio
async def test_paper_close_rejects_negative_size_without_increasing_position():
    from services.nexus_executor.broker_adapter import OrderRequest, OrderSide
    from services.nexus_executor.paper_executor import PaperExecutor

    broker = PaperExecutor()
    opened = await broker.send_order(OrderRequest(
        symbol="XAUUSD", side=OrderSide.BUY, size=0.1,
    ))

    result = await broker.close_position(opened.order_id, size=-0.05)

    positions = await broker.get_positions()
    assert result.status.value == "ERROR"
    assert positions[0]["size"] == pytest.approx(0.1)


@pytest.mark.asyncio
async def test_paper_partial_close_is_not_reported_as_full_close():
    from services.nexus_executor.broker_adapter import OrderRequest, OrderSide
    from services.nexus_executor.paper_executor import PaperExecutor

    broker = PaperExecutor()
    opened = await broker.send_order(OrderRequest(
        symbol="XAUUSD", side=OrderSide.BUY, size=0.1,
    ))

    result = await broker.close_position(opened.order_id, size=0.04)

    positions = await broker.get_positions()
    assert result.status.value == "PARTIAL"
    assert result.raw_response["closed"] is False
    assert positions[0]["size"] == pytest.approx(0.06)


@pytest.mark.asyncio
async def test_mt5_ambiguous_order_result_is_not_retried(monkeypatch):
    from services.nexus_executor.broker_adapter import OrderRequest, OrderSide
    from services.nexus_executor.mt5_executor import MT5Executor

    calls = []
    mt5 = SimpleNamespace(
        TRADE_ACTION_DEAL=1,
        TRADE_ACTION_PENDING=5,
        ORDER_TYPE_BUY=0,
        ORDER_TYPE_SELL=1,
        ORDER_TYPE_BUY_LIMIT=2,
        ORDER_TYPE_SELL_LIMIT=3,
        ORDER_TYPE_BUY_STOP=4,
        ORDER_TYPE_SELL_STOP=5,
        ORDER_TIME_GTC=0,
        ORDER_FILLING_IOC=1,
        ORDER_FILLING_FOK=2,
        ORDER_FILLING_RETURN=3,
        TRADE_RETCODE_INVALID_FILL=10030,
        symbol_info=lambda _symbol: SimpleNamespace(visible=True),
        symbol_info_tick=lambda _symbol: SimpleNamespace(ask=2500.0, bid=2499.0),
        order_send=lambda _request: calls.append("send") or None,
        last_error=lambda: "response unavailable",
    )
    broker = MT5Executor()
    broker._mt5 = mt5
    broker._connected = True

    async def direct_call(fn):
        return fn()

    monkeypatch.setattr("services.nexus_executor.mt5_executor._mt5_call", direct_call)

    result = await broker.send_order(OrderRequest(
        symbol="XAUUSD", side=OrderSide.BUY, size=0.01,
    ))

    assert result.status.value == "ERROR"
    assert len(calls) == 1
