"""Phase 3 portfolio gates (G4) + honest circuit breakers (G5) — engine side.

Golden parity reuses the Phase 0.2 harness from
``tests/test_risk/test_golden_decisions.py`` (no duplicated fixture logic):
every new ``RulesEngineConfig`` field defaults to None, so default-config
decisions must match ``tests/fixtures/golden_decisions.json`` exactly.
"""
from __future__ import annotations

import math
from unittest import mock

import pytest

from services.nexus_risk import rules_engine as rules_engine_mod
from services.nexus_risk.rules_engine import (
    CorrelationSnapshot,
    RulesEngine,
    RulesEngineConfig,
)
from shared.config_loader import ConfigLoader
from shared.models import TradeProposal

try:  # package layout differs between pytest rootdir and direct module runs
    from tests.test_risk.test_golden_decisions import (
        SCENARIOS,
        SCENARIO_IDS,
        _fixed_datetime,
        _run_scenario,
    )
except ImportError:  # pragma: no cover
    from test_risk.test_golden_decisions import (  # type: ignore[no-redef]
        SCENARIOS,
        SCENARIO_IDS,
        _fixed_datetime,
        _run_scenario,
    )

# Monday noon UTC — friday_close / news_blackout stay deterministic.
FIXED_TIME = "2024-01-08T12:00:00+00:00"

NEW_CFG_FIELDS = (
    "max_drawdown_from_peak_pct",
    "max_portfolio_open_risk_pct",
    "max_gross_leverage",
    "max_net_currency_exposure_pct",
    "correlation_threshold",
    "correlation_lookback_bars",
    "max_same_direction_cluster",
)

NEW_GATE_RULES = {
    "max_drawdown_from_peak",
    "portfolio_open_risk",
    "max_gross_leverage",
    "max_net_currency_exposure",
    "portfolio_correlation",
    "correlation_lookback",
    "max_same_direction_cluster",
}

BASE_STATE = {
    "balance": 10_000.0,
    "equity": 10_000.0,
    "daily_loss_pct": 0.0,
    "weekly_dd_pct": 0.0,
    "open_positions_count": 0,
    "open_positions": [],
    "current_spread": 0.0001,
    "avg_spread": 0.0001,
    "expected_price": 1.1,
    "actual_price": 1.1,
}


def _engine(**overrides) -> RulesEngine:
    engine = RulesEngine()
    for key, value in overrides.items():
        setattr(engine._cfg, key, value)
    return engine


def _proposal(symbol: str = "EURUSD", direction: str = "BUY") -> TradeProposal:
    is_buy = direction.upper() == "BUY"
    return TradeProposal(
        id=f"pg-{symbol}-{direction}",
        symbol=symbol,
        direction=direction,
        entry=1.1,
        sl=1.098 if is_buy else 1.102,
        tp1=1.104 if is_buy else 1.096,
        conviction=0.8,
    )


def _check(engine: RulesEngine, state: dict, proposal: TradeProposal | None = None):
    fixed = _fixed_datetime(FIXED_TIME)
    with mock.patch.object(rules_engine_mod, "datetime", fixed):
        return engine.check_all_rules(proposal or _proposal(), dict(state))


def _breakers(engine: RulesEngine, state: dict) -> dict[str, dict]:
    fixed = _fixed_datetime(FIXED_TIME)
    with mock.patch.object(rules_engine_mod, "datetime", fixed):
        return {row["name"]: row for row in engine.get_active_circuit_breakers(dict(state))}


class _StubLoader:
    """Minimal ConfigLoader stand-in returning a fixed raw YAML dict."""

    def __init__(self, raw: dict) -> None:
        self._raw = raw

    def _load_yaml(self, filename: str) -> dict:
        return self._raw


# ── (a) default config ⇒ golden behaviour unchanged ──────────────────────────


