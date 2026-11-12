from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    source_id: str
    name_ar: str
    name_en: str
    organization: str
    category: str
    transport: str
    base_endpoint: str | None
    documentation_url: str | None
    auth_type: str = "none"
    api_key_env: str | None = None
    polling_interval_sec: int = 3600
    freshness_limit_sec: int = 7200
    rate_limit_per_min: int | None = None
    provider_priority: int = 100
    fallback_group: str | None = None
    trust_score: float = 80.0
    license_name: str | None = None
    storage_allowed: bool = True
    redistribution_allowed: bool = False
    commercial_use_notes: str | None = None
    enabled: bool = True

    def as_record(self) -> dict[str, Any]:
        return {**asdict(self), "health_state": "unknown"}


OFFICIAL_SOURCES: tuple[SourceDefinition, ...] = (
    SourceDefinition(
        "bls", "مكتب إحصاءات العمل الأمريكي", "U.S. Bureau of Labor Statistics", "BLS",
        "macro", "api", "https://api.bls.gov/publicAPI/v2/timeseries/data/",
        "https://www.bls.gov/developers/", auth_type="optional_key", api_key_env="BLS_API_KEY",
        polling_interval_sec=900, freshness_limit_sec=7200, trust_score=100,
    ),
    SourceDefinition(
        "bea", "مكتب التحليل الاقتصادي الأمريكي", "U.S. Bureau of Economic Analysis", "BEA",
        "macro", "api", "https://apps.bea.gov/api/data/", "https://apps.bea.gov/api/",
        auth_type="api_key", api_key_env="BEA_API_KEY", polling_interval_sec=1800,
        freshness_limit_sec=14400, trust_score=100,
    ),
    SourceDefinition(
        "fred", "قاعدة بيانات الاحتياطي الفيدرالي الاقتصادية", "FRED", "Federal Reserve Bank of St. Louis",
        "cross_asset", "api", "https://api.stlouisfed.org/fred", "https://fred.stlouisfed.org/docs/api/fred/",
        auth_type="api_key", api_key_env="FRED_API_KEY", polling_interval_sec=300,
        freshness_limit_sec=3600, trust_score=98,
    ),
    SourceDefinition(
        "fed_rss", "الاحتياطي الفيدرالي — الإعلانات والخطب", "Federal Reserve RSS", "Federal Reserve Board",
        "monetary", "rss", "https://www.federalreserve.gov/feeds/press_all.xml",
        "https://www.federalreserve.gov/feeds/feeds.htm", polling_interval_sec=300,
        freshness_limit_sec=1800, trust_score=100,
    ),
    SourceDefinition(
        "cftc", "هيئة تداول السلع الآجلة — COT", "CFTC Commitments of Traders", "CFTC",
        "flows", "json", "https://publicreporting.cftc.gov/resource/jun7-fc8e.json", "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm",
        auth_type="none", api_key_env=None, polling_interval_sec=21600,
        freshness_limit_sec=8 * 24 * 3600, trust_score=100,
    ),
    SourceDefinition(
        "treasury", "وزارة الخزانة الأمريكية", "U.S. Treasury", "U.S. Treasury",
        "cross_asset", "xml", "https://home.treasury.gov/sites/default/files/interest-rates",
        "https://home.treasury.gov/treasury-daily-interest-rate-xml-feed",
        auth_type="none", api_key_env=None, polling_interval_sec=900,
        freshness_limit_sec=7200, trust_score=100,
    ),
    SourceDefinition(
        "nyfed_rates", "بنك الاحتياطي الفيدرالي في نيويورك — معدلات مرجعية", "New York Fed Reference Rates", "Federal Reserve Bank of New York",
        "monetary", "json", "https://markets.newyorkfed.org/api/rates/all/latest.json",
        "https://markets.newyorkfed.org/static/docs/markets-api.html",
        auth_type="none", api_key_env=None, polling_interval_sec=3600,
        freshness_limit_sec=3 * 24 * 3600, trust_score=100,
    ),
    SourceDefinition(
        "census", "مكتب الإحصاء الأمريكي — المؤشرات الاقتصادية", "U.S. Census Economic Indicators", "U.S. Census Bureau",
        "macro", "api", "https://api.census.gov/data/timeseries/eits",
        "https://www.census.gov/data/developers/data-sets/economic-indicators.html",
        auth_type="api_key", api_key_env="CENSUS_API_KEY", polling_interval_sec=1800,
        freshness_limit_sec=14400, trust_score=100,
    ),
    SourceDefinition(
        "eia", "إدارة معلومات الطاقة الأمريكية", "U.S. Energy Information Administration", "EIA",
        "cross_asset", "api", "https://api.eia.gov/v2", "https://www.eia.gov/opendata/",
        auth_type="api_key", api_key_env="EIA_API_KEY", polling_interval_sec=3600,
        freshness_limit_sec=2 * 24 * 3600, trust_score=100,
    ),
    SourceDefinition(
        "cme_fedwatch", "توقعات الفائدة الضمنية من السوق — اختياري", "CME FedWatch / Fed Funds Probabilities (Optional)", "CME Group",
        "monetary", "api", None, "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html",
        auth_type="endpoint_config", api_key_env="CME_FEDWATCH_ENDPOINT", polling_interval_sec=300,
        freshness_limit_sec=900, trust_score=92, enabled=False,
        commercial_use_notes="اختياري/مرخص؛ Atlanta Fed MPT هو المسار المجاني الافتراضي. لا يتم scraping تلقائي.",
    ),
    SourceDefinition(
        "market_cross", "مزود سوق متعدد الأصول — اختياري", "Configured Cross-Asset Market Feed (Optional)", "Configured licensed provider",
        "cross_asset", "api", None, None, auth_type="endpoint_config", api_key_env="CROSS_ASSET_DATA_ENDPOINT",
        polling_interval_sec=60, freshness_limit_sec=300, trust_score=85, enabled=False,
        commercial_use_notes="اختياري للبيانات اللحظية المرخصة؛ MT5/FRED/Treasury/EIA هي المسارات المجانية الأساسية.",
    ),
    SourceDefinition(
        "world_bank", "البنك الدولي", "World Bank", "World Bank",
        "macro", "api", "https://api.worldbank.org/v2", "https://datahelpdesk.worldbank.org/knowledgebase/topics/125589-developer-information",
        polling_interval_sec=86400, freshness_limit_sec=45 * 24 * 3600, trust_score=98,
    ),
    SourceDefinition(
        "imf", "صندوق النقد الدولي", "International Monetary Fund", "IMF",
        "macro", "api", "https://www.imf.org/external/datamapper/api/v2", "https://www.imf.org/external/datamapper/api/",
        auth_type="none", api_key_env=None, polling_interval_sec=86400,
        freshness_limit_sec=45 * 24 * 3600, trust_score=98,
    ),
    SourceDefinition(
        "atlanta_mpt", "بنك أتلانتا الفيدرالي — متعقب احتمالات السوق", "Atlanta Fed Market Probability Tracker", "Federal Reserve Bank of Atlanta",
        "monetary", "text", "https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/research-and-data/data/market-probability-tracker/mpt_histdata.xlsx",
        "https://www.atlantafed.org/research-and-data/data/market-probability-tracker",
        auth_type="none", api_key_env=None, polling_interval_sec=86400,
        freshness_limit_sec=3 * 24 * 3600, trust_score=100,
    ),
    SourceDefinition(
        "gdelt", "GDELT — الأخبار والجيوسياسة العالمية", "GDELT DOC 2.0", "GDELT Project",
        "news", "json", "https://api.gdeltproject.org/api/v2/doc/doc",
        "https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/",
        auth_type="none", api_key_env=None, polling_interval_sec=300,
        freshness_limit_sec=1800, trust_score=75, storage_allowed=False,
    ),
    SourceDefinition(
        "gold_etf_iau", "iShares IAU — حيازات الذهب", "iShares Gold Trust (IAU)", "BlackRock iShares",
        "flows", "text", "https://www.ishares.com/us/products/239561/ishares-gold-trust",
        "https://www.ishares.com/us/products/239561/ishares-gold-trust",
        auth_type="none", api_key_env=None, polling_interval_sec=21600,
        freshness_limit_sec=3 * 24 * 3600, trust_score=95,
        commercial_use_notes="حيازات رسمية؛ لا تتحول اللقطة المنفردة إلى تدفق قبل توفر لقطة سابقة.",
    ),
    SourceDefinition(
        "gold_etf_gld", "SPDR GLD — حيازات الذهب", "SPDR Gold Shares (GLD)", "World Gold Trust Services",
        "flows", "text", "https://www.spdrgoldshares.com/usa/gld/",
        "https://www.spdrgoldshares.com/usa/gld/",
        auth_type="none", api_key_env=None, polling_interval_sec=21600,
        freshness_limit_sec=3 * 24 * 3600, trust_score=95,
        commercial_use_notes="حيازات رسمية؛ لا تتحول اللقطة المنفردة إلى تدفق قبل توفر لقطة سابقة.",
    ),
    SourceDefinition(
        "gold_etf_gldm", "SPDR GLDM — حيازات الذهب", "SPDR Gold MiniShares (GLDM)", "World Gold Trust Services",
        "flows", "text", "https://www.spdrgoldshares.com/usa/gldm/",
        "https://www.spdrgoldshares.com/usa/gldm/",
        auth_type="none", api_key_env=None, polling_interval_sec=21600,
        freshness_limit_sec=3 * 24 * 3600, trust_score=95,
        commercial_use_notes="حيازات رسمية؛ لا تتحول اللقطة المنفردة إلى تدفق قبل توفر لقطة سابقة.",
    ),
    SourceDefinition(
        "gold_etf", "تدفقات صناديق الذهب المتداولة", "Gold ETF Flows", "Configured licensed provider",
        "flows", "api", None, None, auth_type="bearer", api_key_env="GOLD_ETF_API_KEY",
        polling_interval_sec=3600, freshness_limit_sec=2 * 24 * 3600, trust_score=80,
        commercial_use_notes="يتطلب مصدرًا مرخصًا/مسموح التخزين وفق شروط المزود.",
    ),
    SourceDefinition(
        "central_bank_gold", "مشتريات البنوك المركزية من الذهب", "Central-Bank Gold Buying", "Configured licensed/official provider",
        "flows", "api", None, None, auth_type="bearer", api_key_env="CENTRAL_BANK_GOLD_API_KEY",
        polling_interval_sec=86400, freshness_limit_sec=45 * 24 * 3600, trust_score=85,
        commercial_use_notes="بيانات هيكلية؛ لا تستخدم كمحفز مباشر لإطار M5.",
    ),
    SourceDefinition(
        "market_flow", "بيانات العقود والتدفق السوقي", "Market Flow / OI / Volume / Options", "Configured market-data provider",
        "flows", "api", None, None, auth_type="bearer", api_key_env="MARKET_FLOW_API_KEY",
        polling_interval_sec=60, freshness_limit_sec=300, trust_score=80,
        commercial_use_notes="يتطلب مزود سوق فعليًا وحقوق استخدام مناسبة.",
    ),
    SourceDefinition(
        "newsapi", "مزود أخبار NewsAPI", "NewsAPI", "NewsAPI",
        "news", "api", "https://newsapi.org/v2", "https://newsapi.org/docs",
        auth_type="api_key", api_key_env="NEWSAPI_KEY", polling_interval_sec=60,
        freshness_limit_sec=900, trust_score=70, storage_allowed=False,
    ),
    SourceDefinition(
        "gnews", "مزود أخبار GNews", "GNews", "GNews",
        "news", "api", "https://gnews.io/api/v4", "https://gnews.io/docs/",
        auth_type="api_key", api_key_env="GNEWS_KEY", polling_interval_sec=60,
        freshness_limit_sec=900, trust_score=70, storage_allowed=False,
    ),
    SourceDefinition(
        "calendar_secondary", "مزود التقويم الاقتصادي الثانوي", "Secondary Economic Calendar", "Faireconomy/ForexFactory-style feed",
        "calendar", "json", "https://nfs.faireconomy.media/ff_calendar_thisweek.json", None,
        polling_interval_sec=300, freshness_limit_sec=900, trust_score=65, storage_allowed=True,
    ),
    SourceDefinition(
        # MT5 native economic calendar (CalendarValueHistory via the EA bridge).
        # Times arrive in TRADE SERVER time and are normalized to UTC with the
        # reported server offset. Highest trust: it is the broker's own feed.
        "calendar_mt5", "التقويم الاقتصادي من MetaTrader 5", "MT5 Native Economic Calendar", "MetaTrader 5 terminal",
        "calendar", "mt5_bridge", None, "https://www.mql5.com/en/docs/economic_calendar/calendarvaluehistory",
        polling_interval_sec=300, freshness_limit_sec=900, trust_score=95, storage_allowed=True,
    ),
    SourceDefinition(
        "news_secondary", "مصدر أخبار ثانوي", "Secondary News Source", "External publisher",
        "news", "api", None, None, polling_interval_sec=60, freshness_limit_sec=900,
        trust_score=60, storage_allowed=False,
    ),
)

SOURCE_BY_ID = {s.source_id: s for s in OFFICIAL_SOURCES}
