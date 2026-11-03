from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from types import SimpleNamespace
from unittest.mock import AsyncMock

from services.nexus_news import main as news_main


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/news/latest",
        "/api/news/calendar",
        "/api/news/sentiment/XAUUSD",
        "/api/news/sentinel/alerts",
        "/api/news/sentinel/blackout",
        "/api/news/sentinel/status",
    ],
)
@pytest.mark.parametrize("provided_secret", [None, "wrong-secret"])
async def test_news_service_reads_reject_missing_or_wrong_internal_secret(
    monkeypatch, path, provided_secret
):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "news-test-secret")
    monkeypatch.setattr(
        news_main,
        "_calendar",
        SimpleNamespace(get_upcoming_events=AsyncMock(return_value=[])),
    )
    monkeypatch.setattr(
        news_main,
        "_sentiment",
        SimpleNamespace(aggregate_social_sentiment=AsyncMock(return_value=0.1)),
    )
    monkeypatch.setattr(news_main, "_redis", SimpleNamespace(lrange=AsyncMock(return_value=[])))
    monkeypatch.setattr(
        news_main,
        "_fundamental",
        SimpleNamespace(blackout={"active": False}, source_health={}),
    )
    headers = (
        {"X-Nexus-Internal-Secret": provided_secret}
        if provided_secret is not None
        else {}
    )
    async with AsyncClient(
        transport=ASGITransport(app=news_main.app),
        base_url="http://news-test",
    ) as client:
        response = await client.get(path, headers=headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_news_service_reads_accept_valid_internal_secret(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "news-test-secret")
    async with AsyncClient(
        transport=ASGITransport(app=news_main.app),
        base_url="http://news-test",
    ) as client:
        response = await client.get(
            "/api/news/latest",
            headers={"X-Nexus-Internal-Secret": "news-test-secret"},
        )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_news_health_probe_remains_public():
    async with AsyncClient(
        transport=ASGITransport(app=news_main.app),
        base_url="http://news-test",
    ) as client:
        response = await client.get("/health")
    assert response.status_code == 200
