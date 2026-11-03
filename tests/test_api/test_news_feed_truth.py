"""Task 5 truth-contract regression: news feed states, dedup, filters, sources.

All fixtures are disposable in-memory fakes. No live Redis, no DuckDB, and no
external news API calls are made (network-raising guards installed where a
fetcher path is exercised).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

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


def _item(headline: str, *, impact: str = "medium", minutes_ago: int = 2, currencies=None, source: str = "Reuters"):
    return {
        "id": headline,
        "headline": headline,
        "source": source,
        "impact": impact,
        "sentiment": "neutral",
        "timestamp": _iso(datetime.now(UTC) - timedelta(minutes=minutes_ago)),
        "affected_currencies": currencies if currencies is not None else ["USD"],
    }


# ── /api/news/status envelope states ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_status_pipeline_never_ran_is_unavailable_not_empty():
    envelope = await news_router.build_news_truth_envelope(_Redis())

    assert envelope["state"] == "unavailable"
    assert envelope["item_count"] == 0
    assert envelope["last_update_at"] is None
    assert envelope["first_available_at"] is None
    assert envelope["reason_ar"]
    assert "لم تُعرض" in envelope["reason_ar"] or "لم يبلغ" in envelope["reason_ar"]
    assert isinstance(envelope["sources"], list)


@pytest.mark.asyncio
async def test_status_failed_last_poll_is_unavailable_with_error_reason():
    redis = _Redis({
        "news:meta": {
            "polled_at": _iso(datetime.now(UTC)),
            "last_success_at": _iso(datetime.now(UTC) - timedelta(hours=3)),
            "first_available_at": _iso(datetime.now(UTC) - timedelta(hours=3)),
            "item_count": 0,
            "degraded": True,
            "last_error": "providers unreachable",
        },
    })
    envelope = await news_router.build_news_truth_envelope(redis)

    assert envelope["state"] == "unavailable"
    assert "فشل" in envelope["reason_ar"]
    assert "providers unreachable" in envelope["reason_ar"]


@pytest.mark.asyncio
async def test_status_successful_poll_with_zero_items_is_empty_not_ready():
    now = datetime.now(UTC)
    redis = _Redis({
        "news:meta": {
            "polled_at": _iso(now),
            "last_success_at": _iso(now),
            "first_available_at": _iso(now),
            "item_count": 0,
            "degraded": False,
            "last_error": None,
        },
    })
    envelope = await news_router.build_news_truth_envelope(redis)

    assert envelope["state"] == "empty"
    assert envelope["reason_ar"]
    assert envelope["item_count"] == 0
    assert envelope["last_update_at"] is not None


@pytest.mark.asyncio
async def test_status_fresh_items_are_ready_with_first_availability():
    now = datetime.now(UTC)
    first = now - timedelta(minutes=4)
    redis = _Redis({
        "news:latest": [
            _item("Fed holds rates", minutes_ago=1),
            _item("Gold climbs as dollar softens", minutes_ago=4),
        ],
        "news:meta": {
            "polled_at": _iso(now),
            "last_success_at": _iso(now),
            "first_available_at": _iso(first - timedelta(days=1)),
            "item_count": 2,
            "degraded": False,
        },
    })
    envelope = await news_router.build_news_truth_envelope(redis)

    assert envelope["state"] == "ready"
    assert envelope["freshness"]["stale"] is False
    assert envelope["first_available_at"] == _iso(first - timedelta(days=1))
    assert envelope["last_update_at"] is not None
    assert envelope["item_count"] == 2


@pytest.mark.asyncio
async def test_status_stale_chain_is_marked_stale_and_keeps_items():
    now = datetime.now(UTC)
    stale_ts = now - timedelta(hours=6)
    redis = _Redis({
        "news:latest": [_item("Old but real headline", minutes_ago=360)],
        "news:meta": {
            "polled_at": _iso(stale_ts),
            "last_success_at": _iso(stale_ts),
            "first_available_at": _iso(stale_ts),
            "item_count": 1,
            "degraded": False,
        },
    })
    envelope = await news_router.build_news_truth_envelope(redis, now=now)

    assert envelope["state"] == "stale"
    assert envelope["freshness"]["stale"] is True
    assert envelope["freshness"]["age_sec"] >= news_router.NEWS_TRUTH_LIMIT_SEC
    assert envelope["item_count"] == 1
    assert envelope["reason_ar"]


# ── Deduplication and filters on /api/news ───────────────────────────────────

@pytest.mark.asyncio
async def test_latest_news_removes_duplicate_headlines():
    redis = _Redis({
        "news:latest": [
            _item("Gold rallies on weak dollar", impact="high"),
            _item("  gold rallies on weak dollar  ", impact="high", source="GDELT"),
            _item("ECB holds rates", impact="medium"),
        ],
    })
    items = await news_router.latest_news(limit=50, impact=None, symbol=None, redis=redis)

    headlines = [n["headline"] for n in items]
    assert len(items) == 2
    assert sum(1 for h in headlines if "gold rallies" in h.lower()) == 1


@pytest.mark.asyncio
async def test_latest_news_impact_filter_still_applies_after_dedup():
    redis = _Redis({
        "news:latest": [
            _item("Breaking: Fed emergency cut", impact="high"),
            _item("Breaking: Fed emergency cut", impact="high", source="GDELT"),
            _item("Retail sales mild beat", impact="low"),
        ],
    })
    items = await news_router.latest_news(limit=50, impact="high", symbol=None, redis=redis)

    assert len(items) == 1
    assert items[0]["impact"] == "high"


@pytest.mark.asyncio
async def test_latest_news_symbol_filter_matches_affected_currencies():
    redis = _Redis({
        "news:latest": [
            _item("Gold sinks as yields jump", currencies=["XAU", "USD"]),
            _item("Yen firms after BOJ comments", currencies=["JPY"]),
        ],
    })
    items = await news_router.latest_news(limit=50, impact=None, symbol="XAUUSD", redis=redis)

    assert len(items) == 1
    assert "Gold" in items[0]["headline"]


@pytest.mark.asyncio
async def test_sentiment_absence_is_not_reported_as_neutral_score():
    result = await news_router.symbol_sentiment("XAUUSD", redis=_Redis())

    assert result["state"] == "unavailable"
    assert result["overall_sentiment"] is None
    assert result["score"] is None
    assert result["message_ar"]


# ── News provider configuration truth (no network) ───────────────────────────

def _install_managed(monkeypatch, *, enabled: dict, secrets: dict, configs: dict):
    monkeypatch.setattr(news_router, "managed_enabled", lambda sid, default=True: enabled.get(sid, default))
    monkeypatch.setattr(news_router, "managed_secret", lambda sid, env=None: secrets.get(sid, ""))
    monkeypatch.setattr(news_router, "managed_source_config", lambda sid: configs.get(sid))


@pytest.mark.asyncio
async def test_news_sources_report_missing_config_with_external_requirement(monkeypatch):
    _install_managed(
        monkeypatch,
        enabled={},
        secrets={},
        configs={
            "newsapi": {"secret_env": "NEWSAPI_KEY", "secret_optional": False, "auth_mode": "query"},
            "gnews": {"secret_env": "GNEWS_KEY", "secret_optional": False, "auth_mode": "query"},
        },
    )
    redis = _Redis({"news:meta": {"polled_at": _iso(datetime.now(UTC)), "item_count": 0, "degraded": False}})
    envelope = await news_router.build_news_truth_envelope(redis)
    by_id = {s["source_id"]: s for s in envelope["sources"]}

    assert by_id["newsapi"]["configuration_status"] == "missing_config"
    assert "NEWSAPI_KEY" in by_id["newsapi"]["configuration_reason_ar"]
    assert by_id["gnews"]["configuration_status"] == "missing_config"
    assert by_id["gdelt"]["configuration_status"] in {"configured", "missing_config"}


@pytest.mark.asyncio
async def test_news_sources_disabled_source_shows_disabled_reason(monkeypatch):
    _install_managed(
        monkeypatch,
        enabled={"gdelt": False},
        secrets={},
        configs={},
    )
    envelope = await news_router.build_news_truth_envelope(_Redis())
    by_id = {s["source_id"]: s for s in envelope["sources"]}

    assert by_id["gdelt"]["configuration_status"] == "disabled"
    assert by_id["gdelt"]["configuration_reason_ar"]


@pytest.mark.asyncio
async def test_news_sources_runtime_health_connectivity_passthrough(monkeypatch):
    _install_managed(monkeypatch, enabled={}, secrets={}, configs={})
    now = datetime.now(UTC)
    redis = _Redis({
        "fundamental:sources:health": [{
            "source_id": "calendar_secondary",
            "health": "healthy",
            "last_success_at": _iso(now),
        }],
    })
    envelope = await news_router.build_news_truth_envelope(redis)
    cal = next(s for s in envelope["sources"] if s["source_id"] == "calendar_secondary")

    assert cal["connectivity"] == "healthy"
    assert cal["last_success_at"] == _iso(now)


# ── NewsFetcher: dedup and disabled/missing-key paths stay offline ───────────

@pytest.mark.asyncio
async def test_news_fetcher_dedup_is_case_and_whitespace_insensitive():
    from shared.models import NewsItem
    from services.nexus_news.news_fetcher import NewsFetcher

    fetcher = NewsFetcher()
    items = [
        NewsItem(headline="Gold hits record high", source="A"),
        NewsItem(headline="  gold hits record HIGH ", source="B"),
        NewsItem(headline="Dollar slides", source="A"),
    ]
    deduped = fetcher._deduplicate(items)
    assert len(deduped) == 2
    assert deduped[0].headline == "Gold hits record high"


@pytest.mark.asyncio
async def test_news_fetcher_disabled_source_returns_empty_without_network(monkeypatch):
    from services.nexus_news import news_fetcher as fetcher_module

    async def _no_network(*args, **kwargs):  # pragma: no cover - guard
        raise AssertionError("network path must not be taken for disabled/missing sources")

    monkeypatch.setattr(fetcher_module, "managed_enabled", lambda sid, default=True: False)
    monkeypatch.setattr(fetcher_module.NewsFetcher, "_get_client", _no_network)

    fetcher = fetcher_module.NewsFetcher(newsapi_key="k", gnews_key="k")
    assert await fetcher.fetch_newsapi("gold") == []
    assert await fetcher.fetch_gnews("gold") == []
    assert await fetcher.fetch_gdelt("gold") == []


@pytest.mark.asyncio
async def test_news_fetcher_missing_key_returns_empty_without_network(monkeypatch):
    from services.nexus_news import news_fetcher as fetcher_module

    async def _no_network(*args, **kwargs):  # pragma: no cover - guard
        raise AssertionError("network path must not be taken without a configured key")

    monkeypatch.setattr(fetcher_module, "managed_enabled", lambda sid, default=True: True)
    monkeypatch.setattr(fetcher_module, "managed_secret", lambda sid, env=None: "")
    monkeypatch.setattr(fetcher_module.NewsFetcher, "_get_client", _no_network)

    fetcher = fetcher_module.NewsFetcher(newsapi_key="", gnews_key="")
    assert await fetcher.fetch_newsapi("gold") == []
    assert await fetcher.fetch_gnews("gold") == []


def test_news_fetcher_describe_sources_lists_configuration_truth(monkeypatch):
    from services.nexus_news import news_fetcher as fetcher_module

    monkeypatch.setattr(fetcher_module, "managed_enabled", lambda sid, default=True: sid != "gnews")
    monkeypatch.setattr(fetcher_module, "managed_secret", lambda sid, env=None: "" if sid != "newsapi" else "set")

    described = {s["source_id"]: s for s in fetcher_module.NewsFetcher().describe_sources()}

    assert described["newsapi"]["configuration_status"] == "configured"
    assert described["gnews"]["configuration_status"] == "disabled"
    assert described["gdelt"]["configuration_status"] == "configured"
    for entry in described.values():
        assert entry["configuration_reason_ar"]


# ── Runtime meta merge: first availability is sticky ─────────────────────────

def test_news_meta_merge_keeps_first_available_across_empty_and_failed_polls():
    from services.nexus_news.fundamental.runtime import merge_news_meta

    first = merge_news_meta(None, {
        "polled_at": "2026-10-21T10:00:00+00:00",
        "last_success_at": "2026-10-21T10:00:00+00:00",
        "item_count": 3,
        "degraded": False,
        "last_error": None,
    })
    assert first["first_available_at"] == "2026-10-21T10:00:00+00:00"

    after_empty = merge_news_meta(first, {
        "polled_at": "2026-10-21T10:00:30+00:00",
        "item_count": 0,
        "degraded": False,
        "last_error": None,
    })
    assert after_empty["first_available_at"] == "2026-10-21T10:00:00+00:00"
    assert after_empty["last_success_at"] == "2026-10-21T10:00:00+00:00"

    after_failure = merge_news_meta(after_empty, {
        "polled_at": "2026-10-21T10:01:00+00:00",
        "degraded": True,
        "last_error": "providers unreachable",
    })
    assert after_failure["first_available_at"] == "2026-10-21T10:00:00+00:00"
    assert after_failure["degraded"] is True
    assert after_failure["last_error"] == "providers unreachable"
