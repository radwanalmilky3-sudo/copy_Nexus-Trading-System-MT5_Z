from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from shared.fundamental import (
    DataOrigin,
    FundamentalDomain,
    FreshnessState,
    GoldDirection,
    PredictionStage,
    ProviderHealth,
)
from shared.models import CalendarEvent, NewsItem

from ..social_sentiment import _finbert_score, _get_finbert
from .adapters import (
    AtlantaFedMPTAdapter,
    BEAAdapter,
    BLSAdapter,
    CFTCAdapter,
    CensusEconomicIndicatorsAdapter,
    ConfiguredJsonAdapter,
    EIAAdapter,
    FREDAdapter,
    FedRSSAdapter,
    GDELTAdapter,
    GoldETFHoldingsProbeAdapter,
    IMFDataMapperAdapter,
    NewYorkFedRatesAdapter,
    ProbeAdapter,
    TreasuryAdapter,
    WorldBankAdapter,
)
from .asset_impact import AssetImpactEngine
from .blackout import TIMING_FIELDS, BlackoutEngine
from .bootstrap_v5 import asset_factor_profile_records, asset_records, indicator_catalog_records, knowledge_seed
from .engines import (
    CrossAssetEngine,
    FlowsEngine,
    FundamentalFusionEngine,
    GeopoliticalEngine,
    GoldImpactEngine,
    MacroEngine,
    MonetaryEngine,
)
from .explanations import ArabicExplanationEngine
from .news_intelligence import NewsIntelligenceEngine, build_story_cluster_record
from .indicator_catalog import INDICATOR_AR
from .ticker import NewsTickerEngine
from .outcome_collector_v61 import AssetOutcomeCollector
from .normalization import (
    calendar_event_record,
    calendar_to_macro,
    fed_rss_to_monetary,
    indicator_code,
    news_article_record,
    stable_event_id,
)
from .source_registry import OFFICIAL_SOURCES, SOURCE_BY_ID
from shared.source_manager import managed_enabled, managed_source_config, source_manager_store

log = structlog.get_logger("nexus_news.fundamental.runtime")
UTC = timezone.utc


def _utcnow() -> datetime:
    return datetime.now(UTC)


def merge_news_meta(previous: Any, update: dict[str, Any]) -> dict[str, Any]:
    """Merge a news-pipeline meta update over the previous snapshot.

    first_available_at is sticky: once recorded it is never overwritten by a
    later poll, so the UI can show when data first became available even after
    subsequent empty or failed polls.
    """
    merged: dict[str, Any] = dict(previous) if isinstance(previous, dict) else {}
    merged.update(update)
    if not merged.get("first_available_at"):
        merged["first_available_at"] = (
            update.get("last_success_at") or update.get("polled_at") or merged.get("last_success_at")
        )
    return merged


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat() if value.tzinfo else value.replace(tzinfo=UTC).isoformat()
    return str(value)


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def _sentiment_label(score: float) -> str:
    if score > 0.12:
        return "positive"
    if score < -0.12:
        return "negative"
    return "neutral"


def _calendar_timing_fields(event: CalendarEvent) -> dict[str, Any]:
    """Additive Phase-4 pass-through (event -> blackout decision).

    Reads the C1 timing/provenance fields off the calendar model only when the
    model actually defines them; absent attributes yield {} so legacy payloads
    reach BlackoutEngine exactly as before.
    """
    out: dict[str, Any] = {}
    for name in TIMING_FIELDS:
        if hasattr(event, name):
            value = getattr(event, name)
            if value is not None:
                out[name] = value
    return out


_GEO_KEYWORDS: dict[str, tuple[str, ...]] = {
    "war": ("war", "warfare", "invasion", "missile", "airstrike", "attack"),
    "conflict": ("conflict", "clash", "hostilities", "fighting"),
    "escalation": ("escalat", "mobilization", "retaliat", "strike"),
    "sanctions": ("sanction", "embargo", "export ban", "asset freeze"),
    "energy_shock": ("oil shock", "pipeline", "strait", "oil supply", "gas supply"),
    "sovereign_risk": ("default", "sovereign", "debt crisis", "credit downgrade"),
    "financial_stress": ("bank run", "bank failure", "liquidity crisis", "financial stress"),
    "global_crisis": ("global crisis", "emergency", "systemic risk"),
    "deescalation": ("ceasefire", "truce", "peace talks", "de-escalat"),
}


