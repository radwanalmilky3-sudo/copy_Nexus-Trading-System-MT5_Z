from __future__ import annotations

"""Asset-specific fundamental impact mapping with DB-backed factor profiles.

V6.1 keeps XAUUSD on the validated GoldImpactEngine path and maps BTCUSD from
native drivers through ``asset_factor_profiles``.  Static signs are only a safe
bootstrap fallback used to seed those profiles; runtime receives the actual
profile records and resolves them first.
"""

import json
import hashlib
from datetime import datetime, timezone
from typing import Any

from shared.fundamental import FundamentalFactorResult, GoldImpactResult, HorizonClass

UTC = timezone.utc


def _clamp(value: float, lo: float = -100.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(value)))


def _direction(score: float, neutral_band: float = 10.0) -> str:
    if score > neutral_band:
        return "bullish"
    if score < -neutral_band:
        return "bearish"
    return "neutral"


def _stable_id(*parts: Any) -> str:
    raw = "|".join(str(x) for x in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x) for x in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except Exception:
            pass
    return []


class AssetFactorProfileRegistry:
    """Resolve the active asset-factor relationship used by the impact engine."""

    def __init__(self, records: list[dict[str, Any]] | None = None) -> None:
        self._profiles: dict[tuple[str, str], dict[str, Any]] = {}
        for row in records or []:
            if not bool(row.get("active", True)):
                continue
            asset = str(row.get("asset_id") or "").upper()
            code = str(row.get("factor_code") or "").upper()
            if asset and code:
                self._profiles[(asset, code)] = dict(row)

    def resolve(self, asset_id: str, factor_code: str) -> dict[str, Any] | None:
        asset = asset_id.upper()
        code = factor_code.upper()
        exact = self._profiles.get((asset, code))
        if exact:
            return exact
        # Controlled wildcard support is needed for monetary event kinds that
        # become MONETARY_<KIND> at runtime.
        for (a, pattern), row in self._profiles.items():
            if a == asset and pattern.endswith("*") and code.startswith(pattern[:-1]):
                return row
        return None

    @staticmethod
    def sign(profile: dict[str, Any]) -> float | None:
        value = str(profile.get("default_sign") or "conditional").lower()
        if value == "bullish":
            return 1.0
        if value == "bearish":
            return -1.0
        return None

    @staticmethod
    def horizon_allowed(profile: dict[str, Any], horizon_class: str) -> bool:
        allowed = _json_list(profile.get("allowed_horizons_json"))
        if not allowed:
            return True
        return horizon_class in allowed


