from __future__ import annotations

"""Deterministic news intelligence helpers.

The purpose is to keep relevance/novelty/story clustering outside the LLM.
The LLM may summarize these facts later, but it is not allowed to invent them.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from shared.models import NewsItem

UTC = timezone.utc

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)
_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "in", "is",
    "it", "of", "on", "or", "that", "the", "this", "to", "was", "were", "will", "with", "after",
    "before", "new", "says", "said", "over", "amid", "its", "their", "into", "about",
}

_COMMERCIAL_NOISE = {
    "swarovski", "figurine", "necklace", "bracelet", "earring", "earrings", "jewelry", "jewellery",
    "coupon", "shipping", "deal", "sale", "discount", "amazon", "walmart", "gift", "karat", "plated",
    "ring", "rings", "watch", "watches", "collectible", "ornament",
}

_FINANCE_CONTEXT = {
    "price", "prices", "market", "markets", "futures", "spot", "bullion", "commodity", "commodities",
    "fed", "fomc", "inflation", "cpi", "pce", "yield", "yields", "treasury", "dollar", "dxy", "rates",
    "rate", "jobs", "payrolls", "unemployment", "claims", "gdp", "economy", "economic", "central", "bank",
    "banks", "etf", "flows", "positioning", "war", "conflict", "sanctions", "oil", "energy", "bitcoin",
    "crypto", "sec", "liquidity", "recession", "growth", "gold", "silver", "xau",
}

_TOPIC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("monetary", ("fed", "fomc", "powell", "rate decision", "interest rate", "central bank", "hawkish", "dovish")),
    ("inflation", ("inflation", "cpi", "pce", "ppi", "consumer prices", "producer prices")),
    ("labor", ("nonfarm", "payroll", "jobs", "unemployment", "jobless claims", "jolts", "wages", "earnings")),
    ("growth", ("gdp", "retail sales", "ism", "pmi", "industrial production", "durable goods", "consumer confidence")),
    ("rates_yields", ("treasury", "yield", "yields", "real yield", "bond", "bonds")),
    ("fx", ("dollar", "dxy", "euro", "yen", "pound", "forex", "currency")),
    ("metals", ("gold", "xau", "bullion", "silver", "precious metals")),
    ("crypto", ("bitcoin", "btc", "crypto", "ethereum", "sec", "spot etf")),
    ("geopolitics", ("war", "invasion", "missile", "airstrike", "sanctions", "ceasefire", "conflict", "attack", "strait")),
    ("energy", ("oil", "wti", "brent", "opec", "pipeline", "gas supply", "crude")),
    ("equities", ("s&p", "spx", "nasdaq", "stocks", "wall street", "equities")),
)


@dataclass(slots=True)
class NewsAnalysis:
    fingerprint: str
    story_cluster_id: str
    topic: str
    event_type: str
    severity: str
    novelty_score: float
    source_quality: float
    financial_relevance: float
    asset_relevance: dict[str, float]
    reason_ar: str
    is_commercial_noise: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "story_cluster_id": self.story_cluster_id,
            "topic": self.topic,
            "event_type": self.event_type,
            "severity": self.severity,
            "novelty_score": self.novelty_score,
            "source_quality": self.source_quality,
            "financial_relevance": self.financial_relevance,
            "asset_relevance": self.asset_relevance,
            "reason_ar": self.reason_ar,
            "is_commercial_noise": self.is_commercial_noise,
        }


class NewsIntelligenceEngine:
    version = "2.0.0"

    @staticmethod
    def normalized_tokens(headline: str) -> list[str]:
        return [t for t in _TOKEN_RE.findall(headline.lower()) if len(t) > 1 and t not in _STOP]

    @classmethod
    def fingerprint(cls, headline: str) -> str:
        normalized = " ".join(cls.normalized_tokens(headline))
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @classmethod
    def story_cluster_id(cls, headline: str) -> str:
        # Sort unique significant tokens so superficial word-order changes and
        # provider prefixes do not automatically become independent stories.
        tokens = sorted(set(cls.normalized_tokens(headline)))
        signature = "|".join(tokens[:18])
        return hashlib.sha256(signature.encode("utf-8")).hexdigest()[:24]

    def analyze(self, item: NewsItem, *, source_trust: float = 65.0, seen_count: int = 0) -> NewsAnalysis:
        text = item.headline.lower()
        tokens = set(self.normalized_tokens(item.headline))
        commercial_hits = len(tokens & _COMMERCIAL_NOISE)
        finance_hits = len(tokens & _FINANCE_CONTEXT)
        commercial_noise = commercial_hits >= 1 and finance_hits <= 1

        topic = "other"
        for candidate, needles in _TOPIC_RULES:
            if any(n in text for n in needles):
                topic = candidate
                break

        event_type = {
            "monetary": "MONETARY_NEWS",
            "inflation": "INFLATION_NEWS",
            "labor": "LABOR_NEWS",
            "growth": "GROWTH_NEWS",
            "rates_yields": "RATES_YIELDS_NEWS",
            "fx": "FX_NEWS",
            "metals": "METALS_NEWS",
            "crypto": "CRYPTO_NEWS",
            "geopolitics": "GEOPOLITICAL_NEWS",
            "energy": "ENERGY_NEWS",
            "equities": "EQUITIES_NEWS",
        }.get(topic, "GENERAL_NEWS")

        financial_relevance = min(100.0, finance_hits * 18.0 + (25.0 if topic != "other" else 0.0))
        if commercial_noise:
            financial_relevance = min(financial_relevance, 5.0)

        xau = self._xau_relevance(text, topic, commercial_noise)
        btc = self._btc_relevance(text, topic, commercial_noise)

        severity = self._severity(text, topic, financial_relevance, item.impact)
        novelty = max(10.0, 100.0 / max(1, seen_count + 1))
        reason = (
            "تم خفض الملاءمة بسبب نمط تجاري/تسوق غير مالي."
            if commercial_noise
            else f"تصنيف الخبر: {topic}؛ الملاءمة المالية {financial_relevance:.0f}/100."
        )
        return NewsAnalysis(
            fingerprint=self.fingerprint(item.headline),
            story_cluster_id=self.story_cluster_id(item.headline),
            topic=topic,
            event_type=event_type,
            severity=severity,
            novelty_score=novelty,
            source_quality=max(0.0, min(100.0, source_trust)),
            financial_relevance=financial_relevance,
            asset_relevance={"XAUUSD": xau, "BTCUSD": btc},
            reason_ar=reason,
            is_commercial_noise=commercial_noise,
        )

    @staticmethod
    def _xau_relevance(text: str, topic: str, commercial_noise: bool) -> float:
        if commercial_noise:
            return 0.0
        score = 0.0
        if any(k in text for k in ("gold", "xau", "bullion", "precious metal")):
            score = max(score, 95.0)
        if topic in {"monetary", "inflation", "rates_yields", "fx"}:
            score = max(score, 82.0)
        if topic == "labor":
            score = max(score, 75.0)
        if topic == "geopolitics":
            score = max(score, 78.0)
        if topic == "energy":
            score = max(score, 45.0)
        if topic == "growth":
            score = max(score, 55.0)
        return score

    @staticmethod
    def _btc_relevance(text: str, topic: str, commercial_noise: bool) -> float:
        if commercial_noise:
            return 0.0
        score = 0.0
        if any(k in text for k in ("bitcoin", "btc", "crypto", "digital asset", "spot etf")):
            score = max(score, 98.0)
        if topic in {"monetary", "inflation", "rates_yields", "fx"}:
            score = max(score, 68.0)
        if topic in {"equities", "growth", "labor"}:
            score = max(score, 52.0)
        if topic == "geopolitics":
            score = max(score, 35.0)
        return score

    @staticmethod
    def _severity(text: str, topic: str, relevance: float, declared: str) -> str:
        declared = (declared or "").lower()
        if declared in {"critical", "high"} and relevance >= 40:
            return "critical" if declared == "critical" else "high"
        critical_words = ("breaking", "emergency", "default", "bank failure", "invasion", "missile attack", "fomc decision")
        high_words = ("fomc", "fed decision", "cpi", "nonfarm", "payrolls", "rate decision", "powell", "sanctions")
        if any(k in text for k in critical_words) and relevance >= 55:
            return "critical"
        if any(k in text for k in high_words) and relevance >= 45:
            return "high"
        if topic != "other" and relevance >= 35:
            return "medium"
        return "low"


def build_story_cluster_record(item: NewsItem, analysis: NewsAnalysis, *, source_id: str, source_count: int, independent_source_count: int) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "story_cluster_id": analysis.story_cluster_id,
        "canonical_headline": item.headline,
        "canonical_summary": getattr(item, "summary", "") or "",
        "primary_source_id": source_id,
        "topic": analysis.topic,
        "event_type": analysis.event_type,
        "entity_keys_json": list(getattr(item, "affected_currencies", []) or []),
        "first_seen_at": item.timestamp,
        "last_seen_at": now,
        "novelty_score": analysis.novelty_score,
        "source_count": int(source_count),
        "independent_source_count": int(independent_source_count),
        "status": "active",
        "fingerprint": analysis.fingerprint,
    }
