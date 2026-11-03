"""Tests for shared.config_contract — Phase 6 config contract (NEXUS_MASTER_PLAN)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from dotenv import dotenv_values

from shared.config_contract import (
    CONTRACT_ENV_KEYS,
    ConfigContractError,
    validate_config_contract,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def clean_env(monkeypatch):
    """Delete every contract-scanned key so host-shell env cannot leak in."""
    for key in CONTRACT_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


class TestDefaults:
    def test_default_unset_env_is_clean(self, clean_env):
        assert validate_config_contract() == []

    def test_empty_string_values_are_treated_as_absent(self, clean_env):
        clean_env.setenv("NEXUS_TRADING_MODE", "")
        clean_env.setenv("NEXUS_RISK_PER_TRADE", "   ")
        assert validate_config_contract() == []


class TestRiskPerTradeBounds:
    def test_out_of_bounds_reports_violation_without_raising(self, clean_env):
        clean_env.setenv("NEXUS_RISK_PER_TRADE", "0.05")
        violations = validate_config_contract()
        assert any(v.key == "NEXUS_RISK_PER_TRADE" for v in violations)

    def test_in_bounds_value_is_silent(self, clean_env):
        clean_env.setenv("NEXUS_RISK_PER_TRADE", "0.01")
        assert validate_config_contract() == []

    def test_enforce_mode_raises_on_same_violation(self, clean_env):
        clean_env.setenv("NEXUS_RISK_PER_TRADE", "0.05")
        clean_env.setenv("NEXUS_CONFIG_CONTRACT", "enforce")
        with pytest.raises(ConfigContractError) as excinfo:
            validate_config_contract()
        assert any(v.key == "NEXUS_RISK_PER_TRADE" for v in excinfo.value.violations)

    def test_enforce_with_clean_env_does_not_raise(self, clean_env):
        clean_env.setenv("NEXUS_CONFIG_CONTRACT", "enforce")
        assert validate_config_contract() == []


class TestSecretIsolation:
    def test_equal_non_empty_secrets_are_a_violation(self, clean_env):
        clean_env.setenv("NEXUS_RISK_APPROVAL_SECRET", "shared-secret-value")
        clean_env.setenv("NEXUS_INTERNAL_API_SECRET", "shared-secret-value")
        violations = validate_config_contract()
        assert any(v.key == "NEXUS_RISK_APPROVAL_SECRET" for v in violations)

    def test_different_secrets_are_silent(self, clean_env):
        clean_env.setenv("NEXUS_RISK_APPROVAL_SECRET", "approval-key-aaaaaaaaaaaaaaaaaaaaaaaa")
        clean_env.setenv("NEXUS_INTERNAL_API_SECRET", "internal-key-bbbbbbbbbbbbbbbbbbbbbb")
        assert validate_config_contract() == []

    def test_one_secret_empty_is_silent(self, clean_env):
        clean_env.setenv("NEXUS_RISK_APPROVAL_SECRET", "")
        clean_env.setenv("NEXUS_INTERNAL_API_SECRET", "internal-key-bbbbbbbbbbbbbbbbbbbbbb")
        assert validate_config_contract() == []


class TestPortUniqueness:
    def test_duplicate_ports_reported(self, clean_env):
        clean_env.setenv("REDIS_URL", "redis://127.0.0.1:6379")
        clean_env.setenv("NEXUS_LOCAL_LLM_URL", "http://127.0.0.1:6379/v1")
        violations = validate_config_contract()
        assert any("6379" in v.message for v in violations)

    def test_unique_ports_are_silent(self, clean_env):
        clean_env.setenv("REDIS_URL", "redis://127.0.0.1:6379")
        clean_env.setenv("IBKR_PORT", "7497")
        clean_env.setenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
        assert validate_config_contract() == []

    def test_urls_without_explicit_port_do_not_collide(self, clean_env):
        clean_env.setenv("FED_RSS_URL", "https://www.federalreserve.gov/feeds/press_all.xml")
        clean_env.setenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
        assert validate_config_contract() == []


class TestModeSwitch:
    def test_off_via_env_skips_validation(self, clean_env):
        clean_env.setenv("NEXUS_CONFIG_CONTRACT", "off")
        clean_env.setenv("NEXUS_RISK_PER_TRADE", "0.05")
        assert validate_config_contract() == []

    def test_off_via_argument_skips_validation(self, clean_env):
        clean_env.setenv("NEXUS_RISK_PER_TRADE", "0.05")
        assert validate_config_contract("off") == []

    def test_unknown_mode_treated_as_warn_with_violation(self, clean_env):
        clean_env.setenv("NEXUS_CONFIG_CONTRACT", "banana")
        clean_env.setenv("NEXUS_RISK_PER_TRADE", "0.05")
        violations = validate_config_contract()
        keys = [v.key for v in violations]
        assert "NEXUS_CONFIG_CONTRACT" in keys
        assert "NEXUS_RISK_PER_TRADE" in keys


class TestAutoTradeInvariant:
    def test_paper_mode_with_auto_trade_enabled_is_a_violation(self, clean_env):
        clean_env.setenv("NEXUS_TRADING_MODE", "paper")
        clean_env.setenv("NEXUS_SETTINGS__AUTO_TRADE_ENABLED", "true")
        violations = validate_config_contract()
        assert any(v.key == "NEXUS_SETTINGS__AUTO_TRADE_ENABLED" for v in violations)

    def test_unset_mode_defaults_to_paper_and_flags_auto_trade(self, clean_env):
        clean_env.setenv("NEXUS_SETTINGS__AUTO_TRADE_ENABLED", "1")
        violations = validate_config_contract()
        assert any(v.key == "NEXUS_SETTINGS__AUTO_TRADE_ENABLED" for v in violations)

    def test_live_mode_with_auto_trade_enabled_is_silent(self, clean_env):
        clean_env.setenv("NEXUS_TRADING_MODE", "live")
        clean_env.setenv("NEXUS_SETTINGS__AUTO_TRADE_ENABLED", "true")
        assert validate_config_contract() == []


class TestGoldenEnvExample:
    def test_env_example_derived_defaults_produce_no_violations(self, clean_env):
        values = dotenv_values(ROOT / ".env.example")
        assert values.get("NEXUS_CONFIG_CONTRACT") == "warn"
        for key, value in values.items():
            if key:
                clean_env.setenv(key, value or "")
        assert validate_config_contract() == []


class TestRunPyHook:
    def test_run_py_calls_validate_config_contract_after_validate_env(self):
        source = (ROOT / "run.py").read_text(encoding="utf-8")
        assert "from shared.config_contract import validate_config_contract" in source
        match = re.search(
            r"def _check_prerequisites\(.*?(?=\ndef |\Z)", source, flags=re.S
        )
        assert match, "_check_prerequisites not found in run.py"
        body = match.group(0)
        assert "_validate_env(env)" in body
        assert "validate_config_contract()" in body
        assert body.index("_validate_env(env)") < body.index("validate_config_contract()")
