"""Canonical economic indicator semantics used by normalization and scoring.

The catalog is intentionally versioned and explicit.  ``gold_sign`` is a
*conditional default relationship* used by the existing macro engine; it is not
a universal trading rule and is never used when actual/forecast evidence is
missing.
"""
from __future__ import annotations

from typing import Any

CATALOG_VERSION = "2.0.0"


def _spec(
    gold_sign: float,
    importance: float,
    *,
    rate: float = 0.0,
    usd: float = 0.0,
    yield_: float = 0.0,
    domain: str = "macro",
    frequency: str = "monthly",
    horizon: str = "event_shock",
    notes: str = "",
) -> dict[str, Any]:
    return {
        "gold_sign": gold_sign,
        "importance": importance,
        "rate": rate,
        "usd": usd,
        "yield": yield_,
        "domain": domain,
        "frequency": frequency,
        "native_horizon": horizon,
        "notes": notes,
        "catalog_version": CATALOG_VERSION,
    }


INDICATORS: dict[str, dict[str, Any]] = {
    # Inflation
    "CPI": _spec(-1, 95, rate=1.0, usd=0.9, yield_=0.9, notes="Headline CPI; Fed target is not defined by CPI alone."),
    "CORE_CPI": _spec(-1, 100, rate=1.0, usd=0.9, yield_=0.9),
    "PCE": _spec(-1, 92, rate=1.0, usd=0.8, yield_=0.9),
    "CORE_PCE": _spec(-1, 100, rate=1.0, usd=0.9, yield_=0.9),
    "PPI": _spec(-1, 70, rate=0.7, usd=0.6, yield_=0.7),
    "CORE_PPI": _spec(-1, 74, rate=0.75, usd=0.6, yield_=0.7),
    "INFLATION_EXPECTATIONS": _spec(-1, 78, rate=0.8, usd=0.5, yield_=0.8),

    # Employment / labor
    "NFP": _spec(-1, 100, rate=0.9, usd=0.9, yield_=0.9),
    "UNEMPLOYMENT": _spec(+1, 92, rate=-0.9, usd=-0.7, yield_=-0.8),
    "U6_UNDEREMPLOYMENT": _spec(+1, 68, rate=-0.5, usd=-0.4, yield_=-0.4),
    "AVG_HOURLY_EARNINGS": _spec(-1, 94, rate=0.9, usd=0.8, yield_=0.9),
    "AVG_WEEKLY_HOURS": _spec(-1, 58, rate=0.35, usd=0.3, yield_=0.3),
    "LABOR_FORCE_PARTICIPATION": _spec(-0.25, 55, rate=0.2, usd=0.2, yield_=0.2),
    "INITIAL_CLAIMS": _spec(+1, 72, rate=-0.6, usd=-0.5, yield_=-0.5, frequency="weekly"),
    "CONTINUING_CLAIMS": _spec(+1, 66, rate=-0.5, usd=-0.4, yield_=-0.45, frequency="weekly"),
    "CLAIMS_4W_AVG": _spec(+1, 58, rate=-0.45, usd=-0.35, yield_=-0.4, frequency="weekly"),
    "JOBLESS_CLAIMS": _spec(+1, 68, rate=-0.6, usd=-0.5, yield_=-0.5, frequency="weekly"),
    "ADP_EMPLOYMENT": _spec(-1, 58, rate=0.4, usd=0.45, yield_=0.4),
    "JOLTS": _spec(-1, 70, rate=0.6, usd=0.5, yield_=0.5),
    "JOLTS_OPENINGS": _spec(-1, 72, rate=0.6, usd=0.5, yield_=0.5),
    "JOLTS_HIRES": _spec(-1, 58, rate=0.45, usd=0.4, yield_=0.4),
    "JOLTS_QUITS": _spec(-1, 55, rate=0.4, usd=0.35, yield_=0.35),

    # Growth / demand
    "GDP": _spec(-1, 82, rate=0.5, usd=0.7, yield_=0.6, frequency="quarterly"),
    "GDI": _spec(-1, 58, rate=0.35, usd=0.45, yield_=0.4, frequency="quarterly"),
    "PMI": _spec(-1, 65, rate=0.4, usd=0.6, yield_=0.4),
    "ISM_MANUFACTURING": _spec(-1, 76, rate=0.5, usd=0.7, yield_=0.5),
    "ISM_SERVICES": _spec(-1, 82, rate=0.6, usd=0.7, yield_=0.6),
    "RETAIL_SALES": _spec(-1, 80, rate=0.5, usd=0.7, yield_=0.5),
    "INDUSTRIAL_PRODUCTION": _spec(-1, 58, rate=0.35, usd=0.45, yield_=0.35),
    "DURABLE_GOODS": _spec(-1, 62, rate=0.4, usd=0.5, yield_=0.4),
    "CONSUMER_CONFIDENCE": _spec(-1, 55, rate=0.3, usd=0.4, yield_=0.3),
    "MICHIGAN_SENTIMENT": _spec(-1, 60, rate=0.35, usd=0.4, yield_=0.35),
    "HOUSING_STARTS": _spec(-1, 45, rate=0.2, usd=0.3, yield_=0.2),
    "BUILDING_PERMITS": _spec(-1, 45, rate=0.2, usd=0.3, yield_=0.2),
    "EXISTING_HOME_SALES": _spec(-1, 42, rate=0.2, usd=0.25, yield_=0.2),
    "NEW_HOME_SALES": _spec(-1, 42, rate=0.2, usd=0.25, yield_=0.2),
    "TRADE_BALANCE": _spec(-0.5, 45, rate=0.1, usd=0.35, yield_=0.1),
}

