from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from services.nexus_risk import main as risk_main


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("POST", "/api/risk/settings", {}),
        ("POST", "/api/risk/reset-day", None),
        ("POST", "/api/risk/pause?paused=true", None),
    ],
)
async def test_risk_mutating_routes_reject_missing_or_wrong_internal_secret(
    monkeypatch, method, path, payload
):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "configured-risk-secret")

    async with AsyncClient(
        transport=ASGITransport(app=risk_main.app),
        base_url="http://risk-test",
    ) as client:
        missing = await client.request(method, path, json=payload)
        incorrect = await client.request(
            method,
            path,
            json=payload,
            headers={"X-Nexus-Internal-Secret": "wrong-secret"},
        )

    assert missing.status_code == 403
    assert incorrect.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/risk/status",
        "/api/risk/exposure",
        "/api/risk/circuit-breakers",
        "/api/risk/settings",
        "/api/exposure",
    ],
)
async def test_risk_sensitive_reads_reject_missing_or_wrong_internal_secret(
    monkeypatch, path
):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "configured-risk-secret")

    async with AsyncClient(
        transport=ASGITransport(app=risk_main.app),
        base_url="http://risk-test",
    ) as client:
        missing = await client.get(path)
        incorrect = await client.get(
            path,
            headers={"X-Nexus-Internal-Secret": "wrong-secret"},
        )

    assert missing.status_code == 403
    assert incorrect.status_code == 403


@pytest.mark.asyncio
async def test_risk_exposure_accepts_valid_internal_secret(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "configured-risk-secret")

    async with AsyncClient(
        transport=ASGITransport(app=risk_main.app),
        base_url="http://risk-test",
    ) as client:
        response = await client.get(
            "/api/exposure",
            headers={"X-Nexus-Internal-Secret": "configured-risk-secret"},
        )

    assert response.status_code == 200
