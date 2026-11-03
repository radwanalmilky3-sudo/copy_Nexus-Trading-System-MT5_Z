"""Persistent source connection manager for Fundamental Intelligence.

Non-secret connection metadata is stored as JSON. Secrets are write-only from the
API and are encrypted with Windows DPAPI (CurrentUser) when running on Windows.
On non-Windows systems persistent secret storage is intentionally disabled; env
variables remain supported so tests/dev never fall back to plaintext secrets.
"""
from __future__ import annotations

import base64
import ctypes
import ipaddress
import json
import os
import re
import socket
import threading
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_SOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,63}$")
_ALLOWED_AUTH = {"none", "query", "header", "bearer"}
_ALLOWED_TRANSPORT = {"api", "json", "rss", "xml", "text", "sdmx"}
_ALLOWED_MAPPING = {"health_only", "cross_asset", "flows"}

# Central metadata used by the Settings UI and connection tester. The runtime
# source registry stays authoritative for scoring/trust; these records describe
# how a source can be configured and tested.
BUILTIN_SOURCE_MANAGER: dict[str, dict[str, Any]] = {
    "bls": {
        "name_ar": "مكتب إحصاءات العمل الأمريكي", "name_en": "U.S. Bureau of Labor Statistics",
        "organization": "BLS", "source_tier": "FREE_OFFICIAL", "cost_label": "مجاني رسمي",
        "category": "macro", "transport": "api",
        "endpoint": "https://api.bls.gov/publicAPI/v2/timeseries/data/",
        "documentation_url": "https://www.bls.gov/developers/",
        "auth_mode": "query", "secret_env": "BLS_API_KEY", "secret_name": "registrationkey",
        "secret_optional": True, "polling_interval_sec": 900, "freshness_limit_sec": 7200,
        "timeout_sec": 20, "analysis_mapping": "health_only", "analysis_ready": True,
    },
    "bea": {
        "name_ar": "مكتب التحليل الاقتصادي الأمريكي", "name_en": "U.S. Bureau of Economic Analysis",
        "organization": "BEA", "source_tier": "FREE_API_KEY_REQUIRED", "cost_label": "مفتاح مجاني",
        "category": "macro", "transport": "api",
        "endpoint": "https://apps.bea.gov/api/data/",
        "documentation_url": "https://apps.bea.gov/api/",
        "auth_mode": "query", "secret_env": "BEA_API_KEY", "secret_name": "UserID",
        "secret_optional": False, "polling_interval_sec": 1800, "freshness_limit_sec": 14400,
        "timeout_sec": 20, "analysis_mapping": "health_only", "analysis_ready": False,
    },
    "fred": {
        "name_ar": "قاعدة بيانات الاحتياطي الفيدرالي الاقتصادية", "name_en": "FRED",
        "organization": "Federal Reserve Bank of St. Louis", "source_tier": "FREE_API_KEY_REQUIRED", "cost_label": "مفتاح مجاني",
        "category": "cross_asset", "transport": "api",
        "endpoint": "https://api.stlouisfed.org/fred",
        "documentation_url": "https://fred.stlouisfed.org/docs/api/fred/",
        "auth_mode": "query", "secret_env": "FRED_API_KEY", "secret_name": "api_key",
        "secret_optional": False, "polling_interval_sec": 300, "freshness_limit_sec": 3600,
        "timeout_sec": 20, "analysis_mapping": "cross_asset", "analysis_ready": True,
    },
    "fed_rss": {
        "name_ar": "الاحتياطي الفيدرالي — بيانات السياسة النقدية", "name_en": "Federal Reserve RSS",
        "organization": "Federal Reserve Board", "source_tier": "FREE_OFFICIAL", "cost_label": "مجاني رسمي",
        "category": "monetary", "transport": "rss",
        "endpoint": "https://www.federalreserve.gov/feeds/press_all.xml",
        "documentation_url": "https://www.federalreserve.gov/feeds/feeds.htm",
        "auth_mode": "none", "secret_env": None, "secret_name": None,
        "secret_optional": True, "polling_interval_sec": 300, "freshness_limit_sec": 1800,
        "timeout_sec": 20, "analysis_mapping": "health_only", "analysis_ready": True,
    },
    "cftc": {
        "name_ar": "هيئة تداول السلع الآجلة — COT", "name_en": "CFTC Commitments of Traders",
        "organization": "CFTC", "source_tier": "FREE_OFFICIAL", "cost_label": "مجاني رسمي",
        "category": "flows", "transport": "json",
        "endpoint": "https://publicreporting.cftc.gov/resource/jun7-fc8e.json",
        "documentation_url": "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm",
        "auth_mode": "none", "secret_env": None, "secret_name": None,
        "secret_optional": True, "polling_interval_sec": 21600, "freshness_limit_sec": 8 * 24 * 3600,
        "timeout_sec": 25, "analysis_mapping": "flows", "analysis_ready": True,
    },
    "treasury": {
        "name_ar": "وزارة الخزانة الأمريكية", "name_en": "U.S. Treasury",
        "organization": "U.S. Treasury", "source_tier": "FREE_OFFICIAL", "cost_label": "مجاني رسمي",
        "category": "cross_asset", "transport": "xml",
        "endpoint": "https://home.treasury.gov/sites/default/files/interest-rates",
        "documentation_url": "https://home.treasury.gov/treasury-daily-interest-rate-xml-feed",
        "auth_mode": "none", "secret_env": None, "secret_name": None,
        "secret_optional": True, "polling_interval_sec": 900, "freshness_limit_sec": 7200,
        "timeout_sec": 25, "analysis_mapping": "cross_asset", "analysis_ready": True,
    },
    "nyfed_rates": {
        "name_ar": "بنك الاحتياطي الفيدرالي في نيويورك — معدلات مرجعية", "name_en": "New York Fed Reference Rates",
        "organization": "Federal Reserve Bank of New York", "source_tier": "FREE_OFFICIAL", "cost_label": "مجاني رسمي",
        "category": "monetary", "transport": "json",
        "endpoint": "https://markets.newyorkfed.org/api/rates/all/latest.json",
        "documentation_url": "https://markets.newyorkfed.org/static/docs/markets-api.html",
        "auth_mode": "none", "secret_env": None, "secret_name": None,
        "secret_optional": True, "polling_interval_sec": 3600, "freshness_limit_sec": 3 * 24 * 3600,
        "timeout_sec": 20, "analysis_mapping": "health_only", "analysis_ready": False,
    },
    "census": {
        "name_ar": "مكتب الإحصاء الأمريكي — المؤشرات الاقتصادية", "name_en": "U.S. Census Economic Indicators",
        "organization": "U.S. Census Bureau", "source_tier": "FREE_API_KEY_REQUIRED", "cost_label": "مفتاح مجاني",
        "category": "macro", "transport": "api",
        "endpoint": "https://api.census.gov/data/timeseries/eits",
        "documentation_url": "https://www.census.gov/data/developers/data-sets/economic-indicators.html",
        "auth_mode": "query", "secret_env": "CENSUS_API_KEY", "secret_name": "key",
        "secret_optional": False, "polling_interval_sec": 1800, "freshness_limit_sec": 14400,
        "timeout_sec": 20, "analysis_mapping": "health_only", "analysis_ready": False,
    },
    "eia": {
        "name_ar": "إدارة معلومات الطاقة الأمريكية", "name_en": "U.S. Energy Information Administration",
        "organization": "EIA", "source_tier": "FREE_API_KEY_REQUIRED", "cost_label": "مفتاح مجاني",
        "category": "cross_asset", "transport": "api",
        "endpoint": "https://api.eia.gov/v2",
        "documentation_url": "https://www.eia.gov/opendata/",
        "auth_mode": "query", "secret_env": "EIA_API_KEY", "secret_name": "api_key",
        "secret_optional": False, "polling_interval_sec": 3600, "freshness_limit_sec": 2 * 24 * 3600,
        "timeout_sec": 25, "analysis_mapping": "cross_asset", "analysis_ready": True,
    },
    "cme_fedwatch": {
        "name_ar": "CME FedWatch (اختياري)", "name_en": "CME FedWatch (Optional)",
        "organization": "CME Group", "source_tier": "PAID_OPTIONAL", "cost_label": "اختياري/مرخص",
        "category": "monetary", "transport": "json", "endpoint": "", "endpoint_env": "CME_FEDWATCH_ENDPOINT",
        "documentation_url": "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html",
        "auth_mode": "none", "secret_env": None, "secret_name": None, "secret_optional": True, "enabled": False,
        "polling_interval_sec": 300, "freshness_limit_sec": 900, "timeout_sec": 15,
        "analysis_mapping": "health_only", "analysis_ready": False,
    },
    "market_cross": {
        "name_ar": "مزود سوق متعدد الأصول (اختياري)", "name_en": "Cross-Asset Market Feed (Optional)",
        "organization": "User-selected provider", "source_tier": "PAID_OPTIONAL", "cost_label": "اختياري/مدفوع",
        "category": "cross_asset", "transport": "json", "endpoint": "", "endpoint_env": "CROSS_ASSET_DATA_ENDPOINT",
        "documentation_url": "", "auth_mode": "none", "secret_env": None, "secret_name": None, "secret_optional": True, "enabled": False,
        "polling_interval_sec": 60, "freshness_limit_sec": 300, "timeout_sec": 15,
        "analysis_mapping": "cross_asset", "analysis_ready": True,
    },
    "world_bank": {
        "name_ar": "البنك الدولي", "name_en": "World Bank",
        "organization": "World Bank", "source_tier": "FREE_OFFICIAL", "cost_label": "مجاني رسمي",
        "category": "macro", "transport": "api",
        "endpoint": "https://api.worldbank.org/v2",
        "documentation_url": "https://datahelpdesk.worldbank.org/knowledgebase/topics/125589-developer-information",
        "auth_mode": "none", "secret_env": None, "secret_name": None,
        "secret_optional": True, "polling_interval_sec": 86400, "freshness_limit_sec": 45 * 24 * 3600,
        "timeout_sec": 20, "analysis_mapping": "health_only", "analysis_ready": False,
    },
    "imf": {
        "name_ar": "صندوق النقد الدولي", "name_en": "International Monetary Fund",
        "organization": "IMF", "source_tier": "FREE_OFFICIAL", "cost_label": "مجاني رسمي",
        "category": "macro", "transport": "api",
        "endpoint": "https://www.imf.org/external/datamapper/api/v2",
        "documentation_url": "https://www.imf.org/external/datamapper/api/",
        "auth_mode": "none", "secret_env": None, "secret_name": None,
        "secret_optional": True, "polling_interval_sec": 86400, "freshness_limit_sec": 45 * 24 * 3600,
        "timeout_sec": 20, "analysis_mapping": "health_only", "analysis_ready": False,
    },
    "atlanta_mpt": {
        "name_ar": "بنك أتلانتا الفيدرالي — متعقب احتمالات السوق", "name_en": "Atlanta Fed Market Probability Tracker",
        "organization": "Federal Reserve Bank of Atlanta", "source_tier": "FREE_OFFICIAL", "cost_label": "مجاني رسمي",
        "category": "monetary", "transport": "text",
        "endpoint": "https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/research-and-data/data/market-probability-tracker/mpt_histdata.xlsx",
        "documentation_url": "https://www.atlantafed.org/research-and-data/data/market-probability-tracker",
        "auth_mode": "none", "secret_env": None, "secret_name": None,
        "secret_optional": True, "polling_interval_sec": 86400, "freshness_limit_sec": 3 * 24 * 3600,
        "timeout_sec": 30, "analysis_mapping": "health_only", "analysis_ready": False,
    },
    "gdelt": {
        "name_ar": "GDELT — الأخبار والجيوسياسة العالمية", "name_en": "GDELT DOC 2.0",
        "organization": "GDELT Project", "source_tier": "FREE_PUBLIC", "cost_label": "مجاني عام",
        "category": "news", "transport": "json",
        "endpoint": "https://api.gdeltproject.org/api/v2/doc/doc",
        "documentation_url": "https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/",
        "auth_mode": "none", "secret_env": None, "secret_name": None,
        "secret_optional": True, "polling_interval_sec": 300, "freshness_limit_sec": 1800,
        "timeout_sec": 20, "analysis_mapping": "health_only", "analysis_ready": True,
    },
    "gold_etf_iau": {
        "name_ar": "iShares IAU — حيازات الذهب", "name_en": "iShares Gold Trust (IAU)",
        "organization": "BlackRock iShares", "source_tier": "FREE_OFFICIAL_HOLDINGS", "cost_label": "مجاني — حيازات رسمية",
        "category": "flows", "transport": "text",
        "endpoint": "https://www.ishares.com/us/products/239561/ishares-gold-trust",
        "documentation_url": "https://www.ishares.com/us/products/239561/ishares-gold-trust",
        "auth_mode": "none", "secret_env": None, "secret_name": None,
        "secret_optional": True, "polling_interval_sec": 21600, "freshness_limit_sec": 3 * 24 * 3600,
        "timeout_sec": 25, "analysis_mapping": "health_only", "analysis_ready": False,
    },
    "gold_etf_gld": {
        "name_ar": "SPDR GLD — حيازات الذهب", "name_en": "SPDR Gold Shares (GLD)",
        "organization": "World Gold Trust Services", "source_tier": "FREE_OFFICIAL_HOLDINGS", "cost_label": "مجاني — حيازات رسمية",
        "category": "flows", "transport": "text",
        "endpoint": "https://www.spdrgoldshares.com/usa/gld/",
        "documentation_url": "https://www.spdrgoldshares.com/usa/gld/",
        "auth_mode": "none", "secret_env": None, "secret_name": None,
        "secret_optional": True, "polling_interval_sec": 21600, "freshness_limit_sec": 3 * 24 * 3600,
        "timeout_sec": 25, "analysis_mapping": "health_only", "analysis_ready": False,
    },
    "gold_etf_gldm": {
        "name_ar": "SPDR GLDM — حيازات الذهب", "name_en": "SPDR Gold MiniShares (GLDM)",
        "organization": "World Gold Trust Services", "source_tier": "FREE_OFFICIAL_HOLDINGS", "cost_label": "مجاني — حيازات رسمية",
        "category": "flows", "transport": "text",
        "endpoint": "https://www.spdrgoldshares.com/usa/gldm/",
        "documentation_url": "https://www.spdrgoldshares.com/usa/gldm/",
        "auth_mode": "none", "secret_env": None, "secret_name": None,
        "secret_optional": True, "polling_interval_sec": 21600, "freshness_limit_sec": 3 * 24 * 3600,
        "timeout_sec": 25, "analysis_mapping": "health_only", "analysis_ready": False,
    },
    "gold_etf": {
        "name_ar": "مزود تدفقات صناديق الذهب التجاري (اختياري)", "name_en": "Commercial Gold ETF Flow Feed (Optional)",
        "organization": "User-selected provider", "source_tier": "PAID_OPTIONAL", "cost_label": "اختياري/مدفوع",
        "category": "flows", "transport": "json", "endpoint": "", "endpoint_env": "GOLD_ETF_DATA_ENDPOINT",
        "documentation_url": "", "auth_mode": "bearer", "secret_env": "GOLD_ETF_API_KEY",
        "secret_name": "Authorization", "secret_optional": True, "enabled": False,
        "polling_interval_sec": 3600, "freshness_limit_sec": 2 * 24 * 3600,
        "timeout_sec": 20, "analysis_mapping": "flows", "analysis_ready": True,
    },
    "central_bank_gold": {
        "name_ar": "احتياطيات الذهب الرسمية — مسار متوسط/طويل الأجل", "name_en": "Official Central-Bank Gold Reserves",
        "organization": "IMF / official statistical sources", "source_tier": "FREE_OFFICIAL_DELAYED", "cost_label": "مجاني لكن متأخر",
        "category": "flows", "transport": "sdmx", "endpoint": "",
        "documentation_url": "https://data.imf.org/en/Resource-Pages/IMF-API",
        "auth_mode": "none", "secret_env": None, "secret_name": None, "secret_optional": True,
        "enabled": False, "polling_interval_sec": 86400, "freshness_limit_sec": 90 * 24 * 3600,
        "timeout_sec": 30, "analysis_mapping": "health_only", "analysis_ready": False,
    },
    "market_flow": {
        "name_ar": "Order Flow / Options لحظي مؤسسي (اختياري)", "name_en": "Institutional Market Flow / Options (Optional)",
        "organization": "User-selected market-data provider", "source_tier": "PAID_OPTIONAL", "cost_label": "اختياري/مدفوع",
        "category": "flows", "transport": "json", "endpoint": "", "endpoint_env": "MARKET_FLOW_DATA_ENDPOINT",
        "documentation_url": "", "auth_mode": "bearer", "secret_env": "MARKET_FLOW_API_KEY",
        "secret_name": "Authorization", "secret_optional": True, "enabled": False,
        "polling_interval_sec": 60, "freshness_limit_sec": 300,
        "timeout_sec": 15, "analysis_mapping": "flows", "analysis_ready": True,
    },
    "newsapi": {
        "name_ar": "NewsAPI (اختياري)", "name_en": "NewsAPI",
        "organization": "NewsAPI", "source_tier": "PAID_OPTIONAL", "cost_label": "اختياري",
        "category": "news", "transport": "api", "endpoint": "https://newsapi.org/v2",
        "documentation_url": "https://newsapi.org/docs", "auth_mode": "query", "secret_env": "NEWSAPI_KEY",
        "secret_name": "apiKey", "secret_optional": False, "polling_interval_sec": 60,
        "freshness_limit_sec": 900, "timeout_sec": 15, "analysis_mapping": "health_only", "analysis_ready": True,
    },
    "gnews": {
        "name_ar": "GNews (اختياري)", "name_en": "GNews",
        "organization": "GNews", "source_tier": "PAID_OPTIONAL", "cost_label": "اختياري",
        "category": "news", "transport": "api", "endpoint": "https://gnews.io/api/v4",
        "documentation_url": "https://gnews.io/docs/", "auth_mode": "query", "secret_env": "GNEWS_KEY",
        "secret_name": "token", "secret_optional": False, "polling_interval_sec": 60,
        "freshness_limit_sec": 900, "timeout_sec": 15, "analysis_mapping": "health_only", "analysis_ready": True,
    },
    "calendar_secondary": {
        "name_ar": "مزود التقويم الاقتصادي الثانوي", "name_en": "Secondary Economic Calendar",
        "organization": "Faireconomy/ForexFactory-style feed", "source_tier": "FREE_PUBLIC", "cost_label": "مجاني عام",
        "category": "calendar", "transport": "json",
        "endpoint": "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
        "documentation_url": "", "auth_mode": "none", "secret_env": None, "secret_name": None,
        "secret_optional": True, "polling_interval_sec": 300, "freshness_limit_sec": 900,
        "timeout_sec": 20, "analysis_mapping": "health_only", "analysis_ready": True,
    },
    "news_secondary": {
        "name_ar": "مصدر أخبار ثانوي", "name_en": "Secondary News Source",
        "organization": "External publisher", "source_tier": "CUSTOM_OPTIONAL", "cost_label": "حسب المزود",
        "category": "news", "transport": "json", "endpoint": "",
        "documentation_url": "", "auth_mode": "none", "secret_env": None, "secret_name": None,
        "secret_optional": True, "enabled": False, "polling_interval_sec": 60, "freshness_limit_sec": 900,
        "timeout_sec": 15, "analysis_mapping": "health_only", "analysis_ready": False,
    },
}

