from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from shared.fundamental import (
    FundamentalDomain,
    FundamentalDriver,
    FundamentalFactorResult,
    GoldDirection,
    HorizonClass,
    SourceEvidence,
)
from shared.safety import GuardCode, approval_signature, evaluate_executor_guard
from services.nexus_news.fundamental.blackout import BlackoutEngine
from services.nexus_news.fundamental.engines import (
    FlowsEngine,
    FundamentalFusionEngine,
    MacroEngine,
    MonetaryEngine,
)
from services.nexus_news.fundamental.replay import HistoricalReplayGuard, LeakageError

UTC = timezone.utc


def evidence(*, causal: str = "g1", origin: str = "real") -> SourceEvidence:
    return SourceEvidence(
        source_id="test-source",
        source_name="Test Source",
        source_name_ar="مصدر اختبار",
        origin=origin,
        freshness="fresh",
        trust_score=90,
        quality_score=90,
        causal_group_id=causal,
        independence_group="independent-test",
    )


def factor(domain: FundamentalDomain, gold: float, *, causal: str) -> FundamentalFactorResult:
    d = FundamentalDriver(
        code=f"{domain.value}-driver",
        label_ar="عامل",
        label_en="driver",
        native_score=gold,
        gold_impact_score=gold,
        strength=abs(gold),
        confidence=90,
        explanation_ar="اختبار",
        horizon_class=HorizonClass.TACTICAL,
        sources=[evidence(causal=causal)],
    )
    return FundamentalFactorResult(
        domain=domain,
        native_score=gold,
        gold_impact_score=gold,
        direction=GoldDirection.BULLISH if gold > 0 else GoldDirection.BEARISH,
        strength=abs(gold),
        confidence=90,
        coverage_score=90,
        freshness_score=90,
        data_quality_score=90,
        reliability_score=90,
        horizon_class=HorizonClass.TACTICAL,
        primary_drivers=[d] if gold >= 0 else [],
        counter_drivers=[d] if gold < 0 else [],
        engine_version="test",
    )


def test_missing_macro_is_unavailable_not_measured_neutral():
    result = MacroEngine().evaluate([])
    assert result.metadata["state"] == "unavailable"
    assert result.coverage_score == 0
    assert result.confidence == 0


def test_hot_cpi_is_gold_bearish_not_native_sign_confusion():
    result = MacroEngine().evaluate([{
        "indicator_code": "CPI",
        "actual": 3.5,
        "forecast": 3.2,
        "source_id": "calendar_secondary",
        "source_name": "calendar",
        "source_name_ar": "تقويم",
        "origin": "real",
        "freshness": "fresh",
        "quality_score": 80,
        "trust_score": 80,
    }])
    assert result.native_score > 0
    assert result.gold_impact_score < 0
    assert result.direction == GoldDirection.BEARISH


def test_hawkish_monetary_native_positive_gold_negative():
    result = MonetaryEngine().evaluate([{
        "event_kind": "FOMC",
        "tone_score": 80,
        "previous_tone_score": 20,
        "policy_delta": 60,
        "source_id": "fed_rss",
        "source_name": "Fed",
        "source_name_ar": "الاحتياطي الفيدرالي",
        "origin": "real",
        "freshness": "fresh",
        "quality_score": 90,
        "trust_score": 100,
    }])
    assert result.native_score > 0
    assert result.gold_impact_score < 0


def test_structural_flows_do_not_enter_tactical_score():
    result = FlowsEngine().evaluate([{
        "flow_type": "CENTRAL_BANK_BUYING",
        "flow_direction": "buy",
        "strength_score": 95,
        "quality_score": 95,
        "source_id": "central_bank_gold",
        "source_name": "Official source",
        "source_name_ar": "مصدر رسمي",
        "origin": "real",
        "freshness": "fresh",
        "trust_score": 95,
    }])
    assert result.gold_impact_score == 0
    assert result.coverage_score == 0
    assert result.metadata["state"] == "structural_only"
    assert result.metadata["structural_gold_score"] > 0


def test_fusion_penalizes_duplicate_causal_evidence():
    fusion = FundamentalFusionEngine().fuse([
        factor(FundamentalDomain.MACRO, -70, causal="same-cause"),
        factor(FundamentalDomain.CROSS_ASSET, -65, causal="same-cause"),
    ], event_type="CPI")
    assert len(fusion.weights) == 2
    assert all(w.independence_factor < 1 for w in fusion.weights)


def test_blackout_high_impact_window_is_active():
    now = datetime.now(UTC)
    state = BlackoutEngine().evaluate([{
        "event_id": "cpi-1",
        "event_name": "CPI",
        "impact": "high",
        "timestamp": now + timedelta(minutes=5),
    }], now=now)
    assert state["active"] is True
    assert state["reason_code"] == "NEWS_BLACKOUT"


