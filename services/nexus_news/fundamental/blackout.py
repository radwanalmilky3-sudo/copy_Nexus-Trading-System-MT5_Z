from __future__ import annotations

import hashlib
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

# Phase 4 (NEXUS_MASTER_PLAN) additive timing/provenance columns provided by
# nexus-data.  A payload that carries NONE of these fields (or only default
# negative values such as cancelled=0) is a legacy payload and is evaluated
# through the exact pre-Phase-4 code path — byte-identical decisions.
TIMING_FIELDS: tuple[str, ...] = (
    "timing_quality",
    "authority",
    "release_tzid",
    "decision_date_local",
    "scheduled_status",
    "supersedes_event_id",
    "cancelled",
    "source_sha256",
    "retrieved_at_utc",
)

# timing_quality tokens that mean "date known, time not known".  These never
# produce an invented minute: the whole civil day is blocked in the event zone.
# Includes C1's canonical ``official_date_only`` plus tolerant synonyms.
DATE_ONLY_TIMING_QUALITIES = frozenset({
    "date_only", "date-only", "dateonly", "day", "day_only",
    "approximate", "approx", "approximate_date_only",
    "approximate_without_time", "approximate_no_time", "rough",
    "official_date_only",
})

# timing_quality tokens that mean "provider asserts an exact release time".
# Includes C1's canonical verified values plus tolerant synonyms.
VERIFIED_TIMING_QUALITIES = frozenset({
    "exact", "verified", "precise", "minute", "minute_precise",
    "datetime", "timestamp", "confirmed", "time_known",
    "scheduled_time", "published_time",
    "verified_actual_publication", "official_event_scheduled_time",
    "official_rule_derived",
})

# Explicit "timing is not verified" tokens (C1: ``unverified_external``).
# Any other explicitly-present unknown token also fails closed to unverified.
UNVERIFIED_TIMING_QUALITIES = frozenset({
    "unknown", "unverified", "unverified_timing", "unverified_external",
    "null", "none", "missing", "uncertain",
})

# C1 scheduled_status values that mark the row cancelled or superseded; both
# stay on the blocking side until a replacement with verified timing governs.
CANCELLED_STATUSES = frozenset({"cancelled", "canceled", "superseded"})
_BARE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Additive reason codes (extend the {CLEAR, NEWS_BLACKOUT, CALENDAR_DEGRADED}
# set; never replace a legacy value).
REASON_DATE_ONLY_DAY_BLACKOUT = "DATE_ONLY_DAY_BLACKOUT"
REASON_EVENT_CANCELLED = "EVENT_CANCELLED"
REASON_TIMING_UNVERIFIED = "TIMING_UNVERIFIED"


def _field_present(event: dict[str, Any], key: str) -> bool:
    """True only when a new timing field carries real information.

    None, empty strings and the default-negative cancelled flag (0/False/"0")
    do NOT count: C1 may pass these through for legacy rows and those rows must
    behave exactly as today.
    """
    if key not in event:
        return False
    value = event.get(key)
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    if key == "cancelled" and value in (0, False, "0"):
        return False
    return True


def event_carries_timing_fields(event: dict[str, Any]) -> bool:
    """Activation gate for every Phase-4 rule (additive, tolerant)."""
    return any(_field_present(event, key) for key in TIMING_FIELDS)


def _is_cancelled(event: dict[str, Any]) -> bool:
    if _field_present(event, "cancelled"):
        value = event.get("cancelled")
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "cancelled", "canceled"}
        return bool(value)
    status = event.get("scheduled_status")
    if isinstance(status, str) and status.strip().lower() in CANCELLED_STATUSES:
        return True
    return False


def superseded_event_ids(calendar_events: list[dict[str, Any]]) -> set[str]:
    """Event ids referenced by a newer row's supersedes_event_id (append-only)."""
    targets: set[str] = set()
    for event in calendar_events:
        if _field_present(event, "supersedes_event_id"):
            targets.add(str(event.get("supersedes_event_id")).strip())
    return targets


