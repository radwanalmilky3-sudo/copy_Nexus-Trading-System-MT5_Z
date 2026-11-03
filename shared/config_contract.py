"""
Nexus Trader — Phase 6 configuration contract (NEXUS_MASTER_PLAN).

Additive, read-only validation of environment configuration. Every modelled
field is optional (``None``), so a missing or empty key never produces a
violation by itself; only present-but-wrong values are reported.

Modes (``NEXUS_CONFIG_CONTRACT`` env var, or the explicit ``mode`` argument):

* ``off``     — skip validation entirely and return ``[]``.
* ``warn``    — compute violations, log each one with structlog and return the
                list; this path NEVER raises.
* ``enforce`` — compute, log and raise :class:`ConfigContractError` when any
                violation exists (fail closed).

An unknown mode value is treated as ``warn`` and is itself reported as a
violation so the misconfiguration stays visible.

Invariants (cross-field; evaluated after field validation, returned as
violations and never raised directly):

(a) PAPER ⇒ auto-trade stays off. ``NEXUS_TRADING_MODE`` resolves to ``paper``
    when unset (shared/safety.py:43-44), and in that case the only env-level
    auto-trade switch — ``NEXUS_SETTINGS__AUTO_TRADE_ENABLED``, the
    ``NEXUS_SETTINGS__`` prefix override of ``config/settings.yaml``
    ``auto_trade_enabled`` applied by shared/config_loader.py:312-319 — must
    not hold a truthy value. Runtime auto-trade state itself lives in Redis
    (``system:auto_trade``), which the API gateway resets to false at startup
    (services/nexus_api/main.py:91); that runtime key is outside this env
    contract.
(b) ``NEXUS_RISK_APPROVAL_SECRET`` must differ from
    ``NEXUS_INTERNAL_API_SECRET`` when both are non-empty (the same isolation
    run.py ``_validate_env`` and shared/safety.py:78 already enforce).
(c) Ports parsed from the PORT/URL key inventory of ``.env.example`` must be
    unique across those keys (bare ``*_PORT`` ints and explicit
    ``scheme://host:port`` URLs).
"""
from __future__ import annotations

import os
from typing import Any, Literal
from urllib.parse import urlsplit

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from shared.constants import SUPPORTED_TIMEFRAMES

logger = structlog.get_logger(__name__)

MODE_OFF = "off"
MODE_WARN = "warn"
MODE_ENFORCE = "enforce"
_MODES = (MODE_OFF, MODE_WARN, MODE_ENFORCE)

# Values pydantic's lax bool parsing accepts as True; exactly these make
# config_loader SettingsSchema coerce auto_trade_enabled=True (invariant a).
_TRUTHY = frozenset({"1", "true", "t", "yes", "y", "on"})

# PORT/URL key inventory of .env.example (hardcoded so unrelated shell vars
# such as a Node ``PORT`` can never trigger invariant (c)).
_PORT_SCAN_KEYS: tuple[str, ...] = (
    "REDIS_URL",                    # .env.example:28   redis://localhost:6379
    "IBKR_PORT",                    # .env.example:55   7497
    "NEXUS_LOCAL_LLM_URL",          # .env.example:61   http://127.0.0.1:11434/v1
    "MLFLOW_TRACKING_URI",          # .env.example:97   http://localhost:5000
    "FED_RSS_URL",                  # .env.example:71
    "CFTC_COT_ENDPOINT",            # .env.example:70
    "TREASURY_DATA_ENDPOINT",       # .env.example:103
    "IMF_DATA_ENDPOINT",            # .env.example:104
    "GOLD_ETF_DATA_ENDPOINT",       # .env.example:105
    "CENTRAL_BANK_GOLD_ENDPOINT",   # .env.example:106
    "MARKET_FLOW_DATA_ENDPOINT",    # .env.example:107
)

# Case normalization mirrors how each consumer reads the key.
_NORMALIZE_LOWER = frozenset({"NEXUS_TRADING_MODE", "NEXUS_TRADING_MODE_TYPE"})
_NORMALIZE_UPPER = frozenset({"NEXUS_OPERATIONAL_TF"})

# Closed broker-adapter set from services/nexus_executor/main.py:551-563.
_BrokerLiteral = Literal["mt5", "ibkr", "ccxt", "binance", "bybit", "okx", "paper"]


class Violation(BaseModel):
    """One contract finding: ``{key, message}``."""

    model_config = ConfigDict(extra="ignore")

    key: str
    message: str


class ConfigContractError(RuntimeError):
    """Raised only in ``enforce`` mode when at least one violation exists."""

    def __init__(self, violations: list[Violation]) -> None:
        self.violations = violations
        details = "; ".join(f"{v.key}: {v.message}" for v in violations)
        super().__init__(
            f"config contract violated ({len(violations)} violation(s)): {details}"
        )


