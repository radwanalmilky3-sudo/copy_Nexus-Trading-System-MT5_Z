from __future__ import annotations

import inspect
import re
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from shared.models import OHLCV
from services.nexus_data import main as data_main
from services.nexus_data.duckdb_store import DataStore

PIT_PATH = "/api/data/ohlcv/XAUUSD/M15/pit"
FINGERPRINT_PATH = "/api/data/ohlcv/XAUUSD/M15/fingerprint"
BAD_TF_PIT_PATH = "/api/data/ohlcv/XAUUSD/M99/pit"
BAD_TF_FINGERPRINT_PATH = "/api/data/ohlcv/XAUUSD/M99/fingerprint"

AS_OF = "2026-01-05T10:16:00+00:00"
AS_OF_DT = datetime(2026, 1, 5, 10, 16, tzinfo=timezone.utc)
BAR_0945 = datetime(2026, 1, 5, 9, 45, tzinfo=timezone.utc)
BAR_1000 = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
BAR_1015 = datetime(2026, 1, 5, 10, 15, tzinfo=timezone.utc)
BAR_1030 = datetime(2026, 1, 5, 10, 30, tzinfo=timezone.utc)

HEX64 = re.compile(r"[0-9a-f]{64}")


def _bar(timestamp: datetime, close: float = 2500.0) -> OHLCV:
    return OHLCV(
        symbol="XAUUSD", timeframe="M15", open=close, high=close + 1.0,
        low=close - 1.0, close=close, volume=100.0, timestamp=timestamp,
    )


async def _get(path: str, **params):
    async with AsyncClient(
        transport=ASGITransport(app=data_main.app),
        base_url="http://data-test",
    ) as client:
        return await client.get(path, params=params)


def _timestamps(payload: list[dict]) -> list[datetime]:
    """Row timestamps as instants (serializers emit Z or the session offset)."""
    return [
        datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
        for row in payload
    ]


class PitStore:
    """DataStore double exposing the Phase-2 PIT keyword contract."""

    def __init__(self, rows=(), fingerprint=None):
        self.rows = list(rows)
        self.fingerprint = fingerprint
        self.calls = []

    async def query_ohlcv(
        self, symbol, timeframe, start=None, end=None, limit=500, *,
        available_through=None, max_staleness_s=None,
    ):
        self.calls.append({
            "symbol": symbol,
            "timeframe": timeframe,
            "limit": limit,
            "available_through": available_through,
            "max_staleness_s": max_staleness_s,
        })
        return list(self.rows)

    async def fingerprint_ohlcv(self, symbol, timeframe, available_through):
        self.calls.append({
            "fingerprint_symbol": symbol,
            "fingerprint_timeframe": timeframe,
            "fingerprint_through": available_through,
        })
        if self.fingerprint is not None:
            return dict(self.fingerprint)
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "available_through": available_through.isoformat(),
            "row_count": len(self.rows),
            "content_hash": "ab" * 32,
        }


class LegacyStore:
    """DataStore double without the Phase-2 PIT keywords (pre-contract)."""

    def __init__(self):
        self.calls = []

    async def query_ohlcv(self, symbol, timeframe, start=None, end=None, limit=500):
        self.calls.append({"symbol": symbol})
        return [_bar(BAR_0945)]


class NoFingerprintStore:
    async def query_ohlcv(
        self, symbol, timeframe, start=None, end=None, limit=500, *,
        available_through=None, max_staleness_s=None,
    ):
        return []


class UnusedStore:
    async def query_ohlcv(self, *args, **kwargs):
        raise AssertionError("store must not be queried while PIT is disabled")

    async def fingerprint_ohlcv(self, *args, **kwargs):
        raise AssertionError("store must not be queried while PIT is disabled")


