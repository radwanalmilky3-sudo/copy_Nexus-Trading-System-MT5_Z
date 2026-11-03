from __future__ import annotations

"""Deterministic governance seed records for the institutional fundamental layer.

These rows are metadata/contracts, not market observations.  They are safe to
seed repeatedly because every primary key is deterministic and the data service
uses INSERT OR IGNORE.  Knowledge claims are explanation-only by default.
"""

import hashlib
from datetime import datetime, timezone
from typing import Any

from .asset_impact import AssetImpactEngine
from .indicator_catalog import CATALOG_VERSION, INDICATORS, INDICATOR_AR

UTC = timezone.utc


def _id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(p) for p in parts)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


INDICATOR_NAME_EN: dict[str, str] = {
    "CPI": "Consumer Price Index",
    "CORE_CPI": "Core Consumer Price Index",
    "PCE": "PCE Price Index",
    "CORE_PCE": "Core PCE Price Index",
    "PPI": "Producer Price Index",
    "CORE_PPI": "Core Producer Price Index",
    "INFLATION_EXPECTATIONS": "Inflation Expectations",
    "NFP": "Nonfarm Payrolls",
    "UNEMPLOYMENT": "Unemployment Rate",
    "U6_UNDEREMPLOYMENT": "U-6 Labor Underutilization",
    "AVG_HOURLY_EARNINGS": "Average Hourly Earnings",
    "AVG_WEEKLY_HOURS": "Average Weekly Hours",
    "LABOR_FORCE_PARTICIPATION": "Labor Force Participation Rate",
    "INITIAL_CLAIMS": "Initial Jobless Claims",
    "CONTINUING_CLAIMS": "Continuing Jobless Claims",
    "CLAIMS_4W_AVG": "4-Week Average Initial Claims",
    "JOBLESS_CLAIMS": "Jobless Claims",
    "ADP_EMPLOYMENT": "ADP Employment Change",
    "JOLTS": "JOLTS Job Openings",
    "JOLTS_OPENINGS": "JOLTS Job Openings",
    "JOLTS_HIRES": "JOLTS Hires",
    "JOLTS_QUITS": "JOLTS Quits",
    "GDP": "Gross Domestic Product",
    "GDI": "Gross Domestic Income",
    "PMI": "Purchasing Managers Index",
    "ISM_MANUFACTURING": "ISM Manufacturing",
    "ISM_SERVICES": "ISM Services",
    "RETAIL_SALES": "Retail Sales",
    "INDUSTRIAL_PRODUCTION": "Industrial Production",
    "DURABLE_GOODS": "Durable Goods Orders",
    "CONSUMER_CONFIDENCE": "Consumer Confidence",
    "MICHIGAN_SENTIMENT": "University of Michigan Consumer Sentiment",
    "HOUSING_STARTS": "Housing Starts",
    "BUILDING_PERMITS": "Building Permits",
    "EXISTING_HOME_SALES": "Existing Home Sales",
    "NEW_HOME_SALES": "New Home Sales",
    "TRADE_BALANCE": "Trade Balance",
}


def _source_for(code: str) -> str | None:
    if code in {
        "CPI", "CORE_CPI", "NFP", "UNEMPLOYMENT", "U6_UNDEREMPLOYMENT",
        "AVG_HOURLY_EARNINGS", "AVG_WEEKLY_HOURS", "LABOR_FORCE_PARTICIPATION",
    }:
        return "bls"
    if code in {"PCE", "CORE_PCE", "GDP", "GDI"}:
        return "bea"
    if code in {"INITIAL_CLAIMS", "CONTINUING_CLAIMS", "CLAIMS_4W_AVG"}:
        # FRED is currently the configured canonical programmatic route for these
        # official DOL-origin series; provenance remains FRED + source-series id.
        return "fred"
    return "calendar_secondary"


def indicator_catalog_records() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for code, spec in INDICATORS.items():
        horizon = str(spec.get("native_horizon", "event_shock"))
        rows.append({
            "indicator_id": _id("ind", code, CATALOG_VERSION),
            "indicator_code": code,
            "name_ar": INDICATOR_AR.get(code, code),
            "name_en": INDICATOR_NAME_EN.get(code, code.replace("_", " ").title()),
            "domain": str(spec.get("domain", "macro")),
            "country": "US",
            "currency": "USD",
            "frequency": str(spec.get("frequency", "monthly")),
            "unit": None,
            "release_schedule": "provider/calendar controlled",
            "source_id": _source_for(code),
            "importance_default": float(spec.get("importance", 50.0)),
            "structural_vs_tactical": "structural" if horizon == "structural" else "tactical",
            "default_horizons_json": [horizon],
            "freshness_limit_seconds": 86400 if spec.get("frequency") == "weekly" else 14400,
            "revision_policy": "store vintages; never overwrite point-in-time history",
            "catalog_version": CATALOG_VERSION,
            "active": True,
        })
    return rows


