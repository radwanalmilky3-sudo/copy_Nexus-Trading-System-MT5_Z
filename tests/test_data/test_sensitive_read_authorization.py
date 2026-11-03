from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from services.nexus_data import main as data_main


SENSITIVE_READS = [
    "/api/data/performance",
    "/api/data/performance/equity-curve",
    "/api/data/performance/daily",
    "/api/data/performance/by-session",
    "/api/data/performance/by-symbol",
    "/api/data/trades",
    "/api/data/fundamental/latest/event_asset_impacts",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", SENSITIVE_READS)
@pytest.mark.parametrize("provided_secret", [None, "wrong-secret"])
async def test_data_financial_reads_reject_missing_or_wrong_internal_secret(
    monkeypatch, path, provided_secret
):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "configured-data-secret")
    headers = (
        {"X-Nexus-Internal-Secret": provided_secret}
        if provided_secret is not None
        else {}
    )

    async with AsyncClient(
        transport=ASGITransport(app=data_main.app, raise_app_exceptions=False),
        base_url="http://data-test",
    ) as client:
        response = await client.get(path, headers=headers)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_data_performance_read_accepts_valid_internal_secret(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "configured-data-secret")
    monkeypatch.setattr(
        data_main.data_store,
        "get_performance_metrics",
        AsyncMock(return_value={"total_trades": 4}),
    )

    async with AsyncClient(
        transport=ASGITransport(app=data_main.app),
        base_url="http://data-test",
    ) as client:
        response = await client.get(
            "/api/data/performance",
            headers={"X-Nexus-Internal-Secret": "configured-data-secret"},
        )

    assert response.status_code == 200
    assert response.json() == {"total_trades": 4}
