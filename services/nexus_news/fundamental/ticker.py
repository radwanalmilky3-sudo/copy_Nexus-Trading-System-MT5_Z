from __future__ import annotations

"""Deterministic ticker lifecycle for Fundamental Intelligence.

IDs are stable across state transitions.  Reconciliation preserves acknowledgement
and emits explicit SCHEDULED -> BREAKING/ANALYZING -> ANALYZED/UPDATED -> EXPIRED
transitions instead of creating a new row for every status.
"""

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from shared.models import CalendarEvent, NewsItem
from .normalization import calendar_event_record, parse_number

UTC = timezone.utc
_SEVERITY_TTL_MIN = {"critical": 30, "high": 20, "medium": 10, "low": 5}
_STATUS_RANK = {"SCHEDULED": 1, "BREAKING": 2, "ANALYZING": 3, "ANALYZED": 4, "UPDATED": 5, "SUPERSEDED": 6, "EXPIRED": 7}


def _dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d.astimezone(UTC) if d.tzinfo else d.replace(tzinfo=UTC)
    except Exception:
        return None


def _stable_id(*parts: Any) -> str:
    raw = "|".join(str(x) for x in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class NewsTickerEngine:
    version = "2.1.0"

    def build(
        self,
        *,
        calendar: list[CalendarEvent],
        news: list[NewsItem],
        news_analysis: dict[str, dict[str, Any]],
        asset_impacts: list[dict[str, Any]],
        blackout: dict[str, Any],
        now: datetime | None = None,
        previous_items: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        current = now or datetime.now(UTC)
        impact_by_event_asset: dict[tuple[str, str], dict[str, Any]] = {}
        for impact in asset_impacts:
            if impact.get("horizon") != "5m":
                continue
            eid = str(impact.get("event_id") or "")
            aid = str(impact.get("asset_id") or "")
            if eid and aid:
                impact_by_event_asset[(eid, aid)] = impact

        candidates: list[dict[str, Any]] = []
        candidates.extend(self._calendar_items(calendar, impact_by_event_asset, blackout, current))
        candidates.extend(self._news_items(news, news_analysis, blackout, current))
        items = self.reconcile(previous_items or [], candidates, current)
        items.sort(key=lambda x: (self._severity_rank(str(x.get("severity"))), str(x.get("published_at") or x.get("starts_at") or "")), reverse=True)
        return items[:50]

    def reconcile(self, previous: list[dict[str, Any]], candidates: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
        old = {str(x.get("ticker_item_id")): dict(x) for x in previous if x.get("ticker_item_id")}
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for candidate in candidates:
            tid = str(candidate["ticker_item_id"])
            seen.add(tid)
            prior = old.get(tid)
            if prior:
                candidate["created_at"] = prior.get("created_at") or candidate.get("created_at") or now
                candidate["acknowledged"] = bool(prior.get("acknowledged", False))
                candidate["acknowledged_at"] = prior.get("acknowledged_at")
                candidate["acknowledged_by"] = prior.get("acknowledged_by")
                candidate["acknowledge_note"] = prior.get("acknowledge_note")
                prev_status = str(prior.get("status") or "SCHEDULED")
                new_status = str(candidate.get("status") or "BREAKING")
                changed = any(candidate.get(k) != prior.get(k) for k in ("actual_value", "forecast_value", "surprise_value", "direction", "confidence", "summary_ar"))
                if prev_status in {"ANALYZED", "UPDATED"} and new_status in {"ANALYZED", "ANALYZING", "BREAKING"} and changed:
                    candidate["status"] = "UPDATED"
                elif _STATUS_RANK.get(prev_status, 0) > _STATUS_RANK.get(new_status, 0) and prev_status not in {"EXPIRED", "SUPERSEDED"}:
                    candidate["status"] = prev_status
            candidate["updated_at"] = now
            out.append(candidate)

        # Keep recently disappeared items long enough to record an explicit expiry.
        for tid, prior in old.items():
            if tid in seen:
                continue
            expires = _dt(prior.get("expires_at"))
            row = dict(prior)
            if expires and now >= expires:
                row["status"] = "EXPIRED"
                row["freshness_state"] = "expired"
                row["updated_at"] = now
                out.append(row)
            elif expires and now < expires:
                out.append(row)
        return out

    def _calendar_items(self, calendar: list[CalendarEvent], impacts: dict[tuple[str, str], dict[str, Any]], blackout: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for event in calendar:
            ts = _dt(event.timestamp)
            if not ts:
                continue
            delta_min = (ts - now).total_seconds() / 60.0
            impact = (event.impact or "low").lower()
            if impact not in {"high", "critical"}:
                if not (impact == "medium" and -10 <= delta_min <= 10):
                    continue
            if not (-30 <= delta_min <= 20):
                continue

            rec = calendar_event_record(event)
            event_id = rec["event_id"]
            actual = parse_number(event.actual)
            forecast = parse_number(event.forecast)
            surprise = None if actual is None or forecast is None else actual - forecast
            asset_ids = ["XAUUSD", "BTCUSD"] if event.currency.upper() == "USD" else [event.currency.upper()]

            for asset_id in asset_ids:
                impact_row = impacts.get((event_id, asset_id))
                if delta_min > 0:
                    status = "SCHEDULED"
                elif actual is not None:
                    status = "ANALYZED" if impact_row else "ANALYZING"
                else:
                    status = "BREAKING"
                severity = "critical" if impact == "critical" else "high" if impact == "high" else "medium"
                expires = ts + timedelta(minutes=20 if severity in {"high", "critical"} else 10)
                out.append({
                    "ticker_item_id": _stable_id("calendar", event_id, asset_id),
                    "story_cluster_id": None,
                    "event_id": event_id,
                    "impact_id": impact_row.get("impact_id") if impact_row else None,
                    "asset_id": asset_id,
                    "topic": "economic_calendar",
                    "asset_relevance": 100.0 if asset_id == "XAUUSD" else 70.0,
                    "independent_source_count": 1,
                    "severity": severity,
                    "headline_ar": event.event_name,
                    "summary_ar": self._calendar_summary(event, delta_min, surprise),
                    "source_label": str(event.source or "Economic Calendar"),
                    "source_id": "calendar_secondary",
                    "published_at": ts,
                    "received_at": now,
                    "starts_at": ts - timedelta(minutes=30),
                    "expires_at": expires,
                    "status": status,
                    "freshness_state": "fresh",
                    "actual_value": event.actual,
                    "forecast_value": event.forecast,
                    "previous_value": event.previous,
                    "revision_value": None,
                    "surprise_value": surprise,
                    "direction": impact_row.get("direction") if impact_row else "unknown",
                    "confidence": impact_row.get("confidence") if impact_row else None,
                    "data_quality": impact_row.get("quality") if impact_row else 65.0,
                    "blackout_state": str(blackout.get("state", "unknown")),
                    "acknowledged": False,
                    "acknowledged_at": None,
                    "acknowledged_by": None,
                    "acknowledge_note": None,
                    "supersedes_id": None,
                    "created_at": now,
                    "updated_at": now,
                })
        return out

    def _news_items(self, news: list[NewsItem], analysis_by_fingerprint: dict[str, dict[str, Any]], blackout: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in news:
            fingerprint = hashlib.sha256(" ".join(item.headline.lower().split()).encode("utf-8")).hexdigest()
            analysis = analysis_by_fingerprint.get(fingerprint) or analysis_by_fingerprint.get(item.headline)
            if not analysis or bool(analysis.get("is_commercial_noise")):
                continue
            severity = str(analysis.get("severity", "low"))
            if severity == "low":
                continue
            ttl = _SEVERITY_TTL_MIN.get(severity, 5)
            published = _dt(item.timestamp) or now
            expires = published + timedelta(minutes=ttl)
            if now > expires:
                continue
            asset_relevance = analysis.get("asset_relevance") or {}
            for asset_id, relevance_raw in asset_relevance.items():
                relevance = float(relevance_raw or 0.0)
                if relevance < 40.0:
                    continue
                cluster = analysis.get("story_cluster_id")
                out.append({
                    "ticker_item_id": _stable_id("news", cluster, asset_id),
                    "story_cluster_id": cluster,
                    "event_id": None,
                    "impact_id": None,
                    "asset_id": asset_id,
                    "topic": analysis.get("topic"),
                    "asset_relevance": relevance,
                    "independent_source_count": int(analysis.get("independent_source_count", 1) or 1),
                    "severity": severity,
                    "headline_ar": item.headline,
                    "summary_ar": str(analysis.get("reason_ar") or ""),
                    "source_label": str(getattr(item, "source", "") or "News"),
                    "source_id": str(getattr(item, "provider_id", "") or "news_secondary"),
                    "published_at": published,
                    "received_at": now,
                    "starts_at": published,
                    "expires_at": expires,
                    "status": "BREAKING",
                    "freshness_state": "fresh",
                    "actual_value": None,
                    "forecast_value": None,
                    "previous_value": None,
                    "revision_value": None,
                    "surprise_value": None,
                    "direction": "unknown",
                    "confidence": min(float(analysis.get("source_quality", 0.0)), relevance),
                    "data_quality": float(analysis.get("source_quality", 0.0)),
                    "blackout_state": str(blackout.get("state", "unknown")),
                    "acknowledged": False,
                    "acknowledged_at": None,
                    "acknowledged_by": None,
                    "acknowledge_note": None,
                    "supersedes_id": None,
                    "created_at": now,
                    "updated_at": now,
                })
        return out

    @staticmethod
    def _calendar_summary(event: CalendarEvent, delta_min: float, surprise: float | None) -> str:
        if delta_min > 0:
            return f"حدث اقتصادي مجدول بعد {max(1, int(round(delta_min)))} دقيقة."
        if event.actual is None:
            return "موعد الإصدار وصل؛ القيمة الفعلية لم تُستلم بعد."
        if surprise is None:
            return "تم استلام القيمة الفعلية، لكن لا يوجد توقع صالح لحساب المفاجأة."
        return "تم استلام الفعلي والمُتوقع؛ اتجاه الأصل يُعرض فقط بعد محرك الأثر الخاص به."

    @staticmethod
    def _severity_rank(value: str) -> int:
        return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(value.lower(), 0)
