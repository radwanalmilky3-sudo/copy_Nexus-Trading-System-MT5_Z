from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from services.nexus_monitor import main as monitor_main


@pytest.mark.asyncio
@pytest.mark.parametrize("provided_secret", [None, "wrong-secret"])
async def test_monitor_alert_rejects_missing_or_wrong_internal_secret(
    monkeypatch, provided_secret
):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "configured-monitor-secret")
    send_message = AsyncMock(return_value=True)
    monkeypatch.setattr(monitor_main.telegram, "send_message", send_message)

    headers = (
        {"X-Nexus-Internal-Secret": provided_secret}
        if provided_secret is not None
        else {}
    )
    async with AsyncClient(
        transport=ASGITransport(app=monitor_main.app),
        base_url="http://monitor-test",
    ) as client:
        response = await client.post(
            "/api/monitor/alert",
            json={"type": "warning", "message": "test-only"},
            headers=headers,
        )

    assert response.status_code == 403
    send_message.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("provided_secret", [None, "wrong-secret", "configured-monitor-secret"])
async def test_monitor_performance_rejects_missing_or_wrong_internal_secret(
    monkeypatch, provided_secret
):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "configured-monitor-secret")
    client_factory_calls = []

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"trades": []},
            )

    def client_factory(**kwargs):
        client_factory_calls.append(kwargs)
        return FakeClient()

    monkeypatch.setattr(monitor_main, "new_client", client_factory)
    monkeypatch.setattr(
        monitor_main.performance,
        "calculate_metrics",
        lambda _trades: SimpleNamespace(
            total_pnl=0, win_rate=0, profit_factor=0, sharpe_ratio=0,
            sortino_ratio=0, max_drawdown=0, total_trades=0, winning_trades=0,
            losing_trades=0, avg_win=0, avg_loss=0, best_trade=0, worst_trade=0,
            expectancy=0, consecutive_wins=0, consecutive_losses=0,
        ),
    )

    headers = (
        {"X-Nexus-Internal-Secret": provided_secret}
        if provided_secret is not None
        else {}
    )
    async with AsyncClient(
        transport=ASGITransport(app=monitor_main.app),
        base_url="http://monitor-test",
    ) as client:
        response = await client.get("/api/monitor/performance", headers=headers)

    if provided_secret == "configured-monitor-secret":
        assert response.status_code == 200
        assert client_factory_calls == [{"timeout": 5.0}]
    else:
        assert response.status_code == 403
        assert client_factory_calls == []