INDICATOR_AR: dict[str, str] = {
    "CPI": "مؤشر أسعار المستهلك",
    "CORE_CPI": "مؤشر أسعار المستهلك الأساسي",
    "PCE": "نفقات الاستهلاك الشخصي",
    "CORE_PCE": "نفقات الاستهلاك الشخصي الأساسية",
    "PPI": "مؤشر أسعار المنتجين",
    "CORE_PPI": "مؤشر أسعار المنتجين الأساسي",
    "INFLATION_EXPECTATIONS": "توقعات التضخم",
    "NFP": "الوظائف غير الزراعية",
    "UNEMPLOYMENT": "معدل البطالة",
    "U6_UNDEREMPLOYMENT": "مقياس البطالة الموسع U-6",
    "AVG_HOURLY_EARNINGS": "متوسط الأجر بالساعة",
    "AVG_WEEKLY_HOURS": "متوسط ساعات العمل الأسبوعية",
    "LABOR_FORCE_PARTICIPATION": "معدل المشاركة في قوة العمل",
    "INITIAL_CLAIMS": "طلبات إعانة البطالة الأولية",
    "CONTINUING_CLAIMS": "طلبات إعانة البطالة المستمرة",
    "CLAIMS_4W_AVG": "متوسط طلبات الإعانة لأربعة أسابيع",
    "JOBLESS_CLAIMS": "طلبات إعانة البطالة",
    "ADP_EMPLOYMENT": "تقرير ADP للتوظيف",
    "JOLTS": "فرص العمل الشاغرة (JOLTS)",
    "JOLTS_OPENINGS": "فرص العمل الشاغرة (JOLTS)",
    "JOLTS_HIRES": "التعيينات (JOLTS)",
    "JOLTS_QUITS": "الاستقالات (JOLTS)",
    "GDP": "الناتج المحلي الإجمالي",
    "GDI": "الدخل المحلي الإجمالي",
    "PMI": "مؤشر مديري المشتريات",
    "ISM_MANUFACTURING": "مؤشر ISM الصناعي",
    "ISM_SERVICES": "مؤشر ISM للخدمات",
    "RETAIL_SALES": "مبيعات التجزئة",
    "INDUSTRIAL_PRODUCTION": "الإنتاج الصناعي",
    "DURABLE_GOODS": "طلبات السلع المعمرة",
    "CONSUMER_CONFIDENCE": "ثقة المستهلك",
    "MICHIGAN_SENTIMENT": "ثقة المستهلك — جامعة ميشيغان",
    "HOUSING_STARTS": "بدء بناء المساكن",
    "BUILDING_PERMITS": "تصاريح البناء",
    "EXISTING_HOME_SALES": "مبيعات المنازل القائمة",
    "NEW_HOME_SALES": "مبيعات المنازل الجديدة",
    "TRADE_BALANCE": "الميزان التجاري",
}
