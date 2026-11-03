from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping

import structlog

logger = structlog.get_logger(__name__)


class GuardCode(StrEnum):
    ALLOW = "ALLOW"
    PAPER_MODE = "PAPER_MODE"
    AUTO_TRADE_OFF = "AUTO_TRADE_OFF"
    KILL_SWITCH = "KILL_SWITCH"
    NEWS_BLACKOUT = "NEWS_BLACKOUT"
    RISK_APPROVAL_MISSING = "RISK_APPROVAL_MISSING"
    RISK_APPROVAL_EXPIRED = "RISK_APPROVAL_EXPIRED"
    SIGNAL_STALE = "SIGNAL_STALE"
    SAFETY_STATE_UNAVAILABLE = "SAFETY_STATE_UNAVAILABLE"


@dataclass(slots=True)
class GuardDecision:
    allowed: bool
    code: GuardCode
    reason: str
    reason_ar: str


LIVE_MODE_VALUES = {"live", "production", "prod"}


def trading_mode() -> str:
    return os.getenv("NEXUS_TRADING_MODE", "paper").strip().lower() or "paper"


def live_mode_enabled() -> bool:
    return trading_mode() in LIVE_MODE_VALUES


def internal_api_secret() -> str:
    return os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()


def risk_approval_secret() -> str:
    """Return the isolated key used only by central Risk and the Executor."""
    return os.getenv("NEXUS_RISK_APPROVAL_SECRET", "").strip()


_INSECURE_JWT_SECRETS = {
    "change-me-jwt-secret",
    "change-me-in-production",
    "secret",
    "changeme",
    "your-secret",
}


def is_secure_jwt_secret(secret: str) -> bool:
    """Reject sample/default JWT keys and keys below HS256's 256-bit minimum."""
    normalized = secret.strip()
    return (
        len(normalized.encode("utf-8")) >= 32
        and normalized.lower() not in _INSECURE_JWT_SECRETS
    )


def is_secure_risk_approval_secret(secret: str, internal_secret: str) -> bool:
    normalized = secret.strip()
    return is_secure_jwt_secret(normalized) and normalized != internal_secret.strip()


_APPROVAL_NUMERIC_FIELDS = ("entry", "price", "sl", "tp", "size", "signal_timestamp")


def _canonical_approval_payload(payload: Mapping[str, Any] | None) -> str:
    """Serialize the fixed v1 set of risk-approved terms deterministically."""
    if not isinstance(payload, Mapping):
        return ""
    try:
        version = int(payload["version"])
        proposal_id = str(payload["proposal_id"]).strip()
        expires_at = int(payload["expires_at"])
        symbol = str(payload["symbol"]).strip().upper()
        side = str(payload["side"]).strip().upper()
        order_type = str(payload["order_type"]).strip().upper()
        slippage = int(payload["slippage"])
        if (
            version != 1
            or not proposal_id
            or not symbol
            or side not in {"BUY", "SELL"}
            or order_type not in {"MARKET", "LIMIT", "STOP"}
            or slippage < 0
        ):
            return ""
        normalized: dict[str, Any] = {
            "version": 1,
            "proposal_id": proposal_id,
            "expires_at": expires_at,
            "symbol": symbol,
            "side": side,
            "order_type": order_type,
            "slippage": slippage,
        }
        for field in _APPROVAL_NUMERIC_FIELDS:
            value = float(payload[field])
            if not math.isfinite(value):
                return ""
            normalized[field] = value
        if expires_at <= 0 or normalized["size"] <= 0 or normalized["signal_timestamp"] <= 0:
            return ""
        return json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (KeyError, TypeError, ValueError, OverflowError):
        return ""


def approval_signature(payload: Mapping[str, Any]) -> str:
    secret = risk_approval_secret()
    canonical_payload = _canonical_approval_payload(payload)
    if not secret or not canonical_payload:
        return ""
    return hmac.new(secret.encode(), canonical_payload.encode(), hashlib.sha256).hexdigest()