def _timing_quality_token(event: dict[str, Any]) -> str | None:
    raw = event.get("timing_quality")
    if raw is None:
        return None
    token = str(raw).strip().lower()
    return token or None


def _raw_event_time(event: dict[str, Any]) -> Any:
    return event.get("timestamp") or event.get("event_time") or event.get("published_at")


def _parse_timestamp(raw_time: Any) -> datetime | None:
    """Same tolerant parse as the legacy path; None when unusable."""
    if not raw_time:
        return None
    try:
        ts = raw_time if isinstance(raw_time, datetime) else datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    except Exception:
        return None


def _bare_local_date(raw_time: Any) -> date | None:
    """YYYY-MM-DD only (no time component) — never invents an hour."""
    if raw_time is None or isinstance(raw_time, datetime):
        return None
    if isinstance(raw_time, date):
        return raw_time
    text = str(raw_time).strip()
    if not _BARE_DATE_RE.match(text):
        return None
    try:
        return date.fromisoformat(text)
    except Exception:
        return None


def _decision_local_date(event: dict[str, Any]) -> date | None:
    ddl = event.get("decision_date_local")
    if ddl is None:
        return None
    if isinstance(ddl, datetime):
        return ddl.date()
    if isinstance(ddl, date):
        return ddl
    text = str(ddl).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except Exception:
        return None


def resolve_event_zone(event: dict[str, Any]) -> tuple[ZoneInfo | timezone, str]:
    """IANA zone for civil-day windows: release_tzid -> decision zone -> UTC.

    UTC is the module's existing fallback for naive timestamps, so legacy
    interpretation is preserved when no zone information exists.
    """
    tzid = event.get("release_tzid")
    if isinstance(tzid, str) and tzid.strip():
        try:
            return ZoneInfo(tzid.strip()), tzid.strip()
        except Exception:
            pass
    ddl = event.get("decision_date_local")
    if isinstance(ddl, datetime) and ddl.tzinfo is not None:
        zone = ddl.tzinfo
        return zone, getattr(zone, "key", None) or str(zone)
    if isinstance(ddl, str) and ddl.strip():
        try:
            parsed = datetime.fromisoformat(ddl.strip().replace("Z", "+00:00"))
        except Exception:
            parsed = None
        if parsed is not None and parsed.tzinfo is not None:
            zone = parsed.tzinfo
            return zone, getattr(zone, "key", None) or str(zone)
    return timezone.utc, "UTC"


def civil_day_window(day: date, zone: ZoneInfo | timezone) -> tuple[datetime, datetime]:
    """[00:00, 24:00) local civil day converted to UTC. No invented minute."""
    start_local = datetime.combine(day, time.min, tzinfo=zone)
    end_local = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


