from __future__ import annotations

import math
import uuid
from collections import Counter
from datetime import datetime, timezone
from statistics import mean, pstdev
from typing import Any

from shared.fundamental import (
    ConfidenceValidation,
    DataOrigin,
    FundamentalDomain,
    FundamentalDriver,
    FundamentalFactorResult,
    FundamentalFusionResult,
    FusionWeight,
    GoldDirection,
    GoldImpactResult,
    HorizonClass,
    HorizonProbability,
    PredictionStage,
    SourceEvidence,
)

from .scoring import (
    average,
    clamp,
    clamp01,
    confidence_from_components,
    conflict_from_scores,
    direction_from_score,
    independence_factor,
    sigmoid_probability,
)

UTC = timezone.utc


from .indicator_catalog import INDICATORS, INDICATOR_AR


def _source_evidence(record: dict[str, Any]) -> list[SourceEvidence]:
    source_id = str(record.get("source_id", "unknown"))
    origin = str(record.get("origin", "real")).lower()
    try:
        origin_enum = DataOrigin(origin)
    except ValueError:
        origin_enum = DataOrigin.UNKNOWN
    return [SourceEvidence(
        source_id=source_id,
        source_name=str(record.get("source_name", source_id)),
        source_name_ar=str(record.get("source_name_ar", record.get("source_name", source_id))),
        source_url=record.get("source_url"),
        source_timestamp=record.get("source_timestamp"),
        origin=origin_enum,
        freshness=record.get("freshness", "fresh"),
        trust_score=float(record.get("trust_score", 80.0)),
        quality_score=float(record.get("quality_score", record.get("data_quality_score", 80.0))),
        causal_group_id=record.get("causal_group_id"),
        independence_group=record.get("independence_group"),
        story_cluster_id=record.get("story_cluster_id"),
        is_reprint=bool(record.get("is_reprint", False)),
    )]


def _factor_common(drivers: list[FundamentalDriver], domain: FundamentalDomain, horizon: HorizonClass, version: str) -> FundamentalFactorResult:
    if not drivers:
        return FundamentalFactorResult(
            domain=domain,
            native_score=0,
            gold_impact_score=0,
            direction=GoldDirection.NEUTRAL,
            strength=0,
            confidence=0,
            coverage_score=0,
            freshness_score=0,
            data_quality_score=0,
            reliability_score=0,
            horizon_class=horizon,
            primary_drivers=[],
            counter_drivers=[],
            engine_version=version,
            metadata={"state": "unavailable"},
        )

    weights = [max(0.05, d.strength / 100.0) for d in drivers]
    total = sum(weights)
    native = sum(d.native_score * w for d, w in zip(drivers, weights)) / total
    gold = sum(d.gold_impact_score * w for d, w in zip(drivers, weights)) / total
    qualities = [e.quality_score for d in drivers for e in d.sources]
    freshness = [100.0 if str(e.freshness) in {"live", "fresh"} else 45.0 for d in drivers for e in d.sources]
    quality = average(qualities, 75.0)
    fresh = average(freshness, 70.0)
    coverage = min(100.0, 35.0 + len(drivers) * 13.0)
    reliability = average([d.confidence for d in drivers], 50.0)
    pos = [d for d in drivers if d.gold_impact_score >= 0]
    neg = [d for d in drivers if d.gold_impact_score < 0]
    agreement, conflict = conflict_from_scores([d.gold_impact_score for d in drivers])
    confidence = confidence_from_components(
        coverage=coverage,
        quality=quality,
        freshness=fresh,
        reliability=reliability,
        agreement=agreement,
        conflict=conflict,
    )
    primary = sorted((pos if gold >= 0 else neg), key=lambda d: abs(d.gold_impact_score), reverse=True)[:5]
    counter = sorted((neg if gold >= 0 else pos), key=lambda d: abs(d.gold_impact_score), reverse=True)[:5]
    return FundamentalFactorResult(
        domain=domain,
        native_score=clamp(native),
        gold_impact_score=clamp(gold),
        direction=direction_from_score(gold),
        strength=min(100.0, abs(gold)),
        confidence=confidence,
        coverage_score=coverage,
        freshness_score=fresh,
        data_quality_score=quality,
        reliability_score=reliability,
        horizon_class=horizon,
        primary_drivers=primary,
        counter_drivers=counter,
        engine_version=version,
        metadata={"driver_count": len(drivers), "conflict_score": conflict},
    )


