from __future__ import annotations

import hashlib
import io
import os
import re
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

from shared.fundamental import ProviderHealth
from shared.source_manager import managed_endpoint, managed_secret, managed_source_config

from ..url_safety import safe_error
from .source_base import FetchResult, SourceAdapter


def _dt(value: str | None) -> str | None:
    if not value:
        return None
    try:
        from email.utils import parsedate_to_datetime
        d = parsedate_to_datetime(value)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except Exception:
        return value


def _configured_or_result(source_id: str) -> tuple[dict[str, Any], FetchResult]:
    return (managed_source_config(source_id) or {}, FetchResult(source_id=source_id, success=False))


def _disabled(result: FetchResult, cfg: dict[str, Any]) -> bool:
    if cfg and not bool(cfg.get("enabled", True)):
        result.error_code = "DISABLED"
        result.error_message = "source disabled by user"
        result.health = ProviderHealth.OFFLINE
        result.finished_at = datetime.now(timezone.utc)
        return True
    return False


def _auth_parts(source_id: str, cfg: dict[str, Any]) -> tuple[dict[str, str], dict[str, Any]]:
    headers = {str(k): str(v) for k, v in (cfg.get("headers") or {}).items()}
    params = dict(cfg.get("query_params") or {})
    mode = str(cfg.get("auth_mode") or "none")
    secret = managed_secret(source_id, str(cfg.get("secret_env") or "") or None)
    name = str(cfg.get("secret_name") or "")
    if secret:
        if mode == "query" and name:
            params[name] = secret
        elif mode == "header" and name:
            headers[name] = secret
        elif mode == "bearer":
            headers["Authorization"] = f"Bearer {secret}"
    return headers, params


class BLSAdapter(SourceAdapter):
    source_id = "bls"
    api_key_env = None

    SERIES = {
        "CPI_ALL": "CUUR0000SA0",
        "CORE_CPI": "CUUR0000SA0L1E",
        "UNEMPLOYMENT": "LNS14000000",
        "AVG_HOURLY_EARNINGS": "CES0500000003",
        "NFP": "CES0000000001",
    }

    async def fetch(self) -> FetchResult:
        cfg, result = _configured_or_result(self.source_id)
        if _disabled(result, cfg):
            return result
        now = datetime.now(timezone.utc)
        body: dict[str, Any] = {
            "seriesid": list(self.SERIES.values()),
            "startyear": str(max(2000, now.year - 2)),
            "endyear": str(now.year),
        }
        key = managed_secret(self.source_id, "BLS_API_KEY")
        if key:
            body["registrationkey"] = key
        url = managed_endpoint(self.source_id, "https://api.bls.gov/publicAPI/v2/timeseries/data/")
        timeout = float(cfg.get("timeout_sec", 20))
        try:
            status, payload, latency, phash = await self._request_json("POST", url, json_body=body, timeout=timeout)
            reverse = {v: k for k, v in self.SERIES.items()}
            records: list[dict[str, Any]] = []
            for series in payload.get("Results", {}).get("series", []):
                code = reverse.get(series.get("seriesID"), series.get("seriesID", ""))
                for item in series.get("data", []):
                    if str(item.get("period", "")).startswith("M13"):
                        continue
                    try:
                        val = float(str(item.get("value", "")).replace(",", ""))
                    except ValueError:
                        continue
                    records.append({
                        "indicator_code": code, "series_id": series.get("seriesID"),
                        "year": item.get("year"), "period": item.get("period"),
                        "period_name": item.get("periodName"), "value": val,
                        "footnotes": item.get("footnotes", []),
                    })
            result.success, result.records = True, records
            result.http_status, result.latency_ms, result.payload_hash = status, latency, phash
            result.health = ProviderHealth.HEALTHY
        except Exception as exc:
            result.error_code, result.error_message = type(exc).__name__, safe_error(exc)
            result.health = ProviderHealth.DEGRADED
        result.finished_at = datetime.now(timezone.utc)
        return result


