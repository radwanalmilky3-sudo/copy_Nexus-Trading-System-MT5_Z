"""Arabic-first Fundamental Intelligence gateway.

The gateway renders canonical Redis/DB state only; it does not calculate market
scores.  Numerical direction/weights/confidence originate in nexus-news'
deterministic engines.  The optional Local AI endpoint is explanation-only.
"""
from __future__ import annotations

import hashlib
import asyncio as _asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from shared.redis_client import RedisClient
from ..data_client import DataServiceClient, DataServiceRejected, DataServiceUnavailable
from ..deps import get_data_service, get_redis
from ..fundamental_local_ai import GroundedLocalAI
from ..middleware.auth import CurrentUser
from .admin import _require
from .news import build_news_truth_envelope, dedupe_news_items

router = APIRouter(prefix="/api/fundamental", tags=["fundamental"])
UTC = timezone.utc
TTS_HARD_LIMIT_SECONDS = 18


def _permission_guard(permission: str):
    async def guard(
        actor: CurrentUser,
        db: DataServiceClient = Depends(get_data_service),
    ) -> None:
        await _require(db, actor, permission)
    return guard


_fundamental_view = _permission_guard("fundamental.view")
_ticker_view = _permission_guard("ticker.view")
_source_manager_view = _permission_guard("source_manager.view")

_DOMAIN_AR = {
    "macro": "الاقتصاد الكلي",
    "monetary": "السياسة النقدية والبنوك المركزية",
    "cross_asset": "الأسواق المترابطة",
    "geopolitical": "الجيوسياسة والمخاطر العالمية",
    "flows": "التدفقات والتمركزات",
}
_DIRECTION_AR = {
    "bullish": "صاعد",
    "bearish": "هابط",
    "neutral": "محايد",
    "conflicted": "متعارض",
    "unknown": "غير محدد",
}
_GOLD_DIRECTIONS = {"bullish", "bearish", "neutral", "conflicted"}
# مراحل السوق التي يكون فيها رد الفعل قد وقع فعليًا (قيم enum الحقيقية).
_MARKET_CONFIRMED_STAGES = {"confirmation", "secondary_reaction", "reversed", "normalized"}

DEFAULT_TICKER_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "position": "top",
    "speed": "medium",
    "pause_on_hover": True,
    "assets": ["XAUUSD", "BTCUSD"],
    "domains": ["macro", "monetary", "cross_asset", "geopolitical", "flows", "news"],
    "minimum_severity": "medium",
    "minimum_relevance": 40,
    "minimum_source_quality": 50,
    "max_news_age_minutes": 30,
    "audio_enabled": True,
    "critical_audio": True,
    "high_audio": True,
    "medium_audio": False,
    "language": "ar",
    "voice": "system_arabic",
    "volume": 0.85,
    "speech_rate": 1.0,
    "critical_repeat_count": 1,
    "high_repeat_count": 0,
    "repeat_delay_seconds": 25,
    "cooldown_seconds": 20,
    "quiet_hours_enabled": False,
    "quiet_hours_start": "23:00",
    "quiet_hours_end": "07:00",
    "blackout_alerts": True,
    "source_outage_alerts": False,
    "verified_source_only_voice": True,
    "two_source_geopolitical_voice": True,
    "critical_ttl_seconds": 0,
    "high_ttl_seconds": 600,
    "medium_ttl_seconds": 300,
    "low_ttl_seconds": 120,
    "hide_after_ack": True,
    "show_acknowledged": False,
    "show_scheduled": True,
    "show_breaking": True,
    "critical_display_mode": "ticker_banner_tts",
    "high_display_mode": "ticker_toast_sound",
    "medium_display_mode": "ticker_toast",
    "low_display_mode": "ticker",
    "require_ack_critical": True,
    "mute_until": None,
}


class LocalAIRequest(BaseModel):
    question: str = Field(default="اشرح الحالة الأساسية الحالية", max_length=800)
    asset: Literal["XAUUSD", "BTCUSD"] = "XAUUSD"


class TickerSettings(BaseModel):
    enabled: bool = True
    position: Literal["top", "bottom"] = "top"
    speed: Literal["slow", "medium", "fast"] = "medium"
    pause_on_hover: bool = True
    assets: list[str] = Field(default_factory=lambda: ["XAUUSD", "BTCUSD"], max_length=20)
    domains: list[str] = Field(default_factory=lambda: list(DEFAULT_TICKER_SETTINGS["domains"]), max_length=20)
    minimum_severity: Literal["low", "medium", "high", "critical"] = "medium"
    minimum_relevance: float = Field(default=40, ge=0, le=100)
    minimum_source_quality: float = Field(default=50, ge=0, le=100)
    max_news_age_minutes: int = Field(default=30, ge=1, le=1440)
    audio_enabled: bool = True
    critical_audio: bool = True
    high_audio: bool = True
    medium_audio: bool = False
    language: Literal["ar", "en"] = "ar"
    voice: str = Field(default="system_arabic", max_length=120)
    volume: float = Field(default=0.85, ge=0, le=1)
    speech_rate: float = Field(default=1.0, ge=0.6, le=1.5)
    critical_repeat_count: int = Field(default=1, ge=0, le=1)
    high_repeat_count: int = Field(default=0, ge=0, le=1)
    repeat_delay_seconds: int = Field(default=25, ge=10, le=120)
    cooldown_seconds: int = Field(default=20, ge=5, le=600)
    quiet_hours_enabled: bool = False
    quiet_hours_start: str = Field(default="23:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    quiet_hours_end: str = Field(default="07:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    blackout_alerts: bool = True
    source_outage_alerts: bool = False
    verified_source_only_voice: bool = True
    two_source_geopolitical_voice: bool = True
    critical_ttl_seconds: int = Field(default=0, ge=0, le=86400)
    high_ttl_seconds: int = Field(default=600, ge=30, le=86400)
    medium_ttl_seconds: int = Field(default=300, ge=30, le=86400)
    low_ttl_seconds: int = Field(default=120, ge=30, le=86400)
    hide_after_ack: bool = True
    show_acknowledged: bool = False
    show_scheduled: bool = True
    show_breaking: bool = True
    critical_display_mode: str = "ticker_banner_tts"
    high_display_mode: str = "ticker_toast_sound"
    medium_display_mode: str = "ticker_toast"
    low_display_mode: str = "ticker"
    require_ack_critical: bool = True
    mute_until: datetime | None = None


class AlertDelivery(BaseModel):
    ticker_item_id: str = Field(min_length=1, max_length=128)
    channel: Literal["tts", "browser"] = "tts"
    reason: str = Field(default="ticker_alert", max_length=160)
    language: str = Field(default="ar", max_length=12)
    voice_id: str | None = Field(default=None, max_length=160)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0, le=120000)
    repeat_index: int = Field(default=0, ge=0, le=2)
    acknowledged_before_send: bool = False
    result: str = Field(default="delivered", max_length=40)
    error: str | None = Field(default=None, max_length=300)


class TickerAcknowledge(BaseModel):
    acknowledged: bool = True
    actor: str = Field(default="operator", min_length=1, max_length=80)
    note: str | None = Field(default=None, max_length=240)




