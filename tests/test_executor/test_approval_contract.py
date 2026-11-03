from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from services.nexus_executor import main as executor_main
from services.nexus_executor.broker_adapter import OrderResponse, OrderSide, OrderStatus, OrderType
from services.nexus_executor.smart_routing import RoutingDecision
from shared.safety import approval_signature


class FakeRedis:
    async def cache_get(self, key):
        return {
            "system:kill_switch": False,
            "system:auto_trade": True,
            "fundamental:blackout": {"state": "clear", "active": False},
        }.get(key)


def test_risk_approval_signature_requires_a_separate_signing_secret(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "shared-internal-service-secret")
    monkeypatch.delenv("NEXUS_RISK_APPROVAL_SECRET", raising=False)
    approved = {
        "version": 1,
        "proposal_id": "isolated-key-1",
        "expires_at": int(time.time()) + 60,
        "symbol": "XAUUSD",
        "side": "BUY",
        "order_type": "MARKET",
        "entry": 2500.0,
        "price": 0.0,
        "sl": 2490.0,
        "tp": 2520.0,
        "size": 0.03,
        "signal_timestamp": time.time(),
        "slippage": 10,
    }

    assert approval_signature(approved) == ""


@pytest.mark.asyncio
async def test_executor_rest_rejects_changed_size_before_broker_access(monkeypatch):
    monkeypatch.setenv("NEXUS_TRADING_MODE", "paper")
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-risk-approval-secret")
    monkeypatch.setenv("NEXUS_RISK_APPROVAL_SECRET", "separate-risk-approval-key-for-tests")
    monkeypatch.setattr(executor_main, "redis", FakeRedis())

    async def no_op_record(*_args, **_kwargs):
        return None

    async def forbidden_broker_access():
        raise AssertionError("broker must not be acquired for mismatched approval terms")

    monkeypatch.setattr(executor_main, "record_guard_decision", no_op_record)
    monkeypatch.setattr(executor_main, "_get_broker", forbidden_broker_access)
    approved = {
        "version": 1,
        "proposal_id": "rest-contract-1",
        "expires_at": int(time.time()) + 60,
        "symbol": "XAUUSD",
        "side": "BUY",
        "order_type": "MARKET",
        "entry": 2500.0,
        "price": 0.0,
        "sl": 2490.0,
        "tp": 2520.0,
        "size": 0.03,
        "signal_timestamp": time.time(),
        "slippage": 10,
    }

    response = await executor_main.send_order(
        executor_main.SendOrderRequest(
            symbol="XAUUSD",
            side="BUY",
            order_type="MARKET",
            size=0.04,
            price=0.0,
            sl=2490.0,
            tp=2520.0,
            slippage=10,
            proposal_id="rest-contract-1",
            risk_approval_expires_at=approved["expires_at"],
            risk_approval_signature=approval_signature(approved),
            signal_timestamp=approved["signal_timestamp"],
            risk_approved_entry=2500.0,
            risk_approval_payload=approved,
        ),
        x_nexus_internal_secret="test-risk-approval-secret",
    )

    assert response.status == "GUARD_BLOCKED_RISK_APPROVAL_MISSING"
    assert response.broker == "none"


