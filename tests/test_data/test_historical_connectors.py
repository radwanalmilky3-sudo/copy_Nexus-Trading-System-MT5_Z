from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_ccxt_rejects_unknown_timeframe_before_provider_call():
    from services.nexus_data.ccxt_connector import CCXTConnector

    connector = CCXTConnector()
    connector._connected = True
    connector._exchange = SimpleNamespace(fetch_ohlcv=lambda *args, **kwargs: pytest.fail("provider called"))

    with pytest.raises(ValueError, match="Unsupported timeframe"):
        await connector.get_ohlcv("BTC/USDT", "90m", 10)


@pytest.mark.asyncio
async def test_ibkr_rejects_unknown_timeframe_before_provider_call():
    from services.nexus_data.ibkr_connector import IBKRConnector

    connector = IBKRConnector()
    connector._connected = True
    connector._ib = SimpleNamespace()

    with pytest.raises(ValueError, match="Unsupported timeframe"):
        await connector.get_ohlcv("AAPL", "90m", 10)


@pytest.mark.asyncio
async def test_mt5_preserves_single_returned_completed_bar(monkeypatch):
    from services.nexus_data import mt5_connector

    connector = mt5_connector.MT5Connector()
    connector._connected = True
    monkeypatch.setattr(mt5_connector, "ISOLATED_MT5", False)
    monkeypatch.setattr(mt5_connector, "_TF_MAP", {"M1": 1})

    async def dispatch(fn, *args, **kwargs):
        return [{
            "open": 1, "high": 2, "low": 1, "close": 2,
            "tick_volume": 3, "time": 1_700_000_000,
        }]

    monkeypatch.setattr(mt5_connector, "_mt5", dispatch)
    bars = await connector.get_ohlcv("EURUSD", "M1", 1)

    assert len(bars) == 1
    assert bars[0].timestamp == datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)


@pytest.mark.asyncio
async def test_mt5_drops_newer_forming_bar(monkeypatch):
    from services.nexus_data import mt5_connector

    connector = mt5_connector.MT5Connector()
    connector._connected = True
    monkeypatch.setattr(mt5_connector, "ISOLATED_MT5", False)
    monkeypatch.setattr(mt5_connector, "_TF_MAP", {"M1": 1})

    async def dispatch(fn, *args, **kwargs):
        return [
            {"open": 1, "high": 2, "low": 1, "close": 2, "tick_volume": 3, "time": 1_700_000_000},
            {"open": 2, "high": 3, "low": 2, "close": 3, "tick_volume": 4, "time": int(datetime.now(timezone.utc).timestamp())},
        ]

    async def ensure(_symbol):
        return None

    monkeypatch.setattr(mt5_connector, "_mt5", dispatch)
    monkeypatch.setattr(connector, "_ensure_symbol_selected", ensure)

    bars = await connector.get_ohlcv("EURUSD", "M1", 2)

    assert len(bars) == 1
    assert bars[0].timestamp == datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)


@pytest.mark.asyncio
async def test_persist_closed_ohlcv_keeps_single_completed_bar(monkeypatch):
    from services.nexus_data import main
    from shared.models import OHLCV

    captured = []

    class Store:
        async def insert_ohlcv_batch(self, bars, **_kwargs):
            # **_kwargs: the Phase 1 contract adds utc_offset_seconds etc.
            captured.extend(bars)

    monkeypatch.setattr(main, "data_store", Store())
    bar = OHLCV(symbol="EURUSD", timeframe="M1", open=1, high=2, low=1,
                close=2, volume=3, timestamp=datetime(2026, 10, 14, tzinfo=timezone.utc))

    await main._persist_closed_ohlcv([bar])

    assert captured == [bar]


@pytest.mark.asyncio
async def test_ohlcv_route_rejects_inverted_dates_before_store(monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from services.nexus_data import main

    async def unexpected_query(**_kwargs):
        pytest.fail("store queried for invalid range")

    monkeypatch.setattr(main.data_store, "query_ohlcv", unexpected_query)
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.get(
            "/api/data/ohlcv/EURUSD/M1",
            params={"start": "2026-10-15T00:00:00Z", "end": "2026-10-14T00:00:00Z"},
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_ohlcv_mt5_fallback_keeps_chronological_order(monkeypatch, operational_store):
    from httpx import ASGITransport, AsyncClient
    from services.nexus_data import main
    from shared.models import OHLCV

    oldest = OHLCV(
        symbol="EURUSD", timeframe="M1", open=1, high=2, low=1, close=2,
        volume=3, timestamp=datetime(2026, 10, 13, tzinfo=timezone.utc),
    )
    newest = OHLCV(
        symbol="EURUSD", timeframe="M1", open=2, high=3, low=2, close=3,
        volume=4, timestamp=datetime(2026, 10, 14, tzinfo=timezone.utc),
    )

    async def provider_bars(*_args, **_kwargs):
        return [oldest, newest]

    monkeypatch.setattr(main, "data_store", operational_store)
    monkeypatch.setattr(main, "DEFAULT_BROKER", "mt5")
    monkeypatch.setattr(main.mt5, "_connected", True)
    monkeypatch.setattr(main.mt5, "get_ohlcv", provider_bars)
    monkeypatch.setattr(main, "SYNTHETIC_FALLBACK", False)

    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.get("/api/data/ohlcv/EURUSD/M1")

    assert response.status_code == 200
    got = [row["timestamp"].replace("Z", "+00:00") for row in response.json()]
    expected = [oldest.timestamp.isoformat(), newest.timestamp.isoformat()]
    assert got == expected


@pytest.mark.asyncio
async def test_ohlcv_mt5_provider_error_is_not_reported_as_missing_data(monkeypatch, operational_store):
    from httpx import ASGITransport, AsyncClient
    from services.nexus_data import main

    async def provider_failure(*_args, **_kwargs):
        raise ConnectionError("provider unavailable")

    monkeypatch.setattr(main, "data_store", operational_store)
    monkeypatch.setattr(main, "DEFAULT_BROKER", "mt5")
    monkeypatch.setattr(main.mt5, "_connected", True)
    monkeypatch.setattr(main.mt5, "get_ohlcv", provider_failure)
    monkeypatch.setattr(main, "SYNTHETIC_FALLBACK", False)

    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.get("/api/data/ohlcv/EURUSD/M1")

    assert response.status_code == 503