@pytest.mark.asyncio
@pytest.mark.parametrize("off_value", [None, "", "0", "off"])
@pytest.mark.parametrize("path", [PIT_PATH, FINGERPRINT_PATH])
async def test_pit_flag_off_returns_503(monkeypatch, off_value, path):
    if off_value is None:
        monkeypatch.delenv("NEXUS_PIT_ENABLED", raising=False)
    else:
        monkeypatch.setenv("NEXUS_PIT_ENABLED", off_value)
    monkeypatch.setattr(data_main, "data_store", UnusedStore())

    response = await _get(path, available_through=AS_OF)

    assert response.status_code == 503
    assert response.json() == {"detail": "NEXUS_PIT_ENABLED is not set"}


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [PIT_PATH, FINGERPRINT_PATH])
async def test_pit_missing_available_through_is_422(monkeypatch, path):
    monkeypatch.setenv("NEXUS_PIT_ENABLED", "1")
    monkeypatch.setattr(data_main, "data_store", PitStore(rows=[_bar(BAR_0945)]))

    response = await _get(path)

    assert response.status_code == 422
    assert "available_through" in response.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [PIT_PATH, FINGERPRINT_PATH])
async def test_pit_invalid_available_through_is_400(monkeypatch, path):
    monkeypatch.setenv("NEXUS_PIT_ENABLED", "1")
    monkeypatch.setattr(data_main, "data_store", PitStore(rows=[_bar(BAR_0945)]))

    response = await _get(path, available_through="not-a-timestamp")

    assert response.status_code == 400
    assert "ISO 8601" in response.json()["detail"]


@pytest.mark.asyncio
async def test_pit_rejects_negative_max_staleness(monkeypatch):
    monkeypatch.setenv("NEXUS_PIT_ENABLED", "1")
    monkeypatch.setattr(data_main, "data_store", PitStore(rows=[_bar(BAR_0945)]))

    response = await _get(PIT_PATH, available_through=AS_OF, max_staleness_s=-1)

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [BAD_TF_PIT_PATH, BAD_TF_FINGERPRINT_PATH])
async def test_pit_unsupported_timeframe_is_400(monkeypatch, path):
    monkeypatch.setenv("NEXUS_PIT_ENABLED", "1")
    monkeypatch.setattr(data_main, "data_store", PitStore(rows=[_bar(BAR_0945)]))

    response = await _get(path, available_through=AS_OF)

    assert response.status_code == 400
    assert "Unsupported timeframe" in response.json()["detail"]


@pytest.mark.asyncio
async def test_pit_returns_rows_chronological_and_forwards_contract_params(monkeypatch):
    monkeypatch.setenv("NEXUS_PIT_ENABLED", "1")
    store = PitStore(rows=[_bar(BAR_1015), _bar(BAR_0945)])
    monkeypatch.setattr(data_main, "data_store", store)

    response = await _get(PIT_PATH, available_through=AS_OF)

    assert response.status_code == 200
    rows = response.json()
    assert _timestamps(rows) == [BAR_0945, BAR_1015]
    assert all(row["symbol"] == "XAUUSD" for row in rows)
    assert all("source" not in row for row in rows)
    call = store.calls[0]
    assert call["symbol"] == "XAUUSD"
    assert call["timeframe"] == "M15"
    assert call["available_through"] == AS_OF_DT
    assert call["max_staleness_s"] is None


@pytest.mark.asyncio
async def test_pit_forwards_max_staleness_s(monkeypatch):
    monkeypatch.setenv("NEXUS_PIT_ENABLED", "1")
    store = PitStore(rows=[_bar(BAR_0945)])
    monkeypatch.setattr(data_main, "data_store", store)

    response = await _get(PIT_PATH, available_through=AS_OF, max_staleness_s=600)

    assert response.status_code == 200
    assert store.calls[0]["max_staleness_s"] == 600


@pytest.mark.asyncio
async def test_pit_never_serves_rows_after_available_through(monkeypatch):
    monkeypatch.setenv("NEXUS_PIT_ENABLED", "1")
    monkeypatch.setattr(
        data_main, "data_store", PitStore(rows=[_bar(BAR_1030), _bar(BAR_1015)]),
    )

    response = await _get(PIT_PATH, available_through=AS_OF)

    assert response.status_code == 200
    assert _timestamps(response.json()) == [BAR_1015]

    # Every row is after the as-of point: the request must fail closed.
    monkeypatch.setattr(data_main, "data_store", PitStore(rows=[_bar(BAR_1030)]))
    closed = await _get(PIT_PATH, available_through=AS_OF)

    assert closed.status_code == 404


@pytest.mark.asyncio
async def test_pit_returns_404_when_store_has_no_rows(monkeypatch):
    monkeypatch.setenv("NEXUS_PIT_ENABLED", "1")
    monkeypatch.setattr(data_main, "data_store", PitStore(rows=[]))

    response = await _get(PIT_PATH, available_through=AS_OF)

    assert response.status_code == 404
    assert "No OHLCV data" in response.json()["detail"]