def verify_approval_signature(payload: Mapping[str, Any], signature: str) -> bool:
    secret = risk_approval_secret()
    if not secret or not signature:
        return False
    canonical_payload = _canonical_approval_payload(payload)
    if not canonical_payload or int(payload["expires_at"]) < int(time.time()):
        return False
    expected = hmac.new(
        secret.encode(), canonical_payload.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def evaluate_executor_guard(
    redis: Any,
    *,
    approval_payload: Mapping[str, Any] | None = None,
    execution_payload: Mapping[str, Any] | None = None,
    approval_signature_value: str = "",
    require_risk_approval: bool = True,
) -> GuardDecision:
    """Last-line deterministic safety guard before any opening broker call.

    PAPER is hard-blocked from real execution. LIVE requires auto-trade enabled,
    no kill switch, no active/unknown blackout state, a fresh signal, and a
    signed approval minted by central risk. Redis failures fail closed.
    """
    is_live = live_mode_enabled()

    try:
        kill_switch = await redis.cache_get("system:kill_switch")
        if kill_switch:
            return GuardDecision(False, GuardCode.KILL_SWITCH,
                                 "Global kill switch is active",
                                 "تم منع الصفقة لأن مفتاح الإيقاف العام مفعل.")

        auto_trade = await redis.cache_get("system:auto_trade")
        if auto_trade is not True:
            return GuardDecision(False, GuardCode.AUTO_TRADE_OFF,
                                 "Auto-trade is not explicitly enabled",
                                 "تم منع الصفقة لأن التداول الآلي غير مفعل بشكل صريح.")

        blackout = await redis.cache_get("fundamental:blackout")
        if blackout is None:
            return GuardDecision(False, GuardCode.SAFETY_STATE_UNAVAILABLE,
                                 "Fundamental blackout state unavailable",
                                 "حالة حظر الأخبار الأساسية غير متاحة؛ تم المنع احترازيًا.")
        if not isinstance(blackout, dict):
            return GuardDecision(False, GuardCode.SAFETY_STATE_UNAVAILABLE,
                                 "Fundamental blackout state has an invalid shape",
                                 "بيانات حظر الأخبار غير صالحة؛ تم المنع احترازيًا.")
        state = str(blackout.get("state", "unknown")).lower()
        active = blackout.get("active")
        if state not in {"clear", "active", "degraded", "unknown", "unavailable"} or not isinstance(active, bool):
            return GuardDecision(False, GuardCode.SAFETY_STATE_UNAVAILABLE,
                                 "Fundamental blackout state is malformed",
                                 "بيانات حظر الأخبار غير مكتملة أو غير معروفة؛ تم المنع احترازيًا.")
        if active or state in {"active", "unknown", "degraded", "unavailable"}:
            return GuardDecision(False, GuardCode.NEWS_BLACKOUT,
                                 str(blackout.get("reason", "Fundamental/news blackout active")),
                                 str(blackout.get("reason_ar", "تم منع الصفقة بسبب نافذة خبر اقتصادي عالي التأثير.")))

    except Exception:
        return GuardDecision(False, GuardCode.SAFETY_STATE_UNAVAILABLE,
                             "Safety state unavailable from Redis",
                             "تعذر التحقق من حالة الأمان؛ تم منع الصفقة احترازيًا.")

    if require_risk_approval:
        signed_payload = _canonical_approval_payload(approval_payload)
        requested_payload = _canonical_approval_payload(execution_payload)
        if not signed_payload or not requested_payload or not approval_signature_value:
            return GuardDecision(False, GuardCode.RISK_APPROVAL_MISSING,
                                 "Central risk approval proof missing",
                                 "تم منع الصفقة لأن إثبات موافقة إدارة المخاطر المركزية مفقود.")
        expires_at = int(approval_payload["expires_at"])
        if expires_at < int(time.time()):
            return GuardDecision(False, GuardCode.RISK_APPROVAL_EXPIRED,
                                 "Central risk approval expired",
                                 "تم منع الصفقة لأن موافقة إدارة المخاطر انتهت صلاحيتها.")
        if not verify_approval_signature(approval_payload, approval_signature_value):
            return GuardDecision(False, GuardCode.RISK_APPROVAL_MISSING,
                                 "Central risk approval signature invalid",
                                 "تم منع الصفقة لأن توقيع موافقة إدارة المخاطر غير صالح.")
        if not hmac.compare_digest(signed_payload, requested_payload):
            return GuardDecision(False, GuardCode.RISK_APPROVAL_MISSING,
                                 "Execution terms differ from central risk approval",
                                 "تم منع الصفقة لأن تفاصيل التنفيذ تختلف عن موافقة إدارة المخاطر.")

        ttl = int(os.getenv("NEXUS_ACTIVE_SIGNAL_TTL", "120"))
        signal_timestamp_epoch = float(approval_payload["signal_timestamp"])
        if time.time() - signal_timestamp_epoch > ttl:
            return GuardDecision(False, GuardCode.SIGNAL_STALE,
                                 "Signal is stale",
                                 "تم منع الصفقة لأن الإشارة أصبحت قديمة وتحتاج إعادة تقييم.")

    if not is_live:
        return GuardDecision(True, GuardCode.PAPER_MODE,
                             "Safety checks passed; execution must remain simulated in PAPER mode",
                             "اجتازت الصفقة حواجز الأمان، وسيتم تنفيذها كمحاكاة فقط لأن النظام في وضع PAPER.")

    return GuardDecision(True, GuardCode.ALLOW, "Safety checks passed", "اجتازت الصفقة جميع حواجز الأمان.")


async def record_guard_decision(
    redis: Any,
    decision: GuardDecision,
    *,
    signal_id: str = "",
    prediction_id: str | None = None,
    requested_action: str = "OPEN_POSITION",
    risk_version: str | None = None,
    executor_guard_version: str | None = None,
) -> dict[str, Any]:
    """Best-effort guard audit to Redis + canonical nexus-data persistence.

    Audit failures never weaken or change the safety decision. The data-service
    write is authenticated with NEXUS_INTERNAL_API_SECRET and is intentionally
    best-effort so an unavailable audit sink cannot turn a reject into an allow.
    """
    blackout_id: str | None = None
    try:
        blackout = await redis.cache_get("fundamental:blackout")
        if isinstance(blackout, dict):
            blackout_id = blackout.get("blackout_id")
    except Exception:
        blackout_id = None

    record: dict[str, Any] = {
        "decision_id": uuid.uuid4().hex,
        "signal_id": signal_id or None,
        "prediction_id": prediction_id,
        "blackout_id": blackout_id,
        "requested_action": requested_action,
        "decision": "ALLOW" if decision.allowed else "REJECT",
        "reason_code": decision.code.value,
        "reason_ar": decision.reason_ar,
        "risk_version": risk_version,
        "executor_guard_version": executor_guard_version,
        "created_at": utc_iso(),
    }
    try:
        await redis.cache_set("fundamental:guard:last", record, ttl_sec=7 * 24 * 3600)
    except Exception as exc:
        # Best-effort: never affects the decision, but a permanently broken
        # Redis audit sink must be visible instead of silently empty.
        await logger.awarning(
            "safety.guard_audit_cache_write_failed",
            reason_code=decision.code.value,
            error=str(exc),
        )

    secret = internal_api_secret()
    if not secret:
        await logger.awarning(
            "safety.guard_audit_persist_skipped_no_secret",
            reason_code=decision.code.value,
        )
        return record
    try:
        import httpx

        data_url = os.getenv("NEXUS_DATA_URL", "http://127.0.0.1:9001").rstrip("/")
        async with httpx.AsyncClient(timeout=1.5) as client:
            await client.post(
                f"{data_url}/api/data/fundamental/record",
                json={"table": "fundamental_guard_decisions", "record": record},
                headers={"X-Nexus-Internal-Secret": secret},
            )
    except Exception as exc:
        await logger.awarning(
            "safety.guard_audit_persist_failed",
            reason_code=decision.code.value,
            error=str(exc),
        )
    return record