class BlackoutEngine:
    """One canonical news/fundamental blackout state for UI, risk and executor.

    Phase 4: date-only events block their full civil day, cancelled/superseded
    rows stay blocking (append-only, never netted out), and unverified timing
    on enriched payloads blocks with state ``unverified_timing`` (not clear).
    Legacy payloads without the Phase-4 fields keep the original decisions.
    """

    version = "1.1.0"

    def __init__(self) -> None:
        self.high_before_min = int(os.getenv("NEXUS_HIGH_IMPACT_BLACKOUT_BEFORE_MIN", "30"))
        self.high_after_min = int(os.getenv("NEXUS_HIGH_IMPACT_BLACKOUT_AFTER_MIN", "30"))
        self.medium_before_min = int(os.getenv("NEXUS_MEDIUM_IMPACT_BLACKOUT_BEFORE_MIN", "10"))
        self.medium_after_min = int(os.getenv("NEXUS_MEDIUM_IMPACT_BLACKOUT_AFTER_MIN", "10"))

    # ------------------------------------------------------------------
    # Legacy path (payload without Phase-4 fields) — literal pre-4 behavior.
    # ------------------------------------------------------------------
    def _legacy_window(self, event: dict[str, Any], before: int, after: int) -> tuple[datetime, datetime] | str:
        raw_time = _raw_event_time(event)
        if not raw_time:
            return "invalid"
        try:
            ts = raw_time if isinstance(raw_time, datetime) else datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            ts = ts.astimezone(timezone.utc)
            start = ts - timedelta(minutes=before)
            end = ts + timedelta(minutes=after)
        except Exception:
            return "invalid"
        return start, end

    # ------------------------------------------------------------------
    # Phase-4 path (enriched payload).  Returns "invalid" or
    # (start, end, blocking_kind, window_shape, reason_tags).
    # ------------------------------------------------------------------
    def _enriched_window(
        self,
        event: dict[str, Any],
        before: int,
        after: int,
        superseded: set[str],
    ) -> tuple[str, ...] | tuple[datetime, datetime, str, str, list[str]]:
        token = _timing_quality_token(event)
        cancelled = _is_cancelled(event)
        event_id = event.get("event_id")
        is_superseded = event_id is not None and str(event_id).strip() in superseded
        raw_time = _raw_event_time(event)
        bare_date = _bare_local_date(raw_time)
        ts = None if bare_date is not None else _parse_timestamp(raw_time)
        civil = _decision_local_date(event)
        if civil is None and bare_date is not None:
            civil = bare_date
        zone, _zone_id = resolve_event_zone(event)

        date_only = token in DATE_ONLY_TIMING_QUALITIES if token is not None else False
        verified = token in VERIFIED_TIMING_QUALITIES if token is not None else False
        if token is None and civil is not None and ts is None:
            # Missing time component with a known civil day -> day-level truth.
            date_only = True

        # Explicit verified quality without any clock time is contradictory;
        # never invent a minute for it — degrade closed like a missing time.
        if verified and ts is None:
            return ("invalid",)

        if date_only:
            if civil is None and ts is not None:
                civil = ts.astimezone(zone).date()
            if civil is None:
                return ("invalid",)
            start, end = civil_day_window(civil, zone)
            window_shape = "civil_day"
        elif ts is not None:
            start = ts - timedelta(minutes=before)
            end = ts + timedelta(minutes=after)
            window_shape = "timed"
        elif civil is not None:
            # Unverified/unknown quality with only a civil day: block the day,
            # never an invented minute.
            start, end = civil_day_window(civil, zone)
            window_shape = "civil_day"
        else:
            return ("invalid",)

        tags: list[str] = []
        if window_shape == "civil_day":
            tags.append(REASON_DATE_ONLY_DAY_BLACKOUT)
        if cancelled or is_superseded:
            kind = "cancelled"
            tags.insert(0, REASON_EVENT_CANCELLED)
        elif date_only:
            kind = "civil_day"
        elif not verified:
            # Explicitly present but unverified quality, or enriched payload
            # whose timing_quality is NULL/absent (Phase-4 rule: fail closed).
            kind = "unverified"
            tags.append(REASON_TIMING_UNVERIFIED)
        else:
            kind = "timed"
        return start, end, kind, window_shape, tags

    def evaluate(self, calendar_events: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        relevant: list[tuple[datetime, datetime, dict[str, Any], str, str, list[str], bool]] = []
        invalid_event_time = False
        superseded = superseded_event_ids(calendar_events)
        any_enriched = False
        for event in calendar_events:
            impact = str(event.get("impact", event.get("declared_impact", "low"))).lower()
            if impact in {"high", "critical"}:
                before, after = self.high_before_min, self.high_after_min
            elif impact == "medium":
                before, after = self.medium_before_min, self.medium_after_min
            else:
                continue
            if event_carries_timing_fields(event):
                any_enriched = True
                outcome = self._enriched_window(event, before, after, superseded)
                if outcome[0] == "invalid":
                    invalid_event_time = True
                    continue
                start, end, kind, window_shape, tags = outcome
                is_legacy = False
            else:
                legacy = self._legacy_window(event, before, after)
                if legacy == "invalid":
                    invalid_event_time = True
                    continue
                start, end = legacy  # type: ignore[misc]
                kind, window_shape, tags = "timed", "timed", []
                is_legacy = True
            if start <= now <= end:
                relevant.append((start, end, event, kind, window_shape, tags, is_legacy))
        if invalid_event_time:
            return self.degraded(
                "High/medium-impact event time is missing or invalid",
                "وقت حدث اقتصادي متوسط أو عالي التأثير مفقود أو غير صالح.",
            ) | {"checked_at": now.isoformat()}
        if not relevant:
            return {
                "blackout_id": None,
                "active": False,
                "state": "clear",
                "reason_code": "CLEAR",
                "reason": "No active high/medium-impact event window",
                "reason_ar": "لا توجد نافذة حظر نشطة لحدث اقتصادي متوسط أو عالي التأثير.",
                "policy_version": self.version if any_enriched else "1.0.0",
                "checked_at": now.isoformat(),
            }
        start, end, event, kind, window_shape, tags, is_legacy = max(relevant, key=lambda x: x[1])
        # Legacy-only evaluations must reproduce pre-Phase-4 ids/versions
        # byte-for-byte; the 1.1.0 policy tag applies only to enriched paths.
        policy_ver = "1.0.0" if is_legacy else self.version
        title = str(event.get("title_ar") or event.get("event_name") or event.get("name") or event.get("title") or "حدث اقتصادي")
        payload: dict[str, Any] = {
            "blackout_id": hashlib.sha256(f"{event.get('event_id') or title}|{start.isoformat()}|{end.isoformat()}|{policy_ver}".encode()).hexdigest()[:32],
            "event_id": event.get("event_id"),
            "active": True,
            "state": "active",
            "starts_at": start.isoformat(),
            "ends_at": end.isoformat(),
            "impact": str(event.get("impact", "high")).lower(),
            "reason_code": "NEWS_BLACKOUT",
            "reason": f"Fundamental event blackout: {title}",
            "reason_ar": f"تم تفعيل حظر فتح صفقات جديدة بسبب حدث عالي/متوسط التأثير: {title}.",
            "policy_version": policy_ver,
            "checked_at": now.isoformat(),
        }
        if kind == "timed" and not tags:
            return payload
        return self._annotate(payload, event, kind, window_shape, tags)

    @staticmethod
    def _annotate(
        payload: dict[str, Any],
        event: dict[str, Any],
        kind: str,
        window_shape: str,
        tags: list[str],
    ) -> dict[str, Any]:
        """Apply Phase-4 blocking reason codes; legacy keys stay untouched."""
        title = str(event.get("title_ar") or event.get("event_name") or event.get("name") or event.get("title") or "حدث اقتصادي")
        zone = resolve_event_zone(event)[1]
        if kind == "cancelled":
            payload["reason_code"] = REASON_EVENT_CANCELLED
            payload["reason"] = f"Cancelled/superseded fundamental event blackout: {title}"
            payload["reason_ar"] = f"تم تفعيل حظر بسبب حدث اقتصادي ملغي أو محلول بحدث أحدث: {title}."
        elif kind == "civil_day":
            payload["reason_code"] = REASON_DATE_ONLY_DAY_BLACKOUT
            payload["reason"] = f"Date-only fundamental event blackout (full civil day, no invented time): {title}"
            payload["reason_ar"] = f"تم تفعيل حظر لليوم المدني الكامل بسبب حدث اقتصادي معروف بالتاريخ فقط دون وقت محدد: {title}."
        elif kind == "unverified":
            payload["state"] = "unverified_timing"
            payload["reason_code"] = REASON_TIMING_UNVERIFIED
            payload["reason"] = f"Unverified fundamental event timing blocks trading: {title}"
            payload["reason_ar"] = f"توقيت الحدث الاقتصادي غير موثّق؛ تم منع التداول احترازيًا: {title}."
        payload["reason_codes"] = list(tags)
        payload["window_kind"] = window_shape
        payload["timing_quality"] = event.get("timing_quality")
        payload["release_tzid"] = zone
        payload["authority"] = event.get("authority")
        return payload

    @staticmethod
    def degraded(reason: str, reason_ar: str) -> dict[str, Any]:
        return {
            "blackout_id": None,
            "active": False,
            "state": "degraded",
            "reason_code": "CALENDAR_DEGRADED",
            "reason": reason,
            "reason_ar": reason_ar,
            "policy_version": "1.0.0",
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