class TestGoldenParityWithDefaultConfig:
    def test_default_config_all_new_fields_none(self):
        cfg = RulesEngineConfig()
        for name in NEW_CFG_FIELDS:
            assert getattr(cfg, name) is None, name

    @pytest.mark.parametrize("scenario", SCENARIOS, ids=SCENARIO_IDS)
    def test_golden_decision_unchanged(self, scenario: dict):
        passed, violations = _run_scenario(scenario)
        actual_rules = sorted(v.rule for v in violations)
        expected = scenario["expected"]

        assert passed is expected["passed"], (
            f"{scenario['id']}: expected passed={expected['passed']}, "
            f"got {passed} (rules={actual_rules})"
        )
        assert actual_rules == expected["violation_rules"], (
            f"{scenario['id']}: expected violations {expected['violation_rules']}, "
            f"got {actual_rules}"
        )

    @pytest.mark.parametrize("scenario", SCENARIOS, ids=SCENARIO_IDS)
    def test_no_new_gate_violations_under_default_config(self, scenario: dict):
        _, violations = _run_scenario(scenario)
        assert not ({v.rule for v in violations} & NEW_GATE_RULES), scenario["id"]

    def test_clean_state_with_all_new_state_keys_still_passes(self):
        """New state keys present but cfg None ⇒ still a clean approve."""
        state = dict(BASE_STATE)
        state.update(
            equity_peak=12_000.0,
            equity_peak_day="2024-01-08",
            open_risk_amount=500.0,
            proposed_risk_amount=50.0,
            gross_leverage=4.0,
            net_currency_exposure_pct=50.0,
            correlation_snapshot={"pairs": {"EURUSD:GBPUSD": 0.99}},
            same_direction_count=9,
        )
        passed, violations = _check(_engine(), state)
        assert passed is True
        assert violations == []


# ── YAML loader tolerance (null / absent / unparseable) ──────────────────────


class TestYamlLoaderTolerance:
    def test_null_keys_keep_gates_disabled(self):
        raw = {"capital": {name: None for name in NEW_CFG_FIELDS}}
        engine = RulesEngine(config_loader=_StubLoader(raw))
        for name in NEW_CFG_FIELDS:
            assert getattr(engine._cfg, name) is None, name

    def test_missing_capital_section_is_valid(self):
        engine = RulesEngine(config_loader=_StubLoader({"execution": {}}))
        for name in NEW_CFG_FIELDS:
            assert getattr(engine._cfg, name) is None, name

    def test_numeric_values_are_loaded(self, monkeypatch):
        monkeypatch.setenv("NEXUS_RISK_PORTFOLIO_GATES", "1")
        raw = {"capital": {
            "max_drawdown_from_peak_pct": 12.5,
            "max_portfolio_open_risk_pct": 3,
            "max_gross_leverage": 2.5,
            "max_net_currency_exposure_pct": 40,
            "correlation_threshold": 0.8,
            "correlation_lookback_bars": 50,
            "max_same_direction_cluster": 4,
        }}
        engine = RulesEngine(config_loader=_StubLoader(raw))
        assert engine._cfg.max_drawdown_from_peak_pct == 12.5
        assert engine._cfg.max_portfolio_open_risk_pct == 3.0
        assert engine._cfg.max_gross_leverage == 2.5
        assert engine._cfg.max_net_currency_exposure_pct == 40.0
        assert engine._cfg.correlation_threshold == 0.8
        assert engine._cfg.correlation_lookback_bars == 50
        assert engine._cfg.max_same_direction_cluster == 4

    @pytest.mark.parametrize("flag", ["", "0", "off", "false", "no"])
    def test_master_flag_off_ignores_populated_capital(self, monkeypatch, flag):
        monkeypatch.setenv("NEXUS_RISK_PORTFOLIO_GATES", flag)
        raw = {"capital": {"max_drawdown_from_peak_pct": 12.5, "max_gross_leverage": 2.5}}
        engine = RulesEngine(config_loader=_StubLoader(raw))
        for name in NEW_CFG_FIELDS:
            assert getattr(engine._cfg, name) is None, name

    def test_unparseable_value_degrades_to_none(self, monkeypatch):
        monkeypatch.setenv("NEXUS_RISK_PORTFOLIO_GATES", "1")
        engine = RulesEngine(config_loader=_StubLoader({"capital": {"max_gross_leverage": "abc"}}))
        assert engine._cfg.max_gross_leverage is None

    def test_shipped_risk_rules_yaml_keeps_gates_disabled(self):
        engine = RulesEngine(config_loader=ConfigLoader())
        for name in NEW_CFG_FIELDS:
            assert getattr(engine._cfg, name) is None, name

    def test_public_loader_contract_unaffected_by_null_keys(self):
        cfg = ConfigLoader().load_risk_rules()
        assert cfg["max_risk_per_trade_pct"] == 2.0


