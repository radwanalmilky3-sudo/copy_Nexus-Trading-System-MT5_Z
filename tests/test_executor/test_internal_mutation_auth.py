from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from services.nexus_executor import main as executor_main
from services.nexus_executor.broker_adapter import OrderStatus


@pytest.mark.asyncio
@pytest.mark.parametrize("provided_secret", [None, "wrong-secret"])
@pytest.mark.parametrize("operation", ["order", "close", "modify"])
async def test_executor_position_mutations_reject_missing_or_wrong_secret_before_broker(
    monkeypatch, provided_secret, operation
):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "configured-executor-secret")
    broker = SimpleNamespace(
        close_position=AsyncMock(return_value=SimpleNamespace(
            is_success=lambda: False,
            order_id="test-position",
            status=OrderStatus.ERROR,
            fill_price=0.0,
            error="test only",
        )),
        modify_order=AsyncMock(return_value=SimpleNamespace(
            order_id="test-position",
            status=OrderStatus.ERROR,
            sl=0.0,
            tp=0.0,
            error="test only",
        )),
    )
    get_broker = AsyncMock(return_value=broker)
    evaluate_guard = AsyncMock()
    monkeypatch.setattr(executor_main, "_get_broker", get_broker)
    monkeypatch.setattr(executor_main, "evaluate_executor_guard", evaluate_guard)

    headers = (
        {"X-Nexus-Internal-Secret": provided_secret}
        if provided_secret is not None
        else {}
    )
    async with AsyncClient(
        transport=ASGITransport(app=executor_main.app),
        base_url="http://executor-test",
    ) as client:
        if operation == "order":
            response = await client.post(
                "/api/executor/order",
                json={"symbol": "XAUUSD", "side": "BUY"},
                headers=headers,
            )
        elif operation == "close":
            response = await client.delete(
                "/api/executor/position/test-position", headers=headers
            )
        else:
            response = await client.put(
                "/api/executor/position/test-position",
                json={"sl": 2490.0},
                headers=headers,
            )

    assert response.status_code == 403
    evaluate_guard.assert_not_awaited()
    get_broker.assert_not_awaited()
    broker.close_position.assert_not_awaited()
    broker.modify_order.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [0, -0.1, float("nan"), float("inf")])
async def test_executor_close_rejects_nonpositive_or_nonfinite_size_before_broker(
    monkeypatch, size
):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "configured-executor-secret")
    broker = SimpleNamespace(close_position=AsyncMock())
    get_broker = AsyncMock(return_value=broker)
    monkeypatch.setattr(executor_main, "_get_broker", get_broker)

    async with AsyncClient(
        transport=ASGITransport(app=executor_main.app),
        base_url="http://executor-test",
    ) as client:
        response = await client.delete(
            "/api/executor/position/test-position",
            params={"size": str(size)},
            headers={"X-Nexus-Internal-Secret": "configured-executor-secret"},
        )

    assert response.status_code == 422
    get_broker.assert_not_awaited()
    broker.close_position.assert_not_awaited()


@pytest.mark.asyncio
async def test_executor_stacking_check_fails_closed_when_position_snapshot_fails(monkeypatch):
    async def unavailable(_symbol, _side):
        raise RuntimeError("positions unavailable")

    monkeypatch.setattr(executor_main, "_open_same_direction_count", unavailable)

    assert await executor_main._stacking_blocked("XAUUSD", "BUY") is True