async def _user_ticker_overrides(db: DataServiceClient, user_id: str | None) -> dict[str, Any]:
    """Personal ticker overrides. Only explicitly-set (non-NULL) columns are
    returned so unset personal values fall back to the general setting and then
    the default — a NULL never silently overrides the general configuration."""
    if not user_id:
        return {}
    rows = await db.query("notification_preferences", {"user_id": user_id})
    if not rows:
        return {}
    r = rows[0]

    def parsed(k: str) -> list[str] | None:
        raw = r.get(k)
        if raw is None:
            return None
        try:
            v = json.loads(raw or "[]")
            return v if isinstance(v, list) else None
        except Exception:
            return None

    def pick(key: str, column: str, cast):
        value = r.get(column)
        if value is None:
            return
        try:
            out[key] = cast(value)
        except (TypeError, ValueError):
            return

    out: dict[str, Any] = {}
    pick("enabled", "ticker_enabled", bool)
    assets = parsed("assets_json")
    if assets is not None:
        out["assets"] = assets
    domains = parsed("domains_json")
    if domains is not None:
        out["domains"] = domains
    pick("minimum_severity", "minimum_severity", str)
    pick("critical_ttl_seconds", "critical_ttl_seconds", lambda v: int(v or 0))
    pick("high_ttl_seconds", "high_ttl_seconds", lambda v: int(v or 600))
    pick("medium_ttl_seconds", "medium_ttl_seconds", lambda v: int(v or 300))
    pick("low_ttl_seconds", "low_ttl_seconds", lambda v: int(v or 120))
    pick("hide_after_ack", "hide_after_ack", bool)
    pick("show_acknowledged", "show_acknowledged", bool)
    pick("show_scheduled", "show_scheduled", bool)
    pick("show_breaking", "show_breaking", bool)
    pick("source_outage_alerts", "show_source_outage", bool)
    pick("critical_display_mode", "critical_display_mode", str)
    pick("high_display_mode", "high_display_mode", str)
    pick("medium_display_mode", "medium_display_mode", str)
    pick("low_display_mode", "low_display_mode", str)
    pick("audio_enabled", "tts_enabled", bool)
    levels = parsed("tts_levels_json")
    if levels is not None:
        out["critical_audio"] = "critical" in levels
        out["high_audio"] = "high" in levels
        out["medium_audio"] = "medium" in levels
    pick("language", "tts_language", str)
    pick("voice", "tts_voice", str)
    pick("volume", "tts_volume", float)
    pick("speech_rate", "tts_rate", float)
    if r.get("tts_repeat_critical") is not None:
        out["critical_repeat_count"] = 1 if bool(r.get("tts_repeat_critical")) else 0
    pick("repeat_delay_seconds", "tts_repeat_interval_seconds", lambda v: int(v or 25))
    pick("require_ack_critical", "require_ack_critical", bool)
    if r.get("mute_until") is not None:
        out["mute_until"] = r.get("mute_until")
    pick("quiet_hours_enabled", "quiet_hours_enabled", bool)
    pick("quiet_hours_start", "quiet_hours_start", str)
    pick("quiet_hours_end", "quiet_hours_end", str)
    return out

async def _snap(redis: RedisClient, key: str, default: Any = None) -> Any:
    value = await redis.cache_get(key)
    return default if value is None else value


def _domain_contract(item: Any, details: Any) -> dict[str, Any]:
    evidence_count = len(details) if isinstance(details, list) else 0
    unavailable = not isinstance(item, dict) or not item or (
        str(item.get("state", "")).lower() == "unavailable"
        or str((item.get("metadata") or {}).get("state", "")).lower() == "unavailable"
    )
    score_state = "UNAVAILABLE" if unavailable else "AVAILABLE"
    evidence_state = "PRESENT" if evidence_count else "NONE"
    domain_state = "DATA_AVAILABLE" if score_state == "AVAILABLE" else "DEGRADED" if evidence_count else "UNAVAILABLE"
    return {
        "score_state": score_state,
        "evidence_state": evidence_state,
        "evidence_count": evidence_count,
        "domain_state": domain_state,
    }


async def _post_data(table: str, record: dict[str, Any]) -> bool:
    secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
    if not secret:
        return False
    url = os.getenv("NEXUS_DATA_URL", "http://127.0.0.1:9001").rstrip("/") + "/api/data/fundamental/record"
    try:
        safe_record = json.loads(json.dumps(record, ensure_ascii=False, default=str))
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url,
                headers={"X-Nexus-Internal-Secret": secret},
                json={"table": table, "record": safe_record},
            )
        return response.status_code < 400
    except httpx.HTTPError:
        return False


async def _overview_payload(redis: RedisClient) -> dict[str, Any]:
    gold = await _snap(redis, "fundamental:gold:latest")
    fusion = await _snap(redis, "fundamental:fusion:latest")
    explanation = await _snap(redis, "fundamental:explanation:latest")
    blackout = await _snap(redis, "fundamental:blackout", {
        "state": "unavailable", "active": False, "reason_ar": "حالة الحظر غير متاحة.",
    })
    quality = await _snap(redis, "fundamental:data_quality", {})
    domains: list[dict[str, Any]] = []
    for domain in _DOMAIN_AR:
        item = await _snap(redis, f"fundamental:{domain}:latest")
        details = await _snap(redis, f"fundamental:{domain}:details", [])
        details = details if isinstance(details, list) else []
        contract = _domain_contract(item, details)
        if isinstance(item, dict) and item:
            domains.append({**item, **contract, "domain_ar": _DOMAIN_AR[domain], "details": details})
        else:
            domains.append({
                "domain": domain,
                "domain_ar": _DOMAIN_AR[domain],
                "direction": "unknown",  # unknown ≠ 0 ≠ neutral; no fabricated direction
                "metadata": {"state": "unavailable"},
                "coverage_score": None,
                "confidence": None,
                "gold_impact_score": None,
                "native_score": None,
                "strength": None,
                "freshness_score": None,
                "data_quality_score": None,
                "reliability_score": None,
                "horizon_class": "unavailable",
                "primary_drivers": [],
                "counter_drivers": [],
                "details": details,
                **contract,
            })
    if not isinstance(gold, dict) or not gold:
        return {
            "state": "unavailable",
            "message_ar": "لم تكتمل دورة التحليل الأساسي بعد.",
            "reason_ar": "لا توجد لقطة ذهب حقيقية في الذاكرة المؤقتة؛ لن تُعرض قيم محايدة أو صفرية بديلة.",
            "result_origin": "none",
            "blackout": blackout,
            "domains": domains,
            "source_health": await _snap(redis, "fundamental:sources:health", []),
        }
    raw_direction = gold.get("direction")
    direction = str(raw_direction).strip().lower() if raw_direction is not None else ""
    direction_known = direction in _GOLD_DIRECTIONS
    if not direction_known:
        direction = "unknown"
    stage_raw = gold.get("stage")
    stage = str(stage_raw).strip().lower() if stage_raw is not None else None
    market_confirmation = None if stage is None else (
        "مؤكد" if stage in _MARKET_CONFIRMED_STAGES else "متاح بعد قياس تفاعل السوق"
    )
    snapshot_complete = direction_known
    return {
        # "ready" يُطلب فقط من لقطة حقيقية كاملة الاتجاه؛ الجزئية "degraded".
        "state": "ready" if snapshot_complete else "degraded",
        "message_ar": None if snapshot_complete else "لقطة الذهب الحالية ناقصة الاتجاه المحقق؛ تُعرض كبيانات جزئية وليست جاهزة.",
        "reason_ar": None if snapshot_complete else "حقل direction مفقود أو غير معروف في لقطة الذهب؛ لم يُستبدل بقيمة neutral مصطنعة.",
        "result_origin": "redis_gold_snapshot",
        "symbol": gold.get("symbol"),
        "direction": direction,
        "direction_ar": _DIRECTION_AR.get(direction, direction),
        # القيم المفقودة تبقى None —unknown ≠ 0 ≠ neutral.
        "strength": gold.get("strength"),
        "confidence": gold.get("confidence"),
        "confidence_validation": gold.get("confidence_validation"),
        "coverage_score": gold.get("coverage_score"),
        "data_quality_score": gold.get("data_quality_score"),
        "freshness_score": gold.get("freshness_score"),
        "conflict_score": gold.get("conflict_score"),
        "prediction_stage": stage,
        "market_confirmation": market_confirmation,
        "blackout": blackout,
        "horizons": {
            "m5": gold.get("horizon_5m"), "m15": gold.get("horizon_15m"),
            "h1": gold.get("horizon_60m"), "h4": gold.get("horizon_4h"),
            "structural_bias": gold.get("structural_bias"),
        },
        "domains": domains,
        "weights": fusion.get("weights", []) if isinstance(fusion, dict) else [],
        "primary_drivers": gold.get("primary_drivers", []),
        "counter_drivers": gold.get("counter_drivers", []),
        "transmission_chain_ar": gold.get("transmission_chain_ar", []),
        "explanation": explanation,
        "quality": quality,
        "generated_at": gold.get("generated_at"),
    }


