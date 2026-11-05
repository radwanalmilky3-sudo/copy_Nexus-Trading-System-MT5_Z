"""N4 pins (2026-11-05): polling façades translate honest absence to 200.

The dashboard polls /api/v2/market/candles and /api/agents/decision/{symbol}
continuously. While the upstream services answer 404 for "no data yet" (N6
semantics — canonical at the service layer, load-bearing for service
consumers), the *presentation façade* at the gateway translates that absence
into an explicit 200 state so the browser console stays free of the
unsuppressible "Failed to load resource: 404" line for an expected poll:

- candles  : 200 with an empty series ([] — never synthetic bars)
- decision : 200 with a bare {symbol, available: false} marker (never
             fabricated verdict fields)

Honesty is preserved: absence is stated explicitly, UI-05/UI-06 still hold.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from services.nexus_api.routers import agents, market


class _Fake404Response:
    status_code = 404
    text = '{"detail":"absent"}'

    @staticmethod
    def json():
        return {"detail": "absent"}


class _FakeClientContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, *args, **kwargs):
        return _Fake404Response()


def test_candles_facade_translates_upstream_404_to_empty_series(monkeypatch):
    """N4 pin: candles polling answers 200 [] when nexus-data holds nothing."""
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-internal-secret")
    monkeypatch.setattr(market, "new_client", lambda **kwargs: _FakeClientContext())
    payload = asyncio.run(market.candles(symbol="n6unknownzzz", timeframe="M15", count=5))
    assert payload == {"success": True, "data": [], "timestamp": payload["timestamp"]}
    assert payload["data"] == [], "empty series must be explicit — no synthetic bars"


def test_decision_facade_translates_upstream_404_to_not_available(monkeypatch):
    """N4 pin: decision polling answers 200 {available:false} — bare shape."""
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-internal-secret")
    monkeypatch.setattr(agents, "_require", AsyncMock(return_value=None))
    monkeypatch.setattr(agents, "new_client", lambda **kwargs: _FakeClientContext())
    payload = asyncio.run(
        agents.latest_decision(symbol="n6unknownzzz", actor=None, db=None)
    )
    assert payload == {"symbol": "N6UNKNOWNZZZ", "available": False}
    assert "verdict" not in payload, "absence must never carry fabricated fields"


def test_candles_facade_still_502_on_unreachable_data_service(monkeypatch):
    """N4 pin: translation covers absence only — real failures stay errors."""
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-internal-secret")

    class _BoomContext:
        async def __aenter__(self):
            raise httpx.ConnectError("boom")

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(market, "new_client", lambda **kwargs: _BoomContext())
    with pytest.raises(Exception) as exc:
        asyncio.run(market.candles(symbol="XAUUSD", timeframe="M15", count=5))
    assert "unreachable" in str(getattr(exc.value, "detail", exc.value))
