from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from services.nexus_monitor import main as monitor_main


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/monitor/health", "/api/monitor/metrics"])
@pytest.mark.parametrize("provided_secret", [None, "wrong-secret"])
async def test_monitor_operational_reads_reject_missing_or_wrong_secret(
    monkeypatch, path, provided_secret
):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "configured-monitor-secret")
    headers = (
        {"X-Nexus-Internal-Secret": provided_secret}
        if provided_secret is not None
        else {}
    )

    async with AsyncClient(
        transport=ASGITransport(app=monitor_main.app),
        base_url="http://monitor-test",
    ) as client:
        response = await client.get(path, headers=headers)

    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/health", "/metrics"])
async def test_monitor_public_probe_and_prometheus_scrape_remain_available(path):
    async with AsyncClient(
        transport=ASGITransport(app=monitor_main.app),
        base_url="http://monitor-test",
    ) as client:
        response = await client.get(path)

    assert response.status_code == 200