@pytest.mark.asyncio
async def test_pit_fails_closed_when_store_lacks_pit_contract(monkeypatch):
    monkeypatch.setenv("NEXUS_PIT_ENABLED", "1")
    store = LegacyStore()
    monkeypatch.setattr(data_main, "data_store", store)

    response = await _get(PIT_PATH, available_through=AS_OF)

    assert response.status_code == 503
    assert store.calls == []


@pytest.mark.asyncio
async def test_fingerprint_returns_row_count_and_hex_hash(monkeypatch):
    monkeypatch.setenv("NEXUS_PIT_ENABLED", "1")
    store = PitStore(rows=[_bar(BAR_0945), _bar(BAR_1015)])
    monkeypatch.setattr(data_main, "data_store", store)

    response = await _get(FINGERPRINT_PATH, available_through=AS_OF)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["symbol"] == "XAUUSD"
    assert body["timeframe"] == "M15"
    assert body["available_through"] == AS_OF
    assert body["row_count"] == 2
    assert isinstance(body["row_count"], int)
    assert HEX64.fullmatch(body["content_hash"])
    assert store.calls[0]["fingerprint_through"] == AS_OF_DT


@pytest.mark.asyncio
async def test_fingerprint_fails_closed_when_store_method_missing(monkeypatch):
    monkeypatch.setenv("NEXUS_PIT_ENABLED", "1")
    monkeypatch.setattr(data_main, "data_store", NoFingerprintStore())

    response = await _get(FINGERPRINT_PATH, available_through=AS_OF)

    assert response.status_code == 503
    assert "fingerprint_ohlcv" in response.json()["detail"]


@pytest.mark.asyncio
async def test_pit_query_against_real_store(tmp_path, monkeypatch):
    if "available_through" not in inspect.signature(DataStore.query_ohlcv).parameters:
        pytest.skip("duckdb_store.query_ohlcv lacks Phase-2 PIT keywords (C1 in flight)")

    store = DataStore(db_path=str(tmp_path / "pit-query.duckdb"))
    await store.init_tables()
    try:
        # The 10:00 bar only becomes visible at 10:45 - after the as-of point -
        # so a correct PIT query must exclude it despite its bar time fitting.
        await store.insert_ohlcv_batch(
            [_bar(BAR_0945)], available_at=BAR_0945 + timedelta(seconds=60),
        )
        await store.insert_ohlcv_batch(
            [_bar(BAR_1000, close=2501.0)],
            available_at=datetime(2026, 1, 5, 10, 45, tzinfo=timezone.utc),
        )
        await store.insert_ohlcv_batch(
            [_bar(BAR_1015, close=2502.0)], available_at=BAR_1015 + timedelta(seconds=60),
        )

        monkeypatch.setenv("NEXUS_PIT_ENABLED", "1")
        monkeypatch.setattr(data_main, "data_store", store)

        response = await _get(PIT_PATH, available_through=AS_OF)

        assert response.status_code == 200
        assert _timestamps(response.json()) == [BAR_0945, BAR_1015]
    finally:
        store.close()


@pytest.mark.asyncio
async def test_fingerprint_against_real_store(tmp_path, monkeypatch):
    if not hasattr(DataStore, "fingerprint_ohlcv"):
        pytest.skip("DataStore.fingerprint_ohlcv not implemented yet (C1 in flight)")

    store = DataStore(db_path=str(tmp_path / "pit-fingerprint.duckdb"))
    await store.init_tables()
    try:
        await store.insert_ohlcv_batch(
            [_bar(BAR_0945)], available_at=BAR_0945 + timedelta(seconds=60),
        )
        await store.insert_ohlcv_batch(
            [_bar(BAR_1015, close=2502.0)], available_at=BAR_1015 + timedelta(seconds=60),
        )

        monkeypatch.setenv("NEXUS_PIT_ENABLED", "1")
        monkeypatch.setattr(data_main, "data_store", store)

        response = await _get(FINGERPRINT_PATH, available_through=AS_OF)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["row_count"] == 2
        assert isinstance(body["row_count"], int)
        assert HEX64.fullmatch(body["content_hash"])
    finally:
        store.close()
