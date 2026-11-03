from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from services.nexus_ml import main as ml_main


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/ml/train", {}),
        ("/api/traders/train", {}),
        ("/api/traders/mode/switch", {"mode": "swing"}),
        ("/api/traders/retrain/force", None),
        ("/api/traders/autonomous/toggle?enable=true", None),
    ],
)
@pytest.mark.parametrize("provided_secret", [None, "wrong-secret"])
async def test_ml_mutations_reject_missing_or_wrong_internal_secret(
    monkeypatch, path, payload, provided_secret
):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "configured-ml-secret")
    headers = (
        {"X-Nexus-Internal-Secret": provided_secret}
        if provided_secret is not None
        else {}
    )

    async with AsyncClient(
        transport=ASGITransport(app=ml_main.app),
        base_url="http://ml-test",
    ) as client:
        response = await client.post(path, json=payload, headers=headers)

    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/ml/predict/EURUSD",
        "/api/ml/models/status",
        "/api/ml/retrain/status",
    ],
)
@pytest.mark.parametrize("provided_secret", [None, "wrong-secret"])
async def test_ml_sensitive_reads_reject_missing_or_wrong_internal_secret(
    monkeypatch, path, provided_secret
):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "configured-ml-secret")
    headers = (
        {"X-Nexus-Internal-Secret": provided_secret}
        if provided_secret is not None
        else {}
    )

    async with AsyncClient(
        transport=ASGITransport(app=ml_main.app, raise_app_exceptions=False),
        base_url="http://ml-test",
    ) as client:
        response = await client.get(path, headers=headers)

    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/traders/status",
        "/api/traders/predict/EURUSD",
        "/api/traders/predict/ml/EURUSD",
        "/api/traders/comparison",
        "/api/traders/performance/ml",
        "/api/traders/signals/recent/ml",
        "/api/traders/mode",
        "/api/traders/dynamic-params/EURUSD",
        "/api/traders/memory",
        "/api/traders/autonomous/status",
    ],
)
@pytest.mark.parametrize("provided_secret", [None, "wrong-secret"])
async def test_parallel_trader_reads_reject_missing_or_wrong_internal_secret(
    monkeypatch, path, provided_secret
):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "configured-ml-secret")
    headers = (
        {"X-Nexus-Internal-Secret": provided_secret}
        if provided_secret is not None
        else {}
    )

    async with AsyncClient(
        transport=ASGITransport(app=ml_main.app, raise_app_exceptions=False),
        base_url="http://ml-test",
    ) as client:
        response = await client.get(path, headers=headers)

    assert response.status_code == 403