class BEAAdapter(SourceAdapter):
    """BEA connectivity adapter.

    R3 establishes a real authenticated BEA connection and persists health. It
    intentionally does not invent a generic macro mapping for all BEA tables;
    analysis_ready remains false until a table-specific normalization profile is
    configured/implemented.
    """
    source_id = "bea"

    async def fetch(self) -> FetchResult:
        cfg, result = _configured_or_result(self.source_id)
        if _disabled(result, cfg):
            return result
        key = managed_secret(self.source_id, "BEA_API_KEY")
        if not key:
            result.error_code, result.error_message = "CONFIG_REQUIRED", "BEA_API_KEY is not configured"
            result.health, result.finished_at = ProviderHealth.CONFIG_REQUIRED, datetime.now(timezone.utc)
            return result
        url = managed_endpoint(self.source_id, "https://apps.bea.gov/api/data/")
        timeout = float(cfg.get("timeout_sec", 20))
        try:
            status, payload, latency, phash = await self._request_json(
                "GET", url,
                params={"UserID": key, "method": "GETDATASETLIST", "ResultFormat": "JSON"},
                timeout=timeout,
            )
            datasets = payload.get("BEAAPI", {}).get("Results", {}).get("Dataset", [])
            if not isinstance(datasets, list):
                raise ValueError("BEA dataset list response is invalid")
            result.success = True
            result.records = [{"dataset_name": d.get("DatasetName"), "dataset_description": d.get("DatasetDescription")} for d in datasets]
            result.http_status, result.latency_ms, result.payload_hash = status, latency, phash
            result.health = ProviderHealth.HEALTHY
        except Exception as exc:
            result.error_code, result.error_message = type(exc).__name__, safe_error(exc)
            result.health = ProviderHealth.DEGRADED
        result.finished_at = datetime.now(timezone.utc)
        return result


class FREDAdapter(SourceAdapter):
    source_id = "fred"
    api_key_env = "FRED_API_KEY"

    SERIES = {
        "DGS2": "US2Y",
        "DGS10": "US10Y",
        "DFII10": "REAL_YIELD_10Y",
        "VIXCLS": "VIX",
        "DTWEXBGS": "BROAD_DOLLAR",
    }

    async def fetch(self) -> FetchResult:
        cfg, result = _configured_or_result(self.source_id)
        if _disabled(result, cfg):
            return result
        key = managed_secret(self.source_id, self.api_key_env)
        if not key:
            result.error_code = "CONFIG_REQUIRED"
            result.error_message = "FRED_API_KEY is not configured"
            result.health = ProviderHealth.CONFIG_REQUIRED
            result.finished_at = datetime.now(timezone.utc)
            return result
        base = managed_endpoint(self.source_id, "https://api.stlouisfed.org/fred").rstrip("/")
        timeout = float(cfg.get("timeout_sec", 20))
        records: list[dict[str, Any]] = []
        total_latency = 0.0
        hashes: list[str] = []
        try:
            for fred_id, code in self.SERIES.items():
                status, payload, latency, phash = await self._request_json(
                    "GET", f"{base}/series/observations",
                    params={"series_id": fred_id, "api_key": key, "file_type": "json", "sort_order": "desc", "limit": 100},
                    timeout=timeout,
                )
                total_latency += latency
                hashes.append(phash)
                for obs in payload.get("observations", []):
                    if obs.get("value") in {None, "."}:
                        continue
                    records.append({
                        "series_code": code, "source_series_id": fred_id,
                        "timestamp": f"{obs.get('date')}T00:00:00+00:00",
                        "value": float(obs["value"]),
                        "unit": "percent" if fred_id.startswith(("DGS", "DFII")) else "index",
                    })
            result.success, result.records = True, records
            result.http_status, result.latency_ms, result.payload_hash = 200, total_latency, "|".join(hashes)
            result.health = ProviderHealth.HEALTHY
        except Exception as exc:
            result.error_code, result.error_message = type(exc).__name__, safe_error(exc)
            result.health = ProviderHealth.DEGRADED
        result.finished_at = datetime.now(timezone.utc)
        return result