class ConfigContract(BaseModel):
    """Closed-set and bounded env keys; every field optional ⇒ absence is valid."""

    model_config = ConfigDict(extra="ignore")

    # ── Closed enums ────────────────────────────────────────────────────────
    # NEXUS_TRADING_MODE: plan-mandated closed enum. Consumers normalize with
    # .strip().lower() (shared/safety.py:43-44), so input is lower-cased
    # first; shared/safety.py:40 also maps production/prod to live, but those
    # aliases are deliberately rejected here so the canonical value is used.
    nexus_trading_mode: Literal["paper", "live"] | None = Field(
        None, alias="NEXUS_TRADING_MODE"
    )
    # NEXUS_TRADING_MODE_TYPE: scalping|swing enum constructed at import time
    # (services/nexus_ml/traders/trading_mode.py:22-24, 734); an unknown
    # value raises ValueError and crashes nexus-ml startup.
    nexus_trading_mode_type: Literal["scalping", "swing"] | None = Field(
        None, alias="NEXUS_TRADING_MODE_TYPE"
    )
    # NEXUS_OPERATIONAL_TF: must be one of shared/constants.py:220
    # SUPPORTED_TIMEFRAMES (enforced by the validator below); consumed via
    # .upper() (services/nexus_ml/main.py:147, 684) and exact compare
    # (preflight.py:243-244), so input is upper-cased first.
    nexus_operational_tf: str | None = Field(None, alias="NEXUS_OPERATIONAL_TF")
    # NEXUS_ENV: closed set documented in .env.example:9; no runtime consumer
    # yet, so values are checked exactly as documented (lower-case).
    nexus_env: Literal["development", "staging", "production"] | None = Field(
        None, alias="NEXUS_ENV"
    )
    # DEFAULT_BROKER / NEXUS_DEFAULT_BROKER: closed adapter set from
    # services/nexus_executor/main.py:551-563 (unknown names silently fall
    # back to MT5). Comparisons there and in services/nexus_data/main.py:57
    # are case-sensitive ⇒ values are NOT normalized.
    default_broker: _BrokerLiteral | None = Field(None, alias="DEFAULT_BROKER")
    nexus_default_broker: _BrokerLiteral | None = Field(None, alias="NEXUS_DEFAULT_BROKER")

    # ── Bounds (only keys present in .env.example with clear semantics) ─────
    # NEXUS_RISK_PER_TRADE: fraction of equity risked per trade; contract
    # ceiling 0.02 (2%) mirrors risk_rules max_risk_per_trade_pct=2.0
    # (shared/config_loader.py:55). Empty/unset ⇒ None ⇒ no violation.
    nexus_risk_per_trade: float | None = Field(
        None, alias="NEXUS_RISK_PER_TRADE", gt=0, le=0.02
    )
    # NEXUS_MIN_VERDICT_CONVICTION: conviction percent 0-100; int() at
    # preflight.py:224, services/nexus_agents/graph.py:65 and
    # services/nexus_agents/agents/arbitrator.py:44 (non-int crashes).
    nexus_min_verdict_conviction: int | None = Field(
        None, alias="NEXUS_MIN_VERDICT_CONVICTION", ge=0, le=100
    )
    # NEXUS_CONFLICT_LOCK_CONVICTION: conviction percent 0-100;
    # int() at services/nexus_agents/agents/arbitrator.py:45.
    nexus_conflict_lock_conviction: int | None = Field(
        None, alias="NEXUS_CONFLICT_LOCK_CONVICTION", ge=0, le=100
    )
    # NEXUS_RESEARCH_INTERVAL_SEC: seconds between research runs;
    # int() at services/nexus_agents/main.py:50 — must be > 0 or the
    # scheduler hot-spins.
    nexus_research_interval_sec: int | None = Field(
        None, alias="NEXUS_RESEARCH_INTERVAL_SEC", gt=0
    )
    # NEXUS_RESEARCH_BATCH: symbols per research batch, at least 1
    # (services/nexus_agents/main.py:51).
    nexus_research_batch: int | None = Field(None, alias="NEXUS_RESEARCH_BATCH", ge=1)
    # NEXUS_ACTIVE_SIGNAL_TTL: seconds before an approved signal is stale;
    # shared/safety.py:228 — must be > 0 (a negative TTL would make signals
    # never expire).
    nexus_active_signal_ttl: int | None = Field(
        None, alias="NEXUS_ACTIVE_SIGNAL_TTL", gt=0
    )
    # Blackout window minutes, never negative; int() at
    # services/nexus_news/fundamental/blackout.py:217-220.
    nexus_high_impact_blackout_before_min: int | None = Field(
        None, alias="NEXUS_HIGH_IMPACT_BLACKOUT_BEFORE_MIN", ge=0
    )
    nexus_high_impact_blackout_after_min: int | None = Field(
        None, alias="NEXUS_HIGH_IMPACT_BLACKOUT_AFTER_MIN", ge=0
    )
    nexus_medium_impact_blackout_before_min: int | None = Field(
        None, alias="NEXUS_MEDIUM_IMPACT_BLACKOUT_BEFORE_MIN", ge=0
    )
    nexus_medium_impact_blackout_after_min: int | None = Field(
        None, alias="NEXUS_MEDIUM_IMPACT_BLACKOUT_AFTER_MIN", ge=0
    )
    # STRATEGY_MIN_PROFIT_FACTOR: promotion threshold, must be > 0
    # (services/nexus_agents/research/registry.py:70).
    strategy_min_profit_factor: float | None = Field(
        None, alias="STRATEGY_MIN_PROFIT_FACTOR", gt=0
    )
    # STRATEGY_MIN_WIN_RATE: fraction 0-1 (registry.py:71; .env.example:86
    # ships 0.52 — a percent-style value like 52 would never pass).
    strategy_min_win_rate: float | None = Field(
        None, alias="STRATEGY_MIN_WIN_RATE", ge=0, le=1
    )
    # STRATEGY_MAX_DD_PCT: percent drawdown cap 0-100 (registry.py:73).
    strategy_max_dd_pct: float | None = Field(
        None, alias="STRATEGY_MAX_DD_PCT", ge=0, le=100
    )
    # STRATEGY_MIN_TRADES: minimum trade count, at least 1 (registry.py:74).
    strategy_min_trades: int | None = Field(None, alias="STRATEGY_MIN_TRADES", ge=1)
    # IBKR_PORT: TCP port 1-65535; int() at services/nexus_data/main.py:50 and
    # services/nexus_executor/ibkr_executor.py:38 (non-int crashes startup).
    ibkr_port: int | None = Field(None, alias="IBKR_PORT", ge=1, le=65535)

    # ── Keys referenced by invariants (no bounds of their own) ──────────────
    # NEXUS_SETTINGS__AUTO_TRADE_ENABLED: config_loader override of
    # config/settings.yaml auto_trade_enabled (shared/config_loader.py:312-319);
    # read by invariant (a).
    nexus_settings__auto_trade_enabled: str | None = Field(
        None, alias="NEXUS_SETTINGS__AUTO_TRADE_ENABLED"
    )
    # Secrets compared by invariant (b); length/strength checks stay in
    # run.py _validate_env (shared/safety.py:69-81).
    nexus_risk_approval_secret: str | None = Field(None, alias="NEXUS_RISK_APPROVAL_SECRET")
    nexus_internal_api_secret: str | None = Field(None, alias="NEXUS_INTERNAL_API_SECRET")

    @field_validator("nexus_operational_tf", mode="after")
    @classmethod
    def _operational_tf_supported(cls, value: str | None) -> str | None:
        if value is not None and value not in SUPPORTED_TIMEFRAMES:
            raise ValueError(
                f"must be one of {', '.join(SUPPORTED_TIMEFRAMES)}"
            )
        return value


