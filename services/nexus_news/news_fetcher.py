"""
Nexus News — multi-source news aggregation with rate limiting and deduplication.

Integrates GDELT (free-first), NewsAPI and GNews, maps headlines to affected currencies/assets,
and provides a unified async interface consumed by the polling loop in main.py.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from shared.http_client import new_client
import structlog
from pydantic import BaseModel, Field

from shared.models import NewsItem
from shared.source_manager import (
    managed_enabled,
    managed_endpoint,
    managed_secret,
    managed_source_config,
)

from .url_safety import safe_error

log = structlog.get_logger(__name__)

# ── Currency / asset keyword mapping ─────────────────────────────────────────

CURRENCY_KEYWORDS: dict[str, list[str]] = {
    "USD": ["dollar", "usd", "fed", "fomc", "treasury", "us economy", "nonfarm", "cpi"],
    "EUR": ["euro", "eur", "ecb", "eurozone", "eu economy"],
    "GBP": ["pound", "gbp", "boe", "bank of england", "uk economy"],
    "JPY": ["yen", "jpy", "boj", "bank of japan", "japan economy"],
    "AUD": ["aussie", "aud", "rba", "australia economy"],
    "NZD": ["kiwi", "nzd", "rbnz", "new zealand economy"],
    "CAD": ["loonie", "cad", "boc", "canada economy", "oil price"],
    "CHF": ["franc", "chf", "snb", "swiss economy"],
    "XAU": ["gold", "xau", "precious metal", "bullion"],
    "BTC": ["bitcoin", "btc", "crypto"],
    "ETH": ["ethereum", "eth"],
    "SPX": ["s&p", "spx", "sp500", "wall street"],
}

# ── Rate limiter ─────────────────────────────────────────────────────────────

# GDELT DOC 2.0 is a free/public endpoint that rate-limits per IP.  A 429 (or a
# dropped/empty response while throttling) pauses *every* query for a while so
# one poll cycle cannot re-fire the same request seconds later.
_GDELT_BACKOFF_BASE_SEC = 30.0
_GDELT_BACKOFF_MAX_SEC = 300.0
_GDELT_RETRY_AFTER_MAX_SEC = 600.0
_GDELT_LOG_THROTTLE_SEC = 300.0


class _RateLimiter:
    """Token-bucket rate limiter per API source."""

    def __init__(self, calls_per_minute: int = 30):
        self._interval = 60.0 / calls_per_minute
        self._last_call: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._interval - (now - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()


# ── Fetcher ──────────────────────────────────────────────────────────────────

class NewsFetcher:
    """Aggregates headlines from GDELT, NewsAPI and GNews with deduplication."""

    def __init__(
        self,
        newsapi_key: str = "",
        gnews_key: str = "",
        cache_ttl_sec: int = 120,
    ):
        self._newsapi_key = newsapi_key
        self._gnews_key = gnews_key
        self._cache_ttl = cache_ttl_sec

        self._newsapi_limiter = _RateLimiter(calls_per_minute=25)
        self._gnews_limiter = _RateLimiter(calls_per_minute=10)
        self._gdelt_limiter = _RateLimiter(calls_per_minute=6)

        # Shared GDELT backoff state — rate limiting is per IP, so a 429 for
        # one query pauses every query instead of re-firing seconds later.
        self._gdelt_paused_until = 0.0
        self._gdelt_failures = 0
        self._gdelt_skip_logged: dict[str, float] = {}

        self._seen_hashes: dict[str, float] = {}
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = new_client(timeout=15.0, pin_dns=True, follow_redirects=False)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def describe_sources(self) -> list[dict[str, Any]]:
        """Configuration truth for news providers. Never touches the network.

        A missing key is reported as an external requirement, never as an
        implicit fallback to another provider or to empty-but-"ready" data.
        """
        described: list[dict[str, Any]] = []
        for sid in ("newsapi", "gnews", "gdelt"):
            cfg = managed_source_config(sid) or {}
            secret_env = str(cfg.get("secret_env") or "") or None
            secret_optional = bool(cfg.get("secret_optional", True))
            auth_mode = str(cfg.get("auth_mode") or "none")
            if not managed_enabled(sid, True):
                status = "disabled"
                reason = "المصدر معطل من إدارة المصادر؛ فقده متطلب خارجي مسجل."
            elif auth_mode != "none" and secret_env and not secret_optional and not (managed_secret(sid, secret_env) or "").strip():
                status = "missing_config"
                reason = f"المصدر يتطلب مفتاحًا خارجيًا ({secret_env}) غير مضبوط."
            else:
                status = "configured"
                reason = "إعداد المصدر مكتمل محليًا."
            described.append({
                "source_id": sid,
                "configuration_status": status,
                "configuration_reason_ar": reason,
            })
        return described

    # ── NewsAPI ──────────────────────────────────────────────────────────────

    async def fetch_newsapi(
        self, query: str, language: str = "en"
    ) -> list[NewsItem]:
        if not managed_enabled("newsapi", True):
            return []
        self._newsapi_key = managed_secret("newsapi", "NEWSAPI_KEY") or self._newsapi_key
        if not self._newsapi_key:
            log.warning("newsapi_key not configured — skipping NewsAPI")
            return []

        await self._newsapi_limiter.acquire()
        client = await self._get_client()

        params: dict[str, Any] = {
            "q": query,
            "language": language,
            "sortBy": "publishedAt",
            "pageSize": 20,
            "apiKey": self._newsapi_key,
        }

        try:
            resp = await client.get(
                managed_endpoint("newsapi", "https://newsapi.org/v2").rstrip("/") + "/everything", params=params
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                log.warning("newsapi_rate_limited", query=query)
            else:
                log.error("newsapi_error", status=exc.response.status_code)
            return []
        except httpx.HTTPError as exc:
            log.error("newsapi_http_error", error=safe_error(exc))
            return []

        items: list[NewsItem] = []
        for article in data.get("articles", []):
            headline = (article.get("title") or "").strip()
            if not headline:
                continue

            published = article.get("publishedAt", "")
            ts = _parse_iso(published) if published else datetime.now(timezone.utc)

            items.append(
                NewsItem(
                    headline=headline,
                    source=article.get("source", {}).get("name", "NewsAPI"),
                    provider_id="newsapi",
                    url=article.get("url"),
                    summary=(article.get("description") or "")[:1200],
                    timestamp=ts,
                    affected_currencies=_map_currencies(headline),
                )
            )

        log.debug("newsapi_fetched", query=query, count=len(items))
        return items

    # ── GNews ────────────────────────────────────────────────────────────────

    async def fetch_gnews(self, query: str) -> list[NewsItem]:
        if not managed_enabled("gnews", True):
            return []
        self._gnews_key = managed_secret("gnews", "GNEWS_KEY") or self._gnews_key
        if not self._gnews_key:
            log.warning("gnews_key not configured — skipping GNews")
            return []

        await self._gnews_limiter.acquire()
        client = await self._get_client()

        params: dict[str, Any] = {
            "q": query,
            "lang": "en",
            "max": 10,
            "token": self._gnews_key,
        }

        try:
            resp = await client.get(
                managed_endpoint("gnews", "https://gnews.io/api/v4").rstrip("/") + "/search", params=params
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                log.warning("gnews_rate_limited", query=query)
            else:
                log.error("gnews_error", status=exc.response.status_code)
            return []
        except httpx.HTTPError as exc:
            log.error("gnews_http_error", error=safe_error(exc))
            return []

        items: list[NewsItem] = []
        for article in data.get("articles", []):
            headline = (article.get("title") or "").strip()
            if not headline:
                continue

            published = article.get("publishedAt", "")
            ts = _parse_iso(published) if published else datetime.now(timezone.utc)

            items.append(
                NewsItem(
                    headline=headline,
                    source=article.get("source", {}).get("name", "GNews"),
                    provider_id="gnews",
                    url=article.get("url"),
                    summary=(article.get("description") or article.get("content") or "")[:1200],
                    timestamp=ts,
                    affected_currencies=_map_currencies(headline),
                )
            )

        log.debug("gnews_fetched", query=query, count=len(items))
        return items


    # ── GDELT DOC 2.0 (free/public) ─────────────────────────────────────────

    def _gdelt_remaining_pause(self) -> float:
        return max(0.0, self._gdelt_paused_until - time.monotonic())

    def _gdelt_pause(self, retry_after: str | None = None) -> float:
        """Extend the shared GDELT pause and return how long it lasts."""
        self._gdelt_failures += 1
        delay = min(_GDELT_BACKOFF_MAX_SEC,
                    _GDELT_BACKOFF_BASE_SEC * (2 ** min(self._gdelt_failures - 1, 4)))
        parsed = _parse_retry_after(retry_after)
        if parsed is not None:
            # The server asked for a specific wait: honor it, clamped so a
            # bogus header cannot silence news for hours.
            delay = max(delay, min(_GDELT_RETRY_AFTER_MAX_SEC, max(parsed, 1.0)))
        self._gdelt_paused_until = time.monotonic() + delay
        return delay

    def _gdelt_mark_ok(self) -> None:
        self._gdelt_failures = 0
        self._gdelt_paused_until = 0.0
        self._gdelt_skip_logged.clear()

    def _gdelt_skip_log(self, event: str, **kw) -> None:
        """Repeatable GDELT skips: warn once per window, debug in between."""
        now = time.monotonic()
        if now - self._gdelt_skip_logged.get(event, 0.0) >= _GDELT_LOG_THROTTLE_SEC:
            self._gdelt_skip_logged[event] = now
            log.warning(event, **kw)
        else:
            log.debug(event, **kw)

    async def fetch_gdelt(self, query: str) -> list[NewsItem]:
        if not managed_enabled("gdelt", True):
            return []

        paused = self._gdelt_remaining_pause()
        if paused > 0:
            log.debug("gdelt_paused", query=query, retry_in_sec=round(paused, 1))
            return []

        await self._gdelt_limiter.acquire()
        client = await self._get_client()
        endpoint = managed_endpoint("gdelt", "https://api.gdeltproject.org/api/v2/doc/doc")

        params: dict[str, Any] = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": 25,
            "timespan": "1h",
            "sort": "datedesc",
        }

        try:
            resp = await client.get(endpoint, params=params)
        except Exception as exc:
            # Transport trouble (timeout / dropped connection).  With the pinned
            # shared transport these reach here as raw httpcore errors whose
            # str() is often empty — transient, so back off quietly.
            delay = self._gdelt_pause(None)
            self._gdelt_skip_log("gdelt_transport_error", query=query,
                                 error=safe_error(exc) or type(exc).__name__,
                                 retry_in_sec=round(delay, 1))
            return []

        if resp.status_code == 429:
            delay = self._gdelt_pause(resp.headers.get("Retry-After"))
            self._gdelt_skip_log("gdelt_rate_limited", query=query,
                                 retry_in_sec=round(delay, 1))
            return []

        if resp.status_code >= 400:
            self._gdelt_pause(None)
            log.error("gdelt_http_error", status=resp.status_code, query=query)
            return []

        try:
            body = resp.text
        except Exception as exc:
            self._gdelt_skip_log("gdelt_invalid_response", query=query,
                                 error=safe_error(exc) or type(exc).__name__)
            return []
        if not body.strip():
            # GDELT answers 200 with an empty body while throttling: a skip,
            # not an error.
            self._gdelt_skip_log("gdelt_empty_response", query=query,
                                 status=resp.status_code)
            return []
        try:
            data = json.loads(body)
        except ValueError:
            self._gdelt_skip_log("gdelt_invalid_response", query=query,
                                 status=resp.status_code, bytes=len(body))
            return []

        items: list[NewsItem] = []
        articles = data.get("articles", []) if isinstance(data, dict) else []
        if not isinstance(articles, list):
            self._gdelt_mark_ok()
            return []
        for article in articles:
            if not isinstance(article, dict):
                continue
            headline = (article.get("title") or "").strip()
            if not headline:
                continue
            published = article.get("seendate") or article.get("date") or article.get("publishedAt") or ""
            ts = _parse_gdelt_date(published) if published else datetime.now(timezone.utc)
            source_name = article.get("domain") or article.get("sourcecountry") or "GDELT"
            item = NewsItem(
                headline=headline,
                source=str(source_name),
                timestamp=ts,
                affected_currencies=_map_currencies(headline),
            )
            try:
                setattr(item, "provider_id", "gdelt")
                setattr(item, "url", article.get("url"))
            except Exception:
                pass
            items.append(item)

        self._gdelt_mark_ok()
        log.debug("gdelt_fetched", query=query, count=len(items))
        return items

    # ── Aggregator ───────────────────────────────────────────────────────────

    async def fetch_all(self, symbols: list[str]) -> list[NewsItem]:
        """Fetch from all sources for the given symbols, deduplicate, and return."""
        queries = _symbols_to_queries(symbols)
        tasks: list[asyncio.Task[list[NewsItem]]] = []

        for q in queries:
            tasks.append(asyncio.create_task(self.fetch_gdelt(q)))
            tasks.append(asyncio.create_task(self.fetch_newsapi(q)))
            tasks.append(asyncio.create_task(self.fetch_gnews(q)))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        combined: list[NewsItem] = []
        for res in results:
            if isinstance(res, BaseException):
                log.error("fetch_all_task_error", error=safe_error(res))
                continue
            combined.extend(res)

        deduped = self._deduplicate(combined)
        log.info("fetch_all_complete", raw=len(combined), deduped=len(deduped))
        return deduped

    # ── Deduplication ────────────────────────────────────────────────────────

    def _deduplicate(self, items: list[NewsItem]) -> list[NewsItem]:
        self._evict_stale()
        unique: list[NewsItem] = []
        now = time.monotonic()

        for item in items:
            h = _headline_hash(item.headline)
            if h not in self._seen_hashes:
                self._seen_hashes[h] = now
                unique.append(item)

        return unique

    def _evict_stale(self) -> None:
        now = time.monotonic()
        stale = [k for k, t in self._seen_hashes.items() if now - t > self._cache_ttl]
        for k in stale:
            del self._seen_hashes[k]


# ── Module-level helpers ─────────────────────────────────────────────────────

def _headline_hash(headline: str) -> str:
    normalised = headline.lower().strip()
    return hashlib.sha256(normalised.encode()).hexdigest()[:16]


def _map_currencies(text: str) -> list[str]:
    text_lower = text.lower()
    return [
        ccy
        for ccy, keywords in CURRENCY_KEYWORDS.items()
        if any(kw in text_lower for kw in keywords)
    ]


def _symbols_to_queries(symbols: list[str]) -> list[str]:
    """Convert trading symbols like EURUSD into search-friendly queries."""
    queries: set[str] = set()
    for sym in symbols:
        sym_upper = sym.upper().replace("/", "")
        if len(sym_upper) == 6:
            queries.add(sym_upper[:3])
            queries.add(sym_upper[3:])
        else:
            queries.add(sym_upper)

    keyword_map: dict[str, str] = {
        "USD": "US dollar economy",
        "EUR": "Euro eurozone economy",
        "GBP": "British pound economy",
        "JPY": "Japanese yen economy",
        "AUD": "Australian dollar economy",
        "NZD": "New Zealand dollar economy",
        "CAD": "Canadian dollar economy",
        "CHF": "Swiss franc economy",
        "XAU": "gold price",
        "BTC": "bitcoin crypto",
        "ETH": "ethereum crypto",
    }
    return [keyword_map.get(q, q) for q in queries]



def _parse_retry_after(raw: Any) -> float | None:
    """``Retry-After`` header → seconds, or None when unusable.

    Accepts both forms from RFC 9110: delta-seconds and HTTP-date.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        target = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    return (target - datetime.now(timezone.utc)).total_seconds()


def _parse_gdelt_date(raw: str) -> datetime:
    raw = str(raw or "").strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return _parse_iso(raw)

def _parse_iso(raw: str) -> datetime:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)