class FedRSSAdapter(SourceAdapter):
    source_id = "fed_rss"

    async def fetch(self) -> FetchResult:
        cfg, result = _configured_or_result(self.source_id)
        if _disabled(result, cfg):
            return result
        url = managed_endpoint(self.source_id, os.getenv("FED_RSS_URL", "https://www.federalreserve.gov/feeds/press_all.xml"))
        timeout = float(cfg.get("timeout_sec", 20))
        try:
            status, text, latency, phash = await self._request_text("GET", url, timeout=timeout)
            root = ET.fromstring(text)
            records: list[dict[str, Any]] = []
            for item in root.findall(".//item"):
                records.append({
                    "title": (item.findtext("title") or "").strip(),
                    "link": (item.findtext("link") or "").strip(),
                    "description": (item.findtext("description") or "").strip(),
                    "published_at": _dt(item.findtext("pubDate")),
                    "guid": (item.findtext("guid") or "").strip(),
                })
            result.success, result.records = True, records
            result.http_status, result.latency_ms, result.payload_hash = status, latency, phash
            result.health = ProviderHealth.HEALTHY
        except Exception as exc:
            result.error_code, result.error_message = type(exc).__name__, safe_error(exc)
            result.health = ProviderHealth.DEGRADED
        result.finished_at = datetime.now(timezone.utc)
        return result


class CFTCAdapter(SourceAdapter):
    source_id = "cftc"

    async def fetch(self) -> FetchResult:
        cfg, result = _configured_or_result(self.source_id)
        if _disabled(result, cfg):
            return result
        url = managed_endpoint(self.source_id, "https://publicreporting.cftc.gov/resource/jun7-fc8e.json")
        timeout = float(cfg.get("timeout_sec", 25))
        try:
            status, payload, latency, phash = await self._request_json(
                "GET", url,
                params={"$limit": 500, "$order": "report_date_as_yyyy_mm_dd DESC"}, timeout=timeout,
            )
            if not isinstance(payload, list):
                raise ValueError("CFTC response is not a list")
            records: list[dict[str, Any]] = []
            for row in payload:
                market = f"{row.get('commodity_name','')} {row.get('market_and_exchange_names','')}".upper()
                if "GOLD" not in market:
                    continue
                try:
                    long_v = float(row.get("noncomm_positions_long_all") or 0)
                    short_v = float(row.get("noncomm_positions_short_all") or 0)
                    oi = float(row.get("open_interest_all") or 0)
                except (TypeError, ValueError):
                    continue
                net = long_v - short_v
                crowding = (net / oi * 100.0) if oi else 0.0
                records.append({
                    "flow_type": "COT_GOLD_NONCOMM_NET",
                    "value": net,
                    "unit": "contracts",
                    "timestamp": row.get("report_date_as_yyyy_mm_dd"),
                    # COT positions are measured before publication. Use the
                    # actual fetch time as conservative known_at to avoid
                    # historical look-ahead from the report/as-of date.
                    "known_at": datetime.now(timezone.utc).isoformat(),
                    "frequency": "weekly", "native_horizon": "structural",
                    "flow_direction": "bullish" if net > 0 else "bearish" if net < 0 else "neutral",
                    "strength_score": min(100.0, abs(crowding) * 4.0),
                    "crowding_score": max(-100.0, min(100.0, crowding)),
                    "confirmation_score": 70.0, "freshness_score": 85.0, "quality_score": 100.0,
                    "market": row.get("market_and_exchange_names"),
                })
                break
            if not records:
                raise ValueError("no GOLD record found in current CFTC page")
            result.success, result.records = True, records
            result.http_status, result.latency_ms, result.payload_hash = status, latency, phash
            result.health = ProviderHealth.HEALTHY
        except Exception as exc:
            result.error_code, result.error_message = type(exc).__name__, safe_error(exc)
            result.health = ProviderHealth.DEGRADED
        result.finished_at = datetime.now(timezone.utc)
        return result