@router.get("/gold/overview")
async def gold_overview(redis: RedisClient = Depends(get_redis), _auth: None = Depends(_fundamental_view)) -> dict[str, Any]:
    return await _overview_payload(redis)


async def _domain(name: str, redis: RedisClient) -> dict[str, Any]:
    item = await _snap(redis, f"fundamental:{name}:latest")
    details = await _snap(redis, f"fundamental:{name}:details", [])
    details = details if isinstance(details, list) else []
    contract = _domain_contract(item, details)
    if not isinstance(item, dict) or not item:
        return {
            "state": "unavailable", "domain": name, "domain_ar": _DOMAIN_AR[name],
            "message_ar": "بيانات هذا المحور غير متاحة حاليًا.", "details": details, **contract,
        }
    meta = item.get("metadata") or {}
    meta_state = str(meta.get("state") or "").strip().lower()
    raw_direction = item.get("direction")
    has_real_direction = bool(raw_direction) and str(raw_direction).strip().lower() in _GOLD_DIRECTIONS
    if meta_state:
        state = meta_state
        reason = None if state == "ready" else f"حالة المحور معلنة من المسار: {state}."
    elif has_real_direction:
        state = "ready"
        reason = None
    else:
        state = "unknown"
        reason = "لا يوجد اتجاه محقق في لقطة المحور؛ لم تُعرض جاهزية صورية."
    return {
        "state": state, "reason_ar": reason, "domain_ar": _DOMAIN_AR[name],
        **item, "details": details, **contract,
    }


@router.get("/macro")
async def macro(redis: RedisClient = Depends(get_redis), _auth: None = Depends(_fundamental_view)): return await _domain("macro", redis)


@router.get("/monetary")
async def monetary(redis: RedisClient = Depends(get_redis), _auth: None = Depends(_fundamental_view)): return await _domain("monetary", redis)


@router.get("/cross-asset")
async def cross_asset(redis: RedisClient = Depends(get_redis), _auth: None = Depends(_fundamental_view)): return await _domain("cross_asset", redis)


@router.get("/geopolitics")
async def geopolitics(redis: RedisClient = Depends(get_redis), _auth: None = Depends(_fundamental_view)): return await _domain("geopolitical", redis)


@router.get("/flows")
async def flows(redis: RedisClient = Depends(get_redis), _auth: None = Depends(_fundamental_view)): return await _domain("flows", redis)


@router.get("/news")
async def news_context(redis: RedisClient = Depends(get_redis), _auth: None = Depends(_fundamental_view)) -> dict[str, Any]:
    envelope = await build_news_truth_envelope(redis)
    raw_news = await _snap(redis, "news:latest", [])
    news = dedupe_news_items([n for n in raw_news if isinstance(n, dict)]) if isinstance(raw_news, list) else []
    return {
        "news": news,
        "calendar": await _snap(redis, "news:calendar", []),
        "ticker": await _snap(redis, "news:ticker:active", []),
        "blackout": await _snap(redis, "fundamental:blackout", {"state": "unavailable"}),
        # Additive truth contract (Task 5): state/freshness/sources never claim
        # "ready" without a real, recent pipeline result.
        "state": envelope["state"],
        "item_count": envelope["item_count"],
        "last_update_at": envelope["last_update_at"],
        "first_available_at": envelope["first_available_at"],
        "freshness": envelope["freshness"],
        "reason_ar": envelope["reason_ar"],
        "sources": envelope["sources"],
    }


@router.get("/learning")
async def learning(redis: RedisClient = Depends(get_redis), _auth: None = Depends(_fundamental_view)) -> dict[str, Any]:
    return {
        "explanation": await _snap(redis, "fundamental:explanation:latest"),
        "gold": await _snap(redis, "fundamental:gold:latest"),
        "levels": ["simple", "intermediate", "advanced"],
        "levels_ar": ["مبسّط", "متوسط", "متقدم"],
    }


@router.get("/sources/health")
async def source_health(redis: RedisClient = Depends(get_redis), _auth: None = Depends(_source_manager_view)) -> list[dict[str, Any]]:
    value = await _snap(redis, "fundamental:sources:health", [])
    return value if isinstance(value, list) else []


@router.get("/assets/{asset}/latest")
async def asset_latest(asset: str, redis: RedisClient = Depends(get_redis), _auth: None = Depends(_fundamental_view)) -> dict[str, Any]:
    asset = asset.upper()
    if asset not in {"XAUUSD", "BTCUSD"}:
        raise HTTPException(404, "asset is not enabled for fundamental impact")
    value = await _snap(redis, f"fundamental:asset:{asset}:latest")
    if not isinstance(value, dict):
        return {"state": "unavailable", "asset_id": asset, "impacts": []}
    return value


@router.get("/events/{event_id}/impacts")
async def event_impacts(event_id: str, duckdb: DataServiceClient = Depends(get_data_service), _auth: None = Depends(_fundamental_view)) -> dict[str, Any]:
    rows = await duckdb.query("event_asset_impacts", {"event_id": event_id})
    return {"event_id": event_id, "count": len(rows), "impacts": rows}


