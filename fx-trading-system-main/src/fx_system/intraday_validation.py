"""Joint event-day inference gates for frozen intraday FX candidates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

from .portfolio_validation import (
    DeflatedSharpeResult,
    PBOResult,
    SPAInputs,
    cscv_probability_of_backtest_overfitting,
    deflated_sharpe_ratio,
    prepare_spa_inputs,
    validate_daily_net_return_matrix,
)
from .research_controls import (
    FutureInformationError,
    make_future_information_canary,
    validate_research_availability,
)
from .statistical_validation import (
    benjamini_hochberg,
    benjamini_yekutieli,
    joint_stationary_bootstrap_indices,
    minimum_resamples_for_fdr,
    monte_carlo_p_value_standard_error,
)


@dataclass(frozen=True)
class IntradayReturnPanel:
    """A complete common-event-day matrix plus explicit coverage accounting."""

    returns: pd.DataFrame
    coverage: pd.DataFrame
    union_date_count: int
    common_date_count: int


@dataclass(frozen=True)
class IntradayValidationResult:
    """Inference artifacts; none of these fields is a trading approval."""

    panel: IntradayReturnPanel
    candidate_statistics: pd.DataFrame
    negative_control_statistics: pd.DataFrame
    deflated_sharpe: DeflatedSharpeResult | None
    pbo: PBOResult
    spa_inputs: SPAInputs
    manifest: dict[str, Any]


def prepare_intraday_return_panel(
    candidates: Mapping[str, pd.Series],
    *,
    candidate_set_is_complete: bool,
    minimum_common_observations: int = 40,
) -> IntradayReturnPanel:
    """Align a disclosed candidate family on its strict common event dates.

    Missing observations are never filled.  The common-date intersection is
    returned only with a per-candidate union-date coverage table, so dropping a
    hard event or an illiquid symbol cannot be hidden inside ``dropna``.
    """

    if candidate_set_is_complete is not True:
        raise ValueError("formal intraday inference requires the complete candidate set")
    if not isinstance(candidates, Mapping) or not candidates:
        raise ValueError("candidates must be a non-empty mapping of named Series")
    if (
        isinstance(minimum_common_observations, bool)
        or not isinstance(minimum_common_observations, int)
        or minimum_common_observations < 2
    ):
        raise ValueError("minimum_common_observations must be an integer of at least two")

    normalized: dict[str, pd.Series] = {}
    for raw_name, series in candidates.items():
        if not isinstance(raw_name, str) or not raw_name:
            raise ValueError("candidate names must be non-empty strings")
        if raw_name in normalized:
            raise ValueError(f"duplicate candidate name {raw_name!r}")
        if not isinstance(series, pd.Series):
            raise TypeError(f"candidate {raw_name!r} must be a pandas Series")
        index = pd.DatetimeIndex(pd.to_datetime(series.index, utc=True, errors="coerce"))
        if index.hasnans:
            raise ValueError(f"candidate {raw_name!r} contains an invalid event date")
        if not index.is_unique:
            raise ValueError(f"candidate {raw_name!r} event dates must be unique")
        numeric = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
        if np.isinf(numeric).any():
            raise ValueError(f"candidate {raw_name!r} contains an infinite return")
        normalized[raw_name] = pd.Series(numeric, index=index, name=raw_name).sort_index()

    union = pd.concat(normalized.values(), axis=1, join="outer").sort_index()
    common = union.dropna(axis=0, how="any")
    if len(common) < minimum_common_observations:
        raise ValueError(
            "intraday candidates have only "
            f"{len(common)} common event dates; require {minimum_common_observations}"
        )
    matrix = validate_daily_net_return_matrix(
        common,
        minimum_rows=minimum_common_observations,
        minimum_candidates=1,
    )
    zero_volatility = [
        column for column in matrix if float(matrix[column].std(ddof=1)) <= 0
    ]
    if zero_volatility:
        raise ValueError(f"intraday candidates have zero return volatility: {zero_volatility}")
    coverage = pd.DataFrame(
        [
            {
                "candidate": column,
                "union_dates": len(union),
                "observed_dates": int(union[column].notna().sum()),
                "missing_dates": int(union[column].isna().sum()),
                "observed_fraction": float(union[column].notna().mean()),
                "common_dates": len(common),
            }
            for column in union
        ]
    )
    matrix.index.name = "event_date"
    matrix.attrs = {
        "candidate_set_is_complete": True,
        "missing_returns_filled": False,
        "alignment": "strict_common_event_date_intersection",
    }
    return IntradayReturnPanel(
        returns=matrix,
        coverage=coverage,
        union_date_count=len(union),
        common_date_count=len(common),
    )


def generate_joint_sign_negative_controls(
    returns: pd.DataFrame,
    *,
    random_state: int,
) -> pd.DataFrame:
    """Apply one seeded Rademacher sign path jointly to every candidate."""

    matrix = validate_daily_net_return_matrix(returns)
    if isinstance(random_state, bool) or not isinstance(
        random_state, (int, np.integer)
    ):
        raise ValueError("random_state must be a non-negative integer")
    if int(random_state) < 0:
        raise ValueError("random_state must be a non-negative integer")
    generator = np.random.default_rng(int(random_state))
    signs = generator.choice(np.array([-1.0, 1.0]), size=len(matrix))
    if np.all(signs == signs[0]):
        signs[-1] *= -1
    controls = matrix.mul(signs, axis=0)
    controls.columns = [f"negative_control__{column}" for column in matrix]
    controls.attrs = {
        "negative_control": "joint_event_date_rademacher_sign",
        "random_state": int(random_state),
        "cross_candidate_date_mapping_shared": True,
    }
    return controls


def _bootstrap_mean_statistics(
    matrix: pd.DataFrame,
    indices: np.ndarray,
    *,
    fdr_level: float,
) -> pd.DataFrame:
    values = matrix.to_numpy(dtype=float)
    observed_means = values.mean(axis=0)
    centered = values - observed_means
    bootstrap_means = centered[indices].mean(axis=1)
    exceedances = (bootstrap_means >= observed_means[None, :]).sum(axis=0)
    p_values = (exceedances + 1) / (len(indices) + 1)
    bh = benjamini_hochberg(p_values)
    by = benjamini_yekutieli(p_values)
    standard_deviations = values.std(axis=0, ddof=1)
    return pd.DataFrame(
        {
            "candidate": list(matrix.columns),
            "observations": len(matrix),
            "mean_net_log_return": observed_means,
            "event_day_volatility": standard_deviations,
            "event_day_sharpe": observed_means / standard_deviations,
            "bootstrap_exceedances": exceedances.astype(int),
            "empirical_p_value": p_values,
            "p_value_mc_standard_error": [
                monte_carlo_p_value_standard_error(float(value), len(indices))
                for value in p_values
            ],
            "bh_q_value": bh,
            "by_q_value": by,
            "positive_mean": observed_means > 0,
            "bh_selected": (observed_means > 0) & (bh <= fdr_level),
            "by_sensitivity_selected": (observed_means > 0) & (by <= fdr_level),
        }
    )


def run_intraday_validation(
    panel: IntradayReturnPanel,
    *,
    resamples: int,
    expected_block_length: int = 5,
    fdr_level: float = 0.10,
    random_state: int,
    total_trials_evaluated: int,
) -> IntradayValidationResult:
    """Run synchronized event-day inference and anti-overfitting diagnostics."""

    if not isinstance(panel, IntradayReturnPanel):
        raise TypeError("panel must be an IntradayReturnPanel")
    matrix = validate_daily_net_return_matrix(panel.returns)
    if not 0 < fdr_level <= 1:
        raise ValueError("fdr_level must be between zero and one")
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 1:
        raise ValueError("resamples must be a positive integer")
    if (
        isinstance(expected_block_length, bool)
        or not isinstance(expected_block_length, int)
        or not 1 <= expected_block_length <= len(matrix)
    ):
        raise ValueError("expected_block_length must be between one and observations")
    if (
        isinstance(total_trials_evaluated, bool)
        or not isinstance(total_trials_evaluated, int)
        or total_trials_evaluated < max(2, matrix.shape[1])
    ):
        raise ValueError("total_trials_evaluated must disclose all inspected trials")
    minimum_resamples = minimum_resamples_for_fdr(matrix.shape[1], fdr_level)
    if resamples < minimum_resamples:
        raise ValueError(
            f"resamples={resamples} cannot resolve the first BH threshold; "
            f"require at least {minimum_resamples}"
        )

    indices = joint_stationary_bootstrap_indices(
        len(matrix),
        resamples=resamples,
        expected_block_length=expected_block_length,
        random_state=random_state,
    )
    candidate_statistics = _bootstrap_mean_statistics(
        matrix, indices, fdr_level=fdr_level
    )
    controls = generate_joint_sign_negative_controls(
        matrix, random_state=random_state
    )
    control_statistics = _bootstrap_mean_statistics(
        controls, indices, fdr_level=fdr_level
    )
    negative_control_pass = not bool(control_statistics["bh_selected"].any())
    candidate_statistics["negative_control_gate_pass"] = negative_control_pass
    candidate_statistics["eligible_after_controls"] = (
        candidate_statistics["bh_selected"] & negative_control_pass
    )

    selected_candidate = str(
        candidate_statistics.sort_values(
            ["mean_net_log_return", "candidate"], ascending=[False, True]
        ).iloc[0]["candidate"]
    )
    dsr: DeflatedSharpeResult | None
    dsr_reason: str | None = None
    try:
        dsr = deflated_sharpe_ratio(
            matrix,
            selected_candidate=selected_candidate,
            total_trials_evaluated=total_trials_evaluated,
        )
    except ValueError as error:
        dsr = None
        dsr_reason = str(error)
    pbo = cscv_probability_of_backtest_overfitting(matrix)
    spa_inputs = prepare_spa_inputs(matrix)

    canary = make_future_information_canary(matrix.index, lead=timedelta(seconds=1))
    try:
        validate_research_availability(canary)
    except FutureInformationError:
        future_information_canary_rejected = True
    else:  # pragma: no cover - an invariant tripwire, not a reachable research path.
        raise RuntimeError("future-information canary unexpectedly passed")

    manifest: dict[str, Any] = {
        "candidate_count": matrix.shape[1],
        "common_event_dates": len(matrix),
        "union_event_dates": panel.union_date_count,
        "common_start": matrix.index.min().isoformat(),
        "common_end": matrix.index.max().isoformat(),
        "resampling": "joint_stationary_bootstrap_event_date_rows",
        "resamples": resamples,
        "expected_block_length_event_days": expected_block_length,
        "minimum_resamples_for_bh_resolution": minimum_resamples,
        "minimum_resamples_for_by_resolution": minimum_resamples_for_fdr(
            matrix.shape[1], fdr_level, method="by"
        ),
        "empirical_p_value_formula": "(exceedances + 1) / (resamples + 1)",
        "fdr_level": fdr_level,
        "primary_fdr": "BH",
        "dependency_sensitivity": "BY",
        "negative_control": "joint_event_date_rademacher_sign",
        "negative_control_pass": negative_control_pass,
        "future_information_canary_rejected": future_information_canary_rejected,
        "selected_candidate_for_dsr_diagnostic": selected_candidate,
        "total_trials_evaluated": total_trials_evaluated,
        "deflated_sharpe_defined": dsr is not None,
        "deflated_sharpe_undefined_reason": dsr_reason,
        "pbo_defined": pbo.defined,
        "pbo_undefined_reason": pbo.reason,
        "spa_executed": False,
        "interpretation": (
            "Research diagnostics only; a selected row is not a trading approval and still "
            "requires frozen forward evidence and target-broker execution calibration."
        ),
    }
    return IntradayValidationResult(
        panel=panel,
        candidate_statistics=candidate_statistics,
        negative_control_statistics=control_statistics,
        deflated_sharpe=dsr,
        pbo=pbo,
        spa_inputs=spa_inputs,
        manifest=manifest,
    )


__all__ = [
    "IntradayReturnPanel",
    "IntradayValidationResult",
    "generate_joint_sign_negative_controls",
    "prepare_intraday_return_panel",
    "run_intraday_validation",
]
