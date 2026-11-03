from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from services.nexus_executor import main as executor_main


def _fake_broker():
    return SimpleNamespace(
        get_positions=AsyncMock(return_value=[]),
        get_account_info=AsyncMock(return_value=SimpleNamespace(
            balance=100.0,
            equity=101.0,
            margin=2.0,
            free_margin=99.0,
            currency="USD",
            broker="test",
        )),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("provided_secret", [None, "incorrect"])
async def test_positions_reject_missing_or_invalid_internal_secret_before_broker(
    monkeypatch, provided_secret
):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "configured-executor-secret")
    get_broker = AsyncMock(return_value=_fake_broker())
    monkeypatch.setattr(executor_main, "_get_broker", get_broker)
    headers = (
        {"X-Nexus-Internal-Secret": provided_secret}
        if provided_secret is not None
        else {}
    )

    async with AsyncClient(
        transport=ASGITransport(app=executor_main.app),
        base_url="http://executor-test",
    ) as client:
        response = await client.get("/api/executor/positions", headers=headers)

    assert response.status_code == 403
    get_broker.assert_not_awaited()


@pytest.mark.asyncio
async def test_positions_reject_when_internal_secret_is_not_configured(monkeypatch):
    monkeypatch.delenv("NEXUS_INTERNAL_API_SECRET", raising=False)
    get_broker = AsyncMock(return_value=_fake_broker())
    monkeypatch.setattr(executor_main, "_get_broker", get_broker)

    async with AsyncClient(
        transport=ASGITransport(app=executor_main.app),
        base_url="http://executor-test",
    ) as client:
        response = await client.get("/api/executor/positions")

    assert response.status_code == 503
    get_broker.assert_not_awaited()


@pytest.mark.asyncio
async def test_positions_accept_valid_internal_secret(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "configured-executor-secret")
    broker = _fake_broker()
    get_broker = AsyncMock(return_value=broker)
    monkeypatch.setattr(executor_main, "_get_broker", get_broker)

    async with AsyncClient(
        transport=ASGITransport(app=executor_main.app),
        base_url="http://executor-test",
    ) as client:
        response = await client.get(
            "/api/executor/positions",
            headers={"X-Nexus-Internal-Secret": "configured-executor-secret"},
        )

    assert response.status_code == 200
    assert response.json()["account"]["equity"] == 101.0
    broker.get_positions.assert_awaited_once()
