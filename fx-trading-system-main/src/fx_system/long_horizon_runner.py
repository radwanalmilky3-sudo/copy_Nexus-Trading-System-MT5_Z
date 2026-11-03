"""Outcome-blind slow-horizon candidate freeze from transferred SQLite files.

This module deliberately stops before portfolio PnL.  The long-horizon label
contract decides at a New York close and enters at the next session's open,
whereas :func:`fx_system.portfolio_runner.run_portfolio` currently executes a
new target at the supplied session mark.  It also treats target values as
quantities, not account-currency capital weights, and defaults missing
financing to zero.  Those differences are material, so adapting the existing
runner would create a plausible-looking but false net-return series.

The safe bridge implemented here verifies the transferred databases, creates
strict common New York-close bars, builds the long-horizon panel, and freezes a
complete, predeclared set of next-open target schedules.  It writes explicit
readiness blockers and never calls the portfolio or statistical-validation
runners.  A later execution engine can consume the frozen schedule only after
all blockers have been resolved and independently verified.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .dukascopy_daily import (
    DukascopyDailyRun,
    build_common_daily_data_from_cache_audit,
    run_dukascopy_daily_from_sqlite,
)
from .long_horizon import (
    build_long_horizon_panel,
    factor_definitions,
)
from .long_horizon_config import LongHorizonConfig
from .models import CurrencyPair
from .research_registry import ResearchRegistry, audit_research_registry

LONG_HORIZON_FREEZE_SCHEMA_VERSION = 1
LONG_HORIZON_FREEZE_IMPLEMENTATION_VERSION = "long-horizon-freeze-v1"
TARGET_TRANSFORM = "cross_sectional_centered_rank_gross_normalized"
MISSING_DATA_RULE = "require_all_eligible_symbols_or_flat"
FREEZE_ARTIFACT_PATHS = frozenset(
    {
        "candidate_declaration.json",
        "candidate_schedule_audit.csv",
        "daily_session_audit.csv",
        "factor_only_build/factor_catalog.csv",
        "factor_only_build/factor_only_audit.json",
        "factor_only_build/factor_panel.csv.gz",
        "frozen_candidate_signal_schedule.csv",
        "transfer_audit.csv",
    }
)
REGISTERED_SLOW_FACTOR_IMPLEMENTATIONS = {
    "slow_commodity_currency_alignment": "commodity_currency_alignment_12m",
    "slow_positioning_crowding_reversal": "positioning_crowding_reversal",
    "slow_value_trend_agreement": "value_trend_agreement",
}

FORMAL_PORTFOLIO_BLOCKERS = (
    "next_open_execution_and_same_session_close_marking_engine_not_integrated",
    "capital_weights_not_converted_to_account_currency_quantities",
    "account_currency_conversion_contract_not_integrated",
    "multi_currency_unrealized_pnl_cost_basis_and_broker_settlement_not_integrated",
    "historical_target_broker_financing_or_tradable_forward_cost_not_integrated",
    "slippage_model_not_frozen_or_integrated",
    "broker_commission_and_other_fees_not_frozen_or_integrated",
    "per_symbol_execution_quote_timestamp_and_staleness_not_integrated",
    "overlapping_sleeve_capital_conservation_not_integrated",
    "cross_candidate_capital_allocation_and_benchmark_not_frozen",
    "fresh_forward_evidence_required_because_2016_2025_overlaps_inspected_history",
)


class FormalPortfolioNotReadyError(RuntimeError):
    """Raised when a caller tries to promote the freeze into formal PnL."""


class LongHorizonCandidateSpec(BaseModel):
    """One outcome-independent directional candidate and holding horizon."""

    model_config = ConfigDict(extra="forbid")

    name: str
    hypothesis_id: str
    factor: str
    expected_sign: Literal["positive", "negative"]
    horizon_sessions: int = Field(ge=1)
    eligible_symbols: list[str]
    gross_target: float = Field(1.0, gt=0.0, le=1.0)
    transform: Literal["cross_sectional_centered_rank_gross_normalized"] = TARGET_TRANSFORM
    missing_data_rule: Literal["require_all_eligible_symbols_or_flat"] = MISSING_DATA_RULE

    @field_validator("name", "hypothesis_id", "factor")
    @classmethod
    def non_empty_identifier(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("candidate identifiers must be non-empty and trimmed")
        return value

    @field_validator("eligible_symbols")
    @classmethod
    def normalize_symbols(cls, values: list[str]) -> list[str]:
        normalized = [CurrencyPair.parse(value).symbol for value in values]
        if not normalized:
            raise ValueError("eligible_symbols cannot be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("eligible_symbols must be unique")
        return normalized


class LongHorizonCandidateDeclaration(BaseModel):
    """Frozen complete candidate set; realized returns cannot change directions."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    declaration_id: str
    frozen_at: datetime
    registration_market_data_cutoff: date
    candidate_set_is_complete: Literal[True]
    candidate_universe_scope: Literal[
        "implemented_active_directional_slow_hypotheses_excluding_deferred_missing_data"
    ]
    directions_selected_from_dukascopy_outcomes: Literal[False]
    fresh_forward_required: Literal[True]
    inference_eligibility: Literal["exploratory_reused_history_requires_new_forward"]
    selected_candidate_for_future_dsr_diagnostic: str
    total_trials_evaluated: int = Field(ge=2)
    candidates: list[LongHorizonCandidateSpec]

    @field_validator("declaration_id", "selected_candidate_for_future_dsr_diagnostic")
    @classmethod
    def non_empty_identifier(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("declaration identifiers must be non-empty and trimmed")
        return value

    @field_validator("frozen_at")
    @classmethod
    def timezone_aware_freeze(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("frozen_at must include a timezone offset")
        return value

    @model_validator(mode="after")
    def complete_unique_set(self) -> LongHorizonCandidateDeclaration:
        if not self.candidates:
            raise ValueError("candidates cannot be empty")
        names = [candidate.name for candidate in self.candidates]
        if len(names) != len(set(names)):
            raise ValueError("candidate names must be unique")
        if self.selected_candidate_for_future_dsr_diagnostic not in set(names):
            raise ValueError("selected DSR diagnostic candidate is not declared")
        if self.total_trials_evaluated < len(names):
            raise ValueError("total_trials_evaluated cannot be smaller than the candidate set")
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> LongHorizonCandidateDeclaration:
        with Path(path).open("r", encoding="utf-8") as handle:
            return cls.model_validate(yaml.safe_load(handle))


@dataclass(frozen=True)
class LongHorizonFactorOnlyBuildResult:
    """Factor inputs with no future label, outcome, or walk-forward fold."""

    daily_data: dict[str, pd.DataFrame]
    panel: pd.DataFrame
    catalog: pd.DataFrame
    audit: dict[str, Any]
    external_files: list[Path]


@dataclass(frozen=True)
class LongHorizonCandidateFreezeResult:
    daily_run: DukascopyDailyRun
    common_daily_data: dict[str, pd.DataFrame]
    build: LongHorizonFactorOnlyBuildResult
    config: LongHorizonConfig
    declaration: LongHorizonCandidateDeclaration
    candidate_schedule: pd.DataFrame
    schedule_audit: pd.DataFrame
    manifest: dict[str, Any]


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _validate_pipeline_contract(
    config: LongHorizonConfig,
    declaration: LongHorizonCandidateDeclaration,
    symbols: tuple[str, ...],
) -> None:
    if config.data.provider != "dukascopy":
        raise ValueError("direct SQLite freeze requires data.provider=dukascopy")
    if config.data.price_mode != "bid_ask":
        raise ValueError("direct SQLite freeze requires bid_ask market data")
    configured_symbols = tuple(config.data.symbols)
    if configured_symbols != symbols:
        raise ValueError(
            "SQLite symbols must exactly match config.data.symbols in frozen order"
        )
    configured_horizons = set(config.research.horizons)
    declared_horizons = {candidate.horizon_sessions for candidate in declaration.candidates}
    if declared_horizons != configured_horizons:
        raise ValueError(
            "complete candidate declaration must cover every configured horizon exactly as a set; "
            f"configured={sorted(configured_horizons)}, declared={sorted(declared_horizons)}"
        )
    for candidate in declaration.candidates:
        if tuple(candidate.eligible_symbols) != symbols:
            raise ValueError(
                f"{candidate.name}: eligible_symbols must exactly match the frozen symbol universe"
            )


def _validate_registry_contract(
    declaration: LongHorizonCandidateDeclaration,
    registry_path: str | Path,
) -> tuple[ResearchRegistry, dict[str, object]]:
    """Prove each candidate was registered before Dukascopy outcomes are built."""

    registry = ResearchRegistry.from_yaml(registry_path)
    registry_audit = audit_research_registry(registry_path)
    if registry.fresh_forward_required is not True:
        raise ValueError("research registry must keep fresh_forward_required=true")
    if declaration.registration_market_data_cutoff != (
        registry.market_history_previously_inspected_through
    ):
        raise ValueError("candidate declaration cutoff does not match research registry")
    disclosed_trials = int(registry_audit["disclosed_factor_outcome_evaluations"])
    if declaration.total_trials_evaluated < disclosed_trials:
        raise ValueError(
            "candidate declaration understates disclosed factor-outcome evaluations; "
            f"declared={declaration.total_trials_evaluated}, required>={disclosed_trials}"
        )

    hypothesis_by_id = {hypothesis.id: hypothesis for hypothesis in registry.hypotheses}
    expected_scope = {
        hypothesis.id
        for hypothesis in registry.hypotheses
        if hypothesis.track == "slow"
        and hypothesis.status == "preregistered"
        and hypothesis.directional
        and hypothesis.id in REGISTERED_SLOW_FACTOR_IMPLEMENTATIONS
    }
    declared_scope = {candidate.hypothesis_id for candidate in declaration.candidates}
    if declared_scope != expected_scope:
        raise ValueError(
            "candidate declaration does not exactly cover registered active directional "
            f"slow hypotheses; missing={sorted(expected_scope - declared_scope)}, "
            f"unexpected={sorted(declared_scope - expected_scope)}"
        )

    observed_units: set[tuple[str, int]] = set()
    for candidate in declaration.candidates:
        try:
            hypothesis = hypothesis_by_id[candidate.hypothesis_id]
        except KeyError as error:
            raise ValueError(
                f"{candidate.name}: hypothesis_id is absent from the research registry"
            ) from error
        if hypothesis.track != "slow":
            raise ValueError(f"{candidate.name}: registry hypothesis is not slow-horizon")
        if hypothesis.status != "preregistered":
            raise ValueError(f"{candidate.name}: registry hypothesis is not active/preregistered")
        if hypothesis.directional is not True:
            raise ValueError(f"{candidate.name}: registry hypothesis is non-directional")
        if hypothesis.expected_sign != candidate.expected_sign:
            raise ValueError(f"{candidate.name}: expected_sign differs from registry")
        expected_name = f"{candidate.hypothesis_id}__{candidate.horizon_sessions}d"
        if candidate.name != expected_name:
            raise ValueError(
                f"{candidate.name}: candidate name must equal {expected_name!r}"
            )
        try:
            expected_factor = REGISTERED_SLOW_FACTOR_IMPLEMENTATIONS[
                candidate.hypothesis_id
            ]
        except KeyError as error:
            raise ValueError(
                f"{candidate.name}: no frozen registry-to-factor implementation mapping"
            ) from error
        if candidate.factor != expected_factor:
            raise ValueError(
                f"{candidate.name}: factor differs from frozen hypothesis implementation"
            )
        if f"{candidate.horizon_sessions}d" not in set(hypothesis.horizons):
            raise ValueError(f"{candidate.name}: horizon is absent from registry hypothesis")
        if (
            hypothesis.registration_market_data_cutoff
            != declaration.registration_market_data_cutoff
        ):
            raise ValueError(f"{candidate.name}: registration cutoff differs from registry")
        if declaration.frozen_at < hypothesis.registered_at:
            raise ValueError(f"{candidate.name}: declaration predates registry hypothesis")
        unit = (candidate.hypothesis_id, candidate.horizon_sessions)
        if unit in observed_units:
            raise ValueError(f"{candidate.name}: duplicate hypothesis/horizon candidate unit")
        observed_units.add(unit)

    expected_units = {
        (hypothesis.id, int(horizon.removesuffix("d")))
        for hypothesis in registry.hypotheses
        if hypothesis.id in expected_scope
        for horizon in hypothesis.horizons
        if horizon.endswith("d") and horizon.removesuffix("d").isdigit()
    }
    if observed_units != expected_units:
        raise ValueError(
            "candidate declaration must include every registered horizon for the scoped "
            f"hypotheses; missing={sorted(expected_units - observed_units)}, "
            f"unexpected={sorted(observed_units - expected_units)}"
        )
    if declaration.frozen_at > datetime.now(UTC):
        raise ValueError("candidate declaration frozen_at cannot be later than runner time")
    return registry, registry_audit


def _build_factor_only(
    data: dict[str, pd.DataFrame],
    config: LongHorizonConfig,
) -> LongHorizonFactorOnlyBuildResult:
    daily, panel, external_files = build_long_horizon_panel(data, config)
    catalog = pd.DataFrame([asdict(item) for item in factor_definitions(config.research)])
    missing = set(catalog["name"]) - set(panel)
    if missing:
        raise RuntimeError(f"factor-only panel is missing catalog factors {sorted(missing)}")
    forbidden = [
        column
        for column in panel.columns
        if str(column).startswith(("_forward_", "_label_"))
    ]
    if forbidden:
        raise RuntimeError(f"factor-only build generated forbidden outcome columns: {forbidden}")
    factor_coverage = {
        name: float(panel[name].replace([np.inf, -np.inf], np.nan).notna().mean())
        for name in catalog["name"]
    }
    index = next(iter(daily.values())).index
    audit = {
        "factor_only": True,
        "future_labels_generated": False,
        "forward_return_columns": [],
        "label_end_columns": [],
        "walk_forward_folds_generated": False,
        "symbols": sorted(daily),
        "common_sessions": len(index),
        "common_start": index[0].isoformat(),
        "common_end": index[-1].isoformat(),
        "factor_count": len(catalog),
        "factor_coverage": factor_coverage,
        "source_database_transfer_verified": all(
            bool(frame.attrs.get("source_database_transfer_verified", False))
            for frame in daily.values()
        ),
        "trading_approval": False,
    }
    return LongHorizonFactorOnlyBuildResult(
        daily_data=daily,
        panel=panel,
        catalog=catalog,
        audit=audit,
        external_files=external_files,
    )


def _catalog_directionality(build: LongHorizonFactorOnlyBuildResult) -> dict[str, bool]:
    if build.catalog["name"].duplicated().any():
        raise ValueError("long-horizon catalog contains duplicate factor names")
    return {
        str(row["name"]): bool(row["directional"])
        for row in build.catalog.to_dict("records")
    }


def _centered_rank_weights(
    raw_values: pd.Series,
    *,
    expected_sign: str,
    gross_target: float,
) -> pd.Series:
    ranks = raw_values.rank(method="average", pct=True)
    centered = ranks - float(ranks.mean())
    if expected_sign == "negative":
        centered = -centered
    gross = float(centered.abs().sum())
    if not math.isfinite(gross) or gross <= 1e-15:
        return pd.Series(0.0, index=raw_values.index, dtype=float)
    return centered * (gross_target / gross)


def build_frozen_candidate_schedule(
    build: LongHorizonFactorOnlyBuildResult,
    declaration: LongHorizonCandidateDeclaration,
    config: LongHorizonConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build declared targets from factor values only, never labels or returns."""

    symbols = tuple(config.data.symbols)
    directionality = _catalog_directionality(build)
    for candidate in declaration.candidates:
        if candidate.factor not in directionality:
            raise ValueError(f"{candidate.name}: unknown catalog factor {candidate.factor!r}")
        if directionality[candidate.factor] is not True:
            raise ValueError(
                f"{candidate.name}: non-directional factor cannot create a trading target"
            )
        if candidate.factor not in build.panel:
            raise ValueError(f"{candidate.name}: factor is missing from the factor panel")

    panel = build.panel.copy()
    panel["_feature_time"] = pd.to_datetime(panel["_feature_time"], utc=True)
    if panel.duplicated(["_feature_time", "_symbol"]).any():
        raise ValueError("factor panel contains duplicate feature-time/symbol rows")
    panel_times = pd.DatetimeIndex(sorted(panel["_feature_time"].unique()))
    if panel_times.empty:
        raise ValueError("factor panel contains no feature times")
    for symbol in symbols:
        observed = pd.DatetimeIndex(
            panel.loc[panel["_symbol"] == symbol, "_feature_time"].sort_values()
        )
        if not observed.equals(panel_times):
            raise ValueError(f"{symbol}: factor panel does not cover the exact common time index")
        if not build.daily_data[symbol].index.equals(panel_times):
            raise ValueError(f"{symbol}: daily prices do not match the factor-panel time index")
    rebalance_times = panel_times[:: config.research.rebalance_interval_days]
    locations = {timestamp: number for number, timestamp in enumerate(panel_times)}

    rows: list[dict[str, Any]] = []
    for candidate in declaration.candidates:
        candidate_panel = panel.loc[
            panel["_symbol"].isin(candidate.eligible_symbols),
            ["_feature_time", "_symbol", candidate.factor],
        ].set_index(["_feature_time", "_symbol"])
        for decision_time in rebalance_times:
            location = locations[decision_time]
            entry_location = location + 1
            exit_location = location + candidate.horizon_sessions
            raw = candidate_panel.loc[decision_time, candidate.factor].reindex(
                candidate.eligible_symbols
            )
            if entry_location >= len(panel_times):
                status = "flat_no_next_common_session"
            elif exit_location >= len(panel_times):
                status = "flat_insufficient_common_sessions_for_horizon"
            elif raw.isna().any() or not np.isfinite(raw.to_numpy(dtype=float)).all():
                status = "flat_missing_required_factor_leg"
            else:
                weights = _centered_rank_weights(
                    raw,
                    expected_sign=candidate.expected_sign,
                    gross_target=candidate.gross_target,
                )
                status = (
                    "ready_next_open"
                    if float(weights.abs().sum()) > 1e-15
                    else "flat_zero_cross_sectional_dispersion"
                )
            if not status.startswith("ready"):
                weights = pd.Series(0.0, index=candidate.eligible_symbols, dtype=float)

            entry_session = (
                panel_times[entry_location].normalize()
                if entry_location < len(panel_times)
                else pd.NaT
            )
            scheduled_exit_session = (
                panel_times[exit_location].normalize()
                if exit_location < len(panel_times)
                else pd.NaT
            )
            for symbol in candidate.eligible_symbols:
                daily = build.daily_data[symbol]
                entry_quote_time = (
                    pd.Timestamp(daily.iloc[entry_location]["session_open_quote_time"])
                    if entry_location < len(daily)
                    else pd.NaT
                )
                exit_quote_time = (
                    pd.Timestamp(daily.iloc[exit_location]["session_close_quote_time"])
                    if exit_location < len(daily)
                    else pd.NaT
                )
                rows.append(
                    {
                        "candidate": candidate.name,
                        "hypothesis_id": candidate.hypothesis_id,
                        "factor": candidate.factor,
                        "expected_sign": candidate.expected_sign,
                        "horizon_sessions": candidate.horizon_sessions,
                        "decision_time": decision_time,
                        "entry_session": entry_session,
                        "entry_quote_time": entry_quote_time,
                        "scheduled_exit_session": scheduled_exit_session,
                        "exit_quote_time": exit_quote_time,
                        "symbol": symbol,
                        "raw_factor_value": (
                            float(raw.loc[symbol])
                            if pd.notna(raw.loc[symbol])
                            else np.nan
                        ),
                        "proposed_tranche_weight": float(weights.loc[symbol]),
                        "proposed_tranche_gross": candidate.gross_target,
                        "transform": candidate.transform,
                        "missing_data_rule": candidate.missing_data_rule,
                        "status": status,
                        "weight_semantics": (
                            "single_candidate_single_vintage_signal_not_portfolio_allocation"
                        ),
                        "direction_source": "frozen_declaration_not_realized_returns",
                    }
                )

    schedule = pd.DataFrame(rows).sort_values(
        ["decision_time", "candidate", "symbol"]
    ).reset_index(drop=True)
    for column in (
        "decision_time",
        "entry_session",
        "entry_quote_time",
        "scheduled_exit_session",
        "exit_quote_time",
    ):
        schedule[column] = pd.to_datetime(schedule[column], utc=True)
    grouped = schedule.groupby(["candidate", "decision_time"], sort=True)
    gross = grouped["proposed_tranche_weight"].apply(
        lambda values: float(values.abs().sum())
    )
    if (gross > 1.0 + 1e-12).any():
        raise RuntimeError("frozen target schedule exceeds unit gross weight")
    ready_rows = schedule.loc[schedule["status"] == "ready_next_open"]
    if not ready_rows.empty:
        if ready_rows[["entry_quote_time", "exit_quote_time"]].isna().any(axis=None):
            raise RuntimeError("ready target schedule contains a missing execution boundary")
        if not (
            (ready_rows["entry_quote_time"] >= ready_rows["decision_time"])
            & (ready_rows["exit_quote_time"] > ready_rows["entry_quote_time"])
        ).all():
            raise RuntimeError("ready target schedule violates decision/entry/exit time order")
    status_by_decision = grouped["status"].first()
    audit_rows: list[dict[str, Any]] = []
    for candidate in declaration.candidates:
        selected = status_by_decision.loc[candidate.name]
        candidate_gross = gross.loc[candidate.name]
        audit_rows.append(
            {
                "candidate": candidate.name,
                "factor": candidate.factor,
                "expected_sign": candidate.expected_sign,
                "horizon_sessions": candidate.horizon_sessions,
                "decision_count": len(selected),
                "ready_decisions": int(selected.eq("ready_next_open").sum()),
                "flat_missing_factor_decisions": int(
                    selected.eq("flat_missing_required_factor_leg").sum()
                ),
                "flat_insufficient_horizon_decisions": int(
                    selected.eq("flat_insufficient_common_sessions_for_horizon").sum()
                ),
                "flat_no_next_session_decisions": int(
                    selected.eq("flat_no_next_common_session").sum()
                ),
                "flat_zero_dispersion_decisions": int(
                    selected.eq("flat_zero_cross_sectional_dispersion").sum()
                ),
                "maximum_scheduled_gross": float(candidate_gross.max()),
                "all_missing_legs_flatten_complete_vector": True,
            }
        )
    audit = pd.DataFrame(audit_rows).sort_values("candidate").reset_index(drop=True)
    return schedule, audit


def _base_manifest(
    *,
    daily_run: DukascopyDailyRun,
    build: LongHorizonFactorOnlyBuildResult,
    declaration: LongHorizonCandidateDeclaration,
    schedule: pd.DataFrame,
    config: LongHorizonConfig,
    start: date | datetime | str,
    end: date | datetime | str,
) -> dict[str, Any]:
    decisions = schedule.drop_duplicates(["candidate", "decision_time"])
    ready = int(decisions["status"].eq("ready_next_open").sum())
    return {
        "schema_version": LONG_HORIZON_FREEZE_SCHEMA_VERSION,
        "implementation_version": LONG_HORIZON_FREEZE_IMPLEMENTATION_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "pipeline_stage": "verified_sqlite_to_outcome_blind_frozen_next_open_targets",
        "requested_start": str(start),
        "requested_end_exclusive": str(end),
        "symbols": list(config.data.symbols),
        "horizons": list(config.research.horizons),
        "rebalance_interval_sessions": config.research.rebalance_interval_days,
        "config": config.model_dump(mode="json"),
        "transfer_database_sha256": {
            str(row.symbol): str(row.database_sha256)
            for row in daily_run.transfer_audit.itertuples()
        },
        "common_daily_sessions": len(next(iter(build.daily_data.values()))),
        "factor_only_build": True,
        "future_labels_generated": False,
        "forward_return_columns": [],
        "label_end_columns": [],
        "external_files": [
            {"path": str(path), "sha256": _sha256(path)}
            for path in build.external_files
        ],
        "candidate_declaration": declaration.model_dump(mode="json"),
        "candidate_set_is_complete": True,
        "declared_candidate_count": len(declaration.candidates),
        "declared_horizons_cover_config_exactly": True,
        "directions_selected_from_dukascopy_outcomes": False,
        "target_builder_inputs": ["factor_panel", "daily_boundary_quote_times", "declaration"],
        "target_builder_outcome_columns_accessed": [],
        "schedule_semantics": (
            "Each gross-normalized vector is a proposed single-candidate, single-vintage "
            "signal tranche. It is not a final capital weight. Overlapping 42/63-session "
            "vintages and allocation across seven candidates remain unresolved."
        ),
        "portfolio_target_weights_emitted": False,
        "scheduled_candidate_decisions_ready": ready,
        "portfolio_execution_attempted": False,
        "portfolio_validation_attempted": False,
        "portfolio_return_artifacts_emitted": False,
        "formal_net_return_eligible": False,
        "cost_contract_verdict": "cost_incomplete_research_only",
        "historical_financing_treatment": "missing_not_zero_filled",
        "formal_portfolio_blockers": list(FORMAL_PORTFOLIO_BLOCKERS),
        "trading_approval": False,
        "fresh_forward_required": True,
        "interpretation": (
            "Research-input freeze only. The schedule preserves close-t decision, next-session "
            "open entry, and horizon close timestamps. No portfolio PnL, DSR/PBO/SPA verdict, "
            "profitability claim, or trading approval is produced."
        ),
    }


def run_long_horizon_candidate_freeze_from_sqlite(
    *,
    database_directory: str | Path,
    config: LongHorizonConfig,
    declaration: LongHorizonCandidateDeclaration,
    start: date | datetime | str,
    end: date | datetime | str,
    registry_path: str | Path,
    transfer_manifest_path: str | Path | None = None,
    checkpoint_path: str | Path | None = None,
    boundary_max_quote_age: timedelta | None = None,
) -> LongHorizonCandidateFreezeResult:
    """Run the maximum safe pre-portfolio stage over verified SQLite inputs."""

    symbols = tuple(config.data.symbols)
    _validate_pipeline_contract(config, declaration, symbols)
    _, registry_audit = _validate_registry_contract(declaration, registry_path)
    daily_run = run_dukascopy_daily_from_sqlite(
        database_directory,
        symbols,
        start,
        end,
        transfer_manifest_path=transfer_manifest_path,
        checkpoint_path=checkpoint_path,
        boundary_max_quote_age=boundary_max_quote_age,
    )
    # Use the cache-audit common-session path: it trusts daily_bar_emitted verdicts
    # and excludes suppressed sessions without re-imposing the portfolio strictness
    # (missing-hour/boundary/partial checks) that rejects real Dukascopy tick data.
    common_daily = build_common_daily_data_from_cache_audit(daily_run)
    build = _build_factor_only(common_daily, config)
    schedule, schedule_audit = build_frozen_candidate_schedule(build, declaration, config)
    manifest = _base_manifest(
        daily_run=daily_run,
        build=build,
        declaration=declaration,
        schedule=schedule,
        config=config,
        start=start,
        end=end,
    )
    manifest["research_registry"] = {
        "path": str(Path(registry_path).resolve()),
        "sha256": registry_audit["registry_sha256"],
        "disclosed_factor_outcome_evaluations": registry_audit[
            "disclosed_factor_outcome_evaluations"
        ],
        "all_supplied_artifacts_verified": registry_audit[
            "all_supplied_artifacts_verified"
        ],
        "candidate_contract_matched": True,
        "hypothesis_factor_implementation_mapping_matched": True,
    }
    return LongHorizonCandidateFreezeResult(
        daily_run=daily_run,
        common_daily_data=common_daily,
        build=build,
        config=config,
        declaration=declaration,
        candidate_schedule=schedule,
        schedule_audit=schedule_audit,
        manifest=manifest,
    )


def assert_formal_portfolio_ready(result: LongHorizonCandidateFreezeResult) -> None:
    """Fail closed until every material portfolio blocker is implemented."""

    if not isinstance(result, LongHorizonCandidateFreezeResult):
        raise TypeError("result must be a LongHorizonCandidateFreezeResult")
    blockers = tuple(result.manifest.get("formal_portfolio_blockers", ()))
    if blockers:
        raise FormalPortfolioNotReadyError(
            "formal slow-horizon portfolio is blocked: " + "; ".join(blockers)
        )


def _atomic_csv(frame: pd.DataFrame, path: Path, *, index: bool) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        frame.to_csv(temporary, index=index)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_json(payload: dict[str, Any], path: Path) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_long_horizon_candidate_freeze_artifacts(
    result: LongHorizonCandidateFreezeResult,
    output_directory: str | Path,
) -> Path:
    """Write frozen targets and a hash-complete research-only manifest."""

    if not isinstance(result, LongHorizonCandidateFreezeResult):
        raise TypeError("result must be a LongHorizonCandidateFreezeResult")
    output = Path(output_directory)
    if output.is_symlink():
        raise ValueError("freeze output directory cannot be a symbolic link")
    if output.exists() and any(output.iterdir()):
        raise ValueError("freeze output directory must be absent or empty")
    output.mkdir(parents=True, exist_ok=True)
    build_output = output / "factor_only_build"
    build_output.mkdir(parents=True, exist_ok=True)
    panel_path = build_output / "factor_panel.csv.gz"
    panel_temporary = build_output / ".factor_panel.csv.gz.tmp"
    try:
        result.build.panel.replace([np.inf, -np.inf], np.nan).to_csv(
            panel_temporary, index=False, compression="gzip"
        )
        panel_temporary.replace(panel_path)
    finally:
        panel_temporary.unlink(missing_ok=True)
    _atomic_csv(result.build.catalog, build_output / "factor_catalog.csv", index=False)
    _atomic_json(result.build.audit, build_output / "factor_only_audit.json")

    _atomic_csv(result.daily_run.transfer_audit, output / "transfer_audit.csv", index=False)
    _atomic_csv(result.daily_run.session_audit, output / "daily_session_audit.csv", index=False)
    _atomic_csv(
        result.candidate_schedule,
        output / "frozen_candidate_signal_schedule.csv",
        index=False,
    )
    _atomic_csv(result.schedule_audit, output / "candidate_schedule_audit.csv", index=False)
    _atomic_json(
        result.declaration.model_dump(mode="json"), output / "candidate_declaration.json"
    )

    artifact_paths = [output / relative for relative in sorted(FREEZE_ARTIFACT_PATHS)]
    missing_artifacts = [str(path) for path in artifact_paths if not path.is_file()]
    if missing_artifacts:
        raise RuntimeError(f"freeze writer did not create required artifacts: {missing_artifacts}")
    artifacts = {
        str(path.relative_to(output)): {
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        }
        for path in artifact_paths
    }
    manifest = dict(result.manifest)
    manifest["artifacts"] = artifacts
    _atomic_json(manifest, output / "manifest.json")
    return output


def verify_long_horizon_candidate_freeze_artifacts(
    output_directory: str | Path,
) -> dict[str, Any]:
    """Recompute every declared artifact hash and recheck the no-approval gate."""

    output = Path(output_directory)
    if output.is_symlink():
        raise ValueError("freeze output directory cannot be a symbolic link")
    manifest_path = output / "manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("freeze manifest cannot be a symbolic link")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("trading_approval") is not False:
        raise ValueError("freeze manifest must keep trading_approval=false")
    if manifest.get("formal_net_return_eligible") is not False:
        raise ValueError("freeze manifest cannot mark formal net returns eligible")
    if manifest.get("portfolio_return_artifacts_emitted") is not False:
        raise ValueError("freeze stage cannot emit portfolio return artifacts")
    if manifest.get("future_labels_generated") is not False:
        raise ValueError("freeze stage cannot generate future labels")
    if manifest.get("forward_return_columns") != [] or manifest.get(
        "label_end_columns"
    ) != []:
        raise ValueError("freeze manifest declares forbidden outcome columns")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError("freeze manifest has no artifact inventory")
    if set(artifacts) != FREEZE_ARTIFACT_PATHS:
        raise ValueError("freeze artifact inventory differs from the exact allowlist")
    observed_files: set[str] = set()
    for path in output.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"freeze artifacts cannot contain symbolic links: {path}")
        if path.is_file() and path != manifest_path:
            observed_files.add(path.relative_to(output).as_posix())
    if observed_files != FREEZE_ARTIFACT_PATHS:
        raise ValueError("freeze output contains missing, undeclared, or forbidden files")
    for relative, evidence in artifacts.items():
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"unsafe artifact path in freeze manifest: {relative!r}")
        path = output / relative
        if path.resolve().parent != (output / relative_path).resolve().parent:
            raise ValueError(f"artifact path escapes freeze output: {relative!r}")
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.stat().st_size != int(evidence["bytes"]):
            raise ValueError(f"{relative}: artifact byte count changed")
        if _sha256(path) != evidence["sha256"]:
            raise ValueError(f"{relative}: artifact SHA-256 changed")
    panel = pd.read_csv(output / "factor_only_build/factor_panel.csv.gz", nrows=0)
    forbidden = [
        column
        for column in panel.columns
        if str(column).startswith(("_forward_", "_label_"))
    ]
    if forbidden:
        raise ValueError(f"factor-only artifact contains outcome columns: {forbidden}")
    return manifest


__all__ = [
    "FORMAL_PORTFOLIO_BLOCKERS",
    "FormalPortfolioNotReadyError",
    "LongHorizonCandidateDeclaration",
    "LongHorizonCandidateFreezeResult",
    "LongHorizonCandidateSpec",
    "LongHorizonFactorOnlyBuildResult",
    "assert_formal_portfolio_ready",
    "build_frozen_candidate_schedule",
    "run_long_horizon_candidate_freeze_from_sqlite",
    "verify_long_horizon_candidate_freeze_artifacts",
    "write_long_horizon_candidate_freeze_artifacts",
]
