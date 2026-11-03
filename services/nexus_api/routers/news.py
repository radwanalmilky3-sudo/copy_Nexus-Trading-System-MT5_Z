"""
News router — latest news feed, calendar events, and per-symbol sentiment.

Truth contract: an empty list never claims "the market produced no news".
`/api/news/status` and the shared envelope helper distinguish a pipeline that
never ran, a failed last poll, a genuinely empty poll, and a stale snapshot.
Duplicate headlines are removed server-side before filters are applied.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query

from shared.redis_client import RedisClient
from shared.source_manager import (
    managed_enabled,
    managed_secret,
    managed_source_config,
)

from ..deps import get_redis
from .admin import require_permission

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/news", tags=["news"])
_TRADING_VIEW = require_permission("trading.view")

UTC = timezone.utc
NEWS_TRUTH_LIMIT_SEC = 900

_NEWS_PROVIDERS: tuple[tuple[str, str], ...] = (
    ("newsapi", "NewsAPI"),
    ("gnews", "GNews"),
    ("gdelt", "GDELT"),
    ("calendar_secondary", "التقويم الاقتصادي الثانوي"),
)


# ── Truth envelope helpers (shared with the fundamental gateway) ─────────────

def dedupe_news_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop duplicate headlines (case/whitespace-insensitive), keeping order."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        key = " ".join(str(raw.get("headline") or "").lower().split())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(raw)
    return out


def _parse_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


async def news_provider_truth(redis: RedisClient) -> list[dict[str, Any]]:
    """Configuration/connectivity truth for news providers. No network calls."""
    health_raw = await redis.cache_get("fundamental:sources:health")
    by_id: dict[str, dict[str, Any]] = {}
    if isinstance(health_raw, list):
        by_id = {str(x.get("source_id")): x for x in health_raw if isinstance(x, dict)}

    providers: list[dict[str, Any]] = []
    for sid, default_name in _NEWS_PROVIDERS:
        cfg = managed_source_config(sid) or {}
        name = str(cfg.get("name_ar") or default_name)
        secret_env = str(cfg.get("secret_env") or "") or None
        secret_optional = bool(cfg.get("secret_optional", True))
        auth_mode = str(cfg.get("auth_mode") or "none")

        if not managed_enabled(sid, True):
            status = "disabled"
            reason = "المصدر معطل بواسطة المستخدم؛ فقده متطلب خارجي لا يُعالَج تلقائيًا."
        elif auth_mode != "none" and secret_env and not secret_optional and not (managed_secret(sid, secret_env) or "").strip():
            status = "missing_config"
            reason = f"المصدر يتطلب مفتاحًا خارجيًا ({secret_env}) غير مضبوط حاليًا."
        else:
            status = "configured"
            reason = "إعداد المصدر مكتمل من الناحية المحلية."

        health = by_id.get(sid) if isinstance(by_id.get(sid), dict) else {}
        providers.append({
            "source_id": sid,
            "name_ar": name,
            "configuration_status": status,
            "configuration_reason_ar": reason,
            "connectivity": str(health.get("health") or "unknown"),
            "last_success_at": health.get("last_success_at"),
            "health_description_ar": health.get("health_description_ar"),
        })
    return providers


async def build_news_truth_envelope(
    redis: RedisClient,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Truthful state for the news snapshot: unavailable/empty/ready/stale."""
    now = now or datetime.now(UTC)

    raw = await redis.cache_get("news:latest")
    items = dedupe_news_items([x for x in raw if isinstance(x, dict)]) if isinstance(raw, list) else []
    meta_raw = await redis.cache_get("news:meta")
    meta = meta_raw if isinstance(meta_raw, dict) else None

    timestamps = [ts for ts in (_parse_ts(i.get("timestamp")) for i in items) if ts]
    newest = max(timestamps) if timestamps else None
    oldest = min(timestamps) if timestamps else None

    last_update = (meta or {}).get("last_success_at") or _iso(newest)
    first_available = (meta or {}).get("first_available_at") or _iso(oldest)
    degraded = bool((meta or {}).get("degraded"))
    last_error = (meta or {}).get("last_error")

    age_sec = int((now - newest).total_seconds()) if newest else None
    stale = age_sec is not None and age_sec > NEWS_TRUTH_LIMIT_SEC

    if not items:
        if meta is None:
            state = "unavailable"
            reason = "لم يبلغ مسار الأخبار بحالة بعد؛ لا يمكن تأكيد خلوّ الأسواق من الأخبار، ولن تُعرض بيانات بديلة."
        elif degraded:
            reason = f"فشل آخر مسح للأخبار: {last_error or 'سبب غير محدد'}؛ لم تُستبدل اللقطة القديمة بأي بيانات وهمية."
            if last_update:
                reason += f" آخر نجاح مسجل: {last_update}."
            state = "unavailable"
        else:
            state = "empty"
            reason = f"اكتمل آخر مسح للأخبار في {last_update or 'وقت غير معروف'} دون نتائج. الغياب لا يعني جاهزية التحليل."
    elif stale:
        state = "stale"
        reason = (
            f"اللقطة الحالية قديمة (عمرها {age_sec} ثانية، الحد المقبول {NEWS_TRUTH_LIMIT_SEC} ثانية)؛ "
            "تُعرض كبيانات مخزنة وليست حية."
        )
    else:
        state = "ready"
        reason = None

    return {
        "state": state,
        "item_count": len(items),
        "last_update_at": last_update,
        "first_available_at": first_available,
        "freshness": {"stale": stale, "age_sec": age_sec, "limit_sec": NEWS_TRUTH_LIMIT_SEC},
        "reason_ar": reason,
        "sources": await news_provider_truth(redis),
    }


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", dependencies=[Depends(_TRADING_VIEW)])
async def latest_news(
    limit: int = Query(50, ge=1, le=200),
    impact: str | None = Query(None, description="Filter by impact: low, medium, high"),
    symbol: str | None = Query(None, description="Filter by affected currency/asset code, e.g. XAU or USD"),
    redis: RedisClient = Depends(get_redis),
) -> list[dict[str, Any]]:
    cached = await redis.cache_get("news:latest")
    items = dedupe_news_items([n for n in cached if isinstance(n, dict)]) if isinstance(cached, list) else []

    if impact:
        items = [n for n in items if str(n.get("impact", "")).lower() == impact.lower()]
    if symbol:
        wanted = symbol.upper().replace("/", "")
        codes = {wanted, wanted[:3], wanted[3:6]} if len(wanted) >= 6 else {wanted}
        items = [
            n for n in items
            if codes & {str(c).upper() for c in (n.get("affected_currencies") or [])}
        ]
    return items[:limit]