# ── (b) peak drawdown gate ───────────────────────────────────────────────────


class TestDrawdownFromPeakGate:
    def test_skipped_when_cfg_none(self):
        assert _engine().check_drawdown_from_peak(12_000.0, 6_000.0) is None

    def test_blocks_when_exceeded(self):
        v = _engine(max_drawdown_from_peak_pct=10.0).check_drawdown_from_peak(
            12_000.0, 10_000.0, day="2024-01-08",
        )
        assert v is not None
        assert v.rule == "max_drawdown_from_peak"
        assert v.current_value == pytest.approx(16.67, abs=0.01)
        assert v.limit_value == 10.0

    def test_passes_below_threshold(self):
        assert _engine(max_drawdown_from_peak_pct=10.0).check_drawdown_from_peak(
            10_000.0, 9_500.0,
        ) is None

    def test_at_threshold_blocks_like_daily_weekly(self):
        v = _engine(max_drawdown_from_peak_pct=10.0).check_drawdown_from_peak(
            10_000.0, 9_000.0,
        )
        assert v is not None and v.current_value == 10.0

    def test_unknown_peak_skips(self):
        assert _engine(max_drawdown_from_peak_pct=10.0).check_drawdown_from_peak(
            None, 5_000.0,
        ) is None

    def test_blocks_through_check_all_rules(self):
        engine = _engine(max_drawdown_from_peak_pct=10.0)
        state = dict(BASE_STATE)
        state.update(equity_peak=12_000.0, equity_peak_day="2024-01-05")
        passed, violations = _check(engine, state)
        assert passed is False
        assert [v.rule for v in violations] == ["max_drawdown_from_peak"]


# ── (c) portfolio open-risk budget (remaining, not total) ────────────────────


class TestOpenRiskGate:
    def test_skipped_when_cfg_none(self):
        assert _engine().check_portfolio_open_risk(10_000.0, 10_000.0, 500.0) is None

    def test_full_budget_consumed_blocks_new_trade(self):
        # budget = 10_000 × 2% = 200; already 200 open ⇒ remaining 0 ⇒ block.
        v = _engine(max_portfolio_open_risk_pct=2.0).check_portfolio_open_risk(
            200.0, 10_000.0,
        )
        assert v is not None and v.rule == "portfolio_open_risk"

    def test_partially_consumed_over_remaining_blocks(self):
        # remaining = 200 − 150 = 50; proposed 60 > 50 ⇒ block.
        v = _engine(max_portfolio_open_risk_pct=2.0).check_portfolio_open_risk(
            150.0, 10_000.0, proposed_risk_amount=60.0,
        )
        assert v is not None and v.rule == "portfolio_open_risk"

    def test_partially_consumed_within_remaining_passes(self):
        assert _engine(max_portfolio_open_risk_pct=2.0).check_portfolio_open_risk(
            150.0, 10_000.0, proposed_risk_amount=50.0,
        ) is None
        assert _engine(max_portfolio_open_risk_pct=2.0).check_portfolio_open_risk(
            150.0, 10_000.0, proposed_risk_amount=40.0,
        ) is None

    def test_remaining_budget_helper_for_size_clamp(self):
        engine = _engine(max_portfolio_open_risk_pct=2.0)
        assert engine.remaining_open_risk_budget(10_000.0, 150.0) == pytest.approx(50.0)
        assert engine.remaining_open_risk_budget(10_000.0, 250.0) == pytest.approx(-50.0)
        assert engine.remaining_open_risk_budget(0.0, 0.0) == 0.0
        assert math.isinf(_engine().remaining_open_risk_budget(10_000.0, 150.0))

    def test_full_budget_consumed_blocks_through_check_all_rules(self):
        engine = _engine(max_portfolio_open_risk_pct=2.0)
        state = dict(BASE_STATE)
        state["open_risk_amount"] = 250.0
        passed, violations = _check(engine, state)
        assert passed is False
        assert [v.rule for v in violations] == ["portfolio_open_risk"]


