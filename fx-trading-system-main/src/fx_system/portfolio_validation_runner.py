"""Fail-closed validation bridge for cost-adjusted portfolio ledgers.

This module deliberately starts *after* candidate construction.  It does not
select factors, create targets, or approve a strategy.  Its only job is to
turn a disclosed set of :class:`PortfolioRunResult` ledgers into the strict
common-date net-return matrix required by DSR, CSCV/PBO, and SPA.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .portfolio_runner import PortfolioRunResult
from .portfolio_validation import (
    DeflatedSharpeResult,
    PBOResult,
    SPAInputs,
    cscv_probability_of_backtest_overfitting,
    deflated_sharpe_ratio,
    prepare_spa_inputs,
    validate_daily_net_return_matrix,
)

_REQUIRED_LEDGER_COLUMNS = (
    "execution_mode",
    "previous_nav",
    "price_pnl",
    "spread_cost",
    "slippage_cost",
    "financing",
    "cash_interest",
    "net_pnl",
    "nav",
    "simple_return",
    "broker_turnover",
)
_NUMERIC_LEDGER_COLUMNS = tuple(
    column for column in _REQUIRED_LEDGER_COLUMNS if column != "execution_mode"
)


@dataclass(frozen=True)
class PortfolioCandidateValidationResult:
    """Joint diagnostics over complete, cost-adjusted candidate ledgers.

    ``deflated_sharpe`` being ``None`` and ``pbo.defined`` being false are
    explicit diagnostic failures.  No field in this object is a trading
    approval.
    """

    daily_net_returns: pd.DataFrame
    ledger_audit: pd.DataFrame
    deflated_sharpe: DeflatedSharpeResult | None
    pbo: PBOResult
    spa_inputs: SPAInputs
    manifest: dict[str, Any]


def _validate_candidate_name(raw_name: object) -> str:
    if not isinstance(raw_name, str) or not raw_name.strip():
        raise ValueError("candidate names must be non-empty strings")
    if raw_name != raw_name.strip():
        raise ValueError("candidate names cannot have leading or trailing whitespace")
    return raw_name


def _validate_ledger_frame(name: str, run: PortfolioRunResult) -> pd.DataFrame:
    if not isinstance(run, PortfolioRunResult):
        raise TypeError(f"candidate {name!r} must be a PortfolioRunResult")
    frame = run.to_frame()
    missing = sorted(set(_REQUIRED_LEDGER_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"candidate {name!r} ledger is missing columns: {missing}")
    if frame.empty:
        raise ValueError(f"candidate {name!r} ledger cannot be empty")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError(f"candidate {name!r} ledger must use a DatetimeIndex")
    if frame.index.hasnans or not frame.index.is_unique:
        raise ValueError(f"candidate {name!r} ledger dates must be valid and unique")
    if not frame.index.is_monotonic_increasing:
        raise ValueError(f"candidate {name!r} ledger dates must be sorted")

    numeric = frame.loc[:, _NUMERIC_LEDGER_COLUMNS].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError(f"candidate {name!r} ledger contains non-finite accounting values")
    if (numeric["previous_nav"] <= 0).any() or (numeric["nav"] <= 0).any():
        raise ValueError(f"candidate {name!r} ledger NAV must remain positive")
    if (numeric["spread_cost"] < 0).any() or (numeric["slippage_cost"] < 0).any():
        raise ValueError(f"candidate {name!r} ledger execution costs cannot be negative")
    if (numeric["broker_turnover"] < 0).any():
        raise ValueError(f"candidate {name!r} ledger turnover cannot be negative")

    component_pnl = (
        numeric["price_pnl"]
        - numeric["spread_cost"]
        - numeric["slippage_cost"]
        + numeric["financing"]
        + numeric["cash_interest"]
    )
    checks = {
        "net PnL components": (numeric["net_pnl"], component_pnl),
        "NAV movement": (
            numeric["nav"],
            numeric["previous_nav"] + numeric["net_pnl"],
        ),
        "daily simple return": (
            numeric["simple_return"],
            numeric["net_pnl"] / numeric["previous_nav"],
        ),
    }
    for label, (actual, expected) in checks.items():
        if not np.allclose(actual, expected, rtol=1e-12, atol=1e-12):
            raise ValueError(f"candidate {name!r} ledger fails {label} reconciliation")

    initial_nav = float(numeric.iloc[0]["previous_nav"])
    final_nav = float(numeric.iloc[-1]["nav"])
    compounded = float(np.prod(1.0 + numeric["simple_return"].to_numpy(dtype=float)))
    if not math.isclose(compounded, final_nav / initial_nav, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError(f"candidate {name!r} ledger returns do not compound to final NAV")
    return frame.loc[:, _REQUIRED_LEDGER_COLUMNS].copy()


def run_portfolio_candidate_validation(
    candidates: Mapping[str, PortfolioRunResult],
    *,
    candidate_set_is_complete: bool,
    declared_candidate_names: Sequence[str],
    selected_candidate: str,
    total_trials_evaluated: int,
    benchmark_returns: pd.Series | None = None,
) -> PortfolioCandidateValidationResult:
    """Connect complete candidate ledgers to joint DSR/PBO/SPA diagnostics.

    Every ledger must have exactly the same daily index and the supplied names
    must exactly match the separately frozen ``declared_candidate_names``.
    The function never takes an inner intersection or fills a missing return.
    ``selected_candidate`` is supplied by the caller and is never chosen from
    these realized returns.
    """

    if candidate_set_is_complete is not True:
        raise ValueError("formal portfolio validation requires the complete candidate set")
    if not isinstance(candidates, Mapping) or not candidates:
        raise ValueError("candidates must be a non-empty mapping")
    if isinstance(declared_candidate_names, (str, bytes)):
        raise ValueError("declared_candidate_names must be a sequence of names")
    declared = tuple(_validate_candidate_name(name) for name in declared_candidate_names)
    if not declared or len(declared) != len(set(declared)):
        raise ValueError("declared_candidate_names must be non-empty and unique")
    selected = _validate_candidate_name(selected_candidate)
    if isinstance(total_trials_evaluated, bool) or not isinstance(
        total_trials_evaluated, (int, np.integer)
    ):
        raise ValueError("total_trials_evaluated must be an integer")
    trial_count = int(total_trials_evaluated)

    frames: dict[str, pd.DataFrame] = {}
    expected_index: pd.DatetimeIndex | None = None
    for raw_name, run in candidates.items():
        name = _validate_candidate_name(raw_name)
        if name in frames:
            raise ValueError(f"duplicate candidate name {name!r}")
        frame = _validate_ledger_frame(name, run)
        if expected_index is None:
            expected_index = frame.index
        elif not frame.index.equals(expected_index):
            raise ValueError(
                f"candidate {name!r} ledger does not have the exact common date index"
            )
        frames[name] = frame

    supplied_names = set(frames)
    declared_names = set(declared)
    if supplied_names != declared_names:
        raise ValueError(
            "candidates do not exactly match declared_candidate_names; "
            f"missing={sorted(declared_names - supplied_names)}, "
            f"unexpected={sorted(supplied_names - declared_names)}"
        )
    frames = {name: frames[name] for name in declared}

    if selected not in frames:
        raise ValueError("selected_candidate is not present in candidates")
    if trial_count < max(2, len(frames)):
        raise ValueError("total_trials_evaluated must disclose all inspected trials")

    return_matrix = pd.DataFrame(
        {name: frame["simple_return"] for name, frame in frames.items()}
    )
    return_matrix.index.name = "date"
    return_matrix = validate_daily_net_return_matrix(return_matrix)

    # SPA validation is intentionally outside the DSR exception boundary: an
    # invalid benchmark/index must stop the complete run rather than produce a
    # partially usable artifact set.
    spa_inputs = prepare_spa_inputs(
        return_matrix,
        benchmark_returns=benchmark_returns,
    )
    try:
        dsr = deflated_sharpe_ratio(
            return_matrix,
            selected_candidate=selected,
            total_trials_evaluated=trial_count,
        )
    except ValueError as error:
        dsr = None
        dsr_reason: str | None = str(error)
    else:
        dsr_reason = None
    pbo = cscv_probability_of_backtest_overfitting(return_matrix)

    audits: list[dict[str, Any]] = []
    for name, frame in frames.items():
        audits.append(
            {
                "candidate": name,
                "observations": len(frame),
                "start": frame.index[0],
                "end": frame.index[-1],
                "initial_nav": float(frame.iloc[0]["previous_nav"]),
                "final_nav": float(frame.iloc[-1]["nav"]),
                "compounded_return": float(
                    frame.iloc[-1]["nav"] / frame.iloc[0]["previous_nav"] - 1.0
                ),
                "price_pnl": float(frame["price_pnl"].sum()),
                "spread_cost": float(frame["spread_cost"].sum()),
                "slippage_cost": float(frame["slippage_cost"].sum()),
                "financing": float(frame["financing"].sum()),
                "cash_interest": float(frame["cash_interest"].sum()),
                "net_pnl": float(frame["net_pnl"].sum()),
                "broker_turnover": float(frame["broker_turnover"].sum()),
                "accounting_reconciled": True,
            }
        )
    ledger_audit = pd.DataFrame(audits).sort_values("candidate").reset_index(drop=True)
    manifest: dict[str, Any] = {
        "candidate_set_is_complete": True,
        "candidate_count": len(frames),
        "candidate_names": list(return_matrix.columns),
        "declared_candidate_names_matched_exactly": True,
        "common_dates": len(return_matrix),
        "common_start": return_matrix.index[0].isoformat(),
        "common_end": return_matrix.index[-1].isoformat(),
        "date_alignment": "exact_shared_ledger_index_no_intersection_or_fill",
        "return_source": "cost_adjusted_master_account_daily_simple_return",
        "selected_candidate_for_dsr_diagnostic": selected,
        "selected_candidate_was_not_chosen_by_runner": True,
        "total_trials_evaluated": trial_count,
        "deflated_sharpe_defined": dsr is not None,
        "deflated_sharpe_undefined_reason": dsr_reason,
        "pbo_defined": pbo.defined,
        "pbo_undefined_reason": pbo.reason,
        "spa_executed": False,
        "spa_input_validation_passed": True,
        "trading_approval": False,
        "interpretation": (
            "Research diagnostics only. This bridge does not construct, select, or approve "
            "a strategy; frozen forward evidence and target-broker costs remain required."
        ),
    }
    return PortfolioCandidateValidationResult(
        daily_net_returns=return_matrix,
        ledger_audit=ledger_audit,
        deflated_sharpe=dsr,
        pbo=pbo,
        spa_inputs=spa_inputs,
        manifest=manifest,
    )


def write_portfolio_candidate_validation_artifacts(
    result: PortfolioCandidateValidationResult,
    output_directory: str | Path,
) -> Path:
    """Write auditable diagnostics without executing SPA or approving a trade."""

    if not isinstance(result, PortfolioCandidateValidationResult):
        raise TypeError("result must be a PortfolioCandidateValidationResult")
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, dict[str, object]] = {}

    def write_csv(frame: pd.DataFrame | pd.Series, name: str, *, index: bool) -> None:
        path = output / name
        temporary = path.with_name(f".{path.name}.tmp")
        try:
            frame.to_csv(temporary, index=index)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        artifacts[name] = {
            "sha256": digest,
            "bytes": path.stat().st_size,
            "rows": len(frame),
        }

    write_csv(result.daily_net_returns, "daily_net_returns.csv", index=True)
    write_csv(result.ledger_audit, "ledger_accounting_audit.csv", index=False)
    write_csv(
        result.spa_inputs.benchmark_losses,
        "spa_benchmark_losses.csv",
        index=True,
    )
    write_csv(
        result.spa_inputs.candidate_losses,
        "spa_candidate_losses.csv",
        index=True,
    )
    pbo_splits = pd.DataFrame(
        {
            "logit": result.pbo.logits,
            "oos_percentile": result.pbo.oos_percentiles,
        }
    )
    write_csv(pbo_splits, "pbo_splits.csv", index=False)
    pbo_counts = pd.DataFrame(
        result.pbo.selection_counts, columns=["candidate", "selections"]
    )
    write_csv(pbo_counts, "pbo_selection_counts.csv", index=False)
    manifest = dict(result.manifest)
    manifest["artifacts"] = artifacts
    manifest["deflated_sharpe"] = (
        asdict(result.deflated_sharpe) if result.deflated_sharpe is not None else None
    )
    manifest["pbo"] = {
        "defined": result.pbo.defined,
        "pbo": result.pbo.pbo,
        "reason": result.pbo.reason,
        "block_count": result.pbo.block_count,
        "block_sizes": result.pbo.block_sizes,
        "split_count": result.pbo.split_count,
    }
    manifest_path = output / "portfolio_validation_manifest.json"
    manifest_temporary = manifest_path.with_name(f".{manifest_path.name}.tmp")
    try:
        manifest_temporary.write_text(
            json.dumps(manifest, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        manifest_temporary.replace(manifest_path)
    finally:
        manifest_temporary.unlink(missing_ok=True)
    return output


__all__ = [
    "PortfolioCandidateValidationResult",
    "run_portfolio_candidate_validation",
    "write_portfolio_candidate_validation_artifacts",
]
