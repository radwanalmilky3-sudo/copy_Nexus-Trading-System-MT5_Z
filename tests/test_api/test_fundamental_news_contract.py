"""Task 5 truth-contract regression: /api/fundamental/news + overview honesty."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from services.nexus_api.routers import fundamental
from services.nexus_api.routers import news as news_router

UTC = timezone.utc


@pytest.fixture(autouse=True)
def _no_external_network(monkeypatch):
    """No test in this file may reach the real internet (TDD rule)."""
    import socket

    def _blocked(sock, address=None, *_a, **_k):
        host = address[0] if isinstance(address, tuple) and address else str(address)
        # asyncio's own loopback self-pipe must keep working; only the
        # internet is off-limits for these tests.
        if str(host) in {"127.0.0.1", "::1", "localhost"}:
            return _orig_connect(sock, address, *_a, **_k)
        raise RuntimeError(f"external network access is blocked in Task 5 tests: {host!r}")

    _orig_connect = socket.socket.connect
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


class _Redis:
    def __init__(self, store: dict | None = None) -> None:
        self.store = store if store is not None else {}

    async def cache_get(self, key: str, *, prefix: bool = True):
        return self.store.get(key)

    async def cache_set(self, key: str, value, *, ttl_sec: int = 60, prefix: bool = True):
        self.store[key] = value


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _news_item(headline: str, minutes_ago: int = 3):
    return {
        "id": headline,
        "headline": headline,
        "source": "GDELT",
        "impact": "high",
        "sentiment": "neutral",
        "timestamp": _iso(datetime.now(UTC) - timedelta(minutes=minutes_ago)),
        "affected_currencies": ["XAU", "USD"],
    }


@pytest.mark.asyncio
async def test_news_context_keeps_contract_keys_and_adds_truth_envelope():
    now = datetime.now(UTC)
    redis = _Redis({
        "news:latest": [
            _news_item("Gold jumps on geopolitics"),
            _news_item("  gold jumps on geopolitics ", minutes_ago=3),
            _news_item("Powell hints at patience", minutes_ago=6),
        ],
        "news:calendar": [{"id": "e1", "currency": "USD", "impact": "high"}],
        "news:ticker:active": [{"ticker_item_id": "t1"}],
        "fundamental:blackout": {"state": "clear", "active": False},
        "news:meta": {
            "polled_at": _iso(now),
            "last_success_at": _iso(now),
            "first_available_at": _iso(now - timedelta(hours=2)),
            "item_count": 2,
            "degraded": False,
        },
    })

    payload = await fundamental.news_context(redis=redis)

    # Existing contract keys survive unchanged in name.
    assert set(["news", "calendar", "ticker", "blackout"]).issubset(payload)
    # Duplicates removed server-side.
    assert len(payload["news"]) == 2
    # Additive truth fields.
    assert payload["state"] == "ready"
    assert payload["freshness"]["stale"] is False
    assert payload["last_update_at"] is not None
    assert payload["first_available_at"] is not None
    assert isinstance(payload["sources"], list)
    assert payload["blackout"]["state"] == "clear"


@pytest.mark.asyncio
async def test_news_context_without_any_pipeline_state_is_unavailable():
    payload = await fundamental.news_context(redis=_Redis())

    assert payload["news"] == []
    assert payload["calendar"] == []
    assert payload["state"] == "unavailable"
    assert payload["blackout"]["state"] == "unavailable"
    assert payload["reason_ar"]
    # لا جاهزية صورية
    assert payload["last_update_at"] is None


@pytest.mark.asyncio
async def test_news_context_stale_items_are_flagged_not_hidden():
    stale_ts = datetime.now(UTC) - timedelta(hours=5)
    redis = _Redis({
        "news:latest": [{
            "id": "old", "headline": "Old real headline", "source": "GDELT",
            "impact": "medium", "sentiment": "neutral",
            "timestamp": _iso(stale_ts), "affected_currencies": ["USD"],
        }],
        "news:meta": {
            "polled_at": _iso(stale_ts),
            "last_success_at": _iso(stale_ts),
            "first_available_at": _iso(stale_ts),
            "item_count": 1,
            "degraded": False,
        },
    })
    payload = await fundamental.news_context(redis=redis)

    assert payload["state"] == "stale"
    assert payload["freshness"]["stale"] is True
    assert len(payload["news"]) == 1


# ── Gold overview fallback honesty (unknown ≠ 0 ≠ neutral) ──────────────────

@pytest.mark.asyncio
async def test_overview_without_gold_cycle_is_unknown_not_neutral():
    overview = await fundamental._overview_payload(_Redis())

    assert overview["state"] == "unavailable"
    assert overview["message_ar"]
    assert len(overview["domains"]) == 5
    for domain in overview["domains"]:
        assert domain["direction"] == "unknown"
        assert domain["confidence"] is None
        assert domain["strength"] is None
        assert domain["gold_impact_score"] is None
        assert domain["domain_state"] == "UNAVAILABLE"
        assert domain["metadata"]["state"] == "unavailable"


@pytest.mark.asyncio
async def test_overview_blackout_absence_stays_unavailable_not_clear():
    overview = await fundamental._overview_payload(_Redis())

    assert overview["blackout"]["state"] == "unavailable"
    assert overview["blackout"].get("reason_ar")


@pytest.mark.asyncio
async def test_overview_gold_empty_dict_is_unavailable_not_ready():
    overview = await fundamental._overview_payload(_Redis({"fundamental:gold:latest": {}}))

    assert overview["state"] == "unavailable"
    assert overview.get("reason_ar")
    assert overview.get("result_origin") == "none"


@pytest.mark.asyncio
async def test_overview_gold_dict_without_direction_is_unknown_not_neutral():
    overview = await fundamental._overview_payload(_Redis({
        "fundamental:gold:latest": {"strength": 55.0, "confidence": 62.0},
    }))

    assert overview["direction"] == "unknown"
    assert overview["direction_ar"] == "غير محدد"
    assert overview["direction"] != "neutral"
    assert overview["state"] == "degraded"
    assert overview["state"] != "ready"
    assert overview.get("reason_ar")
    assert overview.get("result_origin") == "redis_gold_snapshot"
    # Real present values pass through; missing ones stay None — never fabricated.
    assert overview["strength"] == 55.0
    assert overview["confidence"] == 62.0
    assert overview["coverage_score"] is None
    assert overview["data_quality_score"] is None
    assert overview["freshness_score"] is None
    assert overview["conflict_score"] is None
    assert overview["prediction_stage"] is None
    assert overview["market_confirmation"] is None
    assert overview["symbol"] is None


@pytest.mark.asyncio
async def test_overview_gold_full_real_snapshot_is_ready_and_passes_values():
    overview = await fundamental._overview_payload(_Redis({
        "fundamental:gold:latest": {
            "symbol": "XAUUSD",
            "direction": "bullish",
            "strength": 71.0,
            "confidence": 66.0,
            "coverage_score": 80.0,
            "data_quality_score": 90.0,
            "freshness_score": 88.0,
            "conflict_score": 12.0,
            "stage": "at_release",
            "confidence_validation": "unvalidated",
            "generated_at": "2026-10-22T00:00:00+00:00",
        },
    }))

    assert overview["state"] == "ready"
    assert overview["direction"] == "bullish"
    assert overview["direction_ar"] == "صاعد"
    assert overview["strength"] == 71.0
    assert overview["confidence"] == 66.0
    assert overview["symbol"] == "XAUUSD"
    assert overview["prediction_stage"] == "at_release"
    assert overview["market_confirmation"] == "متاح بعد قياس تفاعل السوق"
    assert overview["result_origin"] == "redis_gold_snapshot"


@pytest.mark.asyncio
async def test_overview_gold_engine_neutral_is_a_real_neutral_not_fabricated():
    overview = await fundamental._overview_payload(_Redis({
        "fundamental:gold:latest": {"direction": "neutral", "strength": 10.0, "confidence": 40.0},
    }))

    # A pipeline that genuinely computed neutral stays neutral AND ready.
    assert overview["direction"] == "neutral"
    assert overview["state"] == "ready"


@pytest.mark.asyncio
async def test_overview_market_confirmation_uses_real_confirmation_stage():
    overview = await fundamental._overview_payload(_Redis({
        "fundamental:gold:latest": {"direction": "bullish", "strength": 50.0, "confidence": 50.0, "stage": "confirmation"},
    }))

    assert overview["market_confirmation"] == "مؤكد"


class _Db:
    def __init__(self, rows=None):
        self.rows = rows or []

    async def query(self, table, filters=None):
        if table == "notification_preferences":
            return self.rows
        return []


@pytest.mark.asyncio
async def test_domain_metadata_none_does_not_crash_and_direction_keeps_real_state():
    payload = await fundamental._domain("macro", _Redis({
        "fundamental:macro:latest": {"direction": "bullish", "metadata": None},
    }))

    assert payload["state"] == "ready"


@pytest.mark.asyncio
async def test_domain_snapshot_without_direction_is_unknown_not_ready():
    payload = await fundamental._domain("macro", _Redis({
        "fundamental:macro:latest": {"coverage_score": 40.0},
    }))

    assert payload["state"] == "unknown"
    assert payload["state"] != "ready"
    assert payload.get("reason_ar")


@pytest.mark.asyncio
async def test_domain_contract_empty_dict_is_unavailable():
    contract = fundamental._domain_contract({}, [])

    assert contract["score_state"] == "UNAVAILABLE"
    assert contract["domain_state"] == "UNAVAILABLE"


@pytest.mark.asyncio
async def test_ticker_without_pipeline_meta_is_unavailable_not_ready():
    payload = await fundamental.ticker("u1", None, _Redis(), _Db())

    assert payload["state"] == "unavailable"
    assert payload["state"] != "ready"
    assert payload.get("reason_ar")
    assert payload["items"] == []


@pytest.mark.asyncio
async def test_ticker_completed_scan_without_items_is_empty_not_ready():
    now = datetime.now(UTC)
    payload = await fundamental.ticker("u1", None, _Redis({
        "news:meta": {"last_success_at": _iso(now), "item_count": 0, "degraded": False},
    }), _Db())

    assert payload["state"] == "empty"
    assert payload["state"] != "ready"
    assert payload.get("reason_ar")


@pytest.mark.asyncio
async def test_ticker_with_real_active_items_stays_ready():
    payload = await fundamental.ticker("u1", None, _Redis({
        "news:ticker:active": [{"ticker_item_id": "t1", "severity": "high"}],
    }), _Db())

    assert payload["state"] == "ready"


class _DbBoom:
    async def query(self, table, filters=None):
        raise RuntimeError("simulated data-service failure")


@pytest.mark.asyncio
async def test_lineage_sources_db_error_is_degraded_not_silently_ready():
    payload = await fundamental.asset_lineage("XAUUSD", _Redis({
        "fundamental:asset:XAUUSD:latest": {
            "state": "ready",
            "impacts": [{
                "impact_id": "i1", "event_id": "e1", "horizon": "5m",
                "source_ids_json": ["s1"], "drivers_json": [],
            }],
        },
    }), _DbBoom(), None)

    assert payload["state"] == "degraded"
    assert payload["state"] != "ready"
    assert payload.get("reason_ar")
    assert payload["sources"] == []


@pytest.mark.asyncio
async def test_lineage_without_impact_is_unavailable():
    payload = await fundamental.asset_lineage("XAUUSD", _Redis(), _DbBoom(), None)

    assert payload["state"] == "unavailable"
    assert payload["impact"] is None


class _Analyst:
    def __init__(self):
        pass

    async def analyze(self, question, structured):
        return {
            "state": "ready",
            "answer": {"summary_ar": "إجابة", "claims_used": [], "sources": []},
            "structured_input": structured,
            "schema_valid": True,
            "hallucination_flags": [],
            "model_name": "local",
            "model_version": "t",
        }


@pytest.mark.asyncio
async def test_local_ai_audit_latency_is_none_not_fabricated_zero(monkeypatch):
    monkeypatch.setattr(fundamental, "_require", AsyncMock(return_value=None))
    monkeypatch.setattr(fundamental, "_post_data", AsyncMock(return_value=True))
    monkeypatch.setattr(fundamental, "GroundedLocalAI", _Analyst)

    captured: dict = {}

    async def _capture(table, record):
        captured.update(record)
        return True

    monkeypatch.setattr(fundamental, "_post_data", _capture)

    result = await fundamental.local_ai_analyze(
        fundamental.LocalAIRequest(question="سؤال", asset="XAUUSD"),
        "u1",
        _Redis(),
        _Db(),
    )

    assert result["state"] == "ready"
    assert "latency_ms" in captured
    assert captured["latency_ms"] is None
