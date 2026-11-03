from __future__ import annotations

from services.nexus_news.fundamental.engines import MonetaryEngine
from services.nexus_news.fundamental.normalization import fed_rss_to_monetary
from shared.source_manager import BUILTIN_SOURCE_MANAGER


def _rss(title: str, description: str = "") -> dict:
    return {
        "title": title,
        "description": description,
        "published_at": "2026-10-10T18:00:00+00:00",
        "guid": title,
    }


def test_free_first_catalog_has_required_sources():
    required = {
        "bls", "bea", "fred", "fed_rss", "cftc", "treasury",
        "nyfed_rates", "census", "eia", "world_bank", "imf",
        "atlanta_mpt", "gdelt", "gold_etf_iau", "gold_etf_gld", "gold_etf_gldm",
    }
    assert required.issubset(BUILTIN_SOURCE_MANAGER)
    assert BUILTIN_SOURCE_MANAGER["treasury"]["source_tier"] == "FREE_OFFICIAL"
    assert BUILTIN_SOURCE_MANAGER["census"]["source_tier"] == "FREE_API_KEY_REQUIRED"
    assert BUILTIN_SOURCE_MANAGER["eia"]["source_tier"] == "FREE_API_KEY_REQUIRED"
    assert BUILTIN_SOURCE_MANAGER["gdelt"]["auth_mode"] == "none"


def test_paid_sources_are_optional_not_required():
    assert BUILTIN_SOURCE_MANAGER["gold_etf"]["source_tier"] == "PAID_OPTIONAL"
    assert BUILTIN_SOURCE_MANAGER["gold_etf"]["enabled"] is False
    assert BUILTIN_SOURCE_MANAGER["market_flow"]["source_tier"] == "PAID_OPTIONAL"
    assert BUILTIN_SOURCE_MANAGER["market_flow"]["enabled"] is False


def test_official_etf_holdings_are_not_fake_flows():
    for sid in ("gold_etf_iau", "gold_etf_gld", "gold_etf_gldm"):
        cfg = BUILTIN_SOURCE_MANAGER[sid]
        assert cfg["analysis_mapping"] == "health_only"
        assert cfg["analysis_ready"] is False


def test_fed_administrative_rss_never_scores_monetary():
    item = fed_rss_to_monetary(_rss(
        "Federal Reserve announces enforcement action against Example Bank",
        "The Board announced a civil money penalty and consent order.",
    ))
    assert item["monetary_relevant"] is False
    assert item["analysis_mode"] == "context_only"
    assert item["tone_score"] is None
    assert item["policy_delta"] is None
    assert item["confidence"] == 0.0


def test_fomc_rss_is_low_confidence_fallback_only():
    item = fed_rss_to_monetary(_rss(
        "Federal Reserve issues FOMC statement",
        "The Federal Open Market Committee noted inflation remains elevated and will maintain the target range.",
    ))
    assert item["monetary_relevant"] is True
    assert item["analysis_mode"] == "rss_policy_fallback"
    assert item["previous_tone_score"] is None
    assert item["policy_delta"] is None
    assert 0.0 < item["confidence"] <= 35.0


def test_monetary_domain_confidence_capped_when_only_rss_fallback():
    events = []
    for i in range(6):
        item = fed_rss_to_monetary(_rss(
            f"Federal Reserve issues FOMC statement {i}",
            "Inflation remains elevated; policy remains restrictive and focused on price stability.",
        ))
        item["source_timestamp"] = f"2026-10-10T1{i}:00:00+00:00"
        events.append(item)
    result = MonetaryEngine().evaluate(events)
    assert result.confidence <= 35.0
    assert result.coverage_score <= 40.0
    assert result.metadata.get("state") == "rss_fallback_only"


def test_r31_preserves_v61_runtime_pipeline():
    from pathlib import Path
    project_root = Path(__file__).resolve().parents[2]
    source = (project_root / "services" / "nexus_news" / "fundamental" / "runtime.py").read_text(encoding="utf-8")
    for token in (
        "AssetImpactEngine", "NewsTickerEngine", "AssetOutcomeCollector",
        "_consume_bls_actuals", "_outcome_collector", "_asset_impact_engine",
        "_seed_v5_governance", "NewsIntelligenceEngine",
    ):
        assert token in source, f"V6.1 runtime regression: missing {token}"


def test_free_cross_asset_sources_have_real_mapping():
    assert BUILTIN_SOURCE_MANAGER["treasury"]["analysis_mapping"] == "cross_asset"
    assert BUILTIN_SOURCE_MANAGER["treasury"]["analysis_ready"] is True
    assert BUILTIN_SOURCE_MANAGER["eia"]["analysis_mapping"] == "cross_asset"
    assert BUILTIN_SOURCE_MANAGER["eia"]["analysis_ready"] is True
    assert BUILTIN_SOURCE_MANAGER["cme_fedwatch"]["enabled"] is False
    assert BUILTIN_SOURCE_MANAGER["market_cross"]["enabled"] is False