# ── (d) gross leverage gate on/off ───────────────────────────────────────────


class TestGrossLeverageGate:
    def test_off_when_cfg_none(self):
        assert _engine().check_gross_leverage(10.0) is None

    def test_missing_state_value_skips(self):
        assert _engine(max_gross_leverage=2.0).check_gross_leverage(None) is None

    def test_blocks_when_exceeded(self):
        v = _engine(max_gross_leverage=2.0).check_gross_leverage(2.5)
        assert v is not None and v.rule == "max_gross_leverage"

    def test_at_limit_blocks(self):
        assert _engine(max_gross_leverage=2.0).check_gross_leverage(2.0) is not None

    def test_below_limit_passes(self):
        assert _engine(max_gross_leverage=2.0).check_gross_leverage(1.5) is None

    def test_gate_on_through_check_all_rules(self):
        engine = _engine(max_gross_leverage=2.0)
        state = dict(BASE_STATE)
        state["gross_leverage"] = 3.0
        passed, violations = _check(engine, state)
        assert passed is False
        assert [v.rule for v in violations] == ["max_gross_leverage"]

    def test_gate_off_through_check_all_rules(self):
        state = dict(BASE_STATE)
        state["gross_leverage"] = 3.0
        passed, _ = _check(_engine(), state)
        assert passed is True


# ── net currency exposure / correlation / cluster (behind cfg fields) ────────


class TestNetCurrencyExposureGate:
    def test_skipped_when_cfg_none(self):
        assert _engine().check_net_currency_exposure(90.0) is None

    def test_blocks_when_abs_exceeded(self):
        v = _engine(max_net_currency_exposure_pct=40.0).check_net_currency_exposure(-45.0)
        assert v is not None and v.rule == "max_net_currency_exposure"

    def test_below_limit_passes(self):
        assert _engine(max_net_currency_exposure_pct=40.0).check_net_currency_exposure(30.0) is None


class TestPortfolioCorrelationGate:
    def test_skipped_when_cfg_none(self):
        snap = CorrelationSnapshot(pairs={"EURUSD:GBPUSD": 0.99})
        assert _engine().check_portfolio_correlation(snap) is None

    def test_skipped_when_snapshot_missing(self):
        assert _engine(correlation_threshold=0.8).check_portfolio_correlation(None) is None

    def test_pairs_over_threshold_blocks(self):
        snap = CorrelationSnapshot(pairs={"EURUSD:GBPUSD": 0.85})
        v = _engine(correlation_threshold=0.8).check_portfolio_correlation(snap)
        assert v is not None and v.rule == "portfolio_correlation"

    def test_matrix_form_blocks(self):
        snap = CorrelationSnapshot(
            symbols=["EURUSD", "GBPUSD"], matrix=[[1.0, 0.9], [0.9, 1.0]],
        )
        v = _engine(correlation_threshold=0.8).check_portfolio_correlation(snap)
        assert v is not None and v.current_value == pytest.approx(0.9)

    def test_plain_dict_form_accepted(self):
        v = _engine(correlation_threshold=0.8).check_portfolio_correlation(
            {"pairs": {"EURUSD:GBPUSD": 0.85}, "lookback_bars": 100},
        )
        assert v is not None

    def test_under_threshold_passes(self):
        snap = CorrelationSnapshot(pairs={"EURUSD:USDJPY": 0.2})
        assert _engine(correlation_threshold=0.8).check_portfolio_correlation(snap) is None

    def test_insufficient_lookback_rejected(self):
        engine = _engine(correlation_threshold=0.8, correlation_lookback_bars=100)
        snap = CorrelationSnapshot(pairs={"EURUSD:GBPUSD": 0.1}, lookback_bars=20)
        v = engine.check_portfolio_correlation(snap)
        assert v is not None and v.rule == "correlation_lookback"


