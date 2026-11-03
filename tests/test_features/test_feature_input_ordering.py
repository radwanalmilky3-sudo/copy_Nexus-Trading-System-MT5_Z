from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from services.nexus_features import main as features_main
from services.nexus_features.multi_timeframe import aggregate_features
from services.nexus_features.ohlcv import chronological_bars


def _bars():
    older = {"timestamp": "2026-10-14T10:00:00+00:00", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1}
    newer = {"timestamp": "2026-10-14T10:15:00+00:00", "open": 20, "high": 21, "low": 19, "close": 20, "volume": 1}
    return older, newer


@pytest.mark.asyncio
async def test_calculate_endpoint_uses_latest_timestamp_not_last_input_row(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "features-test-secret")
    monkeypatch.setattr(features_main, "calculate_all", lambda df: df)
    monkeypatch.setattr(features_main, "tag_dataframe", lambda df: df)
    monkeypatch.setattr(features_main, "_extract_features", lambda df: {"close": float(df.iloc[-1]["close"])})
    monkeypatch.setattr(features_main, "tag_session", lambda _now: "TEST")
    older, newer = _bars()

    async with AsyncClient(transport=ASGITransport(app=features_main.app), base_url="http://features-test") as client:
        response = await client.post(
            "/api/features/calculate",
            headers={"X-Nexus-Internal-Secret": "features-test-secret"},
            json={"symbol": "XAUUSD", "timeframe": "M15", "ohlcv": [newer, older]},
        )

    assert response.status_code == 200
    assert response.json()["features"]["close"] == 20


@pytest.mark.asyncio
async def test_aggregate_features_uses_latest_timestamp_not_last_cached_row(monkeypatch):
    older, newer = _bars()
    redis = AsyncMock()
    redis.get.return_value = json.dumps([newer, older])
    monkeypatch.setattr("services.nexus_features.multi_timeframe.calculate_all", lambda df: df)

    result = await aggregate_features("XAUUSD", ["M15"], redis=redis)

    assert result["M15"]["close"] == 20


def test_chronological_order_compares_instants_across_timezone_offsets():
    utc_later = {"timestamp": "2026-10-14T10:15:00+00:00"}
    offset_earlier = {"timestamp": "2026-10-14T12:00:00+03:00"}

    assert chronological_bars([utc_later, offset_earlier]) == [offset_earlier, utc_later]


def test_chronological_order_does_not_guess_when_timestamps_are_incomplete():
    newest = {"timestamp": "2026-10-14T10:15:00+00:00"}
    undated = {"close": 100}

    assert chronological_bars([newest, undated]) == [newest, undated]


@pytest.mark.asyncio
async def test_calculate_endpoint_rejects_unsupported_timeframe(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "features-test-secret")
    async with AsyncClient(transport=ASGITransport(app=features_main.app), base_url="http://features-test") as client:
        response = await client.post(
            "/api/features/calculate",
            headers={"X-Nexus-Internal-Secret": "features-test-secret"},
            json={"symbol": "XAUUSD", "timeframe": "M2", "ohlcv": [_bars()[0]]},
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_aggregate_features_rejects_unsupported_timeframe():
    with pytest.raises(ValueError, match="Unsupported timeframe"):
        await aggregate_features("XAUUSD", ["M2"], redis=AsyncMock())