class SurpriseEngine:
    version = "1.0.0"

    @staticmethod
    def compute(actual: float | None, forecast: float | None, historical_surprises: list[float] | None = None) -> dict[str, float | None]:
        if actual is None or forecast is None:
            return {"absolute": None, "percent": None, "zscore": None}
        try:
            actual_value = float(actual)
            forecast_value = float(forecast)
        except (TypeError, ValueError):
            return {"absolute": None, "percent": None, "zscore": None}
        if not math.isfinite(actual_value) or not math.isfinite(forecast_value):
            return {"absolute": None, "percent": None, "zscore": None}
        absolute = actual_value - forecast_value
        if not math.isfinite(absolute):
            return {"absolute": None, "percent": None, "zscore": None}
        percent = None if abs(forecast_value) < 1e-12 else absolute / abs(forecast_value) * 100.0
        if percent is not None and not math.isfinite(percent):
            percent = None
        hist: list[float] = []
        for value in historical_surprises or []:
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(parsed):
                hist.append(parsed)
        std = pstdev(hist) if len(hist) >= 8 else 0.0
        zscore = absolute / std if std > 1e-12 else None
        if zscore is not None and not math.isfinite(zscore):
            zscore = None
        return {"absolute": absolute, "percent": percent, "zscore": zscore}


class MacroEngine:
    version = "1.0.0"

    def evaluate(self, releases: list[dict[str, Any]]) -> FundamentalFactorResult:
        drivers: list[FundamentalDriver] = []
        for r in releases:
            code = str(r.get("indicator_code", "")).upper()
            meta = INDICATORS.get(code)
            if not meta:
                continue
            actual = r.get("actual")
            forecast = r.get("forecast")
            if actual is None or forecast is None:
                # Missing forecast is missing evidence, not neutral evidence.
                continue
            hist = r.get("historical_surprises") or []
            surprise = SurpriseEngine.compute(actual, forecast, hist)
            if surprise["absolute"] is None:
                continue
            z = surprise["zscore"]
            if z is None:
                pct = surprise["percent"] if surprise["percent"] is not None else 0.0
                z = max(-3.0, min(3.0, pct / 0.35 if abs(pct) < 10 else math.copysign(3.0, pct)))
            revision = float(r.get("revision_effect_score", 0.0) or 0.0)
            raw_strength = min(100.0, abs(float(z)) * 28.0 + abs(revision) * 0.20)
            native = clamp(float(z) * 30.0)
            gold = clamp(native * float(meta["gold_sign"]) + revision * 0.25)
            confidence = min(100.0, 50.0 + min(35.0, abs(float(z)) * 12.0) + float(meta["importance"]) * 0.15)
            label_ar = INDICATOR_AR.get(code, code)
            drivers.append(FundamentalDriver(
                code=code,
                label_ar=label_ar,
                label_en=code,
                native_score=native,
                gold_impact_score=gold,
                strength=raw_strength,
                confidence=confidence,
                explanation_ar=(
                    f"{label_ar}: الفعلي {actual} مقابل المتوقع {forecast}. "
                    f"حجم المفاجأة المعياري التقريبي {float(z):+.2f}، "
                    f"والأثر المقدر على الذهب {gold:+.1f}/100."
                ),
                horizon_class=HorizonClass.EVENT_SHOCK,
                sources=_source_evidence(r),
            ))
        return _factor_common(drivers, FundamentalDomain.MACRO, HorizonClass.EVENT_SHOCK, self.version)


class MonetaryEngine:
    version = "1.1.0"

    @staticmethod
    def _num(event: dict[str, Any], key: str) -> float | None:
        value = event.get(key)
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    def evaluate(self, events: list[dict[str, Any]]) -> FundamentalFactorResult:
        drivers: list[FundamentalDriver] = []
        for e in events:
            tone = self._num(e, "tone_score")
            prev = self._num(e, "previous_tone_score")
            delta = self._num(e, "policy_delta")
            if delta is None and tone is not None and prev is not None:
                delta = tone - prev
            components = [
                ("tone", tone, 0.35),
                ("policy_delta", delta, 0.20),
                ("rate_surprise_bps", self._num(e, "rate_surprise_bps"), 0.90),
                ("forward_guidance", self._num(e, "forward_guidance_score"), 0.20),
                ("dot_plot", self._num(e, "dot_plot_shift"), 0.15),
                ("qe_qt", self._num(e, "qe_qt_score"), 0.10),
            ]
            available = [(name, value, weight) for name, value, weight in components if value is not None]
            if not available:
                # Evidence may still be displayed in domain details, but it cannot
                # become a fake 0/neutral score.
                continue
            native = clamp(sum(float(value) * weight for _, value, weight in available))
            gold = clamp(-native)
            strength = min(100.0, abs(native))
            kind = str(e.get("event_kind", "policy"))
            label_ar = str(e.get("label_ar") or f"السياسة النقدية — {kind}")
            mode = str(e.get("analysis_mode") or "structured")
            confidence = float(e.get("confidence", min(95.0, 60.0 + strength * 0.30)) or 0.0)
            if mode.startswith("rss_"):
                confidence = min(confidence, 35.0 if mode == "rss_policy_fallback" else 20.0)
            comp_text = ", ".join(f"{name}={float(value):+.1f}" for name, value, _ in available)
            drivers.append(FundamentalDriver(
                code=f"MONETARY_{kind.upper()}",
                label_ar=label_ar,
                label_en=str(e.get("label_en") or kind),
                native_score=native,
                gold_impact_score=gold,
                strength=strength,
                confidence=confidence,
                explanation_ar=(
                    f"المكونات المتاحة فقط: {comp_text}. النتيجة الأصلية {native:+.1f} "
                    f"(الموجب = أكثر تشددًا)، وأثرها على الذهب {gold:+.1f}. "
                    f"وضع التحليل: {mode}."
                ),
                horizon_class=HorizonClass.TACTICAL,
                sources=_source_evidence(e),
            ))
        result = _factor_common(drivers, FundamentalDomain.MONETARY, HorizonClass.TACTICAL, self.version)
        if events and not drivers:
            result.metadata["state"] = "evidence_only_no_scoring_fields"

        relevant_modes = [str(e.get("analysis_mode") or "") for e in events if e.get("monetary_relevant", True)]
        fallback_modes = [m for m in relevant_modes if m.startswith("rss_")]
        if fallback_modes:
            result.metadata["rss_fallback_present"] = True
        # Fresh RSS availability/quality must not inflate MONETARY confidence.
        # When every scored driver is only an RSS fallback, the whole domain is
        # explicitly capped until structured rate/statement/expectation fields exist.
        if drivers and relevant_modes and len(fallback_modes) == len(relevant_modes):
            result.confidence = min(float(result.confidence), 35.0)
            result.coverage_score = min(float(result.coverage_score), 40.0)
            result.reliability_score = min(float(result.reliability_score), 35.0)
            result.metadata["state"] = "rss_fallback_only"
        return result


