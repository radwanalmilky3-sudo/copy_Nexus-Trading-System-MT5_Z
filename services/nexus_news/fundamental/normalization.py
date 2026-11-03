from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from shared.models import CalendarEvent, NewsItem

from .indicator_catalog import INDICATORS, INDICATOR_AR

UTC = timezone.utc


def parse_number(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "—", "n/a", "N/A"}:
        return None
    text = text.replace("%", "")
    mult = 1.0
    if text[-1:].upper() == "K":
        mult, text = 1_000.0, text[:-1]
    elif text[-1:].upper() == "M":
        mult, text = 1_000_000.0, text[:-1]
    elif text[-1:].upper() == "B":
        mult, text = 1_000_000_000.0, text[:-1]
    try:
        return float(text) * mult
    except ValueError:
        m = re.search(r"[-+]?\d+(?:\.\d+)?", text)
        return float(m.group(0)) * mult if m else None


_INDICATOR_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"core.*cpi|cpi.*core", re.I), "CORE_CPI"),
    (re.compile(r"consumer price|\bcpi\b", re.I), "CPI"),
    (re.compile(r"core.*pce|pce.*core", re.I), "CORE_PCE"),
    (re.compile(r"personal consumption|\bpce\b", re.I), "PCE"),
    (re.compile(r"core.*ppi|ppi.*core", re.I), "CORE_PPI"),
    (re.compile(r"producer price|\bppi\b", re.I), "PPI"),
    (re.compile(r"inflation expectation", re.I), "INFLATION_EXPECTATIONS"),
    (re.compile(r"non.?farm|\bnfp\b|nonfarm payroll", re.I), "NFP"),
    (re.compile(r"u.?6.*unemployment|underemployment", re.I), "U6_UNDEREMPLOYMENT"),
    (re.compile(r"unemployment rate", re.I), "UNEMPLOYMENT"),
    (re.compile(r"average hourly|hourly earnings|wage", re.I), "AVG_HOURLY_EARNINGS"),
    (re.compile(r"average weekly hours|weekly hours", re.I), "AVG_WEEKLY_HOURS"),
    (re.compile(r"labor force participation|participation rate", re.I), "LABOR_FORCE_PARTICIPATION"),
    (re.compile(r"continuing claims|continued claims", re.I), "CONTINUING_CLAIMS"),
    (re.compile(r"4.?week.*claims|four.?week.*claims", re.I), "CLAIMS_4W_AVG"),
    (re.compile(r"initial jobless|initial claims", re.I), "INITIAL_CLAIMS"),
    (re.compile(r"jobless claims|unemployment claims", re.I), "JOBLESS_CLAIMS"),
    (re.compile(r"\badp\b.*employment|employment.*\badp\b", re.I), "ADP_EMPLOYMENT"),
    (re.compile(r"jolts.*hires|hires.*jolts", re.I), "JOLTS_HIRES"),
    (re.compile(r"jolts.*quits|quits.*jolts", re.I), "JOLTS_QUITS"),
    (re.compile(r"jolts|job openings", re.I), "JOLTS_OPENINGS"),
    (re.compile(r"gross domestic|\bgdp\b", re.I), "GDP"),
    (re.compile(r"gross domestic income|\bgdi\b", re.I), "GDI"),
    (re.compile(r"ism.*manufact", re.I), "ISM_MANUFACTURING"),
    (re.compile(r"ism.*service", re.I), "ISM_SERVICES"),
    (re.compile(r"\bpmi\b|purchasing managers", re.I), "PMI"),
    (re.compile(r"retail sales", re.I), "RETAIL_SALES"),
    (re.compile(r"industrial production", re.I), "INDUSTRIAL_PRODUCTION"),
    (re.compile(r"durable goods", re.I), "DURABLE_GOODS"),
    (re.compile(r"university of michigan|michigan sentiment", re.I), "MICHIGAN_SENTIMENT"),
    (re.compile(r"consumer confidence|consumer sentiment", re.I), "CONSUMER_CONFIDENCE"),
    (re.compile(r"housing starts", re.I), "HOUSING_STARTS"),
    (re.compile(r"building permits", re.I), "BUILDING_PERMITS"),
    (re.compile(r"existing home sales", re.I), "EXISTING_HOME_SALES"),
    (re.compile(r"new home sales", re.I), "NEW_HOME_SALES"),
    (re.compile(r"trade balance", re.I), "TRADE_BALANCE"),
)


def indicator_code(event_name: str) -> str | None:
    for pattern, code in _INDICATOR_PATTERNS:
        if pattern.search(event_name):
            return code
    return None


def stable_event_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(x) for x in parts)
    return f"{prefix}-{hashlib.sha256(raw.encode()).hexdigest()[:24]}"