_FIELD_ENV: dict[str, str] = {
    name: (info.alias or name) for name, info in ConfigContract.model_fields.items()
}
# Errors may report either the field name or the alias in loc(); map both.
_ENV_LOOKUP: dict[str, str] = {
    **_FIELD_ENV,
    **{env_key: env_key for env_key in _FIELD_ENV.values()},
}

# Every env key this contract reads (modelled fields + mode + port scan).
CONTRACT_ENV_KEYS: tuple[str, ...] = tuple(
    dict.fromkeys(
        [(info.alias or name) for name, info in ConfigContract.model_fields.items()]
        + ["NEXUS_CONFIG_CONTRACT"]
        + list(_PORT_SCAN_KEYS)
    )
)


def _env_payload(env: dict[str, str]) -> dict[str, Any]:
    """Project os.environ onto contract fields; empty/whitespace ⇒ absent."""
    payload: dict[str, Any] = {}
    for env_key in _FIELD_ENV.values():
        raw = env.get(env_key)
        if raw is None:
            continue
        value = raw.strip()
        if value == "":
            continue
        if env_key in _NORMALIZE_LOWER:
            value = value.lower()
        elif env_key in _NORMALIZE_UPPER:
            value = value.upper()
        payload[env_key] = value
    return payload


def _field_violations(exc: ValidationError) -> list[Violation]:
    violations: list[Violation] = []
    for err in exc.errors():
        loc = err.get("loc") or ()
        raw_key = str(loc[0]) if loc else "unknown"
        env_key = _ENV_LOOKUP.get(raw_key, raw_key)
        violations.append(
            Violation(
                key=env_key,
                message=(
                    f"{err.get('msg', 'invalid value')}; "
                    f"{env_key}={err.get('input', None)!r}"
                ),
            )
        )
    return violations


