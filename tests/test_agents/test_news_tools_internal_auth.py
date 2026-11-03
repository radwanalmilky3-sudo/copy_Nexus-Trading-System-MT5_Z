from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from services.nexus_agents.tools import news_tools


@pytest.mark.asyncio
async def test_news_tools_send_shared_internal_credential(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "news-test-secret")
    seen_headers = []

    class FakeClient:
        async def get(self, url, *, params=None, headers=None):
            seen_headers.append(headers)
            body = {"symbol": "XAUUSD"} if "/sentiment/" in url else []
            return SimpleNamespace(status_code=200, json=lambda: body)

    @asynccontextmanager
    async def fake_new_client(**_kwargs):
        yield FakeClient()

    monkeypatch.setattr(news_tools, "new_client", fake_new_client)

    await news_tools.fetch_news("gold")
    await news_tools.get_calendar()
    await news_tools.get_sentiment("XAUUSD")

    assert seen_headers == [
        {"X-Nexus-Internal-Secret": "news-test-secret"},
        {"X-Nexus-Internal-Secret": "news-test-secret"},
        {"X-Nexus-Internal-Secret": "news-test-secret"},
    ]


@pytest.mark.asyncio
async def test_news_tools_map_symbol_and_calendar_hours_to_service_contract(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "news-test-secret")
    seen_requests = []

    class FakeClient:
        async def get(self, url, *, params=None, headers=None):
            seen_requests.append((url, params, headers))
            return SimpleNamespace(status_code=200, json=lambda: [])

    @asynccontextmanager
    async def fake_new_client(**_kwargs):
        yield FakeClient()

    monkeypatch.setattr(news_tools, "new_client", fake_new_client)

    await news_tools.fetch_news("XAUUSD")
    await news_tools.get_calendar(hours=6)

    assert seen_requests == [
        (
            f"{news_tools.NEWS_SERVICE_URL}/api/news/latest",
            {"symbol": "XAUUSD", "limit": 20},
            {"X-Nexus-Internal-Secret": "news-test-secret"},
        ),
        (
            f"{news_tools.NEWS_SERVICE_URL}/api/news/calendar",
            {"minutes": 360},
            {"X-Nexus-Internal-Secret": "news-test-secret"},
        ),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "args"),
    [
        ("fetch_news", ("XAUUSD",)),
        ("get_calendar", (6,)),
        ("get_sentiment", ("XAUUSD",)),
    ],
)
async def test_news_tools_raise_when_service_returns_failure(monkeypatch, tool_name, args):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "news-test-secret")

    class FakeClient:
        async def get(self, *_args, **_kwargs):
            return SimpleNamespace(status_code=503, json=lambda: {})

    @asynccontextmanager
    async def fake_new_client(**_kwargs):
        yield FakeClient()

    monkeypatch.setattr(news_tools, "new_client", fake_new_client)

    with pytest.raises(RuntimeError, match="news service unavailable"):
        await getattr(news_tools, tool_name)(*args)