class TestSameDirectionClusterGate:
    def test_skipped_when_cfg_none(self):
        assert _engine().check_same_direction_cluster(10, direction="BUY") is None

    def test_at_limit_blocks(self):
        v = _engine(max_same_direction_cluster=3).check_same_direction_cluster(3, "BUY")
        assert v is not None and v.rule == "max_same_direction_cluster"

    def test_below_limit_passes(self):
        assert _engine(max_same_direction_cluster=3).check_same_direction_cluster(2, "BUY") is None

    def test_derived_from_open_positions_in_check_all_rules(self):
        engine = _engine(max_same_direction_cluster=3)
        state = dict(BASE_STATE)
        state["open_positions_count"] = 2
        state["open_positions"] = [
            {"symbol": "XAUUSD", "side": "BUY", "size": 0.1, "status": "open"},
            {"symbol": "USDJPY", "side": "BUY", "size": 0.1, "status": "open"},
        ]
        passed, violations = _check(engine, state, _proposal("EURUSD", "BUY"))
        assert passed is False
        assert [v.rule for v in violations] == ["max_same_direction_cluster"]

    def test_explicit_state_count_overrides_derivation(self):
        engine = _engine(max_same_direction_cluster=3)
        state = dict(BASE_STATE)
        state["same_direction_count"] = 5
        passed, violations = _check(engine, state, _proposal("EURUSD", "SELL"))
        assert passed is False
        assert violations[0].current_value == 5


# ── (f) gate order: peak-DD before open-risk ─────────────────────────────────


class TestGateOrder:
    def test_peak_dd_triggers_before_open_risk(self):
        engine = _engine(
            max_drawdown_from_peak_pct=10.0,
            max_portfolio_open_risk_pct=2.0,
        )
        state = dict(BASE_STATE)
        state.update(equity_peak=12_000.0, open_risk_amount=300.0)
        passed, violations = _check(engine, state)
        rules = [v.rule for v in violations]
        assert passed is False
        assert rules == ["max_drawdown_from_peak", "portfolio_open_risk"]

    def test_peak_dd_before_later_gates(self):
        engine = _engine(
            max_drawdown_from_peak_pct=10.0,
            max_gross_leverage=2.0,
            max_same_direction_cluster=1,
        )
        state = dict(BASE_STATE)
        state.update(equity_peak=12_000.0, gross_leverage=3.0)
        _, violations = _check(engine, state)
        rules = [v.rule for v in violations]
        assert rules.index("max_drawdown_from_peak") < rules.index("max_gross_leverage")
        assert rules.index("max_drawdown_from_peak") < rules.index("max_same_direction_cluster")


# ── (e) breaker rows report real state (no hardcoded triggered:False) ────────


BASE_BREAKER_STATE = {
    "daily_loss_pct": 0.0,
    "weekly_dd_pct": 0.0,
    "open_positions_count": 0,
    "tilt_status": "NORMAL",
    "balance": 10_000.0,
    "equity": 10_000.0,
}

MAIN_PY_OWNED_ROWS = (
    "anti_stacking",
    "anti_revenge",
    "session_gate",
    "min_conviction",
    "trade_cooldown",
)