@router.get("/status", dependencies=[Depends(_TRADING_VIEW)])
async def news_status(redis: RedisClient = Depends(get_redis)) -> dict[str, Any]:
    """Truthful availability of the news pipeline (state + freshness + sources)."""
    return await build_news_truth_envelope(redis)


@router.get("/calendar", dependencies=[Depends(_TRADING_VIEW)])
async def economic_calendar(
    currency: str | None = Query(None),
    impact: str | None = Query(None),
    redis: RedisClient = Depends(get_redis),
) -> list[dict[str, Any]]:
    cached = await redis.cache_get("news:calendar")
    if not cached or not isinstance(cached, list):
        return []

    events = cached
    if currency:
        events = [e for e in events if e.get("currency") == currency.upper()]
    if impact:
        events = [e for e in events if str(e.get("impact", "")).lower() == impact.lower()]
    return events


@router.get("/sentiment/{symbol}", dependencies=[Depends(_TRADING_VIEW)])
async def symbol_sentiment(
    symbol: str,
    redis: RedisClient = Depends(get_redis),
) -> dict[str, Any]:
    cached = await redis.cache_get(f"news:sentiment:{symbol.upper()}")
    if cached and isinstance(cached, dict):
        return cached
    return {
        "symbol": symbol.upper(),
        "state": "unavailable",
        "overall_sentiment": None,
        "score": None,
        "headlines_analyzed": 0,
        "sources": [],
        "message_ar": "بيانات المزاج الاجتماعي غير متاحة حاليًا؛ لم تُعامل كقيمة محايدة.",
    }