def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _manager_dir() -> Path:
    explicit = os.getenv("NEXUS_SOURCE_MANAGER_DIR", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    if os.name == "nt":
        root = Path(os.getenv("LOCALAPPDATA") or Path.home())
        return root / "NexusTrader" / "source_manager"
    return Path.home() / ".nexus_trader" / "source_manager"


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[_DATA_BLOB, Any]:
    buf = ctypes.create_string_buffer(data)
    return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))), buf


def _dpapi_protect(value: str) -> str:
    if os.name != "nt":
        raise RuntimeError("persistent secret storage requires Windows DPAPI; use environment variables on this platform")
    in_blob, in_buf = _blob(value.encode("utf-8"))
    out_blob = _DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = [ctypes.POINTER(_DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DATA_BLOB)]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    ok = crypt32.CryptProtectData(ctypes.byref(in_blob), ctypes.c_wchar_p("NexusTrader Source Secret"), None, None, None, 0, ctypes.byref(out_blob))
    if not ok:
        raise ctypes.WinError()
    try:
        raw = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return base64.b64encode(raw).decode("ascii")
    finally:
        kernel32.LocalFree(out_blob.pbData)
        _ = in_buf


def _dpapi_unprotect(value: str) -> str:
    if os.name != "nt":
        raise RuntimeError("persistent secret storage requires Windows DPAPI")
    raw = base64.b64decode(value.encode("ascii"))
    in_blob, in_buf = _blob(raw)
    out_blob = _DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p, ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DATA_BLOB)]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    ok = crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob))
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData).decode("utf-8")
    finally:
        kernel32.LocalFree(out_blob.pbData)
        _ = in_buf