class TestBreakerRowsHonestState:
    @pytest.mark.parametrize("name", MAIN_PY_OWNED_ROWS)
    def test_main_py_owned_rows_reflect_tracked_state(self, name):
        engine = _engine()
        assert _breakers(engine, BASE_BREAKER_STATE)[name]["triggered"] is False

        engine.set_breaker_state(name, True, f"{name} active")
        row = _breakers(engine, BASE_BREAKER_STATE)[name]
        assert row["triggered"] is True
        assert row["reason"] == f"{name} active"
        assert row["triggered_at"] is not None

        engine.clear_breaker_state(name)
        assert _breakers(engine, BASE_BREAKER_STATE)[name]["triggered"] is False

    @pytest.mark.parametrize("name", MAIN_PY_OWNED_ROWS)
    def test_per_call_state_override_supported(self, name):
        state = dict(BASE_BREAKER_STATE)
        state["breaker_state"] = {name: {"triggered": True, "reason": f"{name} live"}}
        row = _breakers(_engine(), state)[name]
        assert row["triggered"] is True
        assert row["reason"] == f"{name} live"

    def test_live_computation_cannot_be_masked_by_tracked_state(self):
        engine = _engine()
        engine.set_breaker_state("daily_loss_limit", False)
        state = dict(BASE_BREAKER_STATE)
        state["daily_loss_pct"] = -6.0  # over the 5% default limit
        assert _breakers(engine, state)["daily_loss_limit"]["triggered"] is True

    def test_spread_limit_row_computed_from_state(self):
        state = dict(BASE_BREAKER_STATE)
        state.update(current_spread=0.0004, avg_spread=0.0001)  # 4x > 2.0x
        row = _breakers(_engine(), state)["spread_limit"]
        assert row["triggered"] is True
        assert "4.0x" in row["reason"]

    def test_correlation_limit_row_computed_from_open_positions(self):
        state = dict(BASE_BREAKER_STATE)
        state["open_positions_count"] = 2
        state["open_positions"] = [
            {"symbol": "EURUSD", "side": "BUY", "size": 0.1, "status": "open"},
            {"symbol": "GBPUSD", "side": "BUY", "size": 0.1, "status": "open"},
        ]
        row = _breakers(_engine(), state)["correlation_limit"]
        assert row["triggered"] is True
        assert "0.85" in row["reason"]

    def test_daily_trade_limit_row_computed_from_counters(self):
        state = dict(BASE_BREAKER_STATE)
        state.update(daily_trade_count=3, max_daily_trades=5)
        assert _breakers(_engine(), state)["daily_trade_limit"]["triggered"] is False
        state.update(daily_trade_count=5)
        assert _breakers(_engine(), state)["daily_trade_limit"]["triggered"] is True

    def test_portfolio_gate_rows_respect_cfg_and_state(self):
        engine = _engine(
            max_drawdown_from_peak_pct=10.0,
            max_portfolio_open_risk_pct=2.0,
        )
        state = dict(BASE_BREAKER_STATE)
        state.update(equity_peak=12_000.0, open_risk_amount=300.0)
        rows = _breakers(engine, state)
        assert rows["drawdown_from_peak"]["triggered"] is True
        assert rows["portfolio_open_risk"]["triggered"] is True

        # cfg None ⇒ gate skipped ⇒ row honestly inactive even with data present.
        rows_off = _breakers(_engine(), state)
        assert rows_off["drawdown_from_peak"]["triggered"] is False
        assert rows_off["portfolio_open_risk"]["triggered"] is False

    def test_triggered_rows_always_carry_reason_and_timestamp(self):
        state = dict(BASE_BREAKER_STATE)
        state.update(
            daily_loss_pct=-6.0,
            tilt_status="TILT",
            current_spread=0.0004,
            avg_spread=0.0001,
        )
        for row in _breakers(_engine(), state).values():
            if row["triggered"]:
                assert row["reason"], row["name"]
                assert row["triggered_at"], row["name"]
            else:
                assert row["triggered_at"] is None, row["name"]
                assert row["reason"] == "", row["name"]
