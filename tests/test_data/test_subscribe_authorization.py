from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock

from services.nexus_data import main as data_main


@pytest.mark.asyncio
@pytest.mark.parametrize("provided_secret", [None, "wrong-secret"])
async def test_runtime_broker_subscription_rejects_missing_or_wrong_internal_secret(
    monkeypatch, provided_secret
):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "configured-data-secret")
    headers = (
        {"X-Nexus-Internal-Secret": provided_secret}
        if provided_secret is not None
        else {}
    )

    async with AsyncClient(
        transport=ASGITransport(app=data_main.app),
        base_url="http://data-test",
    ) as client:
        response = await client.post(
            "/api/data/subscribe",
            json={"symbols": ["EURUSD"], "broker": "mt5"},
            headers=headers,
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_runtime_broker_subscription_accepts_authorized_request_with_mock_connector(
    monkeypatch,
):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "configured-data-secret")
    connector = type("MockConnector", (), {})()
    connector.connected = True
    connector.stream_ticks = AsyncMock(return_value=None)
    tasks = []
    monkeypatch.setattr(data_main, "mt5", connector)
    monkeypatch.setattr(data_main, "_streaming_tasks", tasks)

    async with AsyncClient(
        transport=ASGITransport(app=data_main.app),
        base_url="http://data-test",
    ) as client:
        response = await client.post(
            "/api/data/subscribe",
            json={"symbols": ["EURUSD"], "broker": "mt5"},
            headers={"X-Nexus-Internal-Secret": "configured-data-secret"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "subscribed"
    assert len(tasks) == 1
    await tasks[0]
    connector.stream_ticks.assert_awaited_once()