class TreasuryAdapter(SourceAdapter):
    source_id = "treasury"

    @staticmethod
    def _entries(text: str, source_id: str) -> list[dict[str, Any]]:
        root = ET.fromstring(text)
        out: list[dict[str, Any]] = []
        for entry in root.iter():
            if entry.tag.split("}")[-1] != "entry":
                continue
            values: dict[str, str] = {}
            for el in entry.iter():
                key = el.tag.split("}")[-1]
                if el.text and el.text.strip():
                    values[key] = el.text.strip()
            date = values.get("NEW_DATE") or values.get("updated") or values.get("title")
            for raw_key, code in (("BC_2YEAR", "US2Y"), ("BC_10YEAR", "US10Y"), ("TC_10YEAR", "REAL_YIELD_10Y")):
                val = values.get(raw_key)
                if val is None:
                    continue
                try:
                    f = float(val)
                except ValueError:
                    continue
                out.append({"series_code": code, "timestamp": date, "value": f, "unit": "percent", "source_series_id": raw_key, "source_id": source_id})
        return out

    async def fetch(self) -> FetchResult:
        cfg, result = _configured_or_result(self.source_id)
        if _disabled(result, cfg):
            return result
        base = managed_endpoint(self.source_id, "https://home.treasury.gov/sites/default/files/interest-rates").rstrip("/")
        timeout = float(cfg.get("timeout_sec", 25))
        nominal = f"{base}/yield.xml" if not base.endswith(".xml") else base
        real = f"{base}/real_yield.xml" if not base.endswith(".xml") else base.replace("yield.xml", "real_yield.xml")
        try:
            status1, text1, lat1, hash1 = await self._request_text("GET", nominal, timeout=timeout)
            status2, text2, lat2, hash2 = await self._request_text("GET", real, timeout=timeout)
            records = self._entries(text1, self.source_id) + self._entries(text2, self.source_id)
            # Treasury feeds are newest-first. Preserve latest and prior point so
            # cross-asset scoring receives an observed change rather than a fake 0.
            grouped: dict[str, list[dict[str, Any]]] = {}
            for row in records:
                grouped.setdefault(str(row["series_code"]), []).append(row)
            latest: dict[str, dict[str, Any]] = {}
            for code, rows in grouped.items():
                if not rows:
                    continue
                cur = dict(rows[0])
                if len(rows) > 1:
                    prev = rows[1]
                    change = float(cur["value"]) - float(prev["value"])
                    cur["change"] = change
                    cur["change_pct"] = change / max(abs(float(prev["value"])), 1e-12) * 100.0
                else:
                    cur["change"] = None
                    cur["change_pct"] = None
                cur["frequency"] = "daily"
                cur["native_horizon"] = "tactical"
                latest[code] = cur
            if "US10Y" not in latest and "REAL_YIELD_10Y" not in latest:
                raise ValueError("Treasury XML did not contain expected yield fields")
            result.success, result.records = True, list(latest.values())
            result.http_status, result.latency_ms, result.payload_hash = min(status1, status2), lat1 + lat2, f"{hash1}|{hash2}"
            result.health = ProviderHealth.HEALTHY
        except Exception as exc:
            result.error_code, result.error_message = type(exc).__name__, safe_error(exc)
            result.health = ProviderHealth.DEGRADED
        result.finished_at = datetime.now(timezone.utc)
        return result




class NewYorkFedRatesAdapter(SourceAdapter):
    """Official NY Fed reference-rate connectivity/data adapter (no API key)."""
    source_id = "nyfed_rates"

    async def fetch(self) -> FetchResult:
        cfg, result = _configured_or_result(self.source_id)
        if _disabled(result, cfg):
            return result
        url = managed_endpoint(self.source_id, "https://markets.newyorkfed.org/api/rates/all/latest.json")
        timeout = float(cfg.get("timeout_sec", 20))
        try:
            status, payload, latency, phash = await self._request_json("GET", url, timeout=timeout)
            rows = payload.get("refRates", []) if isinstance(payload, dict) else []
            records: list[dict[str, Any]] = []
            for row in rows:
                kind = str(row.get("type") or "").upper()
                if kind not in {"EFFR", "SOFR", "OBFR", "TGCR", "BGCR", "SOFRAI"}:
                    continue
                value = row.get("percentRate")
                if value is None and kind == "SOFRAI":
                    value = row.get("average30day")
                records.append({
                    "series_code": kind,
                    "timestamp": row.get("effectiveDate"),
                    "value": value,
                    "unit": "percent",
                    "source_series_id": kind,
                })
            if not records:
                raise ValueError("NY Fed response contained no recognized reference rates")
            result.success, result.records = True, records
            result.http_status, result.latency_ms, result.payload_hash = status, latency, phash
            result.health = ProviderHealth.HEALTHY
        except Exception as exc:
            result.error_code, result.error_message = type(exc).__name__, safe_error(exc)
            result.health = ProviderHealth.DEGRADED
        result.finished_at = datetime.now(timezone.utc)
        return result