def asset_records() -> list[dict[str, Any]]:
    return [
        {
            "asset_id": "XAUUSD", "symbol": "XAUUSD", "asset_class": "precious_metal",
            "quote_currency": "USD", "country_or_region": "global", "timezone": "UTC",
            "enabled": True, "paper_supported": True, "live_supported": False,
        },
        {
            "asset_id": "BTCUSD", "symbol": "BTCUSD", "asset_class": "crypto",
            "quote_currency": "USD", "country_or_region": "global", "timezone": "UTC",
            "enabled": True, "paper_supported": True, "live_supported": False,
        },
    ]


def asset_factor_profile_records() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for code, spec in INDICATORS.items():
        sign = float(spec.get("gold_sign", 0.0))
        rows.append({
            "profile_id": _id("afp", "XAUUSD", code, CATALOG_VERSION),
            "asset_id": "XAUUSD",
            "factor_code": code,
            "domain": str(spec.get("domain", "macro")),
            "default_sign": "bullish" if sign > 0 else "bearish" if sign < 0 else "conditional",
            "relationship_type": "conditional",
            "conditions_json": ["actual_vs_expectation evidence exists", "current regime evaluated"],
            "counter_conditions_json": ["market confirmation contradicts", "dominant independent shock"],
            "allowed_horizons_json": [str(spec.get("native_horizon", "event_shock"))],
            "structural_only": str(spec.get("native_horizon")) == "structural",
            "version": CATALOG_VERSION,
            "active": True,
        })
    for code, sign in sorted(AssetImpactEngine.BTC_DRIVER_SIGN.items()):
        rows.append({
            "profile_id": _id("afp", "BTCUSD", code, AssetImpactEngine.version),
            "asset_id": "BTCUSD",
            "factor_code": code,
            "domain": "cross_asset" if code in {"USD_LIQUIDITY_PRESSURE", "REAL_RATE_PRESSURE", "RISK_OFF_SAFE_HAVEN", "ENERGY_INFLATION_PRESSURE"} else "monetary" if code.startswith("MONETARY_") else "macro",
            "default_sign": "bullish" if sign > 0 else "bearish" if sign < 0 else "conditional",
            "relationship_type": "conditional",
            "conditions_json": ["driver is real and fresh", "asset-specific relevance is non-zero"],
            "counter_conditions_json": ["crypto-specific driver dominates", "market confirmation contradicts"],
            "allowed_horizons_json": ["event_shock", "tactical"],
            "structural_only": False,
            "version": AssetImpactEngine.version,
            "active": True,
        })
    return rows


def knowledge_seed() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source_id = "nexus_reviewed_fundamental_pack_v4"
    sources = [{
        "knowledge_source_id": source_id,
        "provider_name": "Nexus reviewed Fundamental Intelligence educational pack",
        "source_type": "reviewed_educational_material",
        "url_or_doc_ref": "Fundamental_Intelligence_Images.zip / 31 images",
        "publisher": "local reviewed material",
        "retrieved_at": datetime.now(UTC),
        "license_notes": "Internal explanatory knowledge only; not an authority for market facts or execution.",
        "version": "4.0",
        "trust_tier": 3,
        "active": True,
    }]
    specs = [
        ("cycle_rates", "macro", "الدورة الاقتصادية", "مستوى الفائدة وحده لا يحدد مرحلة الدورة الاقتصادية.", ["growth", "inflation", "employment", "PMI/ISM", "financial conditions", "yield curve"]),
        ("cpi_fed", "monetary", "التضخم والسياسة النقدية", "لا توجد قاعدة إنتاجية من نوع CPI أعلى من 2% تعني رفع الفائدة تلقائياً.", ["CPI/PCE distinction", "labor", "market pricing", "forward guidance"]),
        ("vix_regime", "cross_asset", "VIX", "VIX عامل تقلب ونظام مخاطر؛ لا يستخدم كإشارة اتجاه مباشرة للذهب ولا كحد عالمي ثابت عند 20.", ["VIX percentile", "VIX change", "SPX", "DXY", "yields"]),
        ("yield_reason", "cross_asset", "العوائد", "اتجاه العائد وحده غير كافٍ؛ يجب فصل العائد الاسمي والحقيقي والتعادل التضخمي وسبب الحركة.", ["nominal yield", "real yield", "breakeven", "DXY", "move reason"]),
        ("labor_bundle", "macro", "سوق العمل", "قراءة سوق العمل تعتمد على الوظائف والبطالة والأجور والمراجعات والمشاركة وطلبات الإعانة وJOLTS معاً.", ["NFP", "unemployment", "wages", "revisions", "participation", "claims", "JOLTS"]),
    ]
    claims = []
    for key, domain, concept, statement, confirmations in specs:
        claims.append({
            "claim_id": f"claim_{key}_v4",
            "knowledge_source_id": source_id,
            "domain": domain,
            "concept": concept,
            "statement_ar": statement,
            "statement_en": None,
            "conditions_json": ["use as explanation/validation context only"],
            "counter_conditions_json": [],
            "default_relationship_json": {"type": "conditional"},
            "asset_scope_json": ["XAUUSD", "BTCUSD"],
            "required_confirmations_json": confirmations,
            "exceptions_json": ["never convert into a fixed trading rule"],
            "horizon_json": ["event_shock", "tactical", "structural"],
            "allowed_for_explanation": True,
            "allowed_for_scoring": False,
            "review_status": "reviewed_for_explanation",
            "version": "4.0",
        })
    return sources, claims
