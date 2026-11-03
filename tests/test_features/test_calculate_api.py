from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from services.nexus_features import main as features_main


def _bars(count: int = 60) -> list[dict[str, float]]:
    return [
        {
            "open": 100.0 + i,
            "high": 102.0 + i,
            "low": 99.0 + i,
            "close": 101.0 + i,
            "volume": 10.0,
        }
        for i in range(count)
    ]


def _mock_feature_calculations(monkeypatch):
    monkeypatch.setattr(features_main, "calculate_all", lambda df: df)
    monkeypatch.setattr(features_main, "tag_dataframe", lambda df: df)
    monkeypatch.setattr(
        features_main,
        "_extract_features",
        lambda df: {"close": float(df["close"].iloc[-1])},
    )
    monkeypatch.setattr(features_main, "tag_session", lambda _now: "TEST")
    monkeypatch.setattr(features_main, "detect_sr_levels", lambda _df: [])
    monkeypatch.setattr(features_main, "find_round_numbers", lambda _close: [])
    monkeypatch.setattr(features_main, "detect_order_blocks", lambda _df: [])


@pytest.mark.asyncio
async def test_empty_ohlcv_uses_cached_bars_and_returns_levels(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "features-test-secret")
    _mock_feature_calculations(monkeypatch)

    class FakeRedis:
        async def get(self, key):
            assert key == "nexus:ohlcv:XAUUSD:M15"
            return json.dumps(_bars())

    monkeypatch.setattr(features_main, "redis_pool", FakeRedis())
    async with AsyncClient(
        transport=ASGITransport(app=features_main.app),
        base_url="http://features-test",
    ) as client:
        response = await client.post(
            "/api/features/calculate",
            json={
                "symbol": "XAUUSD",
                "timeframe": "M15",
                "ohlcv": [],
                "include_levels": True,
            },
            headers={"X-Nexus-Internal-Secret": "features-test-secret"},
        )

    assert response.status_code == 200
    assert response.json()["bar_count"] == 60
    assert response.json()["levels"] == {
        "support_resistance": [],
        "round_numbers": [],
        "order_blocks": [],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("provided_secret", [None, "wrong-secret"])
async def test_calculate_route_rejects_missing_or_wrong_internal_secret(
    monkeypatch, provided_secret
):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "features-test-secret")
    _mock_feature_calculations(monkeypatch)
    headers = (
        {"X-Nexus-Internal-Secret": provided_secret}
        if provided_secret is not None
        else {}
    )
    async with AsyncClient(
        transport=ASGITransport(app=features_main.app),
        base_url="http://features-test",
    ) as client:
        response = await client.post(
            "/api/features/calculate",
            json={"symbol": "XAUUSD", "ohlcv": _bars(1)},
            headers=headers,
        )

    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/features/XAUUSD/M15", "/api/features/institutional/XAUUSD"])
@pytest.mark.parametrize("provided_secret", [None, "wrong-secret"])
async def test_feature_reads_reject_missing_or_wrong_internal_secret(
    monkeypatch, path, provided_secret
):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "features-test-secret")
    headers = (
        {"X-Nexus-Internal-Secret": provided_secret}
        if provided_secret is not None
        else {}
    )
    async with AsyncClient(
        transport=ASGITransport(app=features_main.app),
        base_url="http://features-test",
    ) as client:
        response = await client.get(path, headers=headers)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_feature_agent_client_forwards_internal_credential(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "features-test-secret")
    request = AsyncMock(return_value=SimpleNamespace(
        status_code=200,
        json=lambda: {"levels": {}},
    ))

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return await request(*args, **kwargs)

    monkeypatch.setattr("httpx.AsyncClient", FakeClient)
    from services.nexus_agents.agents.market_analyst import MarketAnalystAgent

    agent = MarketAnalystAgent.__new__(MarketAnalystAgent)
    agent.redis = None
    await agent._get_advanced_levels("XAUUSD", "M15")

    assert request.await_args.kwargs["headers"] == {
        "X-Nexus-Internal-Secret": "features-test-secret"
    }


@pytest.mark.asyncio
async def test_agent_indicator_client_forwards_internal_credential(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "features-test-secret")
    request = AsyncMock(return_value=SimpleNamespace(
        status_code=200,
        json=lambda: {"features": {"rsi": 55}},
    ))

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            return await request(*args, **kwargs)

    monkeypatch.setattr("services.nexus_agents.tools.market_tools.new_client", lambda **kwargs: FakeClient())
    from services.nexus_agents.tools.market_tools import _fetch_indicators_for_symbol

    result = await _fetch_indicators_for_symbol("XAUUSD", "M15")

    assert result == {"rsi": 55}
    assert request.await_args.kwargs["headers"] == {
        "X-Nexus-Internal-Secret": "features-test-secret"
    }