def calendar_event_record(event: CalendarEvent) -> dict[str, Any]:
    event_id = stable_event_id("cal", event.source, event.event_name, event.currency, event.timestamp.isoformat())
    return {
        "event_id": event_id,
        "source_id": "calendar_secondary",
        "category": "macro" if indicator_code(event.event_name) else "calendar",
        "subcategory": indicator_code(event.event_name) or "other",
        "event_type": indicator_code(event.event_name) or "ECONOMIC_CALENDAR",
        "event_code": indicator_code(event.event_name) or re.sub(r"\W+", "_", event.event_name.upper())[:64],
        "title_en": event.event_name,
        "title_ar": event.event_name,
        "country": "US" if event.currency.upper() == "USD" else "",
        "currency": event.currency,
        "source_timestamp": event.timestamp,
        "published_at": event.timestamp,
        "received_at": datetime.now(UTC),
        "declared_impact": event.impact,
        "gold_relevance": 90.0 if event.currency.upper() == "USD" and event.impact == "high" else 60.0,
        "freshness_state": "fresh",
        "data_quality_score": 65.0,
        "raw_hash": hashlib.sha256(str(event.model_dump(mode="json")).encode()).hexdigest(),
        "dedup_group_id": event_id,
        "causal_group_id": f"{event.currency}:{indicator_code(event.event_name) or 'calendar'}:{event.timestamp.date().isoformat()}",
        "independence_group": str(event.source or "calendar_secondary"),
    }


def calendar_to_macro(event: CalendarEvent) -> dict[str, Any] | None:
    code = indicator_code(event.event_name)
    if not code:
        return None
    actual = parse_number(event.actual)
    forecast = parse_number(event.forecast)
    previous = parse_number(event.previous)
    if actual is None and forecast is None and previous is None:
        return None
    event_rec = calendar_event_record(event)
    meta = INDICATORS.get(code, {})
    surprise_absolute = None if actual is None or forecast is None else actual - forecast
    surprise_percent = None
    if surprise_absolute is not None and forecast is not None and abs(forecast) > 1e-12:
        surprise_percent = surprise_absolute / abs(forecast) * 100.0
    return {
        "event_id": event_rec["event_id"],
        "indicator_code": code,
        "indicator_name_en": event.event_name,
        "indicator_name_ar": INDICATOR_AR.get(code, event.event_name),
        "actual": actual,
        "forecast": forecast,
        "previous": previous,
        "first_release_value": actual,
        "latest_value": actual,
        "surprise_absolute": surprise_absolute,
        "surprise_percent": surprise_percent,
        # A true z-score requires historical surprise volatility and is left missing
        # until that history is available. Missing is never written as neutral zero.
        "surprise_zscore": None,
        "historical_importance": float(meta.get("importance", 100.0 if event.impact == "high" else 70.0 if event.impact == "medium" else 45.0)),
        "gold_relevance": event_rec["gold_relevance"],
        "rate_implication_score": None,
        "usd_implication_score": None,
        "yield_implication_score": None,
        "gold_implication_score": None,
        "release_timestamp": event.timestamp,
        # engine-facing provenance
        "source_id": "calendar_secondary",
        "source_name": str(event.source or "Secondary Economic Calendar"),
        "source_name_ar": "مزود التقويم الاقتصادي الثانوي",
        "source_timestamp": event.timestamp,
        "trust_score": 65.0,
        "quality_score": 65.0,
        "freshness": "fresh",
        "origin": "real",
        "causal_group_id": event_rec["causal_group_id"],
        "independence_group": "calendar_secondary",
    }


def news_article_record(item: NewsItem) -> dict[str, Any]:
    provider_id = str(getattr(item, "provider_id", "") or "news_secondary").lower()
    if provider_id not in {"newsapi", "gnews", "news_secondary"}:
        provider_id = "news_secondary"
    aid = stable_event_id("news", provider_id, item.source, item.headline, item.timestamp.isoformat())
    return {
        "article_id": aid,
        "event_id": None,
        "source_id": provider_id,
        "headline": item.headline,
        "summary": str(getattr(item, "summary", "") or "")[:4000],
        "body_excerpt": "",
        "url": getattr(item, "url", None),
        "language": "en",
        "published_at": item.timestamp,
        "received_at": datetime.now(UTC),
        "dedup_hash": hashlib.sha256(item.headline.strip().lower().encode()).hexdigest(),
        "story_cluster_id": hashlib.sha256(re.sub(r"\W+", " ", item.headline.lower()).encode()).hexdigest()[:24],
        "original_source_id": item.source,
        "is_reprint": False,
        "provider": provider_id,
        "source_trust": 70.0 if provider_id in {"newsapi", "gnews"} else 60.0,
        "freshness_state": "fresh",
        "data_quality_score": 70.0 if provider_id in {"newsapi", "gnews"} else 60.0,
    }