class WorldBankAdapter(SourceAdapter):
    source_id = "world_bank"

    async def fetch(self) -> FetchResult:
        cfg, result = _configured_or_result(self.source_id)
        if _disabled(result, cfg):
            return result
        base = managed_endpoint(self.source_id, "https://api.worldbank.org/v2").rstrip("/")
        url = f"{base}/country/USA/indicator/NY.GDP.MKTP.KD.ZG"
        timeout = float(cfg.get("timeout_sec", 20))
        try:
            status, payload, latency, phash = await self._request_json(
                "GET", url, params={"format": "json", "mrv": 3, "per_page": 10}, timeout=timeout
            )
            rows = payload[1] if isinstance(payload, list) and len(payload) > 1 and isinstance(payload[1], list) else []
            records = [{
                "indicator_code": "WB_US_GDP_GROWTH",
                "year": row.get("date"),
                "value": row.get("value"),
                "unit": "percent",
                "country": row.get("countryiso3code") or "USA",
            } for row in rows if row.get("value") is not None]
            if not records:
                raise ValueError("World Bank returned no recent U.S. GDP growth observations")
            result.success, result.records = True, records
            result.http_status, result.latency_ms, result.payload_hash = status, latency, phash
            result.health = ProviderHealth.HEALTHY
        except Exception as exc:
            result.error_code, result.error_message = type(exc).__name__, safe_error(exc)
            result.health = ProviderHealth.DEGRADED
        result.finished_at = datetime.now(timezone.utc)
        return result


class IMFDataMapperAdapter(SourceAdapter):
    source_id = "imf"

    async def fetch(self) -> FetchResult:
        cfg, result = _configured_or_result(self.source_id)
        if _disabled(result, cfg):
            return result
        base = managed_endpoint(self.source_id, "https://www.imf.org/external/datamapper/api/v2").rstrip("/")
        url = f"{base}/NGDP_RPCH/USA"
        timeout = float(cfg.get("timeout_sec", 20))
        try:
            status, payload, latency, phash = await self._request_json("GET", url, timeout=timeout)
            values = payload.get("values", {}) if isinstance(payload, dict) else {}
            indicator = values.get("NGDP_RPCH", {}) if isinstance(values, dict) else {}
            usa = indicator.get("USA", {}) if isinstance(indicator, dict) else {}
            records = [{"indicator_code": "IMF_US_REAL_GDP_GROWTH", "year": y, "value": v, "unit": "percent"}
                       for y, v in (usa.items() if isinstance(usa, dict) else []) if v is not None]
            if not records:
                raise ValueError("IMF DataMapper response did not contain USA NGDP_RPCH observations")
            result.success, result.records = True, records[-5:]
            result.http_status, result.latency_ms, result.payload_hash = status, latency, phash
            result.health = ProviderHealth.HEALTHY
        except Exception as exc:
            result.error_code, result.error_message = type(exc).__name__, safe_error(exc)
            result.health = ProviderHealth.DEGRADED
        result.finished_at = datetime.now(timezone.utc)
        return result


class CensusEconomicIndicatorsAdapter(SourceAdapter):
    """Free-key Census API connectivity test using an official EITS dataset."""
    source_id = "census"

    async def fetch(self) -> FetchResult:
        cfg, result = _configured_or_result(self.source_id)
        if _disabled(result, cfg):
            return result
        key = managed_secret(self.source_id, "CENSUS_API_KEY")
        if not key:
            result.error_code, result.error_message = "CONFIG_REQUIRED", "CENSUS_API_KEY is not configured (free key)"
            result.health, result.finished_at = ProviderHealth.CONFIG_REQUIRED, datetime.now(timezone.utc)
            return result
        base = managed_endpoint(self.source_id, "https://api.census.gov/data/timeseries/eits").rstrip("/")
        url = f"{base}/hv"
        timeout = float(cfg.get("timeout_sec", 20))
        try:
            status, payload, latency, phash = await self._request_json(
                "GET", url,
                params={
                    "get": "cell_value,data_type_code,time_slot_id,category_code,seasonally_adj",
                    "time": "2004-04",
                    "key": key,
                },
                timeout=timeout,
            )
            if not isinstance(payload, list) or len(payload) < 2:
                raise ValueError("Census EITS response is invalid")
            result.success = True
            result.records = [{"rows_received": max(0, len(payload) - 1), "dataset": "eits/hv", "probe_period": "2004-Q4"}]
            result.http_status, result.latency_ms, result.payload_hash = status, latency, phash
            result.health = ProviderHealth.HEALTHY
        except Exception as exc:
            result.error_code, result.error_message = type(exc).__name__, safe_error(exc)
            result.health = ProviderHealth.DEGRADED
        result.finished_at = datetime.now(timezone.utc)
        return result