def validate_endpoint(endpoint: str) -> str:
    endpoint = endpoint.strip()
    if not endpoint:
        return ""
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("endpoint must be an http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError("endpoint credentials are not allowed")
    return endpoint


def resolve_public_ip(host: str) -> str:
    """Resolve one globally routable address for a pinned HTTP connection.

    The caller must use the returned address for the TCP connect while keeping
    the original hostname for TLS SNI and certificate verification.  Resolving
    and selecting the address in the same transport operation prevents a DNS
    answer from being re-resolved between validation and connect.
    """
    value = host.strip().strip("[]")
    try:
        candidates = [ipaddress.ip_address(value)]
    except ValueError:
        infos = socket.getaddrinfo(value, None, type=socket.SOCK_STREAM)
        candidates = []
        for info in infos:
            try:
                candidates.append(ipaddress.ip_address(info[4][0]))
            except ValueError:
                continue
    for address in candidates:
        if address.is_global:
            return str(address)
    raise ValueError("endpoint host does not resolve to a global address")


def normalize_source_id(value: str) -> str:
    sid = value.strip().lower()
    if not _SOURCE_ID_RE.fullmatch(sid):
        raise ValueError("source_id must match [a-z0-9][a-z0-9_.-]{1,63}")
    return sid


class SourceManagerStore:
    def __init__(self, directory: Path | None = None) -> None:
        self.dir = directory or _manager_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.dir / "sources.json"
        self.secret_path = self.dir / "secrets.dpapi.json"
        self._lock = threading.RLock()

    @property
    def secret_backend(self) -> str:
        return "windows_dpapi_current_user" if os.name == "nt" else "env_only"

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except Exception:
            return {}

    @staticmethod
    def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)

    def overrides(self) -> dict[str, dict[str, Any]]:
        raw = self._read_json(self.config_path)
        values = raw.get("sources", {})
        return values if isinstance(values, dict) else {}

    def custom_ids(self) -> list[str]:
        return sorted([sid for sid, cfg in self.overrides().items() if isinstance(cfg, dict) and cfg.get("custom")])

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        sid = normalize_source_id(source_id)
        base = BUILTIN_SOURCE_MANAGER.get(sid)
        override = self.overrides().get(sid)
        if base is None and not isinstance(override, dict):
            return None
        result: dict[str, Any] = {
            "source_id": sid,
            "official": base is not None,
            "custom": base is None,
            "removable": base is None,
            "enabled": True,
        }
        if base:
            result.update(base)
        if isinstance(override, dict):
            result.update(override)
        if not str(result.get("endpoint") or "").strip() and result.get("endpoint_env"):
            env_endpoint = os.getenv(str(result.get("endpoint_env")), "").strip()
            if env_endpoint:
                result["endpoint"] = env_endpoint
        result["source_id"] = sid
        result["official"] = base is not None
        result["custom"] = base is None
        result["removable"] = base is None
        result["enabled"] = bool(result.get("enabled", True))
        result["secret_configured"] = self.has_secret(sid, result.get("secret_env"))
        result["secret_backend"] = self.secret_backend
        return result

    def list_sources(self) -> list[dict[str, Any]]:
        ids = set(BUILTIN_SOURCE_MANAGER) | set(self.overrides())
        return [cfg for sid in sorted(ids) if (cfg := self.get_source(sid)) is not None]

    def upsert_source(self, source_id: str, values: dict[str, Any], *, custom: bool | None = None) -> dict[str, Any]:
        sid = normalize_source_id(source_id)
        with self._lock:
            current = self.overrides()
            existing = current.get(sid, {}) if isinstance(current.get(sid), dict) else {}
            is_builtin = sid in BUILTIN_SOURCE_MANAGER
            is_custom = (not is_builtin) if custom is None else bool(custom)
            if is_builtin and is_custom:
                raise ValueError("built-in source cannot be converted to custom")
            clean = dict(existing)
            allowed = {
                "name_ar", "name_en", "organization", "category", "transport", "endpoint", "endpoint_env", "documentation_url",
                "enabled", "auth_mode", "secret_env", "secret_name", "secret_optional", "polling_interval_sec",
                "freshness_limit_sec", "timeout_sec", "analysis_mapping", "analysis_ready", "headers", "query_params",
            }
            for key in allowed:
                if key in values:
                    clean[key] = values[key]
            if "endpoint" in clean:
                clean["endpoint"] = validate_endpoint(str(clean.get("endpoint") or ""))
            if clean.get("transport", "json") not in _ALLOWED_TRANSPORT:
                raise ValueError("unsupported transport")
            if clean.get("auth_mode", "none") not in _ALLOWED_AUTH:
                raise ValueError("unsupported auth_mode")
            if clean.get("analysis_mapping", "health_only") not in _ALLOWED_MAPPING:
                raise ValueError("unsupported analysis_mapping")
            clean["polling_interval_sec"] = max(15, min(int(clean.get("polling_interval_sec", 300)), 7 * 24 * 3600))
            clean["freshness_limit_sec"] = max(30, min(int(clean.get("freshness_limit_sec", 900)), 90 * 24 * 3600))
            clean["timeout_sec"] = max(3, min(int(clean.get("timeout_sec", 15)), 60))
            clean["custom"] = is_custom
            clean["updated_at"] = utc_iso()
            if is_custom:
                for required in ("name_ar", "name_en", "category", "transport"):
                    if not str(clean.get(required, "")).strip():
                        raise ValueError(f"{required} is required for a custom source")
            current[sid] = clean
            self._atomic_write(self.config_path, {"version": 1, "updated_at": utc_iso(), "sources": current})
        out = self.get_source(sid)
        assert out is not None
        return out

    def delete_source(self, source_id: str) -> None:
        sid = normalize_source_id(source_id)
        if sid in BUILTIN_SOURCE_MANAGER:
            raise ValueError("official sources cannot be deleted; disable them instead")
        with self._lock:
            current = self.overrides()
            current.pop(sid, None)
            self._atomic_write(self.config_path, {"version": 1, "updated_at": utc_iso(), "sources": current})
            self.clear_secret(sid)

    def _secrets(self) -> dict[str, str]:
        raw = self._read_json(self.secret_path)
        values = raw.get("secrets", {})
        return values if isinstance(values, dict) else {}

    def set_secret(self, source_id: str, secret: str) -> None:
        sid = normalize_source_id(source_id)
        if not secret:
            raise ValueError("secret cannot be empty")
        if os.name != "nt":
            raise RuntimeError("persistent secret storage is disabled on non-Windows; configure the source environment variable")
        with self._lock:
            values = self._secrets()
            values[sid] = _dpapi_protect(secret)
            self._atomic_write(self.secret_path, {"version": 1, "updated_at": utc_iso(), "backend": self.secret_backend, "secrets": values})

    def clear_secret(self, source_id: str) -> None:
        sid = normalize_source_id(source_id)
        with self._lock:
            values = self._secrets()
            if sid in values:
                values.pop(sid, None)
                self._atomic_write(self.secret_path, {"version": 1, "updated_at": utc_iso(), "backend": self.secret_backend, "secrets": values})

    def get_secret(self, source_id: str, env_name: str | None = None) -> str:
        sid = normalize_source_id(source_id)
        values = self._secrets()
        encrypted = values.get(sid)
        if encrypted and os.name == "nt":
            try:
                return _dpapi_unprotect(encrypted)
            except Exception:
                pass
        if env_name:
            return os.getenv(env_name, "").strip()
        cfg = self.get_source(sid)
        candidate = str((cfg or {}).get("secret_env") or "")
        return os.getenv(candidate, "").strip() if candidate else ""

    def has_secret(self, source_id: str, env_name: str | None = None) -> bool:
        sid = normalize_source_id(source_id)
        if sid in self._secrets():
            return True
        if env_name and os.getenv(env_name, "").strip():
            return True
        base = BUILTIN_SOURCE_MANAGER.get(sid, {})
        env = str(base.get("secret_env") or "")
        return bool(env and os.getenv(env, "").strip())


_STORE: SourceManagerStore | None = None


def source_manager_store() -> SourceManagerStore:
    global _STORE
    if _STORE is None:
        _STORE = SourceManagerStore()
    return _STORE


def managed_source_config(source_id: str) -> dict[str, Any] | None:
    return source_manager_store().get_source(source_id)


def managed_secret(source_id: str, env_name: str | None = None) -> str:
    return source_manager_store().get_secret(source_id, env_name)


def managed_endpoint(source_id: str, fallback: str = "") -> str:
    cfg = managed_source_config(source_id) or {}
    return str(cfg.get("endpoint") or fallback).strip()


def managed_enabled(source_id: str, default: bool = True) -> bool:
    cfg = managed_source_config(source_id)
    return default if cfg is None else bool(cfg.get("enabled", default))