def _auto_trade_violations(env: dict[str, str]) -> list[Violation]:
    # Invariant (a): effective mode defaults to paper (shared/safety.py:43).
    mode = (env.get("NEXUS_TRADING_MODE") or "").strip().lower() or "paper"
    auto = (env.get("NEXUS_SETTINGS__AUTO_TRADE_ENABLED") or "").strip().lower()
    if mode == "paper" and auto in _TRUTHY:
        return [
            Violation(
                key="NEXUS_SETTINGS__AUTO_TRADE_ENABLED",
                message=(
                    "NEXUS_TRADING_MODE resolves to 'paper' but "
                    f"NEXUS_SETTINGS__AUTO_TRADE_ENABLED={auto!r} would enable "
                    "auto-trade (config/settings.yaml auto_trade_enabled); paper "
                    "mode requires auto-trade disabled"
                ),
            )
        ]
    return []


def _secret_violations(env: dict[str, str]) -> list[Violation]:
    # Invariant (b): approval secret must differ from the internal secret.
    approval = (env.get("NEXUS_RISK_APPROVAL_SECRET") or "").strip()
    internal = (env.get("NEXUS_INTERNAL_API_SECRET") or "").strip()
    if approval and internal and approval == internal:
        return [
            Violation(
                key="NEXUS_RISK_APPROVAL_SECRET",
                message=(
                    "NEXUS_RISK_APPROVAL_SECRET must differ from "
                    "NEXUS_INTERNAL_API_SECRET (both are set to the same "
                    "non-empty value); approval signing must stay isolated"
                ),
            )
        ]
    return []


def _port_violations(env: dict[str, str]) -> list[Violation]:
    # Invariant (c): unique ports across the .env.example PORT/URL inventory.
    ports: dict[int, list[str]] = {}
    for key in _PORT_SCAN_KEYS:
        value = (env.get(key) or "").strip()
        if not value:
            continue
        port: int | None = None
        if key.endswith("_PORT") or key == "PORT":
            try:
                port = int(value)
            except ValueError:
                continue
        elif "://" in value:
            try:
                port = urlsplit(value).port
            except ValueError:
                continue
        if port is None:
            continue
        ports.setdefault(port, []).append(key)

    violations: list[Violation] = []
    for port, keys in ports.items():
        first = keys[0]
        for key in keys[1:]:
            violations.append(
                Violation(
                    key=key,
                    message=(
                        f"port {port} is declared by both {first} and {key}; "
                        "PORT/URL keys in .env.example must be unique"
                    ),
                )
            )
    return violations


def _invariant_violations(env: dict[str, str]) -> list[Violation]:
    # Cross-field invariants, evaluated after field validation.
    return [
        *_auto_trade_violations(env),
        *_secret_violations(env),
        *_port_violations(env),
    ]


def _compute_violations(env: dict[str, str]) -> list[Violation]:
    payload = _env_payload(env)
    try:
        ConfigContract.model_validate(payload)
    except ValidationError as exc:
        violations = _field_violations(exc)
    else:
        violations = []
    violations.extend(_invariant_violations(env))
    return violations


def validate_config_contract(mode: str | None = None) -> list[Violation]:
    """Validate os.environ against the Phase 6 config contract.

    ``mode`` overrides ``NEXUS_CONFIG_CONTRACT`` (default ``warn``):

    * ``off`` — return ``[]`` without validating.
    * ``warn`` — log every violation with structlog and return them; never raises.
    * ``enforce`` — log and raise :class:`ConfigContractError` if any violation exists.
    * unknown value — treated as ``warn`` plus a violation documenting the bad mode.
    """
    raw_mode = mode if mode is not None else os.environ.get("NEXUS_CONFIG_CONTRACT")
    resolved = (raw_mode or "").strip().lower()

    if resolved == MODE_OFF:
        return []

    violations: list[Violation] = []
    if resolved not in (MODE_WARN, MODE_ENFORCE):
        if resolved != "":
            violations.append(
                Violation(
                    key="NEXUS_CONFIG_CONTRACT",
                    message=(
                        f"unknown config-contract mode {raw_mode!r} "
                        f"(expected {'|'.join(_MODES)}); treating as 'warn'"
                    ),
                )
            )
        resolved = MODE_WARN

    violations.extend(_compute_violations(dict(os.environ)))

    for violation in violations:
        logger.warning(
            "config_contract.violation",
            key=violation.key,
            message=violation.message,
        )

    if resolved == MODE_ENFORCE and violations:
        logger.error(
            "config_contract.enforce_failed", violations=len(violations)
        )
        raise ConfigContractError(violations)

    return violations