class EIAAdapter(SourceAdapter):
    """EIA v2 free-key connectivity adapter. Kept health-only until an oil normalization profile is enabled."""
    source_id = "eia"

    async def fetch(self) -> FetchResult:
        cfg, result = _configured_or_result(self.source_id)
        if _disabled(result, cfg):
            return result
        key = managed_secret(self.source_id, "EIA_API_KEY")
        if not key:
            result.error_code, result.error_message = "CONFIG_REQUIRED", "EIA_API_KEY is not configured (free key)"
            result.health, result.finished_at = ProviderHealth.CONFIG_REQUIRED, datetime.now(timezone.utc)
            return result
        base = managed_endpoint(self.source_id, "https://api.eia.gov/v2").rstrip("/")
        url = f"{base}/petroleum/pri/spt/data/"
        timeout = float(cfg.get("timeout_sec", 25))
        try:
            status, payload, latency, phash = await self._request_json(
                "GET", url,
                params={
                    "api_key": key,
                    "frequency": "daily",
                    "data[0]": "value",
                    "facets[series][]": "RWTC",
                    "sort[0][column]": "period",
                    "sort[0][direction]": "desc",
                    "length": 2,
                },
                timeout=timeout,
            )
            rows = payload.get("response", {}).get("data", []) if isinstance(payload, dict) else []
            cleaned = []
            for r in rows:
                if r.get("value") is None:
                    continue
                try:
                    cleaned.append({"series_code": "WTI", "timestamp": r.get("period"), "value": float(r.get("value")), "unit": r.get("units"), "frequency": "daily", "native_horizon": "tactical"})
                except (TypeError, ValueError):
                    continue
            records = cleaned
            if len(records) >= 2:
                change = records[0]["value"] - records[1]["value"]
                records[0]["change"] = change
                records[0]["change_pct"] = change / max(abs(records[1]["value"]), 1e-12) * 100.0
                records = [records[0]]
            elif records:
                records[0]["change"] = None
                records[0]["change_pct"] = None
            if not records:
                raise ValueError("EIA response contained no WTI observations")
            result.success, result.records = True, records
            result.http_status, result.latency_ms, result.payload_hash = status, latency, phash
            result.health = ProviderHealth.HEALTHY
        except Exception as exc:
            result.error_code, result.error_message = type(exc).__name__, safe_error(exc)
            result.health = ProviderHealth.DEGRADED
        result.finished_at = datetime.now(timezone.utc)
        return result


class AtlantaFedMPTAdapter(SourceAdapter):
    """Validates the official Atlanta Fed MPT historical workbook.

    R3.1 deliberately treats the workbook as connection/data-availability evidence
    only. It is not coerced into a Fed-probability score until the workbook schema
    is mapped and version-checked.
    """
    source_id = "atlanta_mpt"

    async def fetch(self) -> FetchResult:
        cfg, result = _configured_or_result(self.source_id)
        if _disabled(result, cfg):
            return result
        url = managed_endpoint(
            self.source_id,
            "https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/research-and-data/data/market-probability-tracker/mpt_histdata.xlsx",
        )
        timeout = float(cfg.get("timeout_sec", 30))
        started = time.perf_counter()
        try:
            from shared.http_client import new_client
            async with new_client(timeout=timeout, pin_dns=True, follow_redirects=False) as client:
                resp = await client.get(url)
            latency = (time.perf_counter() - started) * 1000.0
            raw = resp.content
            resp.raise_for_status()
            if not raw.startswith(b"PK"):
                raise ValueError("Atlanta Fed MPT response is not an XLSX workbook")
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                names = set(zf.namelist())
                if "xl/workbook.xml" not in names:
                    raise ValueError("Atlanta Fed MPT workbook structure is invalid")
                workbook = zf.read("xl/workbook.xml")
                sheet_count = workbook.count(b"<sheet ")
            result.success = True
            result.records = [{"workbook_bytes": len(raw), "sheet_count": int(sheet_count), "analysis_mapping": "health_only"}]
            result.http_status = resp.status_code
            result.latency_ms = latency
            result.payload_hash = hashlib.sha256(raw).hexdigest()
            result.health = ProviderHealth.HEALTHY
        except Exception as exc:
            result.error_code, result.error_message = type(exc).__name__, safe_error(exc)
            result.health = ProviderHealth.DEGRADED
        result.finished_at = datetime.now(timezone.utc)
        return result


