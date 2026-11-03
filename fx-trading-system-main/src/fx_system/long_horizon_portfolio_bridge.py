"""Synthetic two-stage ledger bridge for software acceptance.

Connects pre-netted open/close quantity panels to ``run_long_horizon_execution``
and emits a machine-readable reconcile report. Never clears cost blockers and
never marks formal net returns ready.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from .broker_cost_contract import CostCoverageReport
from .long_horizon_execution import LongHorizonExecutionResult, run_long_horizon_execution

_NAV_TOL = 1e-9


@dataclass(frozen=True)
class SyntheticLedgerBridgeResult:
    execution: LongHorizonExecutionResult
    nav_identity_ok: bool
    max_nav_residual: float
    cost_verdict: str
    formal_net_returns_ready: bool
    trading_approval: bool
    issues: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        # execution is not JSON-safe via asdict deep; expose summary only
        payload["execution"] = {
            "initial_nav": self.execution.initial_nav,
            "final_nav": self.execution.final_nav,
            "sessions": len(self.execution.entries),
            "trades": len(self.execution.trades),
            "formal_net_returns_ready": self.execution.formal_net_returns_ready,
            "trading_approval": self.execution.trading_approval,
            "external_dependencies_remaining": list(self.execution.external_dependencies_remaining),
        }
        return payload


def _nav_residuals(result: LongHorizonExecutionResult) -> list[float]:
    residuals: list[float] = []
    for entry in result.entries:
        expected = math.fsum(
            (
                entry.previous_nav,
                entry.overnight_price_pnl,
                entry.financing,
                entry.cash_interest,
                entry.intraday_price_pnl,
                -entry.open_spread_cost,
                -entry.close_spread_cost,
                -entry.open_slippage_cost,
                -entry.close_slippage_cost,
            )
        )
        residuals.append(abs(entry.nav - expected))
        if entry.accounting_reconciled is not True:
            residuals.append(1.0)
    return residuals


def run_synthetic_two_stage_ledger(
    execution_kwargs: Mapping[str, Any],
    *,
    cost_report: CostCoverageReport | None = None,
) -> SyntheticLedgerBridgeResult:
    """Run two-stage execution on synthetic/fixture inputs and audit readiness."""
    result = run_long_horizon_execution(**dict(execution_kwargs))
    residuals = _nav_residuals(result)
    max_residual = max(residuals) if residuals else 0.0
    nav_ok = max_residual <= _NAV_TOL
    issues: list[str] = []
    if not nav_ok:
        issues.append(f"nav residual {max_residual} exceeds tolerance")
    if cost_report is None:
        cost_verdict = "cost_incomplete_research_only"
        issues.append("cost coverage report not supplied")
    else:
        cost_verdict = cost_report.verdict
        if cost_report.verdict != "historical_market_cost_ready":
            issues.append(f"cost verdict={cost_report.verdict}")
        issues.extend(cost_report.issues)
    if result.formal_net_returns_ready or result.trading_approval:
        issues.append("execution core must not self-approve")
    return SyntheticLedgerBridgeResult(
        execution=result,
        nav_identity_ok=nav_ok,
        max_nav_residual=max_residual,
        cost_verdict=cost_verdict,
        formal_net_returns_ready=False,
        trading_approval=False,
        issues=tuple(dict.fromkeys(issues)),
    )


def net_component_quantity_panels(
    components: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    """Sum component quantity panels with an exact shared index contract."""
    if not components:
        raise ValueError("components cannot be empty")
    expected_index: pd.Index | None = None
    expected_columns: pd.Index | None = None
    total: pd.DataFrame | None = None
    for name, panel in components.items():
        if not isinstance(panel, pd.DataFrame):
            raise TypeError(f"{name}: component panel must be a DataFrame")
        if not panel.index.is_unique or not panel.columns.is_unique:
            raise ValueError(f"{name}: component index and symbols must be unique")
        if expected_index is None:
            expected_index = panel.index
            expected_columns = panel.columns
        elif not panel.index.equals(expected_index) or not panel.columns.equals(expected_columns):
            raise ValueError(f"{name}: component panels must share exact index and symbols")
        numeric = panel.to_numpy(dtype=float)
        if (
            not pd.notna(numeric).all()
            or not pd.DataFrame(numeric).map(pd.api.types.is_number).all().all()
        ):
            raise ValueError(f"{name}: component quantities must be finite")
        if total is None:
            total = panel.astype(float).copy()
        else:
            total = total + panel.astype(float)
    assert total is not None
    return total


def build_execution_targets_from_frozen_schedule(
    schedule: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
    symbols: tuple[str, ...],
    account_quantity_per_weight: Mapping[str, float],
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], pd.DataFrame]:
    """Convert outcome-blind schedule weights into explicit account quantities.

    ``account_quantity_per_weight`` is mandatory because a signal weight is not
    an account-currency quantity.  This adapter validates the conversion but
    does not claim that the supplied synthetic multiplier is a broker rule.
    Open targets include positions through their scheduled exit; close targets
    remove positions whose exit is the current session.
    """
    required = {
        "candidate",
        "symbol",
        "status",
        "proposed_tranche_weight",
        "entry_session",
        "scheduled_exit_session",
    }
    if not required.issubset(schedule.columns):
        raise ValueError(f"schedule is missing columns {sorted(required - set(schedule))}")
    if not isinstance(sessions, pd.DatetimeIndex) or not sessions.is_unique:
        raise ValueError("sessions must be a unique DatetimeIndex")
    sessions = pd.DatetimeIndex(pd.to_datetime(sessions, utc=True)).normalize()
    if not sessions.is_monotonic_increasing:
        raise ValueError("sessions must be sorted")
    if tuple(symbols) != tuple(dict.fromkeys(symbols)) or not symbols:
        raise ValueError("symbols must be non-empty and unique")
    if set(schedule["symbol"]) - set(symbols):
        raise ValueError("schedule contains a symbol outside the execution universe")
    for symbol in symbols:
        multiplier = account_quantity_per_weight.get(symbol)
        if (
            multiplier is None
            or not pd.api.types.is_number(multiplier)
            or not pd.notna(multiplier)
            or multiplier <= 0
        ):
            raise ValueError(f"missing positive account quantity conversion for {symbol}")

    rows = schedule.loc[schedule["status"].eq("ready_next_open")].copy()
    rows["entry_session"] = pd.to_datetime(
        rows["entry_session"], utc=True, errors="coerce"
    ).dt.normalize()
    rows["scheduled_exit_session"] = pd.to_datetime(
        rows["scheduled_exit_session"], utc=True, errors="coerce"
    ).dt.normalize()
    rows["proposed_tranche_weight"] = pd.to_numeric(
        rows["proposed_tranche_weight"], errors="coerce"
    )
    if (
        rows[["entry_session", "scheduled_exit_session", "proposed_tranche_weight"]]
        .isna()
        .any(axis=None)
    ):
        raise ValueError("ready schedule contains invalid target or boundary values")
    if (rows["scheduled_exit_session"] < rows["entry_session"]).any():
        raise ValueError("schedule exit precedes entry")

    candidates = tuple(sorted(rows["candidate"].unique()))
    open_components = {
        candidate: pd.DataFrame(0.0, index=sessions, columns=list(symbols))
        for candidate in candidates
    }
    close_components = {candidate: panel.copy() for candidate, panel in open_components.items()}
    audit_rows: list[dict[str, Any]] = []
    for row in rows.itertuples(index=False):
        entry = pd.Timestamp(row.entry_session)
        exit_ = pd.Timestamp(row.scheduled_exit_session)
        if entry not in sessions or exit_ not in sessions:
            raise ValueError("ready schedule boundary is outside execution sessions")
        quantity = float(row.proposed_tranche_weight) * float(
            account_quantity_per_weight[row.symbol]
        )
        open_mask = (sessions >= entry) & (sessions <= exit_)
        close_mask = (sessions >= entry) & (sessions < exit_)
        open_components[row.candidate].loc[open_mask, row.symbol] += quantity
        close_components[row.candidate].loc[close_mask, row.symbol] += quantity
        audit_rows.append(
            {
                "candidate": row.candidate,
                "symbol": row.symbol,
                "entry_session": entry,
                "scheduled_exit_session": exit_,
                "weight": float(row.proposed_tranche_weight),
                "account_quantity": quantity,
            }
        )
    # The execution engine itself performs the final netting and cost booking.
    net_component_quantity_panels(open_components)
    net_component_quantity_panels(close_components)
    return open_components, close_components, pd.DataFrame(audit_rows)