@router.get("/ticker")
async def ticker(
    actor: CurrentUser,
    _auth: None = Depends(_ticker_view),
    redis: RedisClient = Depends(get_redis),
    duckdb: DataServiceClient = Depends(get_data_service),
) -> dict[str, Any]:
    items = await _snap(redis, "news:ticker:active", [])
    global_settings = await _snap(redis, "news:ticker:settings", DEFAULT_TICKER_SETTINGS)
    base = {**DEFAULT_TICKER_SETTINGS, **(global_settings if isinstance(global_settings, dict) else {})}
    user_id = actor
    settings = {**base, **(await _user_ticker_overrides(duckdb, user_id))}
    out_items = [dict(x) for x in items] if isinstance(items, list) else []
    # صحة الحالة: العناصر الفعلية وحدها تصنع "ready"؛ الفراغ يُميَّز بين
    # مسح مكتمل بلا عناصر ("empty") وبين مسار لم يبلغ بعد ("unavailable").
    news_meta = await _snap(redis, "news:meta")
    meta_ok = isinstance(news_meta, dict) and bool(news_meta.get("last_success_at"))
    if out_items:
        ticker_state, ticker_reason = "ready", None
    elif meta_ok:
        ticker_state = "empty"
        ticker_reason = "اكتمل آخر مسح للأخبار دون تنبيهات شريط نشطة؛ الغياب لا يعني جاهزية إرسال."
    else:
        ticker_state = "unavailable"
        ticker_reason = "لم يبلغ مسار الأخبار بحالة الشريط بعد؛ لن تُعرض تنبيهات بديلة."
    if user_id and out_items:
        try:
            acks = await duckdb.query("user_ticker_acknowledgements", {"user_id": user_id})
            amap = {str(x["ticker_item_id"]): x for x in acks}
            for row in out_items:
                a = amap.get(str(row.get("ticker_item_id")))
                if a:
                    row["acknowledged"] = bool(a.get("acknowledged"))
                    row["acknowledged_at"] = a.get("acknowledged_at")
                    row["acknowledged_by"] = user_id
                    row["acknowledge_note"] = a.get("acknowledge_note")
        except (DataServiceUnavailable, DataServiceRejected):
            raise
        except Exception:
            pass
    return {
        "state": ticker_state,
        "reason_ar": ticker_reason,
        "items": out_items,
        "settings": settings,
        "user_id": user_id,
        "tts_hard_limit_seconds": TTS_HARD_LIMIT_SECONDS,
    }


@router.get("/ticker/history")
async def ticker_history(
    actor: CurrentUser,
    _auth: None = Depends(_ticker_view),
    limit: int = 100,
    duckdb: DataServiceClient = Depends(get_data_service),
) -> dict[str, Any]:
    limit = max(1, min(int(limit), 500))
    rows = await duckdb.query("ticker_history", {"limit": limit})
    return {"count": len(rows), "items": rows}


@router.get("/settings/news-ticker")
async def ticker_settings(
    actor: CurrentUser,
    _auth: None = Depends(_ticker_view),
    redis: RedisClient = Depends(get_redis),
    duckdb: DataServiceClient = Depends(get_data_service),
) -> dict[str, Any]:
    value = await _snap(redis, "news:ticker:settings", DEFAULT_TICKER_SETTINGS)
    base = {**DEFAULT_TICKER_SETTINGS, **(value if isinstance(value, dict) else {})}
    return {**base, **(await _user_ticker_overrides(duckdb, actor))}


@router.put("/settings/news-ticker")
async def update_ticker_settings(
    payload: TickerSettings,
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
    redis: RedisClient = Depends(get_redis),
) -> dict[str, Any]:
    await _require(db, actor, "ticker.manage_global")
    value = payload.model_dump()
    # Long-lived runtime setting; it is presentation-only and never changes risk/scoring.
    await redis.cache_set("news:ticker:settings", value, ttl_sec=10 * 365 * 24 * 3600)
    return {"ok": True, "settings": value}


