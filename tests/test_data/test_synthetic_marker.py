from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from shared.models import OHLCV, Tick


def test_synthetic_tick_helper_marks_source_in_band():
    from services.nexus_data import main

    tick = main._synthetic_tick("XAUUSD")

    assert isinstance(tick, Tick)
    assert tick.symbol == "XAUUSD"
    assert tick.bid > 0
    assert tick.ask > tick.bid
    assert tick.source == "synthetic"


def test_synthetic_ohlcv_helper_marks_every_row_in_band():
    from services.nexus_data import main

    bars = main._synthetic_ohlcv("XAUUSD", "M15", 4)

    assert len(bars) == 4
    assert all(isinstance(bar, OHLCV) for bar in bars)
    assert all(bar.high >= bar.low for bar in bars)
    assert all(bar.source == "synthetic" for bar in bars)


@pytest.mark.asyncio
async def test_ticks_endpoint_marks_synthetic_rows_in_json(monkeypatch):
    from services.nexus_data import main

    class EmptyCache:
        async def get_tick_history(self, symbol: str, count: int):
            return []

    class EmptyStore:
        async def query_latest_ticks(self, symbol: str, count: int):
            return []

    class DisconnectedMT5:
        connected = False

    monkeypatch.setattr(main, "SYNTHETIC_FALLBACK", True)
    monkeypatch.setattr(main, "tick_cache", EmptyCache())
    monkeypatch.setattr(main, "data_store", EmptyStore())
    monkeypatch.setattr(main, "mt5", DisconnectedMT5())

    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.get("/api/data/ticks/XAUUSD?source=db")

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "XAUUSD"
    assert rows[0]["source"] == "synthetic"


@pytest.mark.asyncio
async def test_ohlcv_endpoint_marks_synthetic_rows_in_json(monkeypatch, operational_store):
    from services.nexus_data import main

    class DisconnectedMT5:
        connected = False

    monkeypatch.setattr(main, "SYNTHETIC_FALLBACK", True)
    monkeypatch.setattr(main, "data_store", operational_store)
    monkeypatch.setattr(main, "mt5", DisconnectedMT5())

    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.get("/api/data/ohlcv/XAUUSD/M15?limit=3")

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 3
    assert all(row["symbol"] == "XAUUSD" for row in rows)
    assert all(row["source"] == "synthetic" for row in rows)


@pytest.mark.asyncio
async def test_real_tick_rows_do_not_gain_source_key(monkeypatch):
    from services.nexus_data import main

    class CacheWithTick:
        async def get_tick_history(self, symbol: str, count: int):
            return [Tick(symbol="XAUUSD", bid=2350.0, ask=2350.25)]

    monkeypatch.setattr(main, "tick_cache", CacheWithTick())

    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.get("/api/data/ticks/XAUUSD?source=cache")

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert "source" not in rows[0]
    assert rows[0]["bid"] == 2350.0
    assert rows[0]["spread"] == pytest.approx(0.25)


@pytest.mark.asyncio
async def test_real_ohlcv_rows_do_not_gain_source_key(monkeypatch, operational_store):
    from services.nexus_data import main
    from datetime import datetime, timezone

    await operational_store.insert_ohlcv_batch([OHLCV(
        symbol="XAUUSD", timeframe="M15", open=2350.0, high=2355.0,
        low=2348.0, close=2352.0, volume=100.0,
        timestamp=datetime(2026, 10, 18, 10, 15, tzinfo=timezone.utc),
    )])

    class DisconnectedMT5:
        connected = False

    monkeypatch.setattr(main, "data_store", operational_store)
    monkeypatch.setattr(main, "mt5", DisconnectedMT5())

    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.get("/api/data/ohlcv/XAUUSD/M15?limit=1")

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert "source" not in rows[0]
    assert rows[0]["close"] == 2352.0