def test_replay_rejects_future_vintage():
    decision = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    with pytest.raises(LeakageError):
        HistoricalReplayGuard.assert_known_at(
            {"known_at": decision + timedelta(minutes=1)},
            decision,
        )


class FakeRedis:
    def __init__(self, values):
        self.values = values

    async def cache_get(self, key):
        return self.values.get(key)


def _approval_payload(**overrides):
    payload = {
        "version": 1,
        "proposal_id": "proposal-bound-1",
        "expires_at": int(time.time()) + 60,
        "symbol": "XAUUSD",
        "side": "BUY",
        "order_type": "MARKET",
        "entry": 2500.0,
        "price": 0.0,
        "sl": 2490.0,
        "tp": 2520.0,
        "size": 0.03,
        "signal_timestamp": time.time(),
        "slippage": 10,
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("symbol", "BTCUSD"),
        ("side", "SELL"),
        ("order_type", "LIMIT"),
        ("entry", 2501.0),
        ("price", 2499.0),
        ("sl", 2489.0),
        ("tp", 2521.0),
        ("size", 0.04),
        ("signal_timestamp", 1.0),
        ("proposal_id", "other-proposal"),
        ("expires_at", 1),
        ("slippage", 25),
    ],
)
def test_risk_approval_signature_rejects_changed_order_payload(monkeypatch, field, changed):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "unit-test-secret")
    monkeypatch.setenv("NEXUS_RISK_APPROVAL_SECRET", "separate-risk-approval-key-for-tests")
    approved = _approval_payload()
    signature = approval_signature(approved)
    altered = {**approved, field: changed}

    assert signature
    assert not approval_signature(altered) == signature


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("symbol", "BTCUSD"),
        ("side", "SELL"),
        ("order_type", "LIMIT"),
        ("entry", 2501.0),
        ("price", 2499.0),
        ("sl", 2489.0),
        ("tp", 2521.0),
        ("size", 0.04),
        ("signal_timestamp", 1.0),
        ("proposal_id", "other-proposal"),
        ("expires_at", 1),
        ("slippage", 25),
    ],
)
async def test_executor_guard_rejects_each_modified_approved_field(monkeypatch, field, changed):
    monkeypatch.setenv("NEXUS_TRADING_MODE", "paper")
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "unit-test-secret")
    monkeypatch.setenv("NEXUS_RISK_APPROVAL_SECRET", "separate-risk-approval-key-for-tests")
    approved = _approval_payload()
    actual = {**approved, field: changed}
    redis = FakeRedis({
        "system:kill_switch": False,
        "system:auto_trade": True,
        "fundamental:blackout": {"state": "clear", "active": False},
    })

    decision = await evaluate_executor_guard(
        redis,
        approval_payload=approved,
        execution_payload=actual,
        approval_signature_value=approval_signature(approved),
    )

    assert decision.allowed is False
    assert decision.code == GuardCode.RISK_APPROVAL_MISSING


@pytest.mark.asyncio
async def test_executor_guard_rejects_execution_terms_different_from_signed_approval(monkeypatch):
    monkeypatch.setenv("NEXUS_TRADING_MODE", "paper")
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "unit-test-secret")
    monkeypatch.setenv("NEXUS_RISK_APPROVAL_SECRET", "separate-risk-approval-key-for-tests")
    approved = _approval_payload()
    actual = {**approved, "size": 0.04}
    redis = FakeRedis({
        "system:kill_switch": False,
        "system:auto_trade": True,
        "fundamental:blackout": {"state": "clear", "active": False},
    })

    decision = await evaluate_executor_guard(
        redis,
        approval_payload=approved,
        execution_payload=actual,
        approval_signature_value=approval_signature(approved),
    )

    assert decision.allowed is False
    assert decision.code == GuardCode.RISK_APPROVAL_MISSING


@pytest.mark.asyncio
async def test_executor_hard_guard_blocks_high_impact_blackout(monkeypatch):
    monkeypatch.setenv("NEXUS_TRADING_MODE", "paper")
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "unit-test-secret")
    redis = FakeRedis({
        "system:kill_switch": False,
        "system:auto_trade": True,
        "fundamental:blackout": {
            "state": "active",
            "active": True,
            "reason_code": "NEWS_BLACKOUT",
            "reason_ar": "حدث CPI عالي التأثير",
        },
    })
    decision = await evaluate_executor_guard(
        redis,
    )
    assert decision.allowed is False
    assert decision.code == GuardCode.NEWS_BLACKOUT


