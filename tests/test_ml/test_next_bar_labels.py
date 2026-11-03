import pandas as pd

from services.nexus_ml.labeling import advance_pending_bar, label_next_bar_direction
from services.nexus_ml import main as ml_main
import warnings


def bar(timestamp: int, close: float, value: float, timeframe: str = "M5") -> dict:
    return {
        "timestamp": timestamp,
        "close": close,
        "timeframe": timeframe,
        "features": {"probe": value},
        "ohlcv": {"close": close},
    }


def test_batch_direction_labels_drop_rows_without_a_next_close():
    frame = pd.DataFrame({"timestamp": [1, 2, 3], "close": [10.0, 11.0, 9.0]})

    labeled = label_next_bar_direction(frame)

    assert labeled["timestamp"].tolist() == [1, 2]
    assert labeled["target"].tolist() == [1, 0]


def test_label_is_assigned_to_previous_bar_using_next_close():
    state, completed = advance_pending_bar(None, bar(100, 10.0, 1.0))
    assert completed is None

    state, completed = advance_pending_bar(state, bar(200, 11.0, 2.0))
    assert completed == {
        "timestamp": 100,
        "timeframe": "M5",
        "features": {"probe": 1.0},
        "ohlcv": {"close": 10.0},
        "label": 1,
    }
    assert state["timestamp"] == 200


def test_duplicate_and_out_of_order_bars_do_not_shift_pending_label():
    state, _ = advance_pending_bar(None, bar(200, 10.0, 1.0))
    duplicate_state, duplicate = advance_pending_bar(state, bar(200, 12.0, 2.0))
    assert duplicate is None
    assert duplicate_state == state

    older_state, older = advance_pending_bar(state, bar(100, 8.0, 0.0))
    assert older is None
    assert older_state == state


def test_pending_bar_survives_serialization_and_restart():
    first_state, _ = advance_pending_bar(None, bar(100, 10.0, 1.0))
    restored_state = __import__("json").loads(__import__("json").dumps(first_state))

    next_state, completed = advance_pending_bar(restored_state, bar(200, 9.0, 2.0))
    assert completed["label"] == 0
    assert completed["timestamp"] == 100
    assert next_state["timestamp"] == 200


def test_training_excludes_other_timeframes_and_legacy_unscoped_rows(monkeypatch):
    requested_keys = []

    class RedisFixture:
        async def lrange(self, key, _start, _end):
            requested_keys.append(key)
            if key == "nexus:features:history:v2:XAUUSD:M5":
                return [
                    '{"features":{"probe":1.0},"label":1,"timeframe":"M5","timestamp":"2026-01-01T00:00:00+00:00"}',
                ]
            if key == "nexus:features:history:v2:XAUUSD:M15":
                return ['{"features":{"probe":99.0},"label":0,"timeframe":"M15"}']
            return ['{"features":{"probe":99.0},"label":0}']

    monkeypatch.setattr(ml_main, "_redis", RedisFixture())
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        result = __import__("asyncio").run(ml_main._fetch_training_data(["XAUUSD"], timeframe="M5"))

    assert requested_keys == ["nexus:features:history:v2:XAUUSD:M5"]
    assert result is not None
    X, y, _timestamps, names = result
    assert X.tolist() == [[1.0]]
    assert y.tolist() == [1]
    assert names == ["probe"]
    assert str(_timestamps[0]) == "2026-01-01T00:00:00"
    assert not any("no explicit representation of timezones" in str(w.message) for w in captured)


def test_retrain_sample_count_uses_only_the_requested_timeframe(monkeypatch):
    requested_keys = []

    class RedisFixture:
        async def llen(self, key):
            requested_keys.append(key)
            return {
                "nexus:features:history:v2:XAUUSD:M5": 7,
                "nexus:features:history:v2:XAUUSD:M15": 3,
            }[key]

    monkeypatch.setattr(ml_main, "_redis", RedisFixture())
    total, per_symbol = __import__("asyncio").run(
        ml_main._count_timeframe_samples(["XAUUSD"], "M5")
    )

    assert total == 7
    assert per_symbol == {"XAUUSD": 7}
    assert requested_keys == ["nexus:features:history:v2:XAUUSD:M5"]


def test_completed_pending_label_retains_its_timeframe():
    _state, completed = advance_pending_bar(
        bar(100, 10.0, 1.0, timeframe="M5"),
        bar(200, 11.0, 2.0, timeframe="M15"),
    )

    assert completed["timeframe"] == "M5"


def test_failed_feature_event_is_not_acknowledged(monkeypatch):
    import asyncio

    acknowledgements = []

    class RedisFixture:
        async def xack(self, stream, group, message_id):
            acknowledgements.append((stream, group, message_id))

    monkeypatch.setattr(ml_main, "_redis", RedisFixture())
    monkeypatch.setattr(ml_main, "_ensemble", object())
    monkeypatch.setattr(ml_main, "_rule_based", object())

    asyncio.run(ml_main._handle_feature_event("1-0", {"symbol": "XAUUSD", "features": "{bad json"}))

    assert acknowledgements == []


def test_successfully_published_feature_event_is_acknowledged(monkeypatch):
    import asyncio
    import json

    from services.nexus_ml.ensemble import EnsembleSignal

    acknowledgements = []
    published = []

    class PipelineFixture:
        def set(self, *args, **kwargs):
            return self

        def rpush(self, *args, **kwargs):
            return self

        def ltrim(self, *args, **kwargs):
            return self

        async def execute(self):
            return []

    class RedisFixture:
        async def get(self, key):
            return None

        def pipeline(self, **kwargs):
            return PipelineFixture()

        async def xadd(self, stream, payload, **kwargs):
            published.append((stream, payload))
            return "2-0"

        async def xack(self, stream, group, message_id):
            acknowledgements.append((stream, group, message_id))

    class EnsembleFixture:
        @staticmethod
        def models_status():
            return {"xgboost": True}

        @staticmethod
        def build_feature_array(_features):
            return []

        @staticmethod
        def predict(_array):
            return EnsembleSignal(direction="BUY", confidence=0.9)

    monkeypatch.setenv("NEXUS_OPERATIONAL_TF", "M15")
    monkeypatch.setattr(ml_main, "_redis", RedisFixture())
    monkeypatch.setattr(ml_main, "_ensemble", object())
    monkeypatch.setattr(ml_main, "_rule_based", None)
    monkeypatch.setattr(ml_main, "_last_signal_ts", {})
    monkeypatch.setattr(ml_main, "_get_symbol_ensemble", lambda _symbol, _timeframe=None: EnsembleFixture())

    asyncio.run(ml_main._handle_feature_event("2-0", {
        "symbol": "XAUUSD",
        "timeframe": "M15",
        "bar_timestamp": "2026-10-14T10:00:00+00:00",
        "features": json.dumps({"open": 100, "high": 102, "low": 99, "close": 101, "volume": 10}),
    }))

    assert len(published) == 1
    assert acknowledgements == [(ml_main.RedisStream.FEATURE_STREAM, ml_main.CONSUMER_GROUP, "2-0")]
