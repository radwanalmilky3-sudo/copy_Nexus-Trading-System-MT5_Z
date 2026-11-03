from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from services.nexus_agents import main as agents_main


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("POST", "/api/agents/evaluate/EURUSD", {}),
        ("POST", "/api/strategies/research", {"n": 1}),
        ("POST", "/api/strategies/test-strategy/reevaluate", None),
        ("PUT", "/api/strategies/test-strategy/status", {"status": "active"}),
        ("POST", "/api/agents/brief/generate?symbol=XAUUSD", None),
    ],
)
@pytest.mark.parametrize("provided_secret", [None, "wrong-secret"])
async def test_agent_mutations_reject_missing_or_wrong_internal_secret(
    monkeypatch, method, path, payload, provided_secret
):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "configured-agents-secret")
    headers = (
        {"X-Nexus-Internal-Secret": provided_secret}
        if provided_secret is not None
        else {}
    )

    async with AsyncClient(
        transport=ASGITransport(app=agents_main.app),
        base_url="http://agents-test",
    ) as client:
        response = await client.request(method, path, json=payload, headers=headers)

    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/agents/brain/budget",
        "/api/agents/shadow-trades/stats",
        "/api/agents/status",
        "/api/strategies",
        "/api/strategies/research/log",
        "/api/strategies/strategy-1",
        "/api/agents/decision/EURUSD",
        "/api/agents/reasoning/cycle-1",
    ],
)
@pytest.mark.parametrize("provided_secret", [None, "wrong-secret"])
async def test_agent_sensitive_reads_reject_missing_or_wrong_internal_secret(
    monkeypatch, path, provided_secret
):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "configured-agents-secret")
    headers = (
        {"X-Nexus-Internal-Secret": provided_secret}
        if provided_secret is not None
        else {}
    )

    async with AsyncClient(
        transport=ASGITransport(app=agents_main.app, raise_app_exceptions=False),
        base_url="http://agents-test",
    ) as client:
        response = await client.get(path, headers=headers)

    assert response.status_code == 403