@pytest.mark.asyncio
async def test_executor_rest_rejects_router_changes_outside_signed_approval(monkeypatch):
    monkeypatch.setenv("NEXUS_TRADING_MODE", "paper")
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-risk-approval-secret")
    monkeypatch.setenv("NEXUS_RISK_APPROVAL_SECRET", "separate-risk-approval-key-for-tests")
    monkeypatch.setattr(executor_main, "redis", FakeRedis())

    async def no_op_record(*_args, **_kwargs):
        return None

    async def no_duplicate(*_args, **_kwargs):
        return False

    async def no_stack(*_args, **_kwargs):
        return False

    async def keep_size(size, _symbol):
        return size

    async def forbidden_broker_access():
        raise AssertionError("broker must not be acquired after router changes approved terms")

    monkeypatch.setattr(executor_main, "record_guard_decision", no_op_record)
    monkeypatch.setattr(executor_main, "_is_duplicate_order", no_duplicate)
    monkeypatch.setattr(executor_main, "_stacking_blocked", no_stack)
    monkeypatch.setattr(executor_main, "_clamp_lot_size", keep_size)
    monkeypatch.setattr(executor_main, "_get_broker", forbidden_broker_access)
    monkeypatch.setattr(
        executor_main.smart_router,
        "route_order",
        lambda *_args, **_kwargs: RoutingDecision(
            order_type=OrderType.LIMIT,
            price=2499.5,
            reason="test altered route",
            adjusted=True,
        ),
    )
    approved = {
        "version": 1,
        "proposal_id": "router-contract-1",
        "expires_at": int(time.time()) + 60,
        "symbol": "XAUUSD",
        "side": "BUY",
        "order_type": "MARKET",
        "entry": 2500.0,
        "price": 0.0,
        "sl": 2490.0,
        "tp": 2520.0,
        "size": 0.03,
        "signal_timestamp": time.time(),
        "slippage": 10,
    }

    response = await executor_main.send_order(
        executor_main.SendOrderRequest(
            symbol="XAUUSD",
            side="BUY",
            order_type="MARKET",
            size=0.03,
            price=0.0,
            sl=2490.0,
            tp=2520.0,
            slippage=10,
            proposal_id="router-contract-1",
            risk_approval_expires_at=approved["expires_at"],
            risk_approval_signature=approval_signature(approved),
            signal_timestamp=approved["signal_timestamp"],
            risk_approved_entry=2500.0,
            risk_approval_payload=approved,
            bid=2499.0,
            ask=2501.0,
            current_spread=2.0,
        ),
        x_nexus_internal_secret="test-risk-approval-secret",
    )

    assert response.status == "GUARD_BLOCKED_RISK_APPROVAL_MISSING"
    assert response.broker == "none"


@pytest.mark.asyncio
async def test_executor_uses_the_same_canonical_symbol_and_side_that_were_signed(monkeypatch):
    monkeypatch.setenv("NEXUS_TRADING_MODE", "paper")
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-risk-approval-secret")
    monkeypatch.setenv("NEXUS_RISK_APPROVAL_SECRET", "separate-risk-approval-key-for-tests")
    monkeypatch.setattr(executor_main, "redis", FakeRedis())

    async def no_op_record(*_args, **_kwargs):
        return None

    async def no_duplicate(*_args, **_kwargs):
        return False

    async def no_stack(*_args, **_kwargs):
        return False

    async def keep_size(size, _symbol):
        return size

    class Broker:
        order = None

        async def send_order(self, order):
            self.order = order
            return OrderResponse(
                symbol=order.symbol,
                side=order.side.value,
                order_type=order.order_type.value,
                size=order.size,
                status=OrderStatus.ERROR,
                error="test stops before broker side effects",
                broker="paper",
            )

    broker = Broker()
    async def get_broker():
        return broker

    monkeypatch.setattr(executor_main, "record_guard_decision", no_op_record)
    monkeypatch.setattr(executor_main, "_is_duplicate_order", no_duplicate)
    monkeypatch.setattr(executor_main, "_stacking_blocked", no_stack)
    monkeypatch.setattr(executor_main, "_clamp_lot_size", keep_size)
    monkeypatch.setattr(executor_main, "_get_broker", get_broker)
    approved = {
        "version": 1,
        "proposal_id": "canonical-input-1",
        "expires_at": int(time.time()) + 60,
        "symbol": "XAUUSD",
        "side": "BUY",
        "order_type": "MARKET",
        "entry": 2500.0,
        "price": 0.0,
        "sl": 2490.0,
        "tp": 2520.0,
        "size": 0.03,
        "signal_timestamp": time.time(),
        "slippage": 10,
    }

    await executor_main.send_order(
        executor_main.SendOrderRequest(
            symbol=" xauusd ",
            side=" buy ",
            size=0.03,
            sl=2490.0,
            tp=2520.0,
            proposal_id="canonical-input-1",
            risk_approval_expires_at=approved["expires_at"],
            risk_approval_signature=approval_signature(approved),
            signal_timestamp=approved["signal_timestamp"],
            risk_approved_entry=2500.0,
            risk_approval_payload=approved,
        ),
        x_nexus_internal_secret="test-risk-approval-secret",
    )

    assert broker.order is not None
    assert broker.order.symbol == "XAUUSD"
    assert broker.order.side == OrderSide.BUY
