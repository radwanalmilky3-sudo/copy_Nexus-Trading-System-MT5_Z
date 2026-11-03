import asyncio
import json

import numpy as np
import pytest

from services.nexus_ml import traders_api


def record(value, timeframe=None):
    payload = {
        "features": {"probe": value, "open": value, "high": value, "low": value, "close": value, "volume": 1},
        "ohlcv": {"open": value, "high": value, "low": value, "close": value, "volume": 1},
        "label": int(value) % 2,
    }
    if timeframe is not None:
        payload["timeframe"] = timeframe
    return json.dumps(payload)


@pytest.mark.asyncio
async def test_trader_training_excludes_other_and_unscoped_history_and_outcomes(monkeypatch, tmp_path):
    class RedisFixture:
        async def lrange(self, key, _start, _end):
            if key.endswith("XAUUSD:M5"):
                return [record(5, "M5"), record(15, "M15"), record(99)]
            if key.endswith("XAUUSD"):
                return [record(25, "M5"), record(150, "M15"), record(199)]
            return []

    async def get_redis():
        return RedisFixture()

    monkeypatch.setattr(traders_api, "_get_redis", get_redis)
    monkeypatch.setattr(traders_api, "TRADERS_DIR", str(tmp_path))
    monkeypatch.setattr(traders_api, "_traders", {})

    data = await traders_api._fetch_training_data(["XAUUSD"], ["M5"])

    assert data is not None
    X, y, _ohlcv, names = data
    # history is recency-weighted 2x; only matching explicitly tagged rows survive.
    assert names[0] == "probe"
    assert X[:, 0].tolist() == [5.0, 5.0, 25.0, 25.0, 25.0, 25.0, 25.0]
    assert len(y) == len(X)


@pytest.mark.asyncio
async def test_trader_training_rejects_legacy_rows_without_timeframe(monkeypatch):
    class RedisFixture:
        async def lrange(self, _key, _start, _end):
            return [record(99)]

    async def get_redis():
        return RedisFixture()

    monkeypatch.setattr(traders_api, "_get_redis", get_redis)
    assert await traders_api._fetch_training_data(["XAUUSD"], ["M5"]) is None


@pytest.mark.parametrize("model_type", ["ml", "dl", "rl"])
def test_trader_cache_and_storage_are_scoped_by_symbol_and_timeframe(monkeypatch, tmp_path, model_type):
    monkeypatch.setattr(traders_api, "TRADERS_DIR", str(tmp_path))
    monkeypatch.setattr(traders_api, "_traders", {})
    m5 = traders_api._get_trader_by_type(model_type, "XAUUSD", "M5")
    m15 = traders_api._get_trader_by_type(model_type, "XAUUSD", "M15")
    btc = traders_api._get_trader_by_type(model_type, "BTCUSD", "M5")

    assert m5 is not m15 and m5 is not btc
    assert m5.model_dir != m15.model_dir
    assert m5.model_dir != btc.model_dir
    assert m5.model_dir.parts[-2:] == ("XAUUSD", "M5")


def test_unprovenanced_trader_file_is_not_loaded(monkeypatch, tmp_path):
    loaded = []

    class TraderFixture:
        def __init__(self, model_dir):
            self.model_dir = model_dir

        def load(self):
            loaded.append(self.model_dir)

    monkeypatch.setattr(traders_api, "TRADERS_DIR", str(tmp_path))
    monkeypatch.setattr(traders_api, "_traders", {})
    monkeypatch.setattr(traders_api, "MLTrader", TraderFixture)

    trader = traders_api._get_trader_by_type("ml", "XAUUSD", "M5")

    assert loaded == []
    assert trader.model_dir.parts[-2:] == ("XAUUSD", "M5")


@pytest.mark.asyncio
async def test_prediction_feature_lookup_does_not_fallback_or_accept_mislabeled_cache(monkeypatch):
    class RedisFixture:
        async def get(self, key):
            if key.endswith(":M5"):
                return json.dumps({"timeframe": "M15", "features": {"probe": 15}})
            if key.endswith(":M15"):
                return json.dumps({"timeframe": "M15", "features": {"probe": 15}})
            return None

    class ConfigFixture:
        operational_tf = "M5"

    async def get_redis():
        return RedisFixture()

    monkeypatch.setattr(traders_api, "_get_redis", get_redis)
    monkeypatch.setattr(traders_api, "get_current_config", lambda: ConfigFixture())

    assert await traders_api._get_latest_features("XAUUSD", "M5", allow_fallback=False) is None