def fed_rss_to_monetary(record: dict[str, Any]) -> dict[str, Any]:
    """Classify Federal Reserve RSS items conservatively.

    RSS is never treated as a substitute for a structured rate decision.  R3.1
    filters administrative/regulatory items before any tone calculation so an
    enforcement action, bank application, or consumer survey cannot increase
    MONETARY confidence.
    """
    title = str(record.get("title", "") or "")
    desc = str(record.get("description", "") or "")
    text = f"{title} {desc}".lower()

    hard_policy = (
        "federal open market committee",
        "fomc",
        "monetary policy",
        "summary of economic projections",
        "implementation note",
        "minutes of the federal open market committee",
        "press conference",
    )
    soft_policy = (
        "inflation",
        "price stability",
        "maximum employment",
        "federal funds rate",
        "policy rate",
        "balance sheet",
        "quantitative tightening",
        "quantitative easing",
        "economic outlook",
        "chair powell",
        "vice chair",
    )
    administrative = (
        "enforcement action",
        "civil money penalty",
        "consent order",
        "bank application",
        "application by",
        "approves application",
        "merger application",
        "supervision and regulation",
        "community reinvestment",
        "survey of consumer finances",
        "consumer compliance",
        "termination of enforcement",
        "prohibition order",
    )

    has_hard = any(k in text for k in hard_policy)
    has_soft = any(k in text for k in soft_policy)
    has_admin = any(k in text for k in administrative)
    relevant = bool(has_hard or (has_soft and not has_admin))

    if "minutes" in text and ("fomc" in text or "federal open market" in text):
        kind = "FOMC_MINUTES"
    elif "summary of economic projections" in text or "dot plot" in text:
        kind = "FOMC_SEP"
    elif ("fomc" in text or "federal open market committee" in text) and ("statement" in text or "implementation note" in text):
        kind = "FOMC_STATEMENT"
    elif "monetary policy report" in text:
        kind = "MONETARY_POLICY_REPORT"
    elif "powell" in text or "chair" in text or "vice chair" in text:
        kind = "FED_SPEECH"
    else:
        kind = "FED_CONTEXT"

    hawkish_terms = (
        "inflation remains elevated", "inflation is elevated", "restrictive",
        "higher for longer", "tightening", "price stability", "upside risks to inflation",
        "not appropriate to reduce", "maintain the target range",
    )
    dovish_terms = (
        "rate cut", "reduce the target range", "easing", "downside risks to employment",
        "slowing", "weaker labor", "disinflation", "appropriate to lower",
    )
    hawkish = sum(text.count(w) for w in hawkish_terms) if relevant else 0
    dovish = sum(text.count(w) for w in dovish_terms) if relevant else 0
    hits = hawkish + dovish

    # RSS tone is fallback context only. No comparison => no policy_delta.
    tone = max(-100.0, min(100.0, (hawkish - dovish) * 16.0)) if hits else None
    if not relevant:
        mode = "context_only"
        confidence = 0.0
    elif has_hard:
        mode = "rss_policy_fallback"
        confidence = 35.0 if tone is not None else 15.0
    else:
        mode = "rss_speech_fallback"
        confidence = 20.0 if tone is not None else 10.0

    return {
        "institution": "Federal Reserve",
        "event_kind": kind,
        "monetary_relevant": relevant,
        "tone_score": tone,
        "previous_tone_score": None,
        "policy_delta": None,
        "forward_guidance_score": None,
        "rate_surprise_bps": None,
        "dot_plot_shift": None,
        "qe_qt_score": None,
        "gold_implication_score": (-tone if tone is not None else None),
        "confidence": confidence,
        "analysis_mode": mode,
        "label_ar": (
            f"اتصال سياسة نقدية من الاحتياطي الفيدرالي — {title}"
            if relevant else f"خبر إداري/سياقي من الاحتياطي الفيدرالي — {title}"
        ),
        "label_en": title or "Federal Reserve communication",
        "source_id": "fed_rss",
        "source_name": "Federal Reserve RSS",
        "source_name_ar": "الاحتياطي الفيدرالي",
        "source_timestamp": record.get("published_at"),
        "trust_score": 100.0,
        "quality_score": 85.0 if relevant else 60.0,
        "freshness": "fresh",
        "origin": "real",
        "causal_group_id": stable_event_id("fed", record.get("guid") or record.get("title")),
        "independence_group": "federal_reserve",
    }