class CrossAssetEngine:
    """Causal cross-asset transmission model.

    V6.1 deliberately removes direct instrument->gold coefficients for VIX and
    nominal US10Y.  Raw market series first become *causal channels*; only those
    channels receive an asset implication.  This prevents a single raw print
    from being treated as a timeless directional trading rule.
    """

    version = "1.1.0"

    SERIES_LABEL_AR = {
        "DXY": "مؤشر الدولار الأمريكي (DXY)",
        "BROAD_DOLLAR": "مؤشر الدولار الواسع",
        "US2Y": "عائد السندات الأمريكية لسنتين (US2Y)",
        "US10Y": "عائد السندات الأمريكية لعشر سنوات (US10Y)",
        "US30Y": "عائد السندات الأمريكية لثلاثين سنة (US30Y)",
        "REAL_YIELD_10Y": "العائد الحقيقي لعشر سنوات",
        "BREAKEVEN_5Y": "تعادل التضخم لخمس سنوات",
        "BREAKEVEN_10Y": "تعادل التضخم لعشر سنوات",
        "YIELD_CURVE_2S10S": "منحنى العائد 2s10s",
        "VIX": "مؤشر التقلب المتوقع (VIX)",
        "SPX": "مؤشر S&P 500",
        "NASDAQ": "مؤشر ناسداك",
        "WTI": "النفط WTI",
        "BRENT": "خام برنت",
        "BTCUSD": "بيتكوين (BTC)",
    }

    def _latest(self, observations: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for o in observations:
            code = str(o.get("series_code", "")).upper()
            if code not in self.SERIES_LABEL_AR:
                continue
            if str(o.get("origin", "unknown")).lower() == "synthetic":
                continue
            current = latest.get(code)
            if current is None or str(o.get("timestamp", "")) > str(current.get("timestamp", "")):
                latest[code] = o
        return latest

    @staticmethod
    def _move(row: dict[str, Any] | None) -> float | None:
        if not row:
            return None
        for key in ("change_z", "change_pct", "change"):
            value = row.get(key)
            if value is None:
                continue
            try:
                x = float(value)
            except (TypeError, ValueError):
                continue
            if abs(x) <= 1e-12:
                return 0.0
            return clamp(x * (25.0 if abs(x) <= 4 else 1.0))
        return None

    @staticmethod
    def _quality(rows: list[dict[str, Any] | None]) -> tuple[float, list[SourceEvidence]]:
        used = [r for r in rows if r]
        if not used:
            return 0.0, []
        q = sum(float(r.get("quality_score", 75.0) or 75.0) for r in used) / len(used)
        proxy = any(str(r.get("origin", "unknown")).lower() == "proxy" for r in used)
        if proxy:
            q *= 0.55
        evidence: list[SourceEvidence] = []
        for r in used:
            evidence.extend(_source_evidence(r))
        return max(0.0, min(100.0, q)), evidence

    def _driver(
        self,
        *,
        code: str,
        label_ar: str,
        native: float,
        gold: float,
        rows: list[dict[str, Any] | None],
        explanation: str,
        horizon: HorizonClass = HorizonClass.TACTICAL,
    ) -> FundamentalDriver | None:
        if abs(native) <= 1e-9:
            return None
        quality, evidence = self._quality(rows)
        if not evidence:
            return None
        return FundamentalDriver(
            code=code,
            label_ar=label_ar,
            label_en=code,
            native_score=clamp(native),
            gold_impact_score=clamp(gold),
            strength=min(100.0, abs(gold)),
            confidence=quality,
            explanation_ar=explanation,
            horizon_class=horizon,
            sources=evidence,
        )

    def evaluate(self, observations: list[dict[str, Any]]) -> FundamentalFactorResult:
        latest = self._latest(observations)
        drivers: list[FundamentalDriver] = []

        # 1) USD/liquidity channel. A stronger USD is a direct financing/liquidity
        # headwind for USD-priced gold, but this is expressed as a channel rather
        # than a hard rule attached to one ticker.
        dxy = self._move(latest.get("DXY"))
        broad = self._move(latest.get("BROAD_DOLLAR"))
        usd_parts = [x for x in (dxy, broad) if x is not None]
        if usd_parts:
            native = sum(usd_parts) / len(usd_parts)
            drv = self._driver(
                code="USD_LIQUIDITY_PRESSURE",
                label_ar="قناة الدولار والسيولة",
                native=native,
                gold=-native,
                rows=[latest.get("DXY"), latest.get("BROAD_DOLLAR")],
                explanation=(
                    "تم تجميع DXY/الدولار الواسع في قناة سببية واحدة. "
                    f"قوة القناة {native:+.1f}/100؛ لا يُعامل أي مؤشر منفرد كقاعدة تداول ثابتة."
                ),
            )
            if drv: drivers.append(drv)

        # 2) Rates channel. Prefer REAL_YIELD_10Y. Nominal yields are not given a
        # direct coefficient when real yield is unavailable; they require an
        # inflation/breakeven decomposition or are marked as incomplete evidence.
        real = self._move(latest.get("REAL_YIELD_10Y"))
        be10 = self._move(latest.get("BREAKEVEN_10Y"))
        be5 = self._move(latest.get("BREAKEVEN_5Y"))
        us10 = self._move(latest.get("US10Y"))
        rate_native: float | None = None
        rate_rows: list[dict[str, Any] | None] = []
        rate_note = ""
        if real is not None:
            rate_native = real
            rate_rows = [latest.get("REAL_YIELD_10Y")]
            rate_note = "العائد الحقيقي متاح، لذلك هو مرساة قناة تكلفة الفرصة."
        elif us10 is not None and (be10 is not None or be5 is not None):
            be = be10 if be10 is not None else be5
            rate_native = clamp(us10 - float(be or 0.0))
            rate_rows = [latest.get("US10Y"), latest.get("BREAKEVEN_10Y"), latest.get("BREAKEVEN_5Y")]
            rate_note = "العائد الحقيقي غير متاح؛ استُخدم تفكيك العائد الاسمي مع تعادل التضخم، لا US10Y منفردًا."
        if rate_native is not None:
            drv = self._driver(
                code="REAL_RATE_PRESSURE",
                label_ar="قناة العائد الحقيقي/تكلفة الفرصة",
                native=rate_native,
                gold=-rate_native,
                rows=rate_rows,
                explanation=f"{rate_note} قوة القناة {rate_native:+.1f}/100.",
            )
            if drv: drivers.append(drv)

        # 3) Risk regime. VIX by itself has *zero directional authority*. It only
        # creates a safe-haven channel when corroborated by equity weakness.
        vix = self._move(latest.get("VIX"))
        spx = self._move(latest.get("SPX"))
        nasdaq = self._move(latest.get("NASDAQ"))
        eq_parts = [x for x in (spx, nasdaq) if x is not None]
        equity = (sum(eq_parts) / len(eq_parts)) if eq_parts else None
        if vix is not None and equity is not None and vix > 0 and equity < 0:
            risk = clamp((abs(vix) + abs(equity)) / 2.0)
            # Strong USD can offset part of the classic safe-haven bid.
            usd_offset = max(0.0, (sum(usd_parts) / len(usd_parts)) if usd_parts else 0.0)
            gold = clamp(risk - usd_offset * 0.45)
            drv = self._driver(
                code="RISK_OFF_SAFE_HAVEN",
                label_ar="قناة العزوف عن المخاطر/الملاذ الآمن",
                native=risk,
                gold=gold,
                rows=[latest.get("VIX"), latest.get("SPX"), latest.get("NASDAQ"), latest.get("DXY")],
                explanation=(
                    "VIX لم يُستخدم اتجاهيًا بمفرده؛ القناة فُعّلت فقط مع ضعف الأسهم. "
                    f"ضغط الملاذ {risk:.1f}/100 وبعد تعارض الدولار أصبح أثر الذهب {gold:+.1f}/100."
                ),
            )
            if drv: drivers.append(drv)

        # 4) Energy/inflation channel is conditional and deliberately weaker.
        wti = self._move(latest.get("WTI"))
        brent = self._move(latest.get("BRENT"))
        energy_parts = [x for x in (wti, brent) if x is not None]
        if energy_parts:
            energy = sum(energy_parts) / len(energy_parts)
            gold = clamp(energy * 0.25)
            drv = self._driver(
                code="ENERGY_INFLATION_PRESSURE",
                label_ar="قناة الطاقة/ضغط التضخم",
                native=energy,
                gold=gold,
                rows=[latest.get("WTI"), latest.get("BRENT")],
                explanation=(
                    "الطاقة عامل تضخمي مشروط وليست إشارة ذهب مباشرة؛ "
                    f"قوة الطاقة {energy:+.1f}/100 وأثر الذهب المخفّض {gold:+.1f}/100."
                ),
            )
            if drv: drivers.append(drv)

        result = _factor_common(drivers, FundamentalDomain.CROSS_ASSET, HorizonClass.TACTICAL, self.version)
        real_count = sum(1 for d in drivers for e in d.sources if e.origin == DataOrigin.REAL)
        proxy_count = sum(1 for d in drivers for e in d.sources if e.origin == DataOrigin.PROXY)
        if proxy_count and not real_count:
            result.confidence = min(result.confidence, 35.0)
            result.metadata["state"] = "proxy_only"
        if us10 is not None and real is None and be10 is None and be5 is None:
            result.metadata["nominal_yield_state"] = "INCOMPLETE_CAUSAL_DECOMPOSITION"
        if vix is not None and not (equity is not None and vix > 0 and equity < 0):
            result.metadata["vix_state"] = "REGIME_ONLY_NO_DIRECTION"
        result.metadata.update({
            "model": "causal_channels_v1",
            "direct_vix_coefficient": False,
            "direct_us10y_coefficient": False,
            "real_driver_count": real_count,
            "proxy_driver_count": proxy_count,
        })
        return result


class GeopoliticalEngine:
    version = "1.0.0"

    def evaluate(self, events: list[dict[str, Any]]) -> FundamentalFactorResult:
        drivers: list[FundamentalDriver] = []
        # Do not count reprints as independent evidence.
        by_cluster: dict[str, list[dict[str, Any]]] = {}
        for e in events:
            cluster = str(e.get("story_cluster_id") or e.get("event_id") or uuid.uuid4().hex)
            by_cluster.setdefault(cluster, []).append(e)
        for cluster, group in by_cluster.items():
            e = max(group, key=lambda x: float(x.get("source_trust", 50.0)))
            severity = float(e.get("severity_score", 0.0) or 0.0)
            escalation = float(e.get("escalation_score", 0.0) or 0.0)
            deesc = float(e.get("deescalation_score", 0.0) or 0.0)
            persistence = float(e.get("persistence_score", 0.0) or 0.0)
            global_rel = float(e.get("global_relevance", 0.0) or 0.0)
            safe = float(e.get("safe_haven_score", 0.0) or 0.0)
            energy = float(e.get("energy_risk_score", 0.0) or 0.0)
            consensus = float(e.get("source_consensus_score", 50.0) or 50.0)
            raw = severity * 0.25 + escalation * 0.20 - deesc * 0.25 + persistence * 0.10 + global_rel * 0.10 + safe * 0.30 + energy * 0.10
            gold = clamp(raw)
            independence = len({str(x.get("independence_group") or x.get("source_id")) for x in group})
            confidence = min(100.0, consensus * 0.60 + min(40.0, independence * 10.0))
            drivers.append(FundamentalDriver(
                code=f"GEO_{str(e.get('event_class', 'EVENT')).upper()}",
                label_ar=str(e.get("title_ar") or e.get("event_class") or "حدث جيوسياسي"),
                label_en=str(e.get("title_en") or e.get("event_class") or "Geopolitical event"),
                native_score=clamp(escalation - deesc),
                gold_impact_score=gold,
                strength=min(100.0, abs(gold)),
                confidence=confidence,
                explanation_ar=(
                    f"شدة الحدث {severity:.0f}/100، التصعيد {escalation:.0f}/100، "
                    f"ضغط الملاذ الآمن {safe:.0f}/100، والمصادر المستقلة {independence}."
                ),
                horizon_class=HorizonClass.EVENT_SHOCK,
                sources=_source_evidence(e),
            ))
        return _factor_common(drivers, FundamentalDomain.GEOPOLITICAL, HorizonClass.EVENT_SHOCK, self.version)


class FlowsEngine:
    version = "1.0.0"
    SIGN = {
        "ETF_FLOW": 1.0,
        "ETF_HOLDINGS": 0.7,
        "CENTRAL_BANK_BUYING": 1.0,
        "COT": 0.8,
        "OPEN_INTEREST": 0.25,
        "FUTURES_VOLUME": 0.15,
        "OPTIONS_SKEW": 0.55,
        "PUT_CALL": -0.25,
        "ORDER_FLOW_DELTA": 0.85,
        "LARGE_TRADE_IMBALANCE": 0.85,
    }
    HORIZON = {
        "CENTRAL_BANK_BUYING": HorizonClass.STRUCTURAL,
        "COT": HorizonClass.STRUCTURAL,
        "ETF_FLOW": HorizonClass.TACTICAL,
        "ETF_HOLDINGS": HorizonClass.STRUCTURAL,
        "OPEN_INTEREST": HorizonClass.TACTICAL,
        "FUTURES_VOLUME": HorizonClass.TACTICAL,
        "OPTIONS_SKEW": HorizonClass.TACTICAL,
        "PUT_CALL": HorizonClass.TACTICAL,
        "ORDER_FLOW_DELTA": HorizonClass.EVENT_SHOCK,
        "LARGE_TRADE_IMBALANCE": HorizonClass.EVENT_SHOCK,
    }

    def evaluate(self, observations: list[dict[str, Any]]) -> FundamentalFactorResult:
        drivers: list[FundamentalDriver] = []
        for o in observations:
            t = str(o.get("flow_type", "")).upper()
            if t not in self.SIGN:
                continue
            strength = float(o.get("strength_score", 0.0) or 0.0)
            direction = str(o.get("flow_direction", "neutral")).lower()
            signed = strength if direction in {"inflow", "buy", "bullish", "positive", "long"} else -strength if direction in {"outflow", "sell", "bearish", "negative", "short"} else float(o.get("normalized_value", 0.0) or 0.0)
            crowding = float(o.get("crowding_score", 0.0) or 0.0)
            divergence = float(o.get("divergence_score", 0.0) or 0.0)
            gold = clamp(signed * self.SIGN[t] - math.copysign(min(abs(signed) * 0.35, crowding * 0.25), signed) + divergence * 0.15)
            h = self.HORIZON[t]
            drivers.append(FundamentalDriver(
                code=t,
                label_ar={
                    "COT": "تقرير التزام المتداولين (COT)",
                    "ETF_FLOW": "تدفقات صناديق الذهب المتداولة (Gold ETF)",
                    "ETF_HOLDINGS": "حيازات صناديق الذهب المتداولة (Gold ETF)",
                    "CENTRAL_BANK_BUYING": "مشتريات البنوك المركزية من الذهب",
                    "OPEN_INTEREST": "العقود المفتوحة",
                    "FUTURES_VOLUME": "حجم العقود الآجلة",
                    "OPTIONS_SKEW": "ميل الخيارات",
                    "PUT_CALL": "نسبة Put/Call",
                    "ORDER_FLOW_DELTA": "دلتا تدفق الأوامر",
                    "LARGE_TRADE_IMBALANCE": "اختلال الصفقات الكبيرة",
                }.get(t, t),
                label_en=t,
                native_score=clamp(signed),
                gold_impact_score=gold,
                strength=min(100.0, abs(gold)),
                confidence=float(o.get("quality_score", 70.0)),
                explanation_ar=(
                    f"اتجاه التدفق {direction} بقوة {strength:.0f}/100، "
                    f"الازدحام {crowding:.0f}/100، والأثر على الذهب {gold:+.1f}."
                ),
                horizon_class=h,
                sources=_source_evidence(o),
            ))
        structural = [d for d in drivers if d.horizon_class == HorizonClass.STRUCTURAL]
        tactical = [d for d in drivers if d.horizon_class != HorizonClass.STRUCTURAL]
        # Only EVENT_SHOCK/TACTICAL observations may contribute to the tactical
        # fusion that drives 5m/15m/60m probabilities. Structural COT / central-
        # bank buying is context/prior only and is carried separately below.
        result = _factor_common(tactical, FundamentalDomain.FLOWS, HorizonClass.TACTICAL, self.version)
        result.metadata["structural_gold_score"] = average([d.gold_impact_score for d in structural], 0.0)
        result.metadata["structural_coverage_score"] = min(100.0, len(structural) * 25.0)
        result.metadata["structural_driver_count"] = len(structural)
        result.metadata["tactical_gold_score"] = average([d.gold_impact_score for d in tactical], 0.0)
        if structural and not tactical:
            result.metadata["state"] = "structural_only"
        return result


class FundamentalFusionEngine:
    version = "1.0.0"
    DEFAULT = {
        FundamentalDomain.MACRO: 0.23,
        FundamentalDomain.MONETARY: 0.23,
        FundamentalDomain.CROSS_ASSET: 0.22,
        FundamentalDomain.GEOPOLITICAL: 0.16,
        FundamentalDomain.FLOWS: 0.16,
    }
    EVENT_PROFILES = {
        "CPI": {FundamentalDomain.MACRO: 0.40, FundamentalDomain.MONETARY: 0.22, FundamentalDomain.CROSS_ASSET: 0.25, FundamentalDomain.GEOPOLITICAL: 0.05, FundamentalDomain.FLOWS: 0.08},
        "CORE_CPI": {FundamentalDomain.MACRO: 0.40, FundamentalDomain.MONETARY: 0.22, FundamentalDomain.CROSS_ASSET: 0.25, FundamentalDomain.GEOPOLITICAL: 0.05, FundamentalDomain.FLOWS: 0.08},
        "NFP": {FundamentalDomain.MACRO: 0.38, FundamentalDomain.MONETARY: 0.22, FundamentalDomain.CROSS_ASSET: 0.25, FundamentalDomain.GEOPOLITICAL: 0.05, FundamentalDomain.FLOWS: 0.10},
        "FOMC": {FundamentalDomain.MACRO: 0.10, FundamentalDomain.MONETARY: 0.42, FundamentalDomain.CROSS_ASSET: 0.30, FundamentalDomain.GEOPOLITICAL: 0.06, FundamentalDomain.FLOWS: 0.12},
        "GEOPOLITICAL": {FundamentalDomain.MACRO: 0.07, FundamentalDomain.MONETARY: 0.08, FundamentalDomain.CROSS_ASSET: 0.25, FundamentalDomain.GEOPOLITICAL: 0.45, FundamentalDomain.FLOWS: 0.15},
    }

    def fuse(
        self,
        factors: list[FundamentalFactorResult],
        *,
        symbol: str = "XAUUSD",
        event_type: str = "",
        event_id: str | None = None,
        market_regime: str = "normal",
        safe_haven_environment: float = 0.0,
    ) -> FundamentalFusionResult:
        factor_by_domain = {f.domain: f for f in factors if f.coverage_score > 0}
        profile = self.EVENT_PROFILES.get(event_type.upper(), self.DEFAULT)
        causal_counts = Counter(
            e.causal_group_id
            for f in factor_by_domain.values()
            for d in [*f.primary_drivers, *f.counter_drivers]
            for e in d.sources
            if e.causal_group_id
        )
        weights: list[FusionWeight] = []
        effective_raw: dict[FundamentalDomain, float] = {}
        for domain, factor in factor_by_domain.items():
            base = float(profile.get(domain, self.DEFAULT[domain]))
            freshness = clamp01(factor.freshness_score / 100)
            quality = clamp01(factor.data_quality_score / 100)
            relevance = clamp01((factor.strength + 25.0) / 125.0)
            reliability = clamp01(factor.reliability_score / 100)
            regime_factor = 1.0
            if domain == FundamentalDomain.GEOPOLITICAL and safe_haven_environment > 50:
                regime_factor = min(1.7, 1.0 + safe_haven_environment / 200.0)
            if domain == FundamentalDomain.CROSS_ASSET and market_regime.lower() in {"shock", "risk_off", "high_vol"}:
                regime_factor = 1.2
            groups = [
                e.causal_group_id
                for d in [*factor.primary_drivers, *factor.counter_drivers]
                for e in d.sources
                if e.causal_group_id
            ]
            if groups:
                avg_group = average([causal_counts[g] for g in groups], 1.0)
                independent = independence_factor(max(1, int(round(avg_group))))
            else:
                independent = 1.0
            effective = base * freshness * quality * relevance * reliability * regime_factor * independent
            effective_raw[domain] = effective
            weights.append(FusionWeight(
                domain=domain,
                raw_gold_score=factor.gold_impact_score,
                base_weight=base,
                effective_weight=min(1.0, effective),
                normalized_weight=0.0,
                freshness_factor=freshness,
                quality_factor=quality,
                relevance_factor=relevance,
                reliability_factor=reliability,
                regime_factor=regime_factor,
                independence_factor=independent,
                reason_ar=(
                    f"الوزن الأساسي {base:.2f}، الحداثة {freshness:.2f}، الجودة {quality:.2f}، "
                    f"الملاءمة {relevance:.2f}، الموثوقية {reliability:.2f}، "
                    f"معامل النظام {regime_factor:.2f}، والاستقلال {independent:.2f}."
                ),
            ))
        denom = sum(effective_raw.values())
        for w in weights:
            w.normalized_weight = effective_raw[w.domain] / denom if denom > 0 else 0.0
        score = sum(w.raw_gold_score * w.normalized_weight for w in weights)
        scores = [f.gold_impact_score for f in factor_by_domain.values()]
        agreement, conflict = conflict_from_scores(scores)
        # High opposition should be CONFLICTED instead of falsely looking neutral.
        direction = GoldDirection.CONFLICTED if conflict >= 55 and any(x > 18 for x in scores) and any(x < -18 for x in scores) else direction_from_score(score)
        coverage = sum(f.coverage_score for f in factor_by_domain.values()) / 5.0
        freshness = average([f.freshness_score for f in factor_by_domain.values()], 0.0)
        quality = average([f.data_quality_score for f in factor_by_domain.values()], 0.0)
        reliability = average([f.reliability_score for f in factor_by_domain.values()], 0.0)
        confidence = confidence_from_components(
            coverage=coverage,
            quality=quality,
            freshness=freshness,
            reliability=reliability,
            agreement=agreement,
            conflict=conflict,
        )
        all_drivers = [d for f in factor_by_domain.values() for d in f.primary_drivers]
        all_counter = [d for f in factor_by_domain.values() for d in f.counter_drivers]
        fusion_id = uuid.uuid4().hex
        return FundamentalFusionResult(
            fusion_id=fusion_id,
            symbol=symbol,
            event_id=event_id,
            net_score=clamp(score),
            direction=direction,
            strength=min(100.0, abs(score) + conflict * 0.15),
            confidence=confidence,
            coverage_score=min(100.0, coverage),
            agreement_score=agreement,
            conflict_score=conflict,
            freshness_score=freshness,
            data_quality_score=quality,
            weights=weights,
            primary_drivers=sorted(all_drivers, key=lambda d: abs(d.gold_impact_score), reverse=True)[:6],
            counter_drivers=sorted(all_counter, key=lambda d: abs(d.gold_impact_score), reverse=True)[:6],
            fusion_version=self.version,
        )


class GoldImpactEngine:
    version = "1.0.0"

    @staticmethod
    def _prob(score: float, confidence: float, horizon_scale: float) -> HorizonProbability:
        directional = (score * confidence / 100.0) * horizon_scale
        bull = sigmoid_probability(directional)
        # uncertainty allocates mass to neutral; lower confidence = more neutral.
        neutral = min(0.70, max(0.08, (100.0 - confidence) / 130.0 + (1.0 - min(1.0, abs(score) / 70.0)) * 0.18))
        remaining = 1.0 - neutral
        bullish = remaining * bull
        bearish = remaining * (1.0 - bull)
        return HorizonProbability(bullish=bullish, bearish=bearish, neutral=neutral)

    def predict(
        self,
        fusion: FundamentalFusionResult,
        factors: list[FundamentalFactorResult],
        *,
        blackout: dict[str, Any] | None = None,
        stage: PredictionStage = PredictionStage.AT_RELEASE,
    ) -> GoldImpactResult:
        structural_scores: list[float] = []
        for f in factors:
            if f.horizon_class == HorizonClass.STRUCTURAL:
                structural_scores.append(f.gold_impact_score)
            structural_scores.append(float(f.metadata.get("structural_gold_score", 0.0) or 0.0))
        structural_scores = [x for x in structural_scores if abs(x) > 1e-9]
        structural_score = average(structural_scores, 0.0)
        structural_bias = direction_from_score(structural_score)
        blackout = blackout or {"active": False, "state": "clear"}
        active = bool(blackout.get("active", False)) or str(blackout.get("state", "clear")).lower() in {"active", "unknown", "degraded", "unavailable"}
        return GoldImpactResult(
            prediction_id=uuid.uuid4().hex,
            symbol=fusion.symbol,
            event_id=fusion.event_id,
            fusion_id=fusion.fusion_id,
            stage=stage,
            direction=fusion.direction,
            strength=fusion.strength,
            confidence=fusion.confidence,
            confidence_validation=ConfidenceValidation.UNVALIDATED,
            coverage_score=fusion.coverage_score,
            conflict_score=fusion.conflict_score,
            freshness_score=fusion.freshness_score,
            data_quality_score=fusion.data_quality_score,
            horizon_5m=self._prob(fusion.net_score, fusion.confidence, 1.00),
            horizon_15m=self._prob(fusion.net_score, fusion.confidence, 0.95),
            horizon_60m=self._prob(fusion.net_score, fusion.confidence, 0.82),
            horizon_4h=self._prob(fusion.net_score, fusion.confidence, 0.62),
            structural_bias=structural_bias,
            primary_drivers=fusion.primary_drivers,
            counter_drivers=fusion.counter_drivers,
            confirmations_ar=[d.explanation_ar for d in fusion.primary_drivers[:3]],
            contradictions_ar=[d.explanation_ar for d in fusion.counter_drivers[:3]],
            weakening_factors_ar=(
                ["تغطية البيانات أقل من المستوى المثالي."] if fusion.coverage_score < 75 else []
            ) + (["يوجد تعارض مرتفع بين المحاور الأساسية."] if fusion.conflict_score >= 45 else []),
            invalidation_conditions_ar=[
                "انعكاس اتجاه الدولار والعوائد الحقيقيّة بصورة مستقرة ضد السيناريو الحالي.",
                "ظهور حدث جديد عالي التأثير يغيّر النظام السوقي أو سياسة الفائدة.",
                "انخفاض جودة/حداثة البيانات المستخدمة إلى حالة متدهورة أو غير متاحة.",
            ],
            transmission_chain_ar=[],
            blackout_active=active,
            blackout_reason_ar=str(blackout.get("reason_ar") or "") if active else None,
            model_version=self.version,
        )