@router.post("/ticker/{ticker_item_id}/acknowledge")
async def acknowledge_ticker_item(
    ticker_item_id: str,
    payload: TickerAcknowledge,
    actor: CurrentUser,
    redis: RedisClient = Depends(get_redis),
    duckdb: DataServiceClient = Depends(get_data_service),
) -> dict[str, Any]:
    await _require(duckdb, actor, "ticker.acknowledge")
    now = datetime.now(UTC)
    user_id = actor
    if user_id:
        exists = await duckdb.query("ticker_item_exists", {"ticker_item_id": ticker_item_id})
        active_now = await _snap(redis, "news:ticker:active", [])
        if not exists and not any(isinstance(x, dict) and str(x.get("ticker_item_id")) == ticker_item_id for x in (active_now if isinstance(active_now, list) else [])):
            raise HTTPException(404, "ticker item not found")
        await _post_data("user_ticker_acknowledgements", {
            "user_id": user_id, "ticker_item_id": ticker_item_id, "acknowledged": payload.acknowledged,
            "acknowledged_at": now if payload.acknowledged else None, "acknowledge_note": payload.note, "updated_at": now,
        })
        return {"ok": True, "ticker_item_id": ticker_item_id, "acknowledged": payload.acknowledged, "acknowledged_at": now if payload.acknowledged else None, "user_id": user_id, "persisted": True}
    active = await _snap(redis, "news:ticker:active", [])
    lifecycle = await _snap(redis, "news:ticker:lifecycle", active)
    active = active if isinstance(active, list) else []
    lifecycle = lifecycle if isinstance(lifecycle, list) else []
    found: dict[str, Any] | None = None

    def patch(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        nonlocal found
        out: list[dict[str, Any]] = []
        for raw in rows:
            row = dict(raw) if isinstance(raw, dict) else raw
            if isinstance(row, dict) and str(row.get("ticker_item_id")) == ticker_item_id:
                row["acknowledged"] = payload.acknowledged
                row["acknowledged_at"] = now if payload.acknowledged else None
                row["acknowledged_by"] = payload.actor if payload.acknowledged else None
                row["acknowledge_note"] = payload.note if payload.acknowledged else None
                row["updated_at"] = now
                found = row
            out.append(row)
        return out

    lifecycle = patch(lifecycle)
    active = patch(active)
    if found is None:
        raise HTTPException(404, "ticker item not found in active lifecycle")
    await redis.cache_set("news:ticker:lifecycle", lifecycle, ttl_sec=3600)
    await redis.cache_set("news:ticker:active", active, ttl_sec=180)
    # Provider article text with storage_allowed=False remains Redis-only.  The
    # economic-calendar ticker is allowed to persist and UPSERT its ack fields.
    persisted = False
    if str(found.get("source_id") or "") == "calendar_secondary":
        persisted = await _post_data("news_ticker_items", found)
    return {
        "ok": True,
        "ticker_item_id": ticker_item_id,
        "acknowledged": payload.acknowledged,
        "acknowledged_at": found.get("acknowledged_at"),
        "persisted": persisted,
    }


@router.get("/lineage/{asset}")
async def asset_lineage(asset: str, redis: RedisClient = Depends(get_redis), duckdb: DataServiceClient = Depends(get_data_service), _auth: None = Depends(_fundamental_view)) -> dict[str, Any]:
    asset = asset.upper()
    if asset not in {"XAUUSD", "BTCUSD"}:
        raise HTTPException(404, "asset is not enabled for fundamental lineage")
    snapshot = await _snap(redis, f"fundamental:asset:{asset}:latest", {"state": "unavailable", "impacts": []})
    impacts = snapshot.get("impacts", []) if isinstance(snapshot, dict) else []
    anchor = next((x for x in impacts if isinstance(x, dict) and x.get("horizon") == "5m"), None)
    if anchor is None and impacts:
        anchor = impacts[0] if isinstance(impacts[0], dict) else None
    if not anchor:
        return {
            "state": "unavailable", "asset_id": asset, "impact": None, "sources": [], "edges": [],
            "outcomes": [], "reason_ar": "لا توجد لقطة أثر حقيقية لهذا الأصل؛ لم تُعرض سلسلة بيانات بديلة.",
            "result_origin": "none",
        }

    source_ids = anchor.get("source_ids_json") or []
    if isinstance(source_ids, str):
        try: source_ids = json.loads(source_ids)
        except Exception: source_ids = []
    source_ids = [str(x) for x in source_ids if x]
    sources: list[dict[str, Any]] = []
    degraded_reasons: list[str] = []
    if source_ids:
        try:
            sources = await duckdb.query("fund_sources_by_ids", {"source_ids": source_ids[:100]})
        except (DataServiceUnavailable, DataServiceRejected):
            raise
        except Exception:
            sources = []
            degraded_reasons.append("تعذر جلب سجلات المصادر من قاعدة البيانات؛ القائمة الفارغة لا تعني خلوّ السلسلة من مصادر.")
    drivers = anchor.get("drivers_json") or []
    if isinstance(drivers, str):
        try: drivers = json.loads(drivers)
        except Exception:
            drivers = []
            degraded_reasons.append("حقلا drivers_json غير صالح JSON؛ لم تُعرض علاقات سببية مصطنعة.")
    edges: list[dict[str, Any]] = []
    for driver in drivers if isinstance(drivers, list) else []:
        if not isinstance(driver, dict):
            continue
        code = str(driver.get("code") or "unknown")
        edges.append({"from": code, "to": str(anchor.get("impact_id")), "relation": "contributes_to"})
        for ev in driver.get("sources", []) if isinstance(driver.get("sources"), list) else []:
            if isinstance(ev, dict) and ev.get("source_id"):
                edges.append({"from": str(ev.get("source_id")), "to": code, "relation": "evidence_for"})
    try:
        outcomes = await duckdb.query("asset_event_outcome_by_impact", {"impact_id": anchor.get("impact_id")})
    except (DataServiceUnavailable, DataServiceRejected):
        raise
    except Exception:
        outcomes = []
        degraded_reasons.append("تعذر جلب نتائج الأثر الفعلية من قاعدة البيانات؛ القائمة الفارغة مؤقتة وليست خلوًّا محققًا.")
    collector = await _snap(redis, "fundamental:outcomes:collector", {"state": "unavailable"})
    return {
        "state": "degraded" if degraded_reasons else "ready",
        "reason_ar": "؛ ".join(degraded_reasons) if degraded_reasons else None,
        "result_origin": "redis_asset_snapshot+duckdb",
        "asset_id": asset,
        "event_id": anchor.get("event_id"),
        "impact": anchor,
        "sources": sources,
        "edges": edges,
        "outcomes": outcomes,
        "collector": collector,
        "lineage_version": "v6.1",
    }


@router.get("/outcomes/{asset}")
async def asset_outcomes(asset: str, duckdb: DataServiceClient = Depends(get_data_service), _auth: None = Depends(_fundamental_view), limit: int = 50) -> dict[str, Any]:
    asset = asset.upper()
    if asset not in {"XAUUSD", "BTCUSD"}:
        raise HTTPException(404, "asset is not enabled for outcomes")
    rows = await duckdb.query("asset_outcomes", {"asset_id": asset, "limit": max(1, min(int(limit), 200))})
    return {"asset_id": asset, "count": len(rows), "items": rows}


@router.post("/ticker/delivery")
async def ticker_delivery(
    payload: AlertDelivery,
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
) -> dict[str, Any]:
    await _require(db, actor, "ticker.acknowledge")
    record = {
        "delivery_id": uuid.uuid4().hex,
        "user_id": actor,
        **payload.model_dump(mode="json"),
        "started_at": payload.started_at or datetime.now(UTC),
        "created_at": datetime.now(UTC),
    }
    ok = await _post_data("alert_delivery_log", record)
    return {"ok": ok, "delivery_id": record["delivery_id"]}


def _compact_ai_audit_snapshot(structured: dict[str, Any]) -> dict[str, Any]:
    """Persist lineage IDs and deterministic scores, not licensed article text."""
    impacts = structured.get("impacts") if isinstance(structured.get("impacts"), dict) else {}
    overview = structured.get("overview") if isinstance(structured.get("overview"), dict) else {}
    domains = overview.get("domains") if isinstance(overview.get("domains"), list) else []
    source_health = structured.get("source_health") if isinstance(structured.get("source_health"), list) else []
    ticker = structured.get("ticker") if isinstance(structured.get("ticker"), list) else []
    return {
        "asset": structured.get("asset"),
        "overview": {
            "direction": overview.get("direction"), "confidence": overview.get("confidence"),
            "coverage_score": overview.get("coverage_score"), "data_quality_score": overview.get("data_quality_score"),
            "freshness_score": overview.get("freshness_score"), "conflict_score": overview.get("conflict_score"),
            "prediction_stage": overview.get("prediction_stage"),
        },
        "domains": [{
            "domain": d.get("domain"), "domain_state": d.get("domain_state"),
            "score_state": d.get("score_state"), "evidence_count": d.get("evidence_count"),
            "native_score": d.get("native_score"), "gold_impact_score": d.get("gold_impact_score"),
            "confidence": d.get("confidence"), "coverage_score": d.get("coverage_score"),
        } for d in domains if isinstance(d, dict)],
        "impact_ids": [x.get("impact_id") for x in impacts.get("impacts", []) if isinstance(x, dict) and x.get("impact_id")],
        "source_ids": [x.get("source_id") for x in source_health if isinstance(x, dict) and x.get("source_id")],
        "ticker_ids": [x.get("ticker_item_id") for x in ticker if isinstance(x, dict) and x.get("ticker_item_id")],
        "claim_ids": [x.get("claim_id") for x in structured.get("knowledge_claims", []) if isinstance(x, dict) and x.get("claim_id")],
    }


@router.post("/local-ai/analyze")
async def local_ai_analyze(
    payload: LocalAIRequest,
    actor: CurrentUser,
    redis: RedisClient = Depends(get_redis),
    duckdb: DataServiceClient = Depends(get_data_service),
) -> dict[str, Any]:
    await _require(duckdb, actor, "fundamental.view")
    overview = await _overview_payload(redis)
    asset = await _snap(redis, f"fundamental:asset:{payload.asset}:latest", {"state": "unavailable", "impacts": []})
    source_state = await _snap(redis, "fundamental:sources:health", [])
    ticker_state = await _snap(redis, "news:ticker:active", [])
    try:
        knowledge_claims = await duckdb.query("knowledge_claims")
    except (DataServiceUnavailable, DataServiceRejected):
        raise
    except Exception:
        knowledge_claims = []
    structured = {
        "asset": payload.asset,
        "overview": overview,
        "domains": overview.get("domains", []),
        "impacts": asset,
        "blackout": overview.get("blackout"),
        "source_health": source_state,
        "ticker": ticker_state,
        "knowledge_claims": knowledge_claims,
    }
    analyst = GroundedLocalAI()
    result = await analyst.analyze(payload.question, structured)
    safe_input = result.pop("structured_input", structured)
    serialized = json.dumps(safe_input, ensure_ascii=False, default=str, sort_keys=True)
    audit_input = _compact_ai_audit_snapshot(safe_input)
    impacts = asset.get("impacts", []) if isinstance(asset, dict) else []
    impact_5m = next((x for x in impacts if isinstance(x, dict) and x.get("horizon") == "5m"), {})
    answer = result.get("answer") if isinstance(result.get("answer"), dict) else {}
    record = {
        "analysis_id": uuid.uuid4().hex,
        "asset_id": payload.asset,
        "event_id": asset.get("event_id") if isinstance(asset, dict) else None,
        "impact_id": impact_5m.get("impact_id") if isinstance(impact_5m, dict) else None,
        "question": payload.question,
        "input_snapshot_hash": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        "structured_input_json": audit_input,
        "claims_used_json": answer.get("claims_used", []),
        "source_ids_json": answer.get("sources", []),
        "model_name": result.get("model_name", "local"),
        "model_version": result.get("model_version"),
        "prompt_version": "fundamental-local-ai-v2.1-v6.1",
        "response_json": answer or {"state": result.get("state"), "reason": result.get("reason")},
        "hallucination_flags_json": result.get("hallucination_flags", []),
        "schema_valid": bool(result.get("schema_valid", False)),
        # None يبقى None في العمود BIGINT القابل للفراغ؛ لا يُصطنع صفر كزمن استجابة.
        "latency_ms": (int(float(result["latency_ms"])) if isinstance(result.get("latency_ms"), (int, float)) else None),
    }
    await _post_data("local_ai_analysis_runs", record)
    return {**result, "analysis_id": record["analysis_id"], "asset": payload.asset}


@router.get("/local-ai/history")
async def local_ai_history(duckdb: DataServiceClient = Depends(get_data_service), _auth: None = Depends(_fundamental_view), limit: int = 50) -> dict[str, Any]:
    limit = max(1, min(int(limit), 200))
    rows = await duckdb.query("local_ai_history", {"limit": limit})
    return {"count": len(rows), "items": rows}

# ── R3 Source Connection Manager ─────────────────────────────────────────────
# Secrets are never returned by these endpoints. They are stored with Windows
# DPAPI CurrentUser via shared.source_manager; environment variables remain a
# supported read-only fallback for existing deployments.

import time as _time
import ipaddress as _ipaddress
import socket as _socket
import xml.etree.ElementTree as _ET
from urllib.parse import urlparse as _urlparse

import httpx as _httpx
from fastapi import HTTPException as _HTTPException
from pydantic import BaseModel as _BaseModel, Field as _Field

from shared.source_manager import (
    BUILTIN_SOURCE_MANAGER as _BUILTINS,
    SourceManagerStore as _SourceManagerStore,
    normalize_source_id as _normalize_source_id,
    source_manager_store as _source_manager_store,
)


class SourceManagerUpsert(_BaseModel):
    source_id: str | None = None
    name_ar: str | None = None
    name_en: str | None = None
    organization: str | None = None
    category: str | None = None
    transport: str | None = None
    endpoint: str | None = None
    documentation_url: str | None = None
    enabled: bool | None = None
    auth_mode: str | None = None
    secret_env: str | None = None
    secret_name: str | None = None
    secret_optional: bool | None = None
    polling_interval_sec: int | None = _Field(default=None, ge=15, le=604800)
    freshness_limit_sec: int | None = _Field(default=None, ge=30, le=7776000)
    timeout_sec: int | None = _Field(default=None, ge=3, le=60)
    analysis_mapping: str | None = None
    headers: dict[str, str] | None = None
    query_params: dict[str, Any] | None = None
    secret: str | None = None
    clear_secret: bool = False


class SourceSecretPayload(_BaseModel):
    secret: str | None = None
    clear: bool = False


def _redact_source(source: dict[str, Any]) -> dict[str, Any]:
    clean = dict(source)
    clean.pop("secret", None)
    clean["secret_configured"] = bool(source.get("secret_configured"))
    # Never expose environment variable values or stored ciphertext; variable
    # names are safe and intentionally shown so the user knows what can be set.
    return clean


def _join_url(base: str, suffix: str) -> str:
    return f"{base.rstrip('/')}/{suffix.lstrip('/')}"


async def _is_public_http_endpoint(url: str) -> bool:
    """Reject local/private destinations before a user-configured source test."""
    try:
        parsed = _urlparse(url)
        host = parsed.hostname
        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or host.lower().rstrip(".") == "localhost"
            or host.lower().rstrip(".").endswith(".localhost")
        ):
            return False

        try:
            addresses = {_ipaddress.ip_address(host)}
        except ValueError:
            records = await _asyncio.to_thread(
                _socket.getaddrinfo,
                host,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=_socket.SOCK_STREAM,
            )
            addresses = {
                _ipaddress.ip_address(record[4][0])
                for record in records
            }
        return bool(addresses) and all(address.is_global for address in addresses)
    except (OSError, ValueError):
        return False


