"""
Nexus News — FastAPI service (Service 4: News + NLP).

Provides endpoints for latest news, economic calendar, sentiment analysis,
and free-form text analysis.  Background tasks poll news sources every 30 s
and the economic calendar every 5 min, publishing NewsAlertEvent to Redis
when high-impact news is detected.
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis
import structlog
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from shared.constants import (
    CACHE_HEALTH_PREFIX,
    HEARTBEAT_INTERVAL_SEC,
    RedisStream,
    ServiceName,
    STREAM_MAX_LEN,
)
from shared.events import NewsAlertEvent
from shared.models import CalendarEvent, NewsItem, SystemHealth
from shared.security_headers import SecurityHeadersMiddleware

from .calendar_parser import CalendarParser
from .news_fetcher import NewsFetcher
from .social_sentiment import SentimentResult, SocialSentiment
from .fundamental.runtime import FundamentalRuntime
from .internal_auth import verify_internal_service_secret

# ── Logging ──────────────────────────────────────────────────────────────────

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        structlog.get_config().get("min_level", 20)  # INFO
    ),
)

from shared import setup_logger as _setup_logger
_setup_logger("nexus-news")
log = structlog.get_logger("nexus_news")

# ── Configuration ────────────────────────────────────────────────────────────

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")
GNEWS_KEY = os.getenv("GNEWS_KEY", "")
USE_FINBERT = os.getenv("USE_FINBERT", "true").lower() == "true"
NEWS_POLL_SEC = int(os.getenv("NEWS_POLL_SEC", "30"))
CALENDAR_POLL_SEC = int(os.getenv("CALENDAR_POLL_SEC", "300"))

DEFAULT_SYMBOLS = [
    "XAUUSD",
]

# ── Shared state ─────────────────────────────────────────────────────────────

_redis: aioredis.Redis | None = None
_fetcher: NewsFetcher | None = None
_calendar: CalendarParser | None = None
_sentiment: SocialSentiment | None = None
_fundamental: FundamentalRuntime | None = None

_latest_news: list[NewsItem] = []
_latest_calendar: list[CalendarEvent] = []
_bg_tasks: list[asyncio.Task[None]] = []

# ── Request / response schemas ───────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)
    symbol: str | None = None


class AnalyzeResponse(BaseModel):
    text: str
    keyword_score: float
    finbert_score: float
    combined_score: float
    affected_currencies: list[str]


class SentimentResponse(BaseModel):
    symbol: str
    social_score: float
    reddit: dict[str, Any] = Field(default_factory=dict)
    twitter: dict[str, Any] = Field(default_factory=dict)


# ── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _redis, _fetcher, _calendar, _sentiment, _fundamental, _bg_tasks  # noqa: PLW0603

    log.info("nexus_news_starting", port=8005)

    # Keep ownership local so each start has a fresh list and cleanup cannot
    # accidentally join tasks from another lifespan.
    tasks: list[asyncio.Task[None]] = []
    _bg_tasks = tasks
    async with AsyncExitStack() as resources:
        _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        resources.push_async_callback(_redis.aclose)
        _fetcher = NewsFetcher(newsapi_key=NEWSAPI_KEY, gnews_key=GNEWS_KEY)
        resources.push_async_callback(_fetcher.close)
        _calendar = CalendarParser()
        resources.push_async_callback(_calendar.close)
        _sentiment = SocialSentiment(use_finbert=USE_FINBERT)
        _fundamental = FundamentalRuntime(_redis)
        resources.push_async_callback(_fundamental.close)
        try:
            await _fundamental.initialize()

            tasks.append(asyncio.create_task(_news_poll_loop()))
            tasks.append(asyncio.create_task(_calendar_poll_loop()))
            tasks.append(asyncio.create_task(_heartbeat_loop()))
            tasks.append(asyncio.create_task(_mt5_calendar_worker()))

            # Canonical fundamental source loop. The legacy sentinel is intentionally
            # not started: blackout state is now owned by FundamentalRuntime.
            tasks.append(asyncio.create_task(_fundamental.official_source_loop()))

            log.info("nexus_news_started")
            yield
        finally:
            log.info("nexus_news_shutting_down")
            for task in tasks:
                task.cancel()
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            finally:
                tasks.clear()

    log.info("nexus_news_stopped")


# ── FastAPI app ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="Nexus News",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(SecurityHeadersMiddleware)


def _require_internal_service_secret(
    x_nexus_internal_secret: str | None = Header(default=None),
) -> None:
    verify_internal_service_secret(x_nexus_internal_secret)


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    redis_ok = False
    if _redis:
        try:
            await _redis.ping()
            redis_ok = True
        except Exception:
            pass

    return {
        "service": "nexus-news",
        "status": "healthy" if redis_ok else "degraded",
        "redis": redis_ok,
        "news_cache_size": len(_latest_news),
        "calendar_cache_size": len(_latest_calendar),
        "fundamental_runtime": _fundamental is not None,
        "blackout_state": (_fundamental.blackout.get("state") if _fundamental else "unavailable"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── GET /api/news/latest ────────────────────────────────────────────────────

@app.get(
    "/api/news/latest",
    response_model=list[NewsItem],
    dependencies=[Depends(_require_internal_service_secret)],
)
async def get_latest_news(
    limit: int = Query(default=50, ge=1, le=200),
    symbol: str | None = Query(default=None),
):
    items = _latest_news
    if symbol:
        sym_upper = symbol.upper()
        items = [
            n for n in items
            if sym_upper in n.affected_currencies
            or sym_upper[:3] in n.affected_currencies
            or sym_upper[3:] in n.affected_currencies
        ]
    return items[:limit]


# ── GET /api/news/calendar ──────────────────────────────────────────────────

@app.get(
    "/api/news/calendar",
    response_model=list[CalendarEvent],
    dependencies=[Depends(_require_internal_service_secret)],
)
async def get_calendar(
    minutes: int = Query(default=1440, ge=1, le=10080),
    impact: str | None = Query(default=None),
):
    if not _calendar:
        raise HTTPException(503, "Calendar parser not initialised")

    events = await _calendar.get_upcoming_events(minutes=minutes)
    if impact:
        events = [e for e in events if e.impact == impact.lower()]
    return events


# ── GET /api/news/sentiment/{symbol} ────────────────────────────────────────

@app.get(
    "/api/news/sentiment/{symbol}",
    response_model=SentimentResponse,
    dependencies=[Depends(_require_internal_service_secret)],
)
async def get_sentiment(symbol: str):
    if not _sentiment:
        raise HTTPException(503, "Sentiment analyser not initialised")

    # SocialSentiment exposes aggregate_social_sentiment(); the per-platform
    # fetch_* helpers were removed, so derive the overall score from that and
    # return neutral per-platform placeholders (the dashboard reads social_score).
    try:
        overall = await _sentiment.aggregate_social_sentiment(symbol)
    except Exception:
        log.warning("sentiment.aggregate_failed", symbol=symbol)
        overall = 0.0

    neutral = {"score": 0.0, "volume": 0, "source": "unavailable"}
    return SentimentResponse(
        symbol=symbol.upper(),
        social_score=round(float(overall or 0.0), 4),
        reddit=neutral,
        twitter=neutral,
    )


# ── POST /api/news/analyze ──────────────────────────────────────────────────

@app.post("/api/news/analyze", response_model=AnalyzeResponse)
async def analyze_text(
    req: AnalyzeRequest,
    x_nexus_internal_secret: str | None = Header(default=None),
):
    verify_internal_service_secret(x_nexus_internal_secret)
    from .news_fetcher import _map_currencies
    from .social_sentiment import _finbert_score, _keyword_score

    kw = _keyword_score(req.text)
    fb = await _finbert_score(req.text)
    combined = (kw * 0.4 + fb * 0.6) if fb != 0.0 else kw
    currencies = _map_currencies(req.text)

    return AnalyzeResponse(
        text=req.text,
        keyword_score=round(kw, 4),
        finbert_score=round(fb, 4),
        combined_score=round(combined, 4),
        affected_currencies=currencies,
    )


# ── POST /api/internal/calendar/mt5 — MT5 native calendar bridge ────────────

# The MT5 EA's WebRequest has a hard ~10s read-timeout (returns 1003) that
# ignores the configured timeout. Persistence of a 40-event chunk can exceed
# that when nexus-data is slow (persist retries), so the endpoint ACKs
# immediately and a single worker drains the queue: the EA's chunk chain
# never blocks on storage, and the sync cursor advances only AFTER the batch
# is processed (an interrupted chain resumes on the next full-window sync).
_mt5_cal_queue: "asyncio.Queue[tuple[list, bool]]" = asyncio.Queue(maxsize=64)


async def _mt5_calendar_worker() -> None:
    while True:
        mt5_events, has_more = await _mt5_cal_queue.get()
        try:
            from .fundamental.mt5_calendar import SOURCE_ID, sync_cursor_key

            merged = merge_mt5_primary_ref(mt5_events, _latest_calendar)
            if _fundamental and mt5_events:
                await _fundamental.on_calendar(merged)
            if _fundamental and not merged and not mt5_events:
                # Nothing new from MT5 and no prior calendar: keep the
                # degraded blackout state truthful instead of silently
                # clearing it.
                await _fundamental.on_calendar_failure(
                    RuntimeError("MT5 calendar batch empty; no web fallback yet"))
            if _redis and not has_more:
                try:
                    await _redis.set(
                        sync_cursor_key(),
                        str(int(datetime.now(timezone.utc).timestamp())))
                except Exception as exc:  # cursor loss only widens the window
                    log.warning("mt5_calendar.cursor_write_failed", error=str(exc))
            log.info("mt5_calendar.processed", source=SOURCE_ID,
                     accepted=len(mt5_events), merged_total=len(merged),
                     has_more=has_more)
        except Exception:
            log.exception("mt5_calendar.process_error")
        finally:
            _mt5_cal_queue.task_done()


# Set by the startup hook; avoids importing the merge helper at module load.
merge_mt5_primary_ref = None


@app.post("/api/internal/calendar/mt5")
async def mt5_calendar_ingest(
    payload: dict,
    x_nexus_internal_secret: str | None = Header(default=None),
):
    """Ingest one batch of MT5-native economic calendar events (EA bridge).

    MT5 is the PRIMARY calendar source: parsed events replace matching web
    events, the merged set drives blackout + persistence + Redis publish via
    the existing on_calendar() path.  An empty MT5 batch is accepted honestly
    (it must NOT empty the calendar — absence of MT5 data is not evidence of
    absence of events).
    """
    verify_internal_service_secret(x_nexus_internal_secret)
    from .fundamental.mt5_calendar import (
        SOURCE_ID, merge_mt5_primary, parse_mt5_calendar_payload,
    )

    global merge_mt5_primary_ref  # noqa: PLW0603
    merge_mt5_primary_ref = merge_mt5_primary

    try:
        mt5_events = parse_mt5_calendar_payload(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    has_more = bool(payload.get("has_more"))
    accepted = len(mt5_events)
    merged_total = len(merge_mt5_primary(mt5_events, _latest_calendar))

    # ACK immediately; the worker owns storage latency (see queue comment).
    try:
        _mt5_cal_queue.put_nowait((mt5_events, has_more))
    except asyncio.QueueFull:
        log.warning("mt5_calendar.queue_full_dropped", accepted=accepted,
                    has_more=has_more)

    log.info("mt5_calendar.ingested", source=SOURCE_ID, accepted=accepted,
             merged_total=merged_total, has_more=has_more)
    return {"ok": True, "source": SOURCE_ID, "accepted": accepted,
            "merged_total": merged_total, "has_more": has_more}


# ── Sentinel endpoints (Fase 4) ───────────────────────────────────────────────

@app.get(
    "/api/news/sentinel/alerts",
    dependencies=[Depends(_require_internal_service_secret)],
)
async def get_sentinel_alerts(limit: int = Query(default=20, ge=1, le=50)):
    """Structured impact alerts from the news sentinel."""
    if not _redis:
        raise HTTPException(503, "Redis not initialised")
    try:
        raw = await _redis.lrange("nexus:news:sentinel:alerts", 0, limit - 1)
        return {"alerts": [json.loads(x) for x in raw], "count": len(raw)}
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.get(
    "/api/news/sentinel/blackout",
    dependencies=[Depends(_require_internal_service_secret)],
)
async def get_blackout_status():
    """Compatibility endpoint backed by the canonical fundamental blackout state."""
    if not _fundamental:
        raise HTTPException(503, "Fundamental runtime not initialised")
    return _fundamental.blackout


@app.get(
    "/api/news/sentinel/status",
    dependencies=[Depends(_require_internal_service_secret)],
)
async def get_sentinel_status():
    """Compatibility status for the canonical news/fundamental safety layer."""
    if not _fundamental:
        raise HTTPException(503, "Fundamental runtime not initialised")
    blackout = _fundamental.blackout
    return {
        "last_scan": blackout.get("checked_at"),
        "blackout_active": blackout.get("active", False),
        "blackout_state": blackout.get("state", "unavailable"),
        "blackout_reason": blackout.get("reason_ar", blackout.get("reason", "")),
        "sources": _fundamental.source_health,
    }


# ── Background: news polling ────────────────────────────────────────────────

async def _news_poll_loop() -> None:
    global _latest_news  # noqa: PLW0603
    log.info("news_poll_started", interval_sec=NEWS_POLL_SEC)

    while True:
        try:
            if _fetcher:
                items = await _fetcher.fetch_all(DEFAULT_SYMBOLS)
                if items:
                    _latest_news = sorted(
                        items, key=lambda n: n.timestamp, reverse=True,
                    )
                    if _fundamental:
                        _latest_news = await _fundamental.on_news(_latest_news)
                    await _publish_high_impact_news(_latest_news)
                    log.info("news_poll_ok", count=len(_latest_news))
                elif _fundamental:
                    # A successful poll with no headlines is "empty", not "unavailable".
                    await _fundamental.on_news_empty_poll()
                    log.info("news_poll_ok_empty")
        except asyncio.CancelledError:
            break
        except Exception as exc:
            log.error("news_poll_error", error=str(exc))
            if _fundamental:
                await _fundamental.on_news_failure(exc)

        await asyncio.sleep(NEWS_POLL_SEC)


async def _publish_high_impact_news(items: list[NewsItem]) -> None:
    """Publish NewsAlertEvent to Redis for items with high-impact indicators."""
    if not _redis:
        return

    high_impact_keywords = {
        "breaking", "urgent", "flash", "emergency", "rate decision",
        "surprise", "shock", "crisis", "crash", "surge",
    }

    for item in items:
        headline_lower = item.headline.lower()
        is_high = (
            item.impact == "high"
            or any(kw in headline_lower for kw in high_impact_keywords)
        )
        if not is_high:
            continue

        event = NewsAlertEvent(
            source="nexus-news",
            headline=item.headline,
            source_name=item.source,
            impact=item.impact,
            sentiment=item.sentiment,
            affected_currencies=item.affected_currencies,
            finbert_score=item.finbert_score,
        )

        try:
            await _redis.xadd(
                RedisStream.NEWS_ALERT,
                event.to_stream_dict(),
                maxlen=STREAM_MAX_LEN,
            )
            log.info(
                "news_alert_published",
                headline=item.headline[:80],
                impact=item.impact,
            )
        except Exception as exc:
            log.error("news_alert_publish_error", error=str(exc))


# ── Background: calendar polling ─────────────────────────────────────────────

async def _calendar_poll_loop() -> None:
    global _latest_calendar  # noqa: PLW0603
    log.info("calendar_poll_started", interval_sec=CALENDAR_POLL_SEC)

    while True:
        try:
            if _calendar:
                events = await _calendar.fetch_calendar()
                if not events:
                    raise RuntimeError("calendar providers returned no events; safety state cannot be certified")
                web_events = sorted(
                    events, key=lambda e: e.timestamp,
                )
                # Preserve MT5-native events across the web poll: the web
                # fetch replaces the whole calendar by default, which used to
                # drop the MT5 primary source from the published DTO until
                # the next EA sync re-merged it (cache oscillation).
                from .fundamental.mt5_calendar import merge_mt5_primary
                merged = merge_mt5_primary(
                    _fundamental.mt5_events() if _fundamental else [],
                    web_events)
                _latest_calendar = sorted(
                    merged, key=lambda e: e.timestamp,
                )
                if _fundamental:
                    await _fundamental.on_calendar(_latest_calendar)
                log.info("calendar_poll_ok", count=len(events),
                         merged_total=len(_latest_calendar))
        except asyncio.CancelledError:
            break
        except Exception as exc:
            log.error("calendar_poll_error", error=str(exc))
            if _fundamental:
                await _fundamental.on_calendar_failure(exc)

        await asyncio.sleep(CALENDAR_POLL_SEC)


# ── Background: heartbeat ───────────────────────────────────────────────────

async def _heartbeat_loop() -> None:
    while True:
        try:
            if _redis:
                # P2-2 fix: publish the same SystemHealth dict shape every other
                # service writes (features/monitor/...). A bare ISO timestamp
                # string fails the gateway's isinstance(dict) cache check and
                # made /api/system/health report nexus-news as "unknown".
                health = SystemHealth(
                    service_name=ServiceName.NEWS,
                    status="healthy",
                    last_heartbeat=datetime.now(timezone.utc),
                )
                await _redis.set(
                    f"{CACHE_HEALTH_PREFIX}{ServiceName.NEWS}",
                    health.model_dump_json(),
                    ex=HEARTBEAT_INTERVAL_SEC * 3,
                )
        except asyncio.CancelledError:
            break
        except Exception:
            pass
        await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)


# ── Entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "services.nexus_news.main:app",
        host="127.0.0.1",
        port=int(os.getenv("NEXUS_SERVICE_PORT", "9005")),
        reload=True,
    )
