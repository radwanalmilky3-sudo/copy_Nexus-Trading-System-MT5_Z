from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock

from services.nexus_news import main as news_main


@pytest.mark.asyncio
@pytest.mark.parametrize("provided_secret", [None, "wrong-secret"])
async def test_news_analysis_rejects_missing_or_wrong_internal_secret(
    monkeypatch, provided_secret
):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "news-test-secret")
    finbert = AsyncMock(return_value=0.25)
    monkeypatch.setattr("services.nexus_news.social_sentiment._finbert_score", finbert)
    headers = (
        {"X-Nexus-Internal-Secret": provided_secret}
        if provided_secret is not None
        else {}
    )
    async with AsyncClient(
        transport=ASGITransport(app=news_main.app),
        base_url="http://news-test",
    ) as client:
        response = await client.post(
            "/api/news/analyze",
            json={"text": "The central bank held rates steady."},
            headers=headers,
        )
    assert response.status_code == 403
    finbert.assert_not_awaited()


@pytest.mark.asyncio
async def test_news_analysis_accepts_internal_secret_without_loading_finbert(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "news-test-secret")

    async def finite_score(_text):
        return 0.25

    monkeypatch.setattr(
        "services.nexus_news.social_sentiment._finbert_score", finite_score
    )
    async with AsyncClient(
        transport=ASGITransport(app=news_main.app),
        base_url="http://news-test",
    ) as client:
        response = await client.post(
            "/api/news/analyze",
            json={"text": "The central bank held rates steady."},
            headers={"X-Nexus-Internal-Secret": "news-test-secret"},
        )
    assert response.status_code == 200
    assert response.json()["finbert_score"] == 0.25


@pytest.mark.asyncio
async def test_news_analysis_rejects_text_over_10000_characters(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "news-test-secret")
    monkeypatch.setattr(
        "services.nexus_news.social_sentiment._finbert_score",
        AsyncMock(return_value=0.25),
    )
    async with AsyncClient(
        transport=ASGITransport(app=news_main.app),
        base_url="http://news-test",
    ) as client:
        response = await client.post(
            "/api/news/analyze",
            json={"text": "x" * 10_001},
            headers={"X-Nexus-Internal-Secret": "news-test-secret"},
        )
    assert response.status_code == 422