@pytest.mark.asyncio
@pytest.mark.parametrize("blackout", ["clear", [], {"state": "typo", "active": False}])
async def test_executor_guard_rejects_malformed_blackout_state(monkeypatch, blackout):
    monkeypatch.setenv("NEXUS_TRADING_MODE", "paper")
    approved = _approval_payload()
    redis = FakeRedis({
        "system:kill_switch": False,
        "system:auto_trade": True,
        "fundamental:blackout": blackout,
    })

    decision = await evaluate_executor_guard(
        redis,
        approval_payload=approved,
        execution_payload=approved,
        approval_signature_value=approval_signature(approved),
    )

    assert decision.allowed is False
    assert decision.code == GuardCode.SAFETY_STATE_UNAVAILABLE


@pytest.mark.asyncio
async def test_executor_paper_mode_can_only_reach_simulated_path(monkeypatch):
    monkeypatch.setenv("NEXUS_TRADING_MODE", "paper")
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "unit-test-secret")
    monkeypatch.setenv("NEXUS_RISK_APPROVAL_SECRET", "separate-risk-approval-key-for-tests")
    approved = _approval_payload(proposal_id="proposal-2")
    redis = FakeRedis({
        "system:kill_switch": False,
        "system:auto_trade": True,
        "fundamental:blackout": {"state": "clear", "active": False},
    })
    decision = await evaluate_executor_guard(
        redis,
        approval_payload=approved,
        execution_payload=approved,
        approval_signature_value=approval_signature(approved),
    )
    assert decision.allowed is True
    assert decision.code == GuardCode.PAPER_MODE

@pytest.mark.asyncio
async def test_paper_executor_is_in_process_and_simulated_only():
    from services.nexus_executor.broker_adapter import OrderRequest, OrderSide
    from services.nexus_executor.paper_executor import PaperExecutor

    broker = PaperExecutor()
    assert await broker.connect() is True
    response = await broker.send_order(OrderRequest(symbol="XAUUSD", side=OrderSide.BUY, size=0.01, price=2500.0))
    assert response.is_success()
    assert response.broker == "paper"
    assert response.order_id.startswith("PAPER-")
    assert response.raw_response.get("simulated") is True
    positions = await broker.get_positions()
    assert len(positions) == 1

def test_fundamental_schema_contains_all_24_contract_tables():
    from pathlib import Path
    import re
    sql = Path("services/nexus_data/fundamental_schema.sql").read_text(encoding="utf-8")
    tables = set(re.findall(r"CREATE TABLE IF NOT EXISTS\s+([a-zA-Z0-9_]+)", sql, flags=re.I))
    expected = {
        "fund_sources", "source_fetch_runs", "source_health_history", "fund_events",
        "event_expectations", "data_vintages", "macro_releases", "central_bank_events",
        "news_articles", "news_nlp_analysis", "market_series_observations", "geopolitical_events",
        "flow_observations", "fundamental_factor_scores", "fundamental_fusion_results",
        "gold_impact_predictions", "prediction_reasoning_steps", "fundamental_explanations",
        "fundamental_blackout_windows", "fundamental_guard_decisions", "fundamental_event_outcomes",
        "fundamental_training_features", "model_evaluations", "fundamental_audit_log",
    }
    assert expected <= tables
    assert len(expected) == 24


def test_macro_schema_has_traceable_surprise_and_gold_fields():
    from pathlib import Path
    sql = Path("services/nexus_data/fundamental_schema.sql").read_text(encoding="utf-8")
    macro = sql.split("CREATE TABLE IF NOT EXISTS macro_releases", 1)[1].split(");", 1)[0]
    for field in (
        "actual", "forecast", "previous", "revised_previous", "surprise_absolute",
        "surprise_percent", "surprise_zscore", "historical_importance", "gold_relevance",
        "rate_implication_score", "usd_implication_score", "yield_implication_score",
        "gold_implication_score",
    ):
        assert field in macro

def test_no_docker_artifacts_remain():
    from pathlib import Path
    root = Path('.')
    assert not (root / 'docker-compose.yml').exists()
    assert not list(root.rglob('Dockerfile'))