class GDELTAdapter(SourceAdapter):
    source_id = "gdelt"

    async def fetch(self) -> FetchResult:
        cfg, result = _configured_or_result(self.source_id)
        if _disabled(result, cfg):
            return result
        url = managed_endpoint(self.source_id, "https://api.gdeltproject.org/api/v2/doc/doc")
        timeout = float(cfg.get("timeout_sec", 20))
        try:
            status, payload, latency, phash = await self._request_json(
                "GET", url,
                params={
                    "query": "(gold OR treasury OR federal reserve OR sanctions OR war)",
                    "mode": "artlist",
                    "format": "json",
                    "maxrecords": 10,
                    "timespan": "1h",
                    "sort": "datedesc",
                },
                timeout=timeout,
            )
            articles = payload.get("articles", []) if isinstance(payload, dict) else []
            result.success = True
            result.records = articles if isinstance(articles, list) else []
            result.http_status, result.latency_ms, result.payload_hash = status, latency, phash
            result.health = ProviderHealth.HEALTHY
        except Exception as exc:
            result.error_code, result.error_message = type(exc).__name__, safe_error(exc)
            result.health = ProviderHealth.DEGRADED
        result.finished_at = datetime.now(timezone.utc)
        return result


class GoldETFHoldingsProbeAdapter(SourceAdapter):
    """Official holdings-page probe; never manufactures a flow from one snapshot."""
    def __init__(self, source_id: str) -> None:
        self.source_id = source_id

    async def fetch(self) -> FetchResult:
        cfg, result = _configured_or_result(self.source_id)
        if _disabled(result, cfg):
            return result
        url = managed_endpoint(self.source_id, "")
        if not url:
            result.error_code, result.error_message = "CONFIG_REQUIRED", "holdings URL is not configured"
            result.health, result.finished_at = ProviderHealth.CONFIG_REQUIRED, datetime.now(timezone.utc)
            return result
        timeout = float(cfg.get("timeout_sec", 25))
        try:
            status, text, latency, phash = await self._request_text("GET", url, timeout=timeout)
            lower = text.lower()
            has_holdings_marker = ("ounces in trust" in lower or "total net asset value in the trust" in lower or "historical archive" in lower)
            if not has_holdings_marker:
                raise ValueError("official ETF page did not expose a recognizable holdings marker")
            ounces = None
            if self.source_id == "gold_etf_iau":
                m = re.search(r"Ounces in Trust.{0,500}?([0-9][0-9,]+\.[0-9]+)", text, re.I | re.S)
                if m:
                    try:
                        ounces = float(m.group(1).replace(",", ""))
                    except ValueError:
                        ounces = None
            result.success = True
            result.records = [{
                "fund": self.source_id,
                "holdings_ounces": ounces,
                "analysis_mapping": "holdings_snapshot_only",
                "note": "A single snapshot is not converted to ETF flow; a persisted prior snapshot is required.",
            }]
            result.http_status, result.latency_ms, result.payload_hash = status, latency, phash
            result.health = ProviderHealth.HEALTHY
        except Exception as exc:
            result.error_code, result.error_message = type(exc).__name__, safe_error(exc)
            result.health = ProviderHealth.DEGRADED
        result.finished_at = datetime.now(timezone.utc)
        return result


