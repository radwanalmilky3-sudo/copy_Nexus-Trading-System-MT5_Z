"""Golden risk-decision fixtures (Phase 0.2).

Loads tests/fixtures/golden_decisions.json and replays every scenario through
RulesEngine() with default RulesEngineConfig() (no YAML loader, no runtime
overrides). Wall-clock checks (check_friday_close, check_news_blackout) are
made deterministic by patching rules_engine.datetime with a fixed-time
subclass for each scenario's mock_time_utc.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

from services.nexus_risk import rules_engine as rules_engine_mod
from services.nexus_risk.rules_engine import RulesEngine
from shared.models import TradeProposal

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "golden_decisions.json"

with open(FIXTURE_PATH, encoding="utf-8") as _f:
    _FIXTURES: dict = json.load(_f)

SCENARIOS: list[dict] = _FIXTURES["scenarios"]
SCENARIO_IDS: list[str] = [s["id"] for s in SCENARIOS]


def _fixed_datetime(mock_time_utc: str) -> type[datetime]:
    """Build a datetime subclass whose now() always returns the pinned time.

    Subclassing keeps fromisoformat and tz handling intact, which
    check_news_blackout needs for parsing event timestamps.
    """
    fixed = datetime.fromisoformat(mock_time_utc)

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed if tz is None else fixed.astimezone(tz)

    return _FixedDateTime


def _run_scenario(scenario: dict) -> tuple[bool, list]:
    engine = RulesEngine()
    engine.set_upcoming_news(list(scenario.get("upcoming_news") or []))
    proposal = TradeProposal(**scenario["proposal"])
    fixed_dt = _fixed_datetime(scenario["mock_time_utc"])
    with mock.patch.object(rules_engine_mod, "datetime", fixed_dt):
        return engine.check_all_rules(proposal, dict(scenario["current_state"]))


class TestGoldenDecisionsFixture:
    def test_fixture_metadata(self):
        assert _FIXTURES["version"] == 1
        assert _FIXTURES["created_for_phase"] == 0
        assert "RulesEngineConfig()" in _FIXTURES["config_note"]
        assert len(SCENARIOS) >= 8

    def test_all_scenarios_have_expected_block(self):
        for scenario in SCENARIOS:
            expected = scenario["expected"]
            assert isinstance(expected["passed"], bool), scenario["id"]
            assert isinstance(expected["violation_rules"], list), scenario["id"]
            assert expected["violation_rules"] == sorted(expected["violation_rules"]), (
                f"{scenario['id']}: violation_rules must be stored sorted"
            )

    def test_aggressive_trading_flag_off_for_determinism(self):
        assert rules_engine_mod._AGGRESSIVE_TRADING is False, (
            "NEXUS_AGGRESSIVE_TRADING must be unset/false for golden fixtures — "
            "it loosens limits and skips check_friday_close"
        )


class TestGoldenDecisions:
    @pytest.mark.parametrize("scenario", SCENARIOS, ids=SCENARIO_IDS)
    def test_golden_decision(self, scenario: dict):
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