async def _connection_test(source: dict[str, Any], store: _SourceManagerStore) -> dict[str, Any]:
    sid = str(source["source_id"])
    if not source.get("enabled", True):
        return {"ok": False, "state": "disabled", "source_id": sid, "message_ar": "المصدر معطل بواسطة المستخدم."}
    endpoint = str(source.get("endpoint") or "").strip()
    if not endpoint:
        return {"ok": False, "state": "config_required", "source_id": sid, "message_ar": "رابط المصدر غير مضبوط."}
    parsed = _urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {"ok": False, "state": "invalid_config", "source_id": sid, "message_ar": "رابط المصدر غير صالح."}

    secret = store.get_secret(sid, str(source.get("secret_env") or "") or None)
    if source.get("auth_mode") != "none" and not secret and not bool(source.get("secret_optional", True)):
        return {"ok": False, "state": "config_required", "source_id": sid, "message_ar": "مفتاح/API credential غير مضبوط."}

    headers = {str(k): str(v) for k, v in (source.get("headers") or {}).items()}
    params: dict[str, Any] = dict(source.get("query_params") or {})
    mode = str(source.get("auth_mode") or "none")
    secret_name = str(source.get("secret_name") or "")
    if secret:
        if mode == "query" and secret_name:
            params[secret_name] = secret
        elif mode == "header" and secret_name:
            headers[secret_name] = secret
        elif mode == "bearer":
            headers["Authorization"] = f"Bearer {secret}"

    method = "GET"
    json_body: Any = None
    url = endpoint
    if sid == "bls":
        method = "POST"
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        json_body = {"seriesid": ["CUUR0000SA0"], "startyear": str(now.year), "endyear": str(now.year)}
        if secret:
            json_body["registrationkey"] = secret
        params.pop(secret_name, None)
    elif sid == "bea":
        params.update({"method": "GETDATASETLIST", "ResultFormat": "JSON"})
        if secret:
            params["UserID"] = secret
    elif sid == "fred":
        url = _join_url(endpoint, "series/observations")
        params.update({"series_id": "DGS10", "file_type": "json", "sort_order": "desc", "limit": 1})
        if secret:
            params["api_key"] = secret
    elif sid == "cftc":
        params.update({"$limit": 1, "$order": "report_date_as_yyyy_mm_dd DESC"})
    elif sid == "treasury":
        if not endpoint.lower().endswith(".xml"):
            url = _join_url(endpoint, "real_yield.xml")
    elif sid == "world_bank":
        if "/country/" not in endpoint:
            url = _join_url(endpoint, "country/US/indicator/NY.GDP.MKTP.CD")
            params.update({"format": "json", "per_page": 1})
    elif sid == "imf":
        if "NGDP_RPCH" not in endpoint:
            url = _join_url(endpoint, "NGDP_RPCH/USA")
    elif sid == "census":
        url = _join_url(endpoint, "hv")
        params.update({
            "get": "cell_value,data_type_code,time_slot_id,category_code,seasonally_adj",
            "time": "2004-04",
        })
        if secret:
            params["key"] = secret
    elif sid == "eia":
        url = _join_url(endpoint, "petroleum/pri/spt/data/")
        params.update({
            "frequency": "daily",
            "data[0]": "value",
            "facets[series][]": "RWTC",
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "length": 1,
        })
        if secret:
            params["api_key"] = secret
    elif sid == "gdelt":
        params.update({
            "query": "(gold OR treasury OR federal reserve)",
            "mode": "artlist",
            "format": "json",
            "maxrecords": 5,
            "timespan": "1h",
            "sort": "datedesc",
        })
    elif sid == "newsapi":
        url = _join_url(endpoint, "top-headlines")
        params.update({"country": "us", "pageSize": 1})
        if secret:
            params["apiKey"] = secret
    elif sid == "gnews":
        url = _join_url(endpoint, "top-headlines")
        params.update({"category": "business", "lang": "en", "max": 1})
        if secret:
            params["token"] = secret

    # Validate the final provider-specific URL. Do not follow redirects: each
    # redirect target would otherwise bypass this destination check.
    if not await _is_public_http_endpoint(url):
        return {
            "ok": False,
            "state": "invalid_config",
            "source_id": sid,
            "message_ar": "يجب أن يشير اختبار المصدر إلى عنوان HTTP(S) عام صالح.",
        }

    started = _time.perf_counter()
    try:
        async with _httpx.AsyncClient(timeout=float(source.get("timeout_sec", 15)), follow_redirects=False) as client:
            resp = await client.request(method, url, params=params, json=json_body, headers=headers)
        latency = (_time.perf_counter() - started) * 1000.0
        body = resp.content
        content_type = resp.headers.get("content-type", "")
        parse_ok = True
        record_hint: int | None = None
        if resp.is_success:
            try:
                if "json" in content_type or source.get("transport") in {"api", "json", "sdmx"}:
                    payload = resp.json()
                    if isinstance(payload, list):
                        record_hint = len(payload)
                    elif isinstance(payload, dict):
                        for key in ("data", "results", "records", "articles", "observations", "refRates"):
                            value = payload.get(key)
                            if isinstance(value, list):
                                record_hint = len(value)
                                break
                elif source.get("transport") in {"rss", "xml"} or "xml" in content_type:
                    _ET.fromstring(body)
            except Exception:
                parse_ok = False
        ok = bool(resp.is_success and parse_ok)
        return {
            "ok": ok,
            "state": "healthy" if ok else "degraded",
            "source_id": sid,
            "http_status": resp.status_code,
            "latency_ms": round(latency, 1),
            "content_type": content_type,
            "records_hint": record_hint,
            "message_ar": "تم الاتصال بالمصدر بنجاح." if ok else "تم الوصول للمصدر لكن الاستجابة لم تطابق النوع المتوقع." if resp.is_success else f"فشل HTTP: {resp.status_code}",
            "tested_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        }
    except Exception as exc:
        return {
            "ok": False, "state": "degraded", "source_id": sid,
            "http_status": None,
            "latency_ms": round((_time.perf_counter() - started) * 1000.0, 1),
            "error_type": type(exc).__name__,
            "message_ar": "تعذر الاتصال بالمصدر. تحقق من إعداداته وسجلات الخدمة.",
            "tested_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        }


def _source_truth_fields(
    source: dict[str, Any],
    health: dict[str, Any] | None,
    last_test: dict[str, Any] | None,
    *,
    store: _SourceManagerStore,
) -> dict[str, Any]:
    """Derived truth contract for one managed source.

    configuration_status / connectivity / last_checked_at / data_freshness /
    analysis_eligible are derived facts with explicit reasons. A successful
    health_only source never proves indicator existence or analysis
    eligibility, and a stored last_test is always marked as cached.
    """
    sid = str(source.get("source_id"))
    mapping = str(source.get("analysis_mapping") or "health_only")
    freshness_limit = int(source.get("freshness_limit_sec") or 3600)
    secret_env = str(source.get("secret_env") or "") or None
    secret_optional = bool(source.get("secret_optional", True))
    auth_mode = str(source.get("auth_mode") or "none")
    secret = store.get_secret(sid, secret_env) if secret_env else None

    if not source.get("enabled", True):
        configuration_status = "disabled"
        configuration_reason = "المصدر معطل بواسطة المستخدم؛ لا يُحسب ضمن المصادر العاملة."
    elif not str(source.get("endpoint") or "").strip():
        configuration_status = "missing_config"
        configuration_reason = "رابط المصدر غير مضبوط."
    elif auth_mode != "none" and secret_env and not secret_optional and not (secret or "").strip():
        configuration_status = "missing_config"
        configuration_reason = f"مفتاح/API credential غير مضبوط ({secret_env})."
    else:
        configuration_status = "configured"
        configuration_reason = "إعداد المصدر مكتمل محليًا."

    checked_at: str | None = None
    verification_source = "none"
    if isinstance(health, dict) and health:
        connectivity = str(health.get("health") or "unknown")
        checked_at = health.get("last_success_at") or health.get("last_failure_at")
        reference = health.get("last_success_at")
        verification_source = "runtime_health"
    elif isinstance(last_test, dict) and last_test:
        connectivity = str(last_test.get("state") or "unknown")
        checked_at = last_test.get("tested_at")
        reference = last_test.get("tested_at")
        verification_source = "last_test"
    else:
        connectivity = "disabled" if configuration_status == "disabled" else "unknown"
        reference = None

    data_freshness = "unknown"
    if isinstance(reference, str) and reference.strip():
        parsed = None
        try:
            parsed = datetime.fromisoformat(reference.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            age = (datetime.now(UTC) - parsed).total_seconds()
            data_freshness = "fresh" if 0 <= age <= freshness_limit else "stale"

    analysis_reason: str | None = None
    if configuration_status != "configured":
        analysis_eligible = False
        analysis_reason = f"المصدر غير مؤهل للتحليل: {configuration_reason}"
    elif mapping == "health_only":
        analysis_eligible = False
        analysis_reason = (
            "المصدر مخصص لمراقبة الصحة فقط (health_only)؛ نجاح الاتصال لا يثبت وجود المؤشر "
            "ولا أهلية التحليل منه."
        )
    elif connectivity != "healthy":
        analysis_eligible = False
        analysis_reason = f"الاتصال بالمصدر ليس سليمًا حاليًا ({connectivity})."
    elif data_freshness != "fresh":
        analysis_eligible = False
        analysis_reason = f"بيانات المصدر ليست حديثة بما يكفي ({data_freshness})."
    else:
        analysis_eligible = True
        analysis_reason = "المصدر مؤهل للتحليل وفق آخر فحص حقيقي موثق."

    truth: dict[str, Any] = {
        "configuration_status": configuration_status,
        "configuration_reason_ar": configuration_reason,
        "connectivity": connectivity,
        "last_checked_at": checked_at,
        "data_freshness": data_freshness,
        "analysis_eligible": analysis_eligible,
        "analysis_reason_ar": analysis_reason,
        "verification_source": verification_source,
    }
    if isinstance(last_test, dict) and last_test:
        truth["last_test"] = {**last_test, "result_origin": "cached_last_test"}
    else:
        truth["last_test"] = None
    return truth


@router.get("/sources/manage")
async def manage_sources(
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
    redis: RedisClient = Depends(get_redis),
) -> dict[str, Any]:
    await _require(db, actor, "source_manager.view")
    store = _source_manager_store()
    health = await _snap(redis, "fundamental:sources:health", [])
    health_by_id = {str(x.get("source_id")): x for x in health if isinstance(x, dict)} if isinstance(health, list) else {}
    tests = await _snap(redis, "fundamental:sources:last_tests", {})
    tests = tests if isinstance(tests, dict) else {}
    sources = []
    for item in store.list_sources():
        sid = str(item["source_id"])
        health = health_by_id.get(sid)
        last_test = tests.get(sid)
        sources.append(_redact_source({
            **item,
            "runtime_health": health,
            "last_test": last_test,
            **_source_truth_fields(item, health, last_test, store=store),
        }))
    return {
        "sources": sources,
        "secret_backend": store.secret_backend,
        "storage_dir": str(store.dir),
        "rules": {
            "official_delete_allowed": False,
            "secret_readback_allowed": False,
            "custom_default_analysis_mapping": "health_only",
        },
    }


@router.post("/sources/manage")
async def add_managed_source(
    payload: SourceManagerUpsert,
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
) -> dict[str, Any]:
    await _require(db, actor, "source_manager.edit")
    if payload.secret or payload.clear_secret:
        await _require(db, actor, "source_manager.secrets")
    if not payload.source_id:
        raise _HTTPException(400, "source_id is required")
    store = _source_manager_store()
    sid = _normalize_source_id(payload.source_id)
    if sid in _BUILTINS or store.get_source(sid) is not None:
        raise _HTTPException(409, "source_id already exists")
    values = payload.model_dump(exclude={"source_id", "secret", "clear_secret"}, exclude_none=True)
    try:
        result = store.upsert_source(sid, values, custom=True)
        if payload.secret:
            store.set_secret(sid, payload.secret)
            result = store.get_source(sid) or result
    except (ValueError, RuntimeError) as exc:
        raise _HTTPException(400, str(exc)) from exc
    return {"ok": True, "source": _redact_source(result)}


@router.put("/sources/manage/{source_id}")
async def update_managed_source(
    source_id: str,
    payload: SourceManagerUpsert,
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
) -> dict[str, Any]:
    await _require(db, actor, "source_manager.edit")
    if payload.secret or payload.clear_secret:
        await _require(db, actor, "source_manager.secrets")
    store = _source_manager_store()
    sid = _normalize_source_id(source_id)
    if store.get_source(sid) is None:
        raise _HTTPException(404, "source not found")
    values = payload.model_dump(exclude={"source_id", "secret", "clear_secret"}, exclude_none=True)
    try:
        result = store.upsert_source(sid, values)
        if payload.clear_secret:
            store.clear_secret(sid)
        elif payload.secret:
            store.set_secret(sid, payload.secret)
        result = store.get_source(sid) or result
    except (ValueError, RuntimeError) as exc:
        raise _HTTPException(400, str(exc)) from exc
    return {"ok": True, "source": _redact_source(result)}


@router.delete("/sources/manage/{source_id}")
async def delete_managed_source(
    source_id: str,
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
) -> dict[str, Any]:
    await _require(db, actor, "source_manager.edit")
    store = _source_manager_store()
    try:
        store.delete_source(source_id)
    except ValueError as exc:
        raise _HTTPException(400, str(exc)) from exc
    return {"ok": True, "source_id": source_id}


@router.post("/sources/manage/{source_id}/secret")
async def set_managed_source_secret(
    source_id: str,
    payload: SourceSecretPayload,
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
) -> dict[str, Any]:
    await _require(db, actor, "source_manager.secrets")
    store = _source_manager_store()
    if store.get_source(source_id) is None:
        raise _HTTPException(404, "source not found")
    try:
        if payload.clear:
            store.clear_secret(source_id)
        elif payload.secret:
            store.set_secret(source_id, payload.secret)
        else:
            raise ValueError("secret is required unless clear=true")
    except (ValueError, RuntimeError) as exc:
        raise _HTTPException(400, str(exc)) from exc
    current = store.get_source(source_id) or {}
    return {"ok": True, "source_id": source_id, "secret_configured": bool(current.get("secret_configured")), "secret_backend": store.secret_backend}


@router.post("/sources/manage/{source_id}/test")
async def test_managed_source(
    source_id: str,
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
    redis: RedisClient = Depends(get_redis),
) -> dict[str, Any]:
    await _require(db, actor, "source_manager.test")
    store = _source_manager_store()
    source = store.get_source(source_id)
    if source is None:
        raise _HTTPException(404, "source not found")
    result = await _connection_test(source, store)
    result = {**result, "result_origin": "current_test"}
    tests = await _snap(redis, "fundamental:sources:last_tests", {})
    tests = tests if isinstance(tests, dict) else {}
    tests[str(source_id)] = result
    try:
        await redis.cache_set("fundamental:sources:last_tests", tests, ttl_sec=7 * 24 * 3600)
    except Exception:
        # RedisClient versions without cache_set are still supported.
        try:
            import json as _json
            await redis.r.set("nexus:fundamental:sources:last_tests", _json.dumps(tests, ensure_ascii=False), ex=7 * 24 * 3600)
        except Exception:
            pass
    return result