class ConfiguredJsonAdapter(SourceAdapter):
    """Managed JSON endpoint adapter with encrypted credential support.

    Records are accepted only for explicitly supported mapping profiles. A
    health-only custom source can be tested/monitored but is never fed into a
    scoring engine.
    """

    def __init__(self, source_id: str, endpoint_env: str | None = None) -> None:
        self.source_id = source_id
        self.api_key_env = endpoint_env
        self.endpoint_env = endpoint_env

    async def fetch(self) -> FetchResult:
        cfg, result = _configured_or_result(self.source_id)
        if _disabled(result, cfg):
            return result
        fallback = os.getenv(self.endpoint_env, "").strip() if self.endpoint_env else ""
        url = managed_endpoint(self.source_id, fallback)
        if not url:
            result.error_code = "CONFIG_REQUIRED"
            result.error_message = f"endpoint is not configured for {self.source_id}"
            result.health = ProviderHealth.CONFIG_REQUIRED
            result.finished_at = datetime.now(timezone.utc)
            return result
        headers, params = _auth_parts(self.source_id, cfg)
        timeout = float(cfg.get("timeout_sec", 15))
        if str(cfg.get("auth_mode", "none")) != "none" and not managed_secret(self.source_id, str(cfg.get("secret_env") or "") or None) and not bool(cfg.get("secret_optional", True)):
            result.error_code, result.error_message = "CONFIG_REQUIRED", "API credential is not configured"
            result.health, result.finished_at = ProviderHealth.CONFIG_REQUIRED, datetime.now(timezone.utc)
            return result
        try:
            status, payload, latency, phash = await self._request_json("GET", url, params=params, headers=headers, timeout=timeout)
            if isinstance(payload, list):
                records = payload
            elif isinstance(payload, dict):
                records = payload.get("data", payload.get("results", payload.get("records", [])))
            else:
                records = []
            if not isinstance(records, list):
                raise ValueError("configured endpoint must return list or {data/results/records:[...]} payload")
            result.success, result.records = True, records
            result.http_status, result.latency_ms, result.payload_hash = status, latency, phash
            result.health = ProviderHealth.HEALTHY
        except Exception as exc:
            result.error_code, result.error_message = type(exc).__name__, safe_error(exc)
            result.health = ProviderHealth.DEGRADED
        result.finished_at = datetime.now(timezone.utc)
        return result

class ProbeAdapter(SourceAdapter):
    """Connectivity-only managed source. Never produces analysis records."""
    def __init__(self, source_id: str) -> None:
        self.source_id = source_id

    async def fetch(self) -> FetchResult:
        cfg, result = _configured_or_result(self.source_id)
        if _disabled(result, cfg):
            return result
        url = managed_endpoint(self.source_id, "")
        if not url:
            result.error_code, result.error_message = "CONFIG_REQUIRED", "endpoint is not configured"
            result.health, result.finished_at = ProviderHealth.CONFIG_REQUIRED, datetime.now(timezone.utc)
            return result
        headers, params = _auth_parts(self.source_id, cfg)
        secret = managed_secret(self.source_id, str(cfg.get("secret_env") or "") or None)
        if str(cfg.get("auth_mode", "none")) != "none" and not secret and not bool(cfg.get("secret_optional", True)):
            result.error_code, result.error_message = "CONFIG_REQUIRED", "API credential is not configured"
            result.health, result.finished_at = ProviderHealth.CONFIG_REQUIRED, datetime.now(timezone.utc)
            return result
        timeout = float(cfg.get("timeout_sec", 15))
        try:
            transport = str(cfg.get("transport", "api"))
            if transport in {"rss", "xml", "text"}:
                status, text, latency, phash = await self._request_text("GET", url, params=params, headers=headers, timeout=timeout)
                result.records = []
                if transport in {"rss", "xml"}:
                    ET.fromstring(text)
            else:
                status, payload, latency, phash = await self._request_json("GET", url, params=params, headers=headers, timeout=timeout)
                result.records = []
                _ = payload
            result.success = True
            result.http_status, result.latency_ms, result.payload_hash = status, latency, phash
            result.health = ProviderHealth.HEALTHY
        except Exception as exc:
            result.error_code, result.error_message = type(exc).__name__, safe_error(exc)
            result.health = ProviderHealth.DEGRADED
        result.finished_at = datetime.now(timezone.utc)
        return result