def test_local_ai_factory_has_no_cloud_fallbacks():
    from pathlib import Path
    text = Path('shared/llm_factory.py').read_text(encoding='utf-8').lower()
    assert 'default_provider = "local"' in text
    # D18 contract refresh: the factory grew an explicit, documented Z.ai
    # provider (agents 9004 opt-in via NEXUS_LLM_PROVIDER). The safety
    # semantics are unchanged — local is the default and cloud is never a
    # silent fallback, only an explicit env selection inside the allowlist.
    assert 'supported_providers = ("local", "zai")' in text
    for forbidden in ('api.deepseek.com', 'api.openai.com', 'generativelanguage.googleapis.com'):
        assert forbidden not in text

    # Behavioural half of the golden contract: resolve_provider() must default
    # to local and must NEVER return anything outside the declared allowlist.
    import importlib
    import os
    factory = importlib.import_module('shared.llm_factory')
    old = os.environ.get('NEXUS_LLM_PROVIDER')
    try:
        os.environ.pop('NEXUS_LLM_PROVIDER', None)
        assert factory.resolve_provider() == 'local'
        os.environ['NEXUS_LLM_PROVIDER'] = 'zai'
        assert factory.resolve_provider() == 'zai'
        os.environ['NEXUS_LLM_PROVIDER'] = 'openai'
        assert factory.resolve_provider() == 'local'  # unknown ⇒ local, never cloud
    finally:
        if old is None:
            os.environ.pop('NEXUS_LLM_PROVIDER', None)
        else:
            os.environ['NEXUS_LLM_PROVIDER'] = old


def test_safe_defaults_are_paper_and_auto_trade_off():
    from pathlib import Path
    env = Path('.env.example').read_text(encoding='utf-8')
    settings = Path('config/settings.yaml').read_text(encoding='utf-8').lower()
    assert 'NEXUS_TRADING_MODE=paper' in env
    assert 'trading_mode: paper' in settings
    assert 'auto_trade_enabled: false' in settings


def test_news_ui_contains_no_live_mock_fallbacks():
    from pathlib import Path
    text = Path('dashboard/src/components/windows/NewsFeed.tsx').read_text(encoding='utf-8')
    assert 'MOCK_NEWS' not in text
    assert 'MOCK_CALENDAR' not in text
    assert 'offline — keep mock' not in text


def test_a9_prepares_order_but_does_not_call_executor():
    from pathlib import Path
    text = Path('services/nexus_agents/agents/trade_executor.py').read_text(encoding='utf-8')
    assert 'prepared_for_central_risk' in text
    assert '/api/executor/order' not in text


def test_executor_rest_has_final_guard_before_broker_send():
    from pathlib import Path
    text = Path('services/nexus_executor/main.py').read_text(encoding='utf-8')
    rest = text.split('@app.post("/api/executor/order"', 1)[1]
    assert rest.index('evaluate_executor_guard(') < rest.index('broker.send_order(order)')


def test_source_registry_declares_required_five_domain_sources():
    from services.nexus_news.fundamental.source_registry import SOURCE_BY_ID
    for sid in ('bls','bea','fred','fed_rss','cftc','treasury','world_bank','imf','gold_etf','central_bank_gold','market_flow'):
        assert sid in SOURCE_BY_ID


def test_blackout_id_is_stable_for_same_event_window():
    now = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
    event = {
        "event_id": "cpi-stable",
        "event_name": "CPI",
        "impact": "high",
        "timestamp": now + timedelta(minutes=5),
    }
    engine = BlackoutEngine()
    a = engine.evaluate([event], now=now)
    b = engine.evaluate([event], now=now)
    assert a["blackout_id"] == b["blackout_id"]


def test_api_gateway_resets_auto_trade_off_on_startup():
    from pathlib import Path
    text = Path('services/nexus_api/main.py').read_text(encoding='utf-8')
    lifespan = text.split('async def lifespan', 1)[1].split('# ── App', 1)[0]
    assert 'cache_set("system:auto_trade", False' in lifespan


@pytest.mark.asyncio
async def test_asset_registry_seed_failure_stops_fundamental_startup(monkeypatch):
    from services.nexus_news.fundamental import runtime as fundamental_runtime

    runtime = fundamental_runtime.FundamentalRuntime.__new__(fundamental_runtime.FundamentalRuntime)
    persisted: list[tuple[str, dict]] = []

    async def persist(table: str, record: dict) -> bool:
        persisted.append((table, record))
        return False if table == "asset_registry" else True

    monkeypatch.setattr(fundamental_runtime, "indicator_catalog_records", lambda: [])
    monkeypatch.setattr(fundamental_runtime, "asset_records", lambda: [{"asset_id": "BTCUSD"}])
    monkeypatch.setattr(fundamental_runtime, "asset_factor_profile_records", lambda: [])
    monkeypatch.setattr(fundamental_runtime, "knowledge_seed", lambda: ([], []))
    monkeypatch.setattr(runtime, "_persist", persist)

    with pytest.raises(RuntimeError, match="asset_registry.*BTCUSD"):
        await runtime._seed_v5_governance()

    assert persisted == [("asset_registry", {"asset_id": "BTCUSD"})]