class FundamentalRuntime:
    """Canonical live bridge: sources -> normalization -> five domains -> fusion -> gold.

    Redis is the live state plane. DuckDB persistence is performed only through
    nexus-data's internal API so nexus-data remains the single DuckDB writer.
    Missing source data is surfaced as UNAVAILABLE/DEGRADED; it is never
    converted to a neutral measurement or demo data.
    """

    version = "1.2.0-v6.1-r3.1-free-first"

    def __init__(self, redis: Any) -> None:
        self.redis = redis
        self.data_url = os.getenv("NEXUS_DATA_URL", "http://127.0.0.1:9001").rstrip("/")
        self.internal_secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
        self._client = httpx.AsyncClient(timeout=15.0)
        self._blackout_engine = BlackoutEngine()
        self._macro_engine = MacroEngine()
        self._monetary_engine = MonetaryEngine()
        self._cross_engine = CrossAssetEngine()
        self._geo_engine = GeopoliticalEngine()
        self._flows_engine = FlowsEngine()
        self._fusion_engine = FundamentalFusionEngine()
        self._gold_engine = GoldImpactEngine()
        self._explain_engine = ArabicExplanationEngine()
        self._asset_profiles = asset_factor_profile_records()
        self._asset_impact_engine = AssetImpactEngine(self._asset_profiles)
        self._news_intelligence = NewsIntelligenceEngine()
        self._ticker_engine = NewsTickerEngine()
        self._ticker_state: list[dict[str, Any]] = []
        self._outcome_collector = AssetOutcomeCollector(self._client, self.data_url, self._persist)

        self._calendar: list[CalendarEvent] = []
        # Persist-dedupe state: event_id -> value signature already written.
        # The web poll re-runs on_calendar every ~5 min and the MT5 bridge
        # re-sends the merged set; without dedupe every pass re-POSTs 100+
        # records (~0.3s each = minutes of blocking HTTP) — observed
        # 2026-11-12 as ingest latency >60s, nexus-api 502 forward timeouts
        # and EA WebRequest read-timeout (1003).
        self._persisted_calendar: dict[str, tuple] = {}
        self._calendar_macro_cache: dict[str, dict] = {}
        self._news: list[NewsItem] = []
        self._macro_records: list[dict[str, Any]] = []
        self._macro_official_records: list[dict[str, Any]] = []
        self._monetary_records: list[dict[str, Any]] = []
        self._cross_records: list[dict[str, Any]] = []
        self._geo_records: list[dict[str, Any]] = []
        self._flow_records: list[dict[str, Any]] = []
        self._source_health: dict[str, dict[str, Any]] = {}
        self._news_analysis: dict[str, dict[str, Any]] = {}
        self._story_seen: dict[str, set[str]] = {}
        self._latest_asset_impacts: list[dict[str, Any]] = []
        self._blackout: dict[str, Any] = BlackoutEngine.degraded(
            "Calendar has not completed a successful scan",
            "لم يكتمل فحص التقويم الاقتصادي بنجاح بعد؛ تم اعتماد حالة متدهورة احترازيًا.",
        )
        self._latest_gold: dict[str, Any] | None = None
        self._last_fetch: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._source_manager = source_manager_store()

        # R3.1 extends V6.1 without replacing its asset/ticker/outcome runtime.
        # Free official adapters are primary; paid/configured feeds stay optional.
        self._adapters = {
            "bls": BLSAdapter(),
            "bea": BEAAdapter(),
            "fred": FREDAdapter(),
            "fed_rss": FedRSSAdapter(),
            "cftc": CFTCAdapter(),
            "treasury": TreasuryAdapter(),
            "nyfed_rates": NewYorkFedRatesAdapter(),
            "census": CensusEconomicIndicatorsAdapter(),
            "eia": EIAAdapter(),
            "world_bank": WorldBankAdapter(),
            "imf": IMFDataMapperAdapter(),
            "atlanta_mpt": AtlantaFedMPTAdapter(),
            "gdelt": GDELTAdapter(),
            "gold_etf_iau": GoldETFHoldingsProbeAdapter("gold_etf_iau"),
            "gold_etf_gld": GoldETFHoldingsProbeAdapter("gold_etf_gld"),
            "gold_etf_gldm": GoldETFHoldingsProbeAdapter("gold_etf_gldm"),
            "cme_fedwatch": ConfiguredJsonAdapter("cme_fedwatch", "CME_FEDWATCH_ENDPOINT"),
            "market_cross": ConfiguredJsonAdapter("market_cross", "CROSS_ASSET_DATA_ENDPOINT"),
            "gold_etf": ConfiguredJsonAdapter("gold_etf", "GOLD_ETF_DATA_ENDPOINT"),
            "central_bank_gold": ConfiguredJsonAdapter("central_bank_gold", "CENTRAL_BANK_GOLD_ENDPOINT"),
            "market_flow": ConfiguredJsonAdapter("market_flow", "MARKET_FLOW_DATA_ENDPOINT"),
        }

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def blackout(self) -> dict[str, Any]:
        return self._blackout

    @property
    def source_health(self) -> list[dict[str, Any]]:
        return list(self._source_health.values())

    async def initialize(self) -> None:
        await self._publish_json("nexus:fundamental:blackout", self._blackout, ttl=3600)
        await self._publish_json("nexus:fundamental:sources:health", [], ttl=3600)
        for source in OFFICIAL_SOURCES:
            cfg = managed_source_config(source.source_id) or {}
            record = source.as_record()
            if cfg.get("endpoint"):
                record["base_endpoint"] = cfg.get("endpoint")
            record["enabled"] = bool(cfg.get("enabled", source.enabled))
            await self._persist_source(record)
            if not record["enabled"]:
                self._set_source_health(source.source_id, ProviderHealth.OFFLINE, "المصدر معطل بواسطة المستخدم من إدارة المصادر.")
            elif source.source_id not in self._adapters and source.source_id not in {"newsapi", "gnews", "calendar_secondary", "news_secondary"}:
                required = source.api_key_env or f"CONNECTOR_{source.source_id.upper()}"
                self._set_source_health(
                    source.source_id,
                    ProviderHealth.CONFIG_REQUIRED,
                    f"CONFIG_REQUIRED: المصدر مسجل لكن موصله الحي غير مفعّل. المطلوب: {required}.",
                )
        await self._sync_custom_sources()
        await self._seed_v5_governance()
        try:
            raw_ticker = await self.redis.get("nexus:news:ticker:active")
            restored = json.loads(raw_ticker) if raw_ticker else []
            self._ticker_state = restored if isinstance(restored, list) else []
        except Exception:
            self._ticker_state = []
        self._set_news_provider_initial_health()
        await self._publish_source_health()
        await self.recompute(reason="startup")

    async def _sync_custom_sources(self) -> None:
        """Load user-managed custom sources without granting implicit scoring rights."""
        for cfg in self._source_manager.list_sources():
            sid = str(cfg.get("source_id") or "")
            if not sid or not cfg.get("custom"):
                continue
            await self._persist_source({
                "source_id": sid,
                "name_ar": cfg.get("name_ar") or sid,
                "name_en": cfg.get("name_en") or sid,
                "organization": cfg.get("organization") or "Custom source",
                "category": cfg.get("category") or "custom",
                "transport": cfg.get("transport") or "json",
                "base_endpoint": cfg.get("endpoint") or None,
                "documentation_url": cfg.get("documentation_url") or None,
                "auth_type": cfg.get("auth_mode") or "none",
                "api_key_env": cfg.get("secret_env") or None,
                "polling_interval_sec": cfg.get("polling_interval_sec", 300),
                "freshness_limit_sec": cfg.get("freshness_limit_sec", 900),
                "rate_limit_per_min": None,
                "provider_priority": 200,
                "fallback_group": None,
                "trust_score": 50.0,
                "license_name": None,
                "storage_allowed": True,
                "redistribution_allowed": False,
                "commercial_use_notes": "User-managed source. Analysis use requires an explicit mapping profile.",
                "enabled": bool(cfg.get("enabled", True)),
                "health_state": "unknown",
            })
            if sid not in self._adapters:
                mapping = str(cfg.get("analysis_mapping") or "health_only")
                self._adapters[sid] = ConfiguredJsonAdapter(sid) if mapping in {"flows", "cross_asset"} else ProbeAdapter(sid)
            if not bool(cfg.get("enabled", True)):
                self._set_source_health(sid, ProviderHealth.OFFLINE, "المصدر المخصص معطل بواسطة المستخدم.")

    async def _seed_v5_governance(self) -> None:
        """Seed deterministic metadata only; never inserts fabricated market observations."""
        for row in indicator_catalog_records():
            await self._persist("economic_indicator_catalog", row)
        for row in asset_records():
            if not await self._persist("asset_registry", row):
                asset_id = str(row.get("asset_id") or "unknown")
                raise RuntimeError(f"fundamental bootstrap could not persist asset_registry row: {asset_id}")
        for row in asset_factor_profile_records():
            await self._persist("asset_factor_profiles", row)
        sources, claims = knowledge_seed()
        for row in sources:
            await self._persist("fundamental_knowledge_sources", row)
        for row in claims:
            await self._persist("fundamental_knowledge_claims", row)

    def _set_news_provider_initial_health(self) -> None:
        for sid in ("newsapi", "gnews"):
            cfg = managed_source_config(sid) or {}
            if not bool(cfg.get("enabled", True)):
                self._set_source_health(sid, ProviderHealth.OFFLINE, "المصدر معطل بواسطة المستخدم.")
            elif bool(cfg.get("secret_configured")):
                self._set_source_health(sid, ProviderHealth.UNKNOWN, "المصدر مضبوط وينتظر أول فحص ناجح.")
            else:
                self._set_source_health(sid, ProviderHealth.CONFIG_REQUIRED, "المفتاح غير مضبوط؛ المصدر اختياري ولن تُختلق أخبار بديلة.")
        if managed_enabled("gdelt", True):
            self._set_source_health("gdelt", ProviderHealth.UNKNOWN, "المصدر المجاني ينتظر أول فحص ناجح.")
        if managed_enabled("calendar_secondary", True):
            self._set_source_health("calendar_secondary", ProviderHealth.UNKNOWN, "ينتظر أول فحص للتقويم الاقتصادي.")
        else:
            self._set_source_health("calendar_secondary", ProviderHealth.OFFLINE, "المصدر معطل بواسطة المستخدم.")

    async def _publish_json(self, key: str, value: Any, *, ttl: int = 900) -> None:
        await self.redis.set(key, json.dumps(_jsonable(value), ensure_ascii=False, default=str), ex=ttl)

    async def _publish_news_meta(self, update: dict[str, Any]) -> None:
        """Publish pipeline meta (last/first availability, errors) for the API truth envelope."""
        previous: Any = None
        try:
            raw = await self.redis.get("nexus:news:meta")
            previous = json.loads(raw) if raw else None
        except Exception:
            previous = None
        merged = merge_news_meta(previous, update)
        await self._publish_json("nexus:news:meta", merged, ttl=24 * 3600)

    async def on_news_empty_poll(self) -> None:
        """A successful poll that returned no headlines is 'empty', not 'unavailable'."""
        await self._publish_news_meta({
            "polled_at": _utcnow().isoformat(),
            "item_count": 0,
            "degraded": False,
            "last_error": None,
        })

    async def _persist_source(self, source: dict[str, Any]) -> bool:
        return await self._post_data("/api/data/fundamental/source", {"source": source})

    async def _persist(self, table: str, record: dict[str, Any]) -> bool:
        clean = {k: _jsonable(v) for k, v in record.items()}
        return await self._post_data("/api/data/fundamental/record", {"table": table, "record": clean})

    async def _post_data(self, path: str, payload: dict[str, Any]) -> bool:
        if not self.internal_secret:
            log.error("fundamental.persistence_disabled", reason="NEXUS_INTERNAL_API_SECRET missing")
            return False
        # Boot-order race (seen 2026-11-06): this service starts in parallel
        # with nexus-data, so the first bootstrap persists can hit
        # "All connection attempts failed" while :9001 is still binding.
        # A connection error is transient by definition — retry it a bounded
        # number of times (~8s total). HTTP >=400 responses are NOT retried:
        # they are real rejections and must fail exactly as before.
        attempts = 5
        backoff_sec = 2.0
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                resp = await self._client.post(
                    self.data_url + path,
                    json=payload,
                    headers={"X-Nexus-Internal-Secret": self.internal_secret},
                )
                if resp.status_code >= 400:
                    log.warning("fundamental.persistence_failed", path=path, status=resp.status_code, body=resp.text[:300])
                    return False
                return True
            except Exception as exc:
                last_error = exc
                if attempt < attempts:
                    log.warning(
                        "fundamental.persistence_retry",
                        path=path,
                        attempt=attempt,
                        next_backoff_sec=backoff_sec,
                        error=str(exc),
                    )
                    await asyncio.sleep(backoff_sec)
        log.warning("fundamental.persistence_unavailable", path=path, error=str(last_error))
        return False

    def _set_source_health(
        self,
        source_id: str,
        health: ProviderHealth,
        description_ar: str,
        *,
        latency_ms: float | None = None,
        received: int = 0,
        accepted: int = 0,
        success: bool | None = None,
    ) -> None:
        definition = SOURCE_BY_ID.get(source_id)
        managed = managed_source_config(source_id) or {}
        now = _utcnow().isoformat()
        old = self._source_health.get(source_id, {})
        self._source_health[source_id] = {
            "source_id": source_id,
            "name_ar": managed.get("name_ar") or (definition.name_ar if definition else source_id),
            "name_en": managed.get("name_en") or (definition.name_en if definition else source_id),
            "health": health.value,
            "health_description_ar": description_ar,
            "last_success_at": now if success is True else old.get("last_success_at"),
            "last_failure_at": now if success is False else old.get("last_failure_at"),
            "latency_ms": latency_ms,
            "freshness": "fresh" if health == ProviderHealth.HEALTHY else "unavailable" if health in {ProviderHealth.CONFIG_REQUIRED, ProviderHealth.OFFLINE} else "degraded",
            "origin": "real" if health == ProviderHealth.HEALTHY else "unknown",
            "records_received": received,
            "records_accepted": accepted,
        }

    async def _publish_source_health(self) -> None:
        payload = sorted(self.source_health, key=lambda x: x["source_id"])
        await self._publish_json("nexus:fundamental:sources:health", payload, ttl=3600)

    async def on_news(self, items: list[NewsItem]) -> list[NewsItem]:
        """Enrich live headlines once and apply deterministic relevance before domain use.

        Provider lineage and finance relevance are deterministic.  FinBERT is a
        supporting sentiment feature only and never determines asset direction.
        """
        async with self._lock:
            self._news = list(items[:100])
            finbert_available = (await _get_finbert()) is not None
            enriched: list[NewsItem] = []
            geo_records: list[dict[str, Any]] = []
            batch_cluster_sources: dict[str, set[str]] = {}
            batch_cluster_counts: dict[str, int] = {}
            analyses: dict[str, dict[str, Any]] = {}

            # First pass: deterministic classification/cluster counts.
            for item in self._news:
                provider_id = str(getattr(item, "provider_id", "") or "news_secondary")
                source_def = SOURCE_BY_ID.get(provider_id)
                source_trust = float(source_def.trust_score if source_def else 60.0)
                pre = self._news_intelligence.analyze(item, source_trust=source_trust, seen_count=0)
                publisher_key = str(getattr(item, "source", "") or provider_id).strip().lower()
                batch_cluster_sources.setdefault(pre.story_cluster_id, set()).add(publisher_key)
                batch_cluster_counts[pre.story_cluster_id] = batch_cluster_counts.get(pre.story_cluster_id, 0) + 1

            for item in self._news:
                provider_id = str(getattr(item, "provider_id", "") or "news_secondary")
                source_def = SOURCE_BY_ID.get(provider_id)
                source_trust = float(source_def.trust_score if source_def else 60.0)
                pre = self._news_intelligence.analyze(item, source_trust=source_trust, seen_count=0)
                prior_sources = self._story_seen.setdefault(pre.story_cluster_id, set())
                seen_count = len(prior_sources)
                analysis = self._news_intelligence.analyze(item, source_trust=source_trust, seen_count=seen_count)
                publisher_key = str(getattr(item, "source", "") or provider_id).strip().lower()
                prior_sources.add(publisher_key)
                ad = analysis.as_dict()
                # independent source count is batch/runtime evidence, not an LLM inference
                # and is consumed by ticker voice policy for geopolitical alerts.
                analyses[analysis.fingerprint] = ad
                analyses[item.headline] = ad

                if finbert_available:
                    score = float(await _finbert_score(item.headline))
                    item.finbert_score = score
                    item.sentiment = _sentiment_label(score)

                article = news_article_record(item)
                storage_allowed = bool(source_def and source_def.storage_allowed)
                independent_count = len(batch_cluster_sources.get(analysis.story_cluster_id, set()) | prior_sources)
                source_count = batch_cluster_counts.get(analysis.story_cluster_id, 1)
                ad["independent_source_count"] = independent_count
                ad["source_count"] = source_count

                # Commercial/noise headlines are never admitted to the geopolitical
                # engine.  Financial relevance is required in addition to keywords.
                geo = None
                if not analysis.is_commercial_noise and analysis.financial_relevance >= 35.0:
                    geo = self._headline_geopolitics(item, article)
                    if geo:
                        geo["source_consensus_score"] = min(100.0, 35.0 + 20.0 * max(0, independent_count - 1))
                        geo["independent_source_count"] = independent_count
                        geo["confidence"] = min(90.0, 35.0 + 12.0 * independent_count + 0.20 * analysis.source_quality)

                # Respect retention/licensing: live Redis may contain the provider
                # snapshot, while persistent article/cluster text is stored only
                # where the source contract permits it.
                if storage_allowed:
                    await self._persist("news_articles", article)
                    cluster = build_story_cluster_record(
                        item,
                        analysis,
                        source_id=provider_id,
                        source_count=source_count,
                        independent_source_count=independent_count,
                    )
                    await self._persist("news_story_clusters", cluster)
                    analysis_id = stable_event_id("nlp", article["article_id"], "finbert-v2")
                    await self._persist("news_nlp_analysis", {
                        "analysis_id": analysis_id,
                        "article_id": article["article_id"],
                        "finbert_label": item.sentiment if finbert_available else "unavailable",
                        "finbert_score": float(item.finbert_score) if finbert_available else None,
                        "gold_relevance": float(analysis.asset_relevance.get("XAUUSD", 0.0)),
                        "topic": analysis.topic,
                        "event_type": analysis.event_type,
                        "economic_relevance": analysis.financial_relevance,
                        "geopolitical_severity": geo.get("severity_score", 0.0) if geo else 0.0,
                        "safe_haven_score": geo.get("safe_haven_score", 0.0) if geo else 0.0,
                        "novelty_score": analysis.novelty_score,
                        "surprise_language_score": 65.0 if any(k in item.headline.lower() for k in ("breaking", "surprise", "shock", "unexpected")) else 20.0,
                        "model_name": "ProsusAI/finbert" if finbert_available else "unavailable",
                        "model_version": "runtime",
                        "analyzed_at": _utcnow(),
                    })

                if geo:
                    geo_records.append(geo)
                    if storage_allowed:
                        await self._persist_geo_event(item, geo)
                enriched.append(item)

            self._news_analysis = analyses
            self._geo_records = geo_records[-100:]
            providers_used = {str(getattr(x, "provider_id", "") or "news_secondary") for x in enriched}
            for sid in ("newsapi", "gnews"):
                if sid in providers_used:
                    count = sum(1 for x in enriched if str(getattr(x, "provider_id", "")) == sid)
                    self._set_source_health(sid, ProviderHealth.HEALTHY, "تم جلب أخبار حقيقية من المصدر بنجاح.", received=count, accepted=count, success=True)

            payload: list[dict[str, Any]] = []
            for item in enriched:
                dto = self._news_dto(item, finbert_available)
                a = analyses.get(item.headline, {})
                dto.update({
                    "topic": a.get("topic"),
                    "event_type": a.get("event_type"),
                    "severity": a.get("severity"),
                    "novelty_score": a.get("novelty_score"),
                    "financial_relevance": a.get("financial_relevance"),
                    "asset_relevance": a.get("asset_relevance"),
                    "story_cluster_id": a.get("story_cluster_id"),
                    "is_commercial_noise": a.get("is_commercial_noise", False),
                })
                payload.append(dto)
            await self._publish_json("nexus:news:latest", payload, ttl=max(120, int(os.getenv("NEWS_POLL_SEC", "30")) * 4))
            await self._publish_news_meta({
                "polled_at": _utcnow().isoformat(),
                "last_success_at": _utcnow().isoformat(),
                "item_count": len(payload),
                "degraded": False,
                "last_error": None,
            })
            await self._publish_source_health()
            await self.recompute(reason="news")
            return enriched

    async def on_news_failure(self, error: Exception) -> None:
        # Do not replace the previous snapshot with demo data. Keep last real snapshot but mark it stale/degraded.
        log.warning("fundamental.news_degraded", error=str(error))
        for sid in ("newsapi", "gnews"):
            if os.getenv("NEWSAPI_KEY" if sid == "newsapi" else "GNEWS_KEY", "").strip():
                self._set_source_health(sid, ProviderHealth.DEGRADED, f"فشل آخر جلب للأخبار: {error}", success=False)
        await self._publish_news_meta({
            "polled_at": _utcnow().isoformat(),
            "degraded": True,
            "last_error": str(error)[:500],
        })
        await self._publish_source_health()

    def mt5_events(self) -> list:
        """MT5-sourced events currently held in memory (web poll preserves them)."""
        return [e for e in self._calendar if e.source == "calendar_mt5"]

    async def on_calendar(self, events: list[CalendarEvent]) -> None:
        async with self._lock:
            self._calendar = sorted(events, key=lambda x: x.timestamp)
            event_dicts = [
                calendar_event_record(e)
                | {"timestamp": e.timestamp, "impact": e.impact, "event_name": e.event_name}
                | _calendar_timing_fields(e)
                for e in self._calendar
            ]
            self._blackout = self._blackout_engine.evaluate(event_dicts)
            await self._publish_json("nexus:fundamental:blackout", self._blackout, ttl=max(600, int(os.getenv("CALENDAR_POLL_SEC", "300")) * 4))
            await self._publish_json("nexus:news:calendar", [self._calendar_dto(e) for e in self._calendar], ttl=max(600, int(os.getenv("CALENDAR_POLL_SEC", "300")) * 4))
            self._set_source_health("calendar_secondary", ProviderHealth.HEALTHY, "تم تحديث التقويم الاقتصادي الحقيقي بنجاح.", received=len(events), accepted=len(events), success=True)

            macro: list[dict[str, Any]] = []
            persisted = skipped = 0
            for e in self._calendar:
                ev = calendar_event_record(e)
                sig = (e.impact, e.actual, e.forecast, e.previous, str(e.timestamp))
                if self._persisted_calendar.get(ev["event_id"]) == sig:
                    # Unchanged since the last successful pass — reuse the
                    # cached macro record and skip every HTTP persist.
                    cached = self._calendar_macro_cache.get(ev["event_id"])
                    if cached is not None:
                        macro.append(cached)
                        skipped += 1
                        continue
                failed = False
                if not await self._persist("fund_events", ev):
                    failed = True
                rec = calendar_to_macro(e)
                if rec is None:
                    # Nothing macro-shaped to persist; still record the
                    # fund_events outcome so we don't retry forever.
                    if not failed:
                        self._persisted_calendar[ev["event_id"]] = sig
                        self._calendar_macro_cache[ev["event_id"]] = {}
                        persisted += 1
                    macro.append({})
                    continue
                now_known = _utcnow()
                if rec.get("forecast") is not None:
                        await self._persist("event_expectations", {
                            "expectation_id": stable_event_id("exp", ev["event_id"], "calendar_secondary", e.timestamp.isoformat()),
                            "event_id": ev["event_id"],
                            "provider_source_id": "calendar_secondary",
                            "forecast_value": rec.get("forecast"),
                            "consensus_median": rec.get("forecast"),
                            "observed_at": now_known,
                            "known_at": now_known,
                            "freshness_score": 80.0,
                            "quality_score": 65.0,
                        })
                for field_name in ("actual", "previous"):
                    value = rec.get(field_name)
                    if value is not None:
                        await self._persist("data_vintages", {
                            "vintage_id": stable_event_id("vintage", ev["event_id"], field_name, value),
                            "event_id": ev["event_id"],
                            "source_id": "calendar_secondary",
                            "field_name": field_name,
                            "value_numeric": value,
                            "source_published_at": e.timestamp,
                            "known_at": now_known,
                            "revision_number": 0,
                        })
                # Persist only DB columns; engine provenance fields remain live-only.
                db_macro = {k: v for k, v in rec.items() if k in {
                    "event_id", "indicator_code", "indicator_name_en", "indicator_name_ar", "frequency", "unit", "actual", "forecast", "previous",
                    "first_release_value", "revised_previous", "latest_value", "consensus_low", "consensus_high", "surprise_absolute", "surprise_percent",
                    "surprise_zscore", "revision_effect_score", "historical_importance", "gold_relevance", "rate_implication_score", "usd_implication_score",
                    "yield_implication_score", "gold_implication_score", "release_timestamp", "revision_timestamp",
                }}
                await self._persist("macro_releases", db_macro)
                if failed:
                    continue  # retry this event on the next pass
                self._persisted_calendar[ev["event_id"]] = sig
                self._calendar_macro_cache[ev["event_id"]] = rec
                persisted += 1
                macro.append(rec)
            if skipped:
                log.info("fundamental.calendar_persist_deduped", persisted=persisted, skipped=skipped)
            self._macro_records = macro[-200:]
            if self._blackout.get("active"):
                await self._persist_blackout(self._blackout)
            await self._publish_source_health()
            await self.recompute(reason="calendar")

    async def on_calendar_failure(self, error: Exception) -> None:
        async with self._lock:
            self._blackout = BlackoutEngine.degraded(
                f"Calendar fetch failed: {error}",
                "تعذر تحديث التقويم الاقتصادي؛ تم منع فتح تعرّض جديد احترازيًا حتى عودة المصدر.",
            )
            self._set_source_health("calendar_secondary", ProviderHealth.DEGRADED, f"فشل تحديث التقويم: {error}", success=False)
            await self._publish_json("nexus:fundamental:blackout", self._blackout, ttl=3600)
            await self._publish_source_health()
            await self.recompute(reason="calendar_degraded")

    async def official_source_loop(self, poll_sec: int = 60) -> None:
        while True:
            try:
                await self._poll_due_sources()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("fundamental.official_source_loop")
            await asyncio.sleep(max(15, poll_sec))

    async def _poll_due_sources(self) -> None:
        now = time.monotonic()
        await self._sync_custom_sources()
        for sid, adapter in list(self._adapters.items()):
            definition = SOURCE_BY_ID.get(sid)
            cfg = managed_source_config(sid) or {}
            enabled = bool(cfg.get("enabled", definition.enabled if definition else True))
            if not enabled:
                self._set_source_health(sid, ProviderHealth.OFFLINE, "المصدر معطل بواسطة المستخدم من إدارة المصادر.")
                continue
            polling = int(cfg.get("polling_interval_sec") or (definition.polling_interval_sec if definition else 300))
            if now - self._last_fetch.get(sid, 0.0) < max(15, polling):
                continue
            self._last_fetch[sid] = now
            result = await adapter.fetch()
            await self._record_fetch_result(result)
            if not result.success:
                continue
            mapping = str(cfg.get("analysis_mapping") or "health_only")
            if sid == "bls":
                await self._consume_bls_actuals(result.records)
            elif sid == "fred":
                await self._consume_fred(result.records)
            elif sid == "fed_rss":
                await self._consume_fed_rss(result.records)
            elif sid == "cftc" or sid in {"gold_etf", "central_bank_gold", "market_flow"} or mapping == "flows":
                await self._consume_flows(result.records, source_id=sid)
            elif sid in {"treasury", "eia", "market_cross"} or mapping == "cross_asset":
                await self._consume_configured_cross(result.records, source_id=sid)
            elif sid == "cme_fedwatch":
                await self._consume_market_policy_expectations(result.records)
            # BEA/Census/NYFed/WorldBank/IMF/Atlanta-MPT/GDELT/ETF holdings are
            # health/data-availability evidence until an explicit normalization
            # contract exists. Successful HTTP never becomes an implicit score.
        await self._publish_source_health()
        await self.recompute(reason="official_sources")
        try:
            outcome_state = await self._outcome_collector.collect_recent(now=_utcnow())
            await self._publish_json("nexus:fundamental:outcomes:collector", outcome_state, ttl=180)
        except Exception:
            log.exception("fundamental.outcome_collector_failed")

    async def _record_fetch_result(self, result: Any) -> None:
        received = len(result.records)
        self._set_source_health(
            result.source_id,
            result.health,
            "المصدر يعمل وتم جلب بيانات حقيقية." if result.success else (
                "يتطلب المصدر إعدادًا إضافيًا." if result.health == ProviderHealth.CONFIG_REQUIRED else f"تعذر الجلب: {result.error_message or result.error_code or 'خطأ غير محدد'}"
            ),
            latency_ms=result.latency_ms,
            received=received,
            accepted=received if result.success else 0,
            success=result.success,
        )
        await self._persist("source_fetch_runs", {
            "fetch_run_id": uuid.uuid4().hex,
            "source_id": result.source_id,
            "started_at": result.started_at,
            "finished_at": result.finished_at or _utcnow(),
            "http_status": result.http_status,
            "success": result.success,
            "records_received": received,
            "records_accepted": received if result.success else 0,
            "records_rejected": 0 if result.success else received,
            "duplicates": 0,
            "latency_ms": result.latency_ms,
            "error_code": result.error_code,
            "error_message": result.error_message,
            "payload_hash": result.payload_hash,
        })
        await self._persist("source_health_history", {
            "health_id": uuid.uuid4().hex,
            "source_id": result.source_id,
            "observed_at": _utcnow(),
            "health_state": result.health.value,
            "freshness_state": "fresh" if result.success else "unavailable" if result.health == ProviderHealth.CONFIG_REQUIRED else "degraded",
            "latency_ms": result.latency_ms,
            "consecutive_failures": 0 if result.success else 1,
            "status_code": result.http_status,
            "description_ar": self._source_health[result.source_id]["health_description_ar"],
        })

    async def _consume_bls_actuals(self, records: list[dict[str, Any]]) -> None:
        """Expose official BLS actuals without inventing consensus or release-time history."""
        grouped: dict[str, list[dict[str, Any]]] = {}
        known = _utcnow()
        for row in records:
            code = str(row.get("indicator_code", "")).upper()
            if not code:
                continue
            grouped.setdefault(code, []).append(row)
            period = f"{row.get('year','')}-{row.get('period','')}"
            if isinstance(row.get("value"), (int, float)):
                await self._persist("economic_indicator_observations", {
                    "observation_id": stable_event_id("econobs", "bls", code, period, row.get("value")),
                    "indicator_code": code,
                    "source_id": "bls",
                    "source_series_id": row.get("series_id"),
                    "period": period,
                    "observed_at": None,
                    "source_timestamp": None,
                    "received_at": known,
                    "known_at": known,
                    "value": float(row["value"]),
                    "unit": None,
                    "origin": "real",
                    "freshness_score": 85.0,
                    "quality_score": 100.0,
                    "revision_number": 0,
                    "metadata_json": {"retrieved_historical_snapshot": True, "footnotes": row.get("footnotes", [])},
                })
        out: list[dict[str, Any]] = []
        for code, rows in grouped.items():
            rows = sorted(rows, key=lambda x: (str(x.get("year", "")), str(x.get("period", ""))))
            if not rows:
                continue
            latest = rows[-1]
            prev = rows[-2] if len(rows) > 1 else None
            period = f"{latest.get('year','')}-{latest.get('period','')}"
            out.append({
                "indicator_code": code,
                "indicator_name_ar": INDICATOR_AR.get(code, code),
                "indicator_name_en": code.replace("_", " ").title(),
                "actual": latest.get("value"),
                "forecast": None,
                "previous": prev.get("value") if prev else None,
                "revised_previous": None,
                "surprise_absolute": None,
                "surprise_zscore": None,
                "period": period,
                "source_id": "bls",
                "source_name": "U.S. Bureau of Labor Statistics",
                "source_name_ar": "مكتب إحصاءات العمل الأمريكي",
                "source_timestamp": None,
                "received_at": known,
                "origin": "real",
                "trust_score": 100.0,
                "quality_score": 100.0,
                "freshness": "fresh",
                "causal_group_id": f"bls:{code}:{period}",
                "independence_group": "bls",
                "metadata": {"score_eligible": False, "reason": "official_actual_without_known_market_consensus"},
            })
        self._macro_official_records = out

    async def _consume_fred(self, records: list[dict[str, Any]]) -> None:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for r in records:
            grouped.setdefault(str(r.get("series_code", "")).upper(), []).append(r)
        live: list[dict[str, Any]] = []
        macro_extra: list[dict[str, Any]] = []
        macro_codes = {"INITIAL_CLAIMS", "CONTINUING_CLAIMS", "CLAIMS_4W_AVG"}
        for code, rows in grouped.items():
            rows = sorted(rows, key=lambda x: str(x.get("timestamp", "")))
            if not rows:
                continue
            latest = rows[-1]
            prev = rows[-2] if len(rows) > 1 else None
            value = float(latest["value"])
            change = value - float(prev["value"]) if prev else 0.0
            change_pct = change / max(abs(float(prev["value"])), 1e-12) * 100.0 if prev else 0.0
            if code in macro_codes:
                for row in rows:
                    await self._persist("economic_indicator_observations", {
                        "observation_id": stable_event_id("econobs", "fred", code, row.get("timestamp"), row.get("value")),
                        "indicator_code": code,
                        "source_id": "fred",
                        "source_series_id": row.get("source_series_id"),
                        "period": str(row.get("timestamp") or "")[:10],
                        "observed_at": row.get("timestamp"),
                        "source_timestamp": row.get("timestamp"),
                        "received_at": _utcnow(),
                        "known_at": _utcnow(),
                        "value": float(row["value"]),
                        "unit": row.get("unit"),
                        "origin": "real",
                        "freshness_score": 90.0,
                        "quality_score": 98.0,
                        "revision_number": 0,
                        "metadata_json": {"source": "FRED", "original_publisher": "U.S. Employment and Training Administration" if code in {"INITIAL_CLAIMS", "CONTINUING_CLAIMS", "CLAIMS_4W_AVG"} else None, "score_eligible": False},
                    })
                macro_extra.append({
                    "indicator_code": code,
                    "indicator_name_ar": INDICATOR_AR.get(code, code),
                    "indicator_name_en": code.replace("_", " ").title(),
                    "actual": value,
                    "forecast": None,
                    "previous": float(prev["value"]) if prev else None,
                    "revised_previous": None,
                    "surprise_absolute": None,
                    "surprise_zscore": None,
                    "source_id": "fred",
                    "source_name": "FRED",
                    "source_name_ar": "قاعدة بيانات الاحتياطي الفيدرالي الاقتصادية",
                    "source_timestamp": latest["timestamp"],
                    "origin": "real",
                    "trust_score": 98.0,
                    "quality_score": 98.0,
                    "freshness": "fresh",
                    "causal_group_id": f"labor:{code}:{str(latest['timestamp'])[:10]}",
                    "independence_group": "fred",
                    "metadata": {"score_eligible": False, "reason": "actual_series_without_market_consensus"},
                })
                continue

            obs = {
                "observation_id": stable_event_id("mkt", "fred", code, latest["timestamp"]),
                "series_code": code,
                "source_id": "fred",
                "timestamp": latest["timestamp"],
                "received_at": _utcnow(),
                "value": value,
                "unit": latest.get("unit"),
                "frequency": "daily",
                "native_horizon": "tactical",
                "origin": "real",
                "freshness_score": 85.0,
                "quality_score": 98.0,
            }
            await self._persist("market_series_observations", obs)
            live.append(obs | {
                "change": change,
                "change_pct": change_pct,
                "source_name": "FRED",
                "source_name_ar": "قاعدة بيانات الاحتياطي الفيدرالي الاقتصادية",
                "source_timestamp": latest["timestamp"],
                "trust_score": 98.0,
                "freshness": "fresh",
                "quality_score": 98.0,
                "causal_group_id": f"cross_asset:{code}:{str(latest['timestamp'])[:10]}",
                "independence_group": "fred",
                "reason_for_yield_move": "unknown_requires_event_context" if code in {"US2Y", "US10Y", "US30Y", "REAL_YIELD_10Y"} else None,
            })

        # Derived 2s10s curve is transparent and based only on same-source real data.
        latest_by = {x["series_code"]: x for x in live}
        if "US2Y" in latest_by and "US10Y" in latest_by:
            two, ten = latest_by["US2Y"], latest_by["US10Y"]
            spread = float(ten["value"]) - float(two["value"])
            curve = {
                "observation_id": stable_event_id("mkt", "fred", "YIELD_CURVE_2S10S", ten["timestamp"]),
                "series_code": "YIELD_CURVE_2S10S",
                "source_id": "fred",
                "timestamp": ten["timestamp"],
                "received_at": _utcnow(),
                "value": spread,
                "unit": "percentage_points",
                "frequency": "daily",
                "native_horizon": "tactical",
                "origin": "real",
                "freshness_score": min(float(two["freshness_score"]), float(ten["freshness_score"])),
                "quality_score": 98.0,
            }
            await self._persist("market_series_observations", curve)
            live.append(curve | {
                "change": 0.0,
                "change_pct": 0.0,
                "source_name": "FRED (derived from US10Y-US2Y)",
                "source_name_ar": "FRED — مشتق شفاف من US10Y وUS2Y",
                "source_timestamp": ten["timestamp"],
                "trust_score": 98.0,
                "freshness": "fresh",
                "causal_group_id": f"cross_asset:curve:{str(ten['timestamp'])[:10]}",
                "independence_group": "fred",
            })
        self._cross_records = live
        if macro_extra:
            existing_bls = [r for r in self._macro_official_records if str(r.get("source_id")) != "fred"]
            self._macro_official_records = (existing_bls + macro_extra)[-100:]

    async def _consume_fed_rss(self, records: list[dict[str, Any]]) -> None:
        live: list[dict[str, Any]] = []
        for r in sorted(records, key=lambda x: str(x.get("published_at") or ""), reverse=True)[:20]:
            m = fed_rss_to_monetary(r)
            event_id = stable_event_id("fed", r.get("guid") or r.get("link") or r.get("title"))
            relevant = bool(m.get("monetary_relevant"))
            event = {
                "event_id": event_id,
                "source_id": "fed_rss",
                "category": "monetary" if relevant else "fed_context",
                "subcategory": m["event_kind"],
                "event_type": m["event_kind"],
                "event_code": m["event_kind"],
                "title_en": r.get("title", "Federal Reserve communication"),
                "title_ar": (f"اتصال سياسة نقدية من الاحتياطي الفيدرالي: {r.get('title','')}" if relevant else f"خبر إداري/سياقي من الاحتياطي الفيدرالي: {r.get('title','')}"),
                "country": "US",
                "currency": "USD",
                "source_timestamp": r.get("published_at"),
                "published_at": r.get("published_at"),
                "received_at": _utcnow(),
                "declared_impact": "medium" if relevant else "low",
                "gold_relevance": 85.0 if relevant else 0.0,
                "freshness_state": "fresh",
                "data_quality_score": 90.0 if relevant else 70.0,
                "raw_hash": hashlib.sha256(json.dumps(r, sort_keys=True, default=str).encode()).hexdigest(),
                "dedup_group_id": event_id,
                "causal_group_id": m["causal_group_id"],
                "independence_group": "federal_reserve",
            }
            await self._persist("fund_events", event)
            if not relevant:
                continue
            db = {k: v for k, v in m.items() if k in {
                "institution", "event_kind", "rate_before", "rate_expected", "rate_after", "rate_surprise_bps", "tone_score", "previous_tone_score",
                "policy_delta", "forward_guidance_score", "dot_plot_shift", "qe_qt_score", "balance_sheet_score", "hawkish_probability", "dovish_probability",
                "speaker", "statement_hash", "statement_version", "gold_implication_score", "confidence",
            }}
            await self._persist("central_bank_events", {"event_id": event_id, **db})
            live.append(m | {"event_id": event_id})
        self._monetary_records = live

    async def _consume_configured_cross(self, records: list[dict[str, Any]], *, source_id: str) -> None:
        """Consume an explicitly configured normalized cross-asset endpoint.

        Required record contract: series_code, value, timestamp/date.  Optional
        change/change_pct/change_z may be provided by the licensed feed.  Invalid
        rows are skipped rather than coerced into neutral evidence.
        """
        definition = SOURCE_BY_ID.get(source_id)
        accepted: list[dict[str, Any]] = []
        for r in records:
            code = str(r.get("series_code") or r.get("code") or "").upper()
            value = r.get("value")
            ts = r.get("timestamp") or r.get("date")
            if not code or not isinstance(value, (int, float)) or not ts:
                continue
            rec = {
                "observation_id": stable_event_id("mkt", source_id, code, ts),
                "series_code": code,
                "source_id": source_id,
                "timestamp": ts,
                "received_at": _utcnow(),
                "value": float(value),
                "unit": r.get("unit"),
                "frequency": r.get("frequency") or "intraday",
                "native_horizon": r.get("native_horizon") or "tactical",
                "origin": "real",
                "freshness_score": float(r.get("freshness_score", 90.0) or 90.0),
                "quality_score": float(r.get("quality_score", definition.trust_score if definition else 80.0) or 80.0),
            }
            await self._persist("market_series_observations", rec)
            # A point-in-time value without a measured change is stored as evidence
            # but never coerced into a neutral cross-asset driver.
            if not any(isinstance(r.get(k), (int, float)) for k in ("change", "change_pct", "change_z")):
                continue
            accepted.append(rec | {
                "change": float(r["change"]) if isinstance(r.get("change"), (int, float)) else None,
                "change_pct": float(r["change_pct"]) if isinstance(r.get("change_pct"), (int, float)) else None,
                "change_z": float(r["change_z"]) if isinstance(r.get("change_z"), (int, float)) else None,
                "source_name": definition.name_en if definition else source_id,
                "source_name_ar": definition.name_ar if definition else source_id,
                "source_timestamp": ts,
                "trust_score": float(definition.trust_score if definition else 80.0),
                "freshness": "fresh",
                "causal_group_id": f"cross_asset:{code}:{str(ts)[:10]}",
                "independence_group": source_id,
                "reason_for_yield_move": r.get("reason_for_yield_move") or ("unknown_requires_event_context" if code in {"US2Y", "US10Y", "US30Y", "REAL_YIELD_10Y"} else None),
            })
        # Replace only rows belonging to this source; preserve FRED/other feeds.
        retained = [x for x in self._cross_records if str(x.get("source_id")) != source_id]
        self._cross_records = (retained + accepted)[-200:]

    async def _consume_market_policy_expectations(self, records: list[dict[str, Any]]) -> None:
        """Consume a configured Fed-probability feed only when it supplies normalized facts.

        We do not infer policy_delta from arbitrary probability blobs here.  The
        adapter contract must supply an explicit, provider-derived policy_delta
        or rate_surprise_bps; otherwise the row stays outside the scoring engine.
        """
        accepted: list[dict[str, Any]] = []
        for r in records:
            if not isinstance(r, dict):
                continue
            policy_delta = r.get("policy_delta")
            rate_surprise = r.get("rate_surprise_bps")
            if not isinstance(policy_delta, (int, float)) and not isinstance(rate_surprise, (int, float)):
                continue
            ts = r.get("timestamp") or r.get("known_at") or _utcnow().isoformat()
            accepted.append({
                "event_kind": "market_policy_expectations",
                "label_ar": "توقعات السوق لمسار الفائدة",
                "label_en": "Market-implied Fed path",
                "tone_score": float(r["tone_score"]) if isinstance(r.get("tone_score"), (int, float)) else None,
                "previous_tone_score": float(r["previous_tone_score"]) if isinstance(r.get("previous_tone_score"), (int, float)) else None,
                "policy_delta": float(policy_delta) if isinstance(policy_delta, (int, float)) else None,
                "rate_surprise_bps": float(rate_surprise) if isinstance(rate_surprise, (int, float)) else None,
                "forward_guidance_score": float(r["forward_guidance_score"]) if isinstance(r.get("forward_guidance_score"), (int, float)) else None,
                "dot_plot_shift": float(r["dot_plot_shift"]) if isinstance(r.get("dot_plot_shift"), (int, float)) else None,
                "qe_qt_score": float(r["qe_qt_score"]) if isinstance(r.get("qe_qt_score"), (int, float)) else None,
                "analysis_mode": "market_implied",
                "confidence": float(r.get("confidence", 70.0) or 70.0),
                "source_id": "cme_fedwatch",
                "source_name": "CME FedWatch / configured licensed feed",
                "source_name_ar": "توقعات السوق لمسار الفائدة",
                "source_timestamp": ts,
                "origin": "real",
                "trust_score": float(SOURCE_BY_ID["cme_fedwatch"].trust_score),
                "quality_score": float(r.get("quality_score", 85.0) or 85.0),
                "freshness": "fresh",
                "causal_group_id": f"monetary:market_expectations:{str(ts)[:16]}",
                "independence_group": "cme_fedwatch",
                "probabilities": r.get("probabilities"),
            })
        retained = [x for x in self._monetary_records if str(x.get("source_id")) != "cme_fedwatch"]
        self._monetary_records = (retained + accepted)[-100:]

    async def _consume_flows(self, records: list[dict[str, Any]], *, source_id: str = "cftc") -> None:
        accepted: list[dict[str, Any]] = []
        for r in records:
            flow_type = r.get("flow_type") or r.get("type")
            value = r.get("value")
            if not flow_type or not isinstance(value, (int, float)):
                continue
            ts = r.get("timestamp") or r.get("date") or _utcnow().isoformat()
            horizon = str(r.get("native_horizon") or ("structural" if "central" in str(flow_type).lower() else "structural" if "cot" in str(flow_type).lower() else "tactical"))
            rec = {
                "observation_id": stable_event_id("flow", source_id, flow_type, ts),
                "flow_type": str(flow_type).upper(),
                "source_id": source_id,
                "timestamp": ts,
                "known_at": r.get("known_at") or ts,
                "value": float(value),
                "unit": r.get("unit"),
                "frequency": r.get("frequency") or ("weekly" if "COT" in str(flow_type).upper() else "unknown"),
                "native_horizon": horizon,
                "flow_direction": r.get("flow_direction"),
                "strength_score": float(r.get("strength_score", 50.0) or 50.0),
                "crowding_score": float(r.get("crowding_score", 0.0) or 0.0),
                "confirmation_score": float(r.get("confirmation_score", 50.0) or 50.0),
                "divergence_score": float(r.get("divergence_score", 0.0) or 0.0),
                "origin": "real",
                "freshness_score": float(r.get("freshness_score", 80.0) or 80.0),
                "quality_score": float(r.get("quality_score", 90.0) or 90.0),
            }
            await self._persist("flow_observations", rec)
            accepted.append(rec | {
                "source_name": SOURCE_BY_ID.get(source_id).name_en if SOURCE_BY_ID.get(source_id) else source_id,
                "source_name_ar": SOURCE_BY_ID.get(source_id).name_ar if SOURCE_BY_ID.get(source_id) else source_id,
                "source_timestamp": ts,
                "trust_score": float(SOURCE_BY_ID.get(source_id).trust_score if SOURCE_BY_ID.get(source_id) else 70.0),
                "freshness": "fresh",
                "causal_group_id": f"flow:{flow_type}:{str(ts)[:10]}",
                "independence_group": source_id,
            })
        retained = [x for x in self._flow_records if str(x.get("source_id")) != source_id]
        self._flow_records = (retained + accepted)[-200:]

    async def recompute(self, *, reason: str) -> None:
        macro = self._macro_engine.evaluate(self._macro_records)
        monetary = self._monetary_engine.evaluate(self._monetary_records)
        cross_records = list(self._cross_records)
        if not cross_records:
            cross_records = await self._cross_from_runtime_cache()
        cross = self._cross_engine.evaluate(cross_records)
        geo = self._geo_engine.evaluate(self._geo_records)
        flows = self._flows_engine.evaluate(self._flow_records)
        factors = [macro, monetary, cross, geo, flows]

        event_type = ""
        event_id = None
        for e in sorted(self._calendar, key=lambda x: x.timestamp, reverse=True):
            code = indicator_code(e.event_name)
            if code:
                event_type = code
                event_id = calendar_event_record(e)["event_id"]
                break
        if geo.strength > 60 and geo.confidence > macro.confidence:
            event_type = "GEOPOLITICAL"
            event_id = None

        fusion = self._fusion_engine.fuse(
            factors,
            symbol="XAUUSD",
            event_type=event_type,
            event_id=event_id,
            market_regime="shock" if self._blackout.get("active") else "normal",
            safe_haven_environment=max(0.0, geo.gold_impact_score),
        )
        gold = self._gold_engine.predict(fusion, factors, blackout=self._blackout, stage=PredictionStage.AT_RELEASE)
        gold.transmission_chain_ar = self._transmission_chain(event_type, gold.direction)
        explanation = self._explain_engine.build(gold)
        asset_impacts = self._asset_impact_engine.evaluate(
            event_id=event_id, event_type=event_type, factors=factors, gold=gold, known_at=_utcnow()
        )
        self._latest_asset_impacts = asset_impacts

        details_by_domain = {
            "macro": (self._macro_records + self._macro_official_records)[-100:],
            "monetary": self._monetary_records[-100:],
            "cross_asset": cross_records[-100:],
            "geopolitical": self._geo_records[-100:],
            "flows": self._flow_records[-100:],
        }
        for factor in factors:
            await self._publish_json(f"nexus:fundamental:{factor.domain.value}:latest", factor, ttl=900)
            await self._publish_json(
                f"nexus:fundamental:{factor.domain.value}:details",
                details_by_domain.get(factor.domain.value, []),
                ttl=900,
            )
        await self._publish_json("nexus:fundamental:fusion:latest", fusion, ttl=900)
        await self._publish_json("nexus:fundamental:gold:latest", gold, ttl=900)
        await self._publish_json("nexus:fundamental:explanation:latest", explanation, ttl=900)
        await self._publish_json("nexus:fundamental:data_quality", {
            "coverage": gold.coverage_score,
            "quality": gold.data_quality_score,
            "freshness": gold.freshness_score,
            "conflict": gold.conflict_score,
            "reason": reason,
            "updated_at": _utcnow().isoformat(),
        }, ttl=900)

        for asset_id in ("XAUUSD", "BTCUSD"):
            rows = [x for x in asset_impacts if x.get("asset_id") == asset_id]
            await self._publish_json(f"nexus:fundamental:asset:{asset_id}:latest", {
                "state": "ready" if any(float(x.get("coverage", 0.0) or 0.0) > 0 for x in rows) else "degraded",
                "asset_id": asset_id,
                "event_id": event_id,
                "event_type": event_type or None,
                "impacts": rows,
                "generated_at": _utcnow().isoformat(),
            }, ttl=900)

        ticker_all = self._ticker_engine.build(
            calendar=self._calendar,
            news=self._news,
            news_analysis=self._news_analysis,
            asset_impacts=asset_impacts,
            blackout=self._blackout,
            now=_utcnow(),
            previous_items=self._ticker_state,
        )
        self._ticker_state = ticker_all
        ticker_active = [x for x in ticker_all if str(x.get("status")) not in {"EXPIRED", "SUPERSEDED"}]
        await self._publish_json("nexus:news:ticker:active", ticker_active, ttl=180)
        await self._publish_json("nexus:news:ticker:lifecycle", ticker_all, ttl=3600)
        self._latest_gold = gold.model_dump(mode="json")

        for factor in factors:
            await self._persist_factor(factor, event_id)
        await self._persist_fusion(fusion)
        await self._persist_gold(gold)
        await self._persist_explanation(explanation)
        for impact in asset_impacts:
            await self._persist("event_asset_impacts", impact)
        for row in ticker_all:
            source_id = str(row.get("source_id") or "")
            source_def = SOURCE_BY_ID.get(source_id)
            # Provider news with storage_allowed=False stays live in Redis only.
            # Official/calendar items may be retained for ticker history/audit.
            if source_def is not None and source_def.storage_allowed:
                await self._persist("news_ticker_items", row)

    async def _cross_from_runtime_cache(self) -> list[dict[str, Any]]:
        try:
            raw = await self.redis.get("nexus:cross_asset:summary")
            if not raw:
                return []
            data = json.loads(raw)
            origin = str(data.get("origin", "unknown"))
            if not data.get("available", False) or origin in {"unavailable", "synthetic"}:
                return []
            now = data.get("updated_at") or _utcnow().isoformat()
            out: list[dict[str, Any]] = []
            dxy = data.get("dxy", {})
            us10y = data.get("us10y", {})
            if dxy.get("level") is not None:
                out.append({
                    "series_code": "DXY", "timestamp": now, "value": dxy.get("level"), "change_pct": dxy.get("change_5d", 0.0),
                    "source_id": "market_cross", "source_name": str(dxy.get("source", "runtime cross-asset")), "source_name_ar": "مصدر سوق مترابط",
                    "origin": origin, "quality_score": 60.0 if origin == "proxy" else 78.0, "trust_score": 65.0, "freshness": "fresh",
                    "causal_group_id": f"crossasset:dxy:{str(now)[:10]}", "independence_group": str(dxy.get("source", "runtime")),
                })
            if us10y.get("level") is not None:
                out.append({
                    "series_code": "US10Y", "timestamp": now, "value": us10y.get("level"), "change": us10y.get("change_5d", 0.0),
                    "source_id": "market_cross", "source_name": str(us10y.get("source", "runtime cross-asset")), "source_name_ar": "مصدر سوق مترابط",
                    "origin": origin, "quality_score": 60.0 if origin == "proxy" else 78.0, "trust_score": 65.0, "freshness": "fresh",
                    "causal_group_id": f"crossasset:us10y:{str(now)[:10]}", "independence_group": str(us10y.get("source", "runtime")),
                })
            return out
        except Exception:
            log.exception("fundamental.cross_runtime_read_failed")
            return []

    def _headline_geopolitics(self, item: NewsItem, article: dict[str, Any]) -> dict[str, Any] | None:
        text = item.headline.lower()
        matched: list[str] = []
        deesc = 0.0
        for cls, words in _GEO_KEYWORDS.items():
            if any(w in text for w in words):
                if cls == "deescalation":
                    deesc = 65.0
                else:
                    matched.append(cls)
        if not matched and not deesc:
            return None
        event_class = matched[0] if matched else "deescalation"
        severity = min(100.0, 35.0 + len(matched) * 14.0 + (15.0 if item.impact == "high" else 0.0))
        safe = min(100.0, severity * 0.75)
        return {
            "event_id": stable_event_id("geo", article["story_cluster_id"]),
            "title_ar": item.headline,
            "title_en": item.headline,
            "event_class": event_class,
            "region": "global",
            "severity_score": severity,
            "escalation_score": min(100.0, severity if "escalation" in matched or "war" in matched else severity * 0.55),
            "deescalation_score": deesc,
            "persistence_score": 50.0,
            "global_relevance": min(100.0, 55.0 + severity * 0.35),
            "safe_haven_score": safe,
            "energy_risk_score": 70.0 if "energy_shock" in matched else 25.0,
            "currency_risk_score": 55.0 if "sanctions" in matched or "sovereign_risk" in matched else 25.0,
            "source_consensus_score": 45.0,  # one headline is not source consensus
            "independent_source_count": 1,
            "story_cluster_id": article["story_cluster_id"],
            "gold_implication_score": safe - deesc,
            "confidence": 45.0,
            "source_id": article["source_id"],
            "source_name": item.source,
            "source_name_ar": item.source,
            "source_timestamp": item.timestamp,
            "source_trust": article["source_trust"],
            "trust_score": article["source_trust"],
            "quality_score": article["data_quality_score"],
            "freshness": "fresh",
            "origin": "real",
            "causal_group_id": f"geo:{article['story_cluster_id']}",
            "independence_group": item.source,
        }

    async def _persist_geo_event(self, item: NewsItem, geo: dict[str, Any]) -> None:
        event = {
            "event_id": geo["event_id"],
            "source_id": geo["source_id"],
            "category": "geopolitical",
            "subcategory": geo["event_class"],
            "event_type": geo["event_class"],
            "event_code": str(geo["event_class"]).upper(),
            "title_en": item.headline,
            "title_ar": item.headline,
            "country": None,
            "currency": "USD",
            "source_timestamp": item.timestamp,
            "published_at": item.timestamp,
            "received_at": _utcnow(),
            "declared_impact": item.impact,
            "gold_relevance": geo["global_relevance"],
            "novelty_score": 50.0,
            "freshness_state": "fresh",
            "data_quality_score": geo["quality_score"],
            "raw_hash": hashlib.sha256(item.headline.encode()).hexdigest(),
            "dedup_group_id": geo["story_cluster_id"],
            "causal_group_id": geo["causal_group_id"],
            "independence_group": geo["independence_group"],
        }
        await self._persist("fund_events", event)
        db = {k: v for k, v in geo.items() if k in {
            "region", "event_class", "severity_score", "escalation_score", "deescalation_score", "persistence_score", "global_relevance",
            "safe_haven_score", "energy_risk_score", "currency_risk_score", "source_consensus_score", "independent_source_count",
            "story_cluster_id", "gold_implication_score", "confidence",
        }}
        await self._persist("geopolitical_events", {"event_id": geo["event_id"], **db})

    async def _persist_blackout(self, blackout: dict[str, Any]) -> None:
        if not blackout.get("blackout_id") or not blackout.get("starts_at") or not blackout.get("ends_at"):
            return
        await self._persist("fundamental_blackout_windows", {
            "blackout_id": blackout["blackout_id"],
            "event_id": blackout.get("event_id"),
            "starts_at": blackout["starts_at"],
            "ends_at": blackout["ends_at"],
            "impact": blackout.get("impact", "high"),
            "affected_assets_json": ["XAUUSD"],
            "policy_version": blackout.get("policy_version", self._blackout_engine.version),
            "state": blackout.get("state", "active"),
            "reason_code": blackout.get("reason_code", "NEWS_BLACKOUT"),
            "reason_ar": blackout.get("reason_ar", "حظر خبر أساسي"),
        })

    async def _persist_factor(self, factor: Any, event_id: str | None) -> None:
        await self._persist("fundamental_factor_scores", {
            "score_id": uuid.uuid4().hex,
            "timestamp": factor.generated_at,
            "symbol": "XAUUSD",
            "event_id": event_id,
            "domain": factor.domain.value,
            "native_score": factor.native_score,
            "gold_impact_score": factor.gold_impact_score,
            "direction": factor.direction.value,
            "strength": factor.strength,
            "confidence": factor.confidence,
            "coverage_score": factor.coverage_score,
            "freshness_score": factor.freshness_score,
            "data_quality_score": factor.data_quality_score,
            "reliability_score": factor.reliability_score,
            "horizon_class": factor.horizon_class.value,
            "primary_drivers_json": [d.model_dump(mode="json") for d in factor.primary_drivers],
            "counter_drivers_json": [d.model_dump(mode="json") for d in factor.counter_drivers],
            "source_count": len({e.source_id for d in [*factor.primary_drivers, *factor.counter_drivers] for e in d.sources}),
            "engine_version": factor.engine_version,
        })

    async def _persist_fusion(self, fusion: Any) -> None:
        by = {w.domain.value: w for w in fusion.weights}
        await self._persist("fundamental_fusion_results", {
            "fusion_id": fusion.fusion_id,
            "timestamp": fusion.generated_at,
            "symbol": fusion.symbol,
            "event_id": fusion.event_id,
            "net_score": fusion.net_score,
            "direction": fusion.direction.value,
            "strength": fusion.strength,
            "confidence": fusion.confidence,
            "coverage_score": fusion.coverage_score,
            **{f"{d}_score": by[d].raw_gold_score if d in by else None for d in ("macro", "monetary", "cross_asset", "geopolitical", "flows")},
            **{f"{d}_weight": by[d].normalized_weight if d in by else 0.0 for d in ("macro", "monetary", "cross_asset", "geopolitical", "flows")},
            "agreement_score": fusion.agreement_score,
            "conflict_score": fusion.conflict_score,
            "freshness_score": fusion.freshness_score,
            "data_quality_score": fusion.data_quality_score,
            "dominant_cluster": max(by, key=lambda d: by[d].normalized_weight) if by else None,
            "minority_cluster": min(by, key=lambda d: by[d].normalized_weight) if by else None,
            "weight_reasons_json": {d: by[d].reason_ar for d in by},
            "fusion_version": fusion.fusion_version,
        })

    async def _persist_gold(self, gold: Any) -> None:
        await self._persist("gold_impact_predictions", {
            "prediction_id": gold.prediction_id,
            "timestamp": gold.generated_at,
            "symbol": gold.symbol,
            "event_id": gold.event_id,
            "fusion_id": gold.fusion_id,
            "prediction_stage": gold.stage.value,
            "direction": gold.direction.value,
            "strength": gold.strength,
            "confidence": gold.confidence,
            "confidence_validation": gold.confidence_validation.value,
            "coverage_score": gold.coverage_score,
            "bullish_probability_5m": gold.horizon_5m.bullish,
            "bearish_probability_5m": gold.horizon_5m.bearish,
            "neutral_probability_5m": gold.horizon_5m.neutral,
            "bullish_probability_15m": gold.horizon_15m.bullish,
            "bearish_probability_15m": gold.horizon_15m.bearish,
            "neutral_probability_15m": gold.horizon_15m.neutral,
            "bullish_probability_60m": gold.horizon_60m.bullish,
            "bearish_probability_60m": gold.horizon_60m.bearish,
            "neutral_probability_60m": gold.horizon_60m.neutral,
            "bullish_probability_4h": gold.horizon_4h.bullish,
            "bearish_probability_4h": gold.horizon_4h.bearish,
            "neutral_probability_4h": gold.horizon_4h.neutral,
            "structural_bias": gold.structural_bias.value,
            "conflict_score": gold.conflict_score,
            "freshness_score": gold.freshness_score,
            "data_quality_score": gold.data_quality_score,
            "primary_drivers_json": [d.model_dump(mode="json") for d in gold.primary_drivers],
            "counter_drivers_json": [d.model_dump(mode="json") for d in gold.counter_drivers],
            "confirmations_json": gold.confirmations_ar,
            "contradictions_json": gold.contradictions_ar,
            "weakening_factors_json": gold.weakening_factors_ar,
            "invalidation_conditions_json": gold.invalidation_conditions_ar,
            "transmission_chain_json": gold.transmission_chain_ar,
            "blackout_active": gold.blackout_active,
            "blackout_reason": gold.blackout_reason_ar,
            "model_version": gold.model_version,
        })
        for i, (src, dst) in enumerate(zip(gold.transmission_chain_ar, gold.transmission_chain_ar[1:]), start=1):
            await self._persist("prediction_reasoning_steps", {
                "step_id": uuid.uuid4().hex,
                "prediction_id": gold.prediction_id,
                "sequence_no": i,
                "from_factor": src,
                "to_factor": dst,
                "relationship": "causal_transmission",
                "direction": gold.direction.value,
                "strength": gold.strength,
                "confidence": gold.confidence,
                "confirmed": False,
                "historical_support": None,
                "explanation_ar": f"انتقال سببي متوقع: {src} ←→ {dst}",
            })

    async def _persist_explanation(self, explanation: Any) -> None:
        await self._persist("fundamental_explanations", {
            "explanation_id": uuid.uuid4().hex,
            "prediction_id": explanation.prediction_id,
            "headline_ar": explanation.headline_ar,
            "what_happened_ar": explanation.what_happened_ar,
            "why_it_matters_ar": explanation.why_it_matters_ar,
            "economic_meaning_ar": explanation.why_it_matters_ar,
            "transmission_to_gold_ar": explanation.transmission_to_gold_ar,
            "gold_effect_ar": explanation.gold_effect_ar,
            "confirmations_ar": explanation.confirmations_ar,
            "contradictions_ar": explanation.contradictions_ar,
            "weakening_factors_ar": explanation.weakening_factors_ar,
            "why_confidence_changed_ar": explanation.confidence_reason_ar,
            "invalidation_ar": explanation.invalidation_ar,
            "expected_horizon_ar": explanation.horizon_ar,
            "actual_outcome_ar": explanation.actual_outcome_ar,
            "lesson_ar": explanation.lesson_ar,
            "simple_summary_ar": explanation.simple_summary_ar,
            "advanced_summary_ar": explanation.advanced_summary_ar,
            "explanation_version": explanation.explanation_version,
        })

    @staticmethod
    def _news_dto(item: NewsItem, finbert_available: bool) -> dict[str, Any]:
        return {
            "id": stable_event_id("news-ui", item.source, item.headline, item.timestamp.isoformat()),
            "headline": item.headline,
            "source": item.source,
            "provider_id": getattr(item, "provider_id", "") or "news_secondary",
            "url": getattr(item, "url", None),
            "timestamp": item.timestamp.isoformat(),
            "impact": str(item.impact).upper(),
            "sentiment": item.sentiment,
            "affected_currencies": item.affected_currencies,
            "finbert_score": item.finbert_score if finbert_available else None,
            "finbert_state": "available" if finbert_available else "unavailable",
            "data_origin": "REAL",
        }

    @staticmethod
    def _calendar_dto(event: CalendarEvent) -> dict[str, Any]:
        return {
            # Include currency in the UI id: storage-level ids (stable_event_id
            # "cal") hash source+name+currency+timestamp, but this DTO id omitted
            # currency, so same-name/same-time events across currencies collided
            # and React rendered duplicate keys in the dashboard calendar list.
            "id": stable_event_id("cal-ui", event.source, event.event_name, event.currency, event.timestamp.isoformat()),
            "event_name": event.event_name,
            "currency": event.currency,
            "impact": str(event.impact).upper(),
            "forecast": event.forecast,
            "previous": event.previous,
            "actual": event.actual,
            "timestamp": event.timestamp.isoformat(),
            "source": event.source,
            "data_origin": "REAL",
        }

    @staticmethod
    def _transmission_chain(event_type: str, direction: GoldDirection) -> list[str]:
        if event_type in {"CPI", "CORE_CPI", "PCE", "CORE_PCE", "PPI"}:
            return [
                "مفاجأة التضخم",
                "توقعات مسار الفائدة",
                "عوائد السندات والعائد الحقيقي",
                "مؤشر الدولار الأمريكي (DXY)",
                "تكلفة الفرصة وطلب الذهب",
                "XAUUSD",
            ]
        if event_type in {"NFP", "UNEMPLOYMENT", "AVG_HOURLY_EARNINGS", "JOBLESS_CLAIMS", "JOLTS"}:
            return ["بيانات سوق العمل", "توقعات الاحتياطي الفيدرالي", "العوائد والدولار", "شهية المخاطرة", "XAUUSD"]
        if event_type == "FOMC":
            return ["قرار/نبرة الاحتياطي الفيدرالي", "توقعات الفائدة", "العوائد الحقيقية", "الدولار", "XAUUSD"]
        if event_type == "GEOPOLITICAL":
            return ["صدمة جيوسياسية", "طلب الملاذ الآمن/مخاطر الطاقة", "الدولار والعوائد وشهية المخاطرة", "التدفقات", "XAUUSD"]
        return ["المحاور الأساسية الخمسة", "الدمج الديناميكي", "العوائد والدولار/الملاذ الآمن", "XAUUSD"]