class AssetImpactEngine:
    version = "2.1.1"

    HORIZON_SCALES = {"5m": 1.00, "15m": 0.95, "60m": 0.82, "4h": 0.65}

    # Bootstrap relationships. They are persisted by bootstrap_v5.py and runtime
    # passes the resulting asset_factor_profiles back into this engine.
    BTC_DRIVER_SIGN: dict[str, float] = {
        "CPI": -1.0, "CORE_CPI": -1.0, "PCE": -1.0, "CORE_PCE": -1.0,
        "PPI": -1.0, "CORE_PPI": -1.0, "NFP": -1.0,
        "UNEMPLOYMENT": +1.0, "U6_UNDEREMPLOYMENT": +1.0,
        "AVG_HOURLY_EARNINGS": -1.0, "AVG_WEEKLY_HOURS": -1.0,
        "LABOR_FORCE_PARTICIPATION": -1.0, "INITIAL_CLAIMS": +1.0,
        "CONTINUING_CLAIMS": +1.0, "JOBLESS_CLAIMS": +1.0,
        "JOLTS_OPENINGS": -1.0, "JOLTS_HIRES": -1.0, "JOLTS_QUITS": -1.0,
        "JOLTS": -1.0, "GDP": -1.0, "RETAIL_SALES": -1.0,
        "ISM_MANUFACTURING": -1.0, "ISM_SERVICES": -1.0, "PMI": -1.0,
        "CONSUMER_CONFIDENCE": -1.0,
        # Causal cross-asset channels only — no direct VIX/US10Y rule.
        "USD_LIQUIDITY_PRESSURE": -1.0,
        "REAL_RATE_PRESSURE": -1.0,
        "RISK_OFF_SAFE_HAVEN": -1.0,
        "ENERGY_INFLATION_PRESSURE": -1.0,
        "MONETARY_*": -1.0,
    }

    def __init__(self, profile_records: list[dict[str, Any]] | None = None) -> None:
        if profile_records is None:
            profile_records = self._bootstrap_profiles()
        self.profiles = AssetFactorProfileRegistry(profile_records)

    @classmethod
    def _bootstrap_profiles(cls) -> list[dict[str, Any]]:
        rows = []
        for code, sign in cls.BTC_DRIVER_SIGN.items():
            rows.append({
                "asset_id": "BTCUSD",
                "factor_code": code,
                "default_sign": "bullish" if sign > 0 else "bearish",
                "allowed_horizons_json": ["event_shock", "tactical"],
                "active": True,
                "version": cls.version,
            })
        return rows

    def evaluate(
        self,
        *,
        event_id: str | None,
        event_type: str,
        factors: list[FundamentalFactorResult],
        gold: GoldImpactResult,
        known_at: datetime | None = None,
    ) -> list[dict[str, Any]]:
        known = known_at or datetime.now(UTC)
        impacts: list[dict[str, Any]] = []
        impacts.extend(self._gold_impacts(gold, known))
        impacts.extend(self._btc_impacts(event_id, event_type, factors, known))
        return impacts

    def _gold_impacts(self, gold: GoldImpactResult, known_at: datetime) -> list[dict[str, Any]]:
        horizon_prob = {"5m": gold.horizon_5m, "15m": gold.horizon_15m, "60m": gold.horizon_60m, "4h": gold.horizon_4h}
        source_ids = sorted({
            evidence.source_id
            for driver in [*gold.primary_drivers, *gold.counter_drivers]
            for evidence in driver.sources
        })
        rows: list[dict[str, Any]] = []
        for horizon, probs in horizon_prob.items():
            score = _clamp((probs.bullish - probs.bearish) * 100.0)
            rows.append({
                # Outcomes reference a particular prediction snapshot. A later
                # computation must not rewrite that historical parent row.
                "impact_id": _stable_id("impact", gold.event_id or gold.prediction_id, "XAUUSD", horizon, gold.stage.value, known_at.astimezone(UTC).isoformat()),
                "event_id": gold.event_id,
                "asset_id": "XAUUSD",
                "prediction_id": gold.prediction_id,
                "event_stage": gold.stage.value,
                "relevance_score": min(100.0, max(0.0, gold.coverage_score + 20.0)),
                "direction": _direction(score),
                "impact_score": score,
                "confidence": gold.confidence,
                "coverage": gold.coverage_score,
                "quality": gold.data_quality_score,
                "freshness": gold.freshness_score,
                "agreement": max(0.0, 100.0 - gold.conflict_score),
                "conflict": gold.conflict_score,
                "horizon": horizon,
                "transmission_path_json": list(gold.transmission_chain_ar),
                "drivers_json": [d.model_dump(mode="json") for d in gold.primary_drivers[:6]],
                "counter_drivers_json": [d.model_dump(mode="json") for d in gold.counter_drivers[:6]],
                "confirmations_json": list(gold.confirmations_ar),
                "contradictions_json": list(gold.contradictions_ar),
                "invalidation_json": list(gold.invalidation_conditions_ar),
                "source_ids_json": source_ids,
                "claim_ids_json": [],
                "engine_version": self.version,
                "feature_schema_version": "fundamental-v6.1",
                "known_at": known_at,
                "calculated_at": known_at,
            })
        return rows

    def _btc_impacts(
        self,
        event_id: str | None,
        event_type: str,
        factors: list[FundamentalFactorResult],
        known_at: datetime,
    ) -> list[dict[str, Any]]:
        contributions: list[dict[str, Any]] = []
        source_ids: set[str] = set()

        for factor in factors:
            for driver in [*factor.primary_drivers, *factor.counter_drivers]:
                code = str(driver.code).upper()
                if code in {"COT", "ETF_FLOW", "ETF_HOLDINGS", "CENTRAL_BANK_BUYING"}:
                    continue
                profile = self.profiles.resolve("BTCUSD", code)
                if not profile:
                    # Fail closed: an unprofiled factor does not silently acquire
                    # an asset relationship.
                    continue
                sign = self.profiles.sign(profile)
                if sign is None:
                    continue
                horizon = driver.horizon_class.value
                if not self.profiles.horizon_allowed(profile, horizon):
                    continue
                base = _clamp(driver.native_score * sign)
                weight = max(0.05, min(1.0, driver.strength / 100.0))
                weight *= max(0.20, min(1.0, driver.confidence / 100.0))
                contributions.append({
                    "code": code,
                    "profile_id": profile.get("profile_id"),
                    "profile_version": profile.get("version"),
                    "label_ar": driver.label_ar,
                    "score": base,
                    "weight": weight,
                    "confidence": driver.confidence,
                    "horizon_class": horizon,
                    "explanation_ar": driver.explanation_ar,
                })
                for ev in driver.sources:
                    source_ids.add(ev.source_id)

        rows: list[dict[str, Any]] = []
        for horizon, scale in self.HORIZON_SCALES.items():
            eligible = []
            for item in contributions:
                h = item["horizon_class"]
                if horizon in {"5m", "15m"} and h == HorizonClass.STRUCTURAL.value:
                    continue
                eligible.append(item)

            if not eligible:
                score = confidence = coverage = quality = agreement = conflict = 0.0
                relevance = self._event_relevance(event_type, driver_count=0)
            else:
                denom = sum(float(x["weight"]) for x in eligible)
                score = _clamp(sum(float(x["score"]) * float(x["weight"]) for x in eligible) / max(denom, 1e-9) * scale)
                confidence = sum(float(x["confidence"]) * float(x["weight"]) for x in eligible) / max(denom, 1e-9)
                coverage = min(100.0, len(eligible) * 14.0)
                quality = min(100.0, confidence)
                positive = sum(1 for x in eligible if float(x["score"]) > 8)
                negative = sum(1 for x in eligible if float(x["score"]) < -8)
                directional = positive + negative
                conflict = 0.0 if directional == 0 else min(100.0, 200.0 * min(positive, negative) / directional)
                agreement = max(0.0, 100.0 - conflict)
                relevance = self._event_relevance(event_type, driver_count=len(eligible))
                confidence = max(0.0, min(100.0, confidence * (0.55 + 0.45 * coverage / 100.0) * (1.0 - conflict / 180.0)))

            primary = sorted((x for x in eligible if float(x["score"]) * score >= 0), key=lambda x: abs(float(x["score"])), reverse=True)[:6]
            counter = sorted((x for x in eligible if float(x["score"]) * score < 0), key=lambda x: abs(float(x["score"])), reverse=True)[:6]
            rows.append({
                "impact_id": _stable_id("impact", event_id or "runtime", "BTCUSD", horizon, "at_release", known_at.astimezone(UTC).isoformat()),
                "event_id": event_id,
                "asset_id": "BTCUSD",
                "prediction_id": None,
                "event_stage": "at_release",
                "relevance_score": relevance,
                "direction": _direction(score),
                "impact_score": score,
                "confidence": confidence,
                "coverage": coverage,
                "quality": quality,
                "freshness": quality,
                "agreement": agreement,
                "conflict": conflict,
                "horizon": horizon,
                "transmission_path_json": self._btc_transmission(event_type, primary),
                "drivers_json": primary,
                "counter_drivers_json": counter,
                "confirmations_json": [str(x["label_ar"]) for x in primary[:3]],
                "contradictions_json": [str(x["label_ar"]) for x in counter[:3]],
                "invalidation_json": [
                    "انعكاس قناة الدولار أو العائد الحقيقي بصورة مستمرة ضد السيناريو.",
                    "تغير مفاجئ في سيولة الدولار أو شهية المخاطرة أو خبر خاص بسوق العملات المشفرة.",
                    "تدهور جودة/حداثة البيانات الأساسية المستخدمة.",
                ],
                "source_ids_json": sorted(source_ids),
                "claim_ids_json": [],
                "engine_version": self.version,
                "feature_schema_version": "fundamental-v6.1",
                "known_at": known_at,
                "calculated_at": known_at,
            })
        return rows

    @staticmethod
    def _event_relevance(event_type: str, driver_count: int) -> float:
        event = (event_type or "").upper()
        if event in {"CPI", "CORE_CPI", "PCE", "CORE_PCE", "NFP", "FOMC", "FED_COMMUNICATION"}:
            base = 85.0
        elif event == "GEOPOLITICAL":
            base = 55.0
        elif event in {"CENTRAL_BANK_BUYING", "GOLD_ETF_FLOW", "COT"}:
            base = 8.0
        else:
            base = 45.0
        return max(0.0, min(100.0, base + min(15.0, driver_count * 2.0)))

    @staticmethod
    def _btc_transmission(event_type: str, drivers: list[dict[str, Any]]) -> list[str]:
        event = (event_type or "حدث أساسي").upper()
        chain = [f"{event}: مفاجأة/معلومة أساسية"]
        codes = {str(x.get("code", "")) for x in drivers}
        if any(c.startswith("MONETARY_") or c in {"CPI", "CORE_CPI", "PCE", "CORE_PCE", "NFP", "AVG_HOURLY_EARNINGS"} for c in codes):
            chain.append("توقعات السياسة النقدية والسيولة")
        if "REAL_RATE_PRESSURE" in codes:
            chain.append("قناة العائد الحقيقي")
        if "USD_LIQUIDITY_PRESSURE" in codes:
            chain.append("قناة الدولار والسيولة")
        if "RISK_OFF_SAFE_HAVEN" in codes:
            chain.append("نظام شهية المخاطرة")
        chain.append("أثر مستقل على BTCUSD عبر ملف عوامل الأصل")
        return chain
