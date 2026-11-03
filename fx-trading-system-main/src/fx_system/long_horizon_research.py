from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .long_horizon import LongHorizonBuildResult
from .long_horizon_config import LongHorizonConfig, LongHorizonSettings
from .statistical_validation import (
    benjamini_hochberg,
    benjamini_yekutieli,
    minimum_resamples_for_fdr,
    monte_carlo_p_value_standard_error,
)


@dataclass
class LongHorizonScreenResult:
    train_statistics: pd.DataFrame
    oos_statistics: pd.DataFrame
    stability_summary: pd.DataFrame
    summary: dict[str, Any]


def _block_bootstrap_mean_p_value(
    values: pd.Series,
    settings: LongHorizonSettings,
    seed_offset: int,
) -> tuple[float, float, int]:
    clean = values.replace([np.inf, -np.inf], np.nan).dropna().to_numpy(dtype=float)
    block_length = max(
        1,
        int(np.ceil(settings.bootstrap_block_days / settings.rebalance_interval_days)),
    )
    if len(clean) < block_length * 2:
        return (float(np.mean(clean)) if len(clean) else 0.0), 1.0, 0
    observed = float(np.mean(clean))
    centered = clean - observed
    block_length = min(block_length, len(centered))
    circular = np.concatenate([centered, centered[: block_length - 1]])
    block_means = np.convolve(circular, np.ones(block_length), mode="valid") / block_length
    block_count = int(np.ceil(len(centered) / block_length))
    generator = np.random.default_rng(settings.random_state + seed_offset)
    starts = generator.integers(
        0, len(centered), size=(settings.bootstrap_samples, block_count)
    )
    null_means = block_means[starts].mean(axis=1)
    p_value = float(
        (1 + np.count_nonzero(np.abs(null_means) >= abs(observed)))
        / (settings.bootstrap_samples + 1)
    )
    return observed, p_value, block_count


def _cross_sectional_daily_ic(frame: pd.DataFrame) -> pd.Series:
    def calculate(group: pd.DataFrame) -> float:
        valid = group[["factor", "outcome"]].dropna()
        if len(valid) < 5 or valid["factor"].nunique() < 3 or valid["outcome"].nunique() < 3:
            return float("nan")
        return float(valid["factor"].corr(valid["outcome"], method="spearman"))

    return frame.groupby("_feature_time", sort=True).apply(calculate, include_groups=False)


def _cross_sectional_quintile_spread(frame: pd.DataFrame) -> float:
    def calculate(group: pd.DataFrame) -> float:
        valid = group[["factor", "outcome"]].dropna()
        if len(valid) < 5 or valid["factor"].nunique() < 5:
            return float("nan")
        try:
            buckets = pd.qcut(valid["factor"], 5, labels=False, duplicates="drop")
        except ValueError:
            return float("nan")
        means = valid.groupby(buckets, observed=True)["outcome"].mean()
        return float(means.iloc[-1] - means.iloc[0]) if len(means) >= 2 else float("nan")

    spreads = frame.groupby("_feature_time", sort=True).apply(
        calculate, include_groups=False
    )
    return float(spreads.mean()) if spreads.notna().any() else 0.0


def _time_series_directional_rank_contributions(frame: pd.DataFrame) -> pd.Series:
    """Aggregate within-symbol rank contributions on joint feature dates."""
    contributions: list[pd.DataFrame] = []
    for _symbol, group in frame.groupby("_symbol", sort=True):
        valid = group[["_feature_time", "factor", "outcome"]].dropna().copy()
        if len(valid) < 20 or valid["factor"].nunique() < 3 or valid["outcome"].nunique() < 3:
            continue
        factor_rank = valid["factor"].rank(method="average", pct=True)
        outcome_rank = valid["outcome"].rank(method="average", pct=True)
        factor_scale = float(factor_rank.std(ddof=0))
        outcome_scale = float(outcome_rank.std(ddof=0))
        if factor_scale <= 1e-12 or outcome_scale <= 1e-12:
            continue
        valid["contribution"] = (
            (factor_rank - factor_rank.mean()) / factor_scale
        ) * ((outcome_rank - outcome_rank.mean()) / outcome_scale)
        contributions.append(valid[["_feature_time", "contribution"]])
    if not contributions:
        return pd.Series(dtype=float)
    combined = pd.concat(contributions, ignore_index=True)
    return combined.groupby("_feature_time", sort=True)["contribution"].mean()


def _time_series_directional_quintile_spread(frame: pd.DataFrame) -> float:
    spreads: list[float] = []
    for _symbol, group in frame.groupby("_symbol", sort=True):
        valid = group[["factor", "outcome"]].dropna()
        if len(valid) < 50 or valid["factor"].nunique() < 5:
            continue
        try:
            buckets = pd.qcut(valid["factor"], 5, labels=False, duplicates="drop")
        except ValueError:
            continue
        means = valid.groupby(buckets, observed=True)["outcome"].mean()
        if len(means) >= 2:
            spreads.append(float(means.iloc[-1] - means.iloc[0]))
    return float(np.mean(spreads)) if spreads else float("nan")


def _regime_rank_contributions(frame: pd.DataFrame) -> pd.Series:
    daily = frame.groupby("_feature_time", sort=True).agg(
        factor=("factor", "median"), outcome=("outcome", "median")
    )
    daily = daily.dropna()
    if len(daily) < 20 or daily["factor"].nunique() < 3 or daily["outcome"].nunique() < 3:
        return pd.Series(dtype=float)
    factor_rank = daily["factor"].rank(method="average", pct=True)
    outcome_rank = daily["outcome"].rank(method="average", pct=True)
    factor_scale = float(factor_rank.std(ddof=0))
    outcome_scale = float(outcome_rank.std(ddof=0))
    if factor_scale <= 1e-12 or outcome_scale <= 1e-12:
        return pd.Series(dtype=float)
    return ((factor_rank - factor_rank.mean()) / factor_scale) * (
        (outcome_rank - outcome_rank.mean()) / outcome_scale
    )


def _regime_quintile_spread(frame: pd.DataFrame) -> float:
    daily = frame.groupby("_feature_time", sort=True).agg(
        factor=("factor", "median"), outcome=("outcome", "median")
    )
    daily = daily.dropna()
    if len(daily) < 50 or daily["factor"].nunique() < 5:
        return float("nan")
    try:
        buckets = pd.qcut(daily["factor"], 5, labels=False, duplicates="drop")
    except ValueError:
        return float("nan")
    means = daily.groupby(buckets, observed=True)["outcome"].mean()
    return float(means.iloc[-1] - means.iloc[0]) if len(means) >= 2 else float("nan")


def _filter_oos_horizon_before_test_end(
    test: pd.DataFrame,
    horizon: int,
    test_end_exclusive: pd.Timestamp,
) -> pd.DataFrame:
    """Keep only OOS rows whose per-horizon label end is strictly before test end.

    Rows with missing label-end times are excluded. Equality with
    ``test_end_exclusive`` is treated as spill and dropped.
    """
    label_end_col = f"_label_end_time_{horizon}d"
    if label_end_col not in test.columns:
        raise KeyError(f"missing OOS spill column: {label_end_col}")
    end = pd.Timestamp(test_end_exclusive)
    label_end = pd.to_datetime(test[label_end_col], utc=True, errors="coerce")
    keep = label_end.notna() & (label_end < end)
    return test.loc[keep].copy()


def _one_factor_statistic(
    frame: pd.DataFrame,
    *,
    factor: str,
    horizon: int,
    directional: bool,
    settings: LongHorizonSettings,
    seed_offset: int,
    run_bootstrap: bool,
) -> dict[str, Any]:
    outcome_column = f"_forward_mid_return_{horizon}d"
    work = frame[["_feature_time", "_symbol", factor, outcome_column]].copy()
    work.columns = ["_feature_time", "_symbol", "factor", "raw_outcome"]
    work["outcome"] = work["raw_outcome"] if directional else work["raw_outcome"].abs()
    work = work.replace([np.inf, -np.inf], np.nan)
    total_rows = len(work)
    valid_rows = int(work[["factor", "outcome"]].notna().all(axis=1).sum())
    coverage = valid_rows / total_rows if total_rows else 0.0
    if directional:
        if settings.research_mode == "time_series_panel":
            time_scores = _time_series_directional_rank_contributions(work)
            spread = _time_series_directional_quintile_spread(work)
            test_role = "within_symbol_time_series_directional_return"
        else:
            time_scores = _cross_sectional_daily_ic(work)
            spread = _cross_sectional_quintile_spread(work)
            test_role = "cross_sectional_directional_return"
        observed = float(time_scores.mean()) if time_scores.notna().any() else 0.0
    else:
        time_scores = _regime_rank_contributions(work)
        observed = float(time_scores.mean()) if len(time_scores) else 0.0
        spread = _regime_quintile_spread(work)
        test_role = "time_series_absolute_return_regime"
    if run_bootstrap:
        observed, p_value, time_blocks = _block_bootstrap_mean_p_value(
            time_scores, settings, seed_offset
        )
    else:
        p_value = float("nan")
        time_blocks = 0
    return {
        "factor": factor,
        "horizon_days": horizon,
        "directional": directional,
        "test_role": test_role,
        "coverage": coverage,
        "ic": observed,
        "absolute_ic": abs(observed),
        "quintile_spread": spread,
        "valid_rows": valid_rows,
        "time_points": int(time_scores.notna().sum()),
        "bootstrap_p_value": p_value,
        "effective_time_blocks": time_blocks,
    }


def _fold_frames(
    build: LongHorizonBuildResult,
    fold_row: pd.Series,
    maximum_horizon: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    dataset = build.dataset
    label_end = f"_label_end_time_{maximum_horizon}d"
    train = dataset.loc[
        (dataset["_feature_time"] >= fold_row["train_start"])
        & (dataset["_feature_time"] < fold_row["train_end_exclusive"])
        & dataset["_rebalance_eligible"]
        & dataset[label_end].notna()
        & (dataset[label_end] < fold_row["test_start"])
    ]
    test = dataset.loc[
        (dataset["_feature_time"] >= fold_row["test_start"])
        & (dataset["_feature_time"] < fold_row["test_end_exclusive"])
        & dataset["_rebalance_eligible"]
        & dataset[label_end].notna()
    ]
    return train, test


def run_long_horizon_screen(
    build: LongHorizonBuildResult,
    config: LongHorizonConfig,
) -> LongHorizonScreenResult:
    if build.folds.empty:
        raise ValueError("no complete long-horizon walk-forward fold is available")
    catalog = build.catalog.set_index("name")
    train_rows: list[dict[str, Any]] = []
    oos_rows: list[dict[str, Any]] = []
    hypotheses_per_fold = len(catalog) * len(config.research.horizons)
    minimum_resamples = minimum_resamples_for_fdr(
        hypotheses_per_fold, config.research.factor_fdr_level
    )
    minimum_by_resamples = minimum_resamples_for_fdr(
        hypotheses_per_fold,
        config.research.factor_fdr_level,
        method="by",
    )
    if config.research.bootstrap_samples < minimum_resamples:
        raise ValueError(
            "bootstrap_samples cannot resolve the first Benjamini-Hochberg threshold: "
            f"configured={config.research.bootstrap_samples}, required>={minimum_resamples}"
        )
    for _, fold_row in build.folds.iterrows():
        fold = int(fold_row["fold"])
        train, test = _fold_frames(build, fold_row, config.research.maximum_horizon)
        fold_train: list[dict[str, Any]] = []
        for horizon_number, horizon in enumerate(config.research.horizons):
            for factor_number, (factor, definition) in enumerate(catalog.iterrows()):
                statistic = _one_factor_statistic(
                    train,
                    factor=factor,
                    horizon=horizon,
                    directional=bool(definition["directional"]),
                    settings=config.research,
                    seed_offset=fold * hypotheses_per_fold
                    + horizon_number * len(catalog)
                    + factor_number,
                    run_bootstrap=True,
                )
                statistic.update(
                    {
                        "fold": fold,
                        "train_start": fold_row["train_start"],
                        "train_end_exclusive": fold_row["train_end_exclusive"],
                    }
                )
                fold_train.append(statistic)
        fold_train_frame = pd.DataFrame(fold_train)
        fold_train_frame["fdr_q_value"] = benjamini_hochberg(
            fold_train_frame["bootstrap_p_value"]
        )
        fold_train_frame["by_fdr_q_value"] = benjamini_yekutieli(
            fold_train_frame["bootstrap_p_value"]
        )
        fold_train_frame["by_fdr_significant"] = (
            fold_train_frame["by_fdr_q_value"] <= config.research.factor_fdr_level
        )
        fold_train_frame["selected"] = (
            (fold_train_frame["coverage"] >= config.research.minimum_factor_coverage)
            & (
                fold_train_frame["absolute_ic"]
                >= config.research.minimum_absolute_train_ic
            )
            & (fold_train_frame["fdr_q_value"] <= config.research.factor_fdr_level)
        )
        train_rows.extend(fold_train_frame.to_dict("records"))

        selection = fold_train_frame.set_index(["factor", "horizon_days"])
        for horizon in config.research.horizons:
            # Fix 3 (per-horizon spill gate): the OOS outcome window for this
            # horizon must not cross the test-fold exclusive end. Feature time
            # windows are already non-overlapping, but a long-horizon label end
            # can land in the next fold; exclude those rows for this horizon.
            test_horizon = _filter_oos_horizon_before_test_end(
                test,
                horizon=horizon,
                test_end_exclusive=fold_row["test_end_exclusive"],
            )
            for factor, definition in catalog.iterrows():
                training = selection.loc[(factor, horizon)]
                was_selected = bool(training["selected"])
                if was_selected:
                    # Fix 2 (OOS only for selected): materialize OOS statistics
                    # solely for factor/horizons selected in training. Computing
                    # OOS for the whole catalog would open outcomes the freeze
                    # contract says to view only after training selection.
                    statistic = _one_factor_statistic(
                        test_horizon,
                        factor=factor,
                        horizon=horizon,
                        directional=bool(definition["directional"]),
                        settings=config.research,
                        seed_offset=0,
                        run_bootstrap=False,
                    )
                    statistic.update(
                        {
                            "fold": fold,
                            "test_start": fold_row["test_start"],
                            "test_end_exclusive": fold_row["test_end_exclusive"],
                            "selected_in_train": True,
                            "train_ic": float(training["ic"]),
                            "train_fdr_q_value": float(training["fdr_q_value"]),
                            "train_by_fdr_q_value": float(training["by_fdr_q_value"]),
                            "sign_matches_train": bool(
                                float(training["ic"]) * float(statistic["ic"]) > 0
                            ),
                            "oos_evaluated": True,
                        }
                    )
                else:
                    statistic = {
                        "factor": factor,
                        "horizon_days": horizon,
                        "directional": bool(definition["directional"]),
                        "test_role": "",
                        "coverage": float("nan"),
                        "ic": float("nan"),
                        "absolute_ic": float("nan"),
                        "quintile_spread": float("nan"),
                        "valid_rows": int(test_horizon.shape[0]),
                        "time_points": 0,
                        "bootstrap_p_value": float("nan"),
                        "effective_time_blocks": 0,
                        "fold": fold,
                        "test_start": fold_row["test_start"],
                        "test_end_exclusive": fold_row["test_end_exclusive"],
                        "selected_in_train": False,
                        "train_ic": float(training["ic"]),
                        "train_fdr_q_value": float(training["fdr_q_value"]),
                        "train_by_fdr_q_value": float(training["by_fdr_q_value"]),
                        "sign_matches_train": False,
                        "oos_evaluated": False,
                    }
                oos_rows.append(statistic)

    train_statistics = pd.DataFrame(train_rows).sort_values(
        ["fold", "fdr_q_value", "absolute_ic"]
    )
    oos_statistics = pd.DataFrame(oos_rows).sort_values(
        ["fold", "horizon_days", "factor"]
    )
    summary_rows: list[dict[str, Any]] = []
    for (factor, horizon), group in oos_statistics.groupby(
        ["factor", "horizon_days"], sort=True
    ):
        selected = group.loc[group["selected_in_train"]]
        summary_rows.append(
            {
                "factor": factor,
                "horizon_days": horizon,
                "folds": len(group),
                "selected_folds": len(selected),
                "selection_fraction": float(group["selected_in_train"].mean()),
                "mean_train_ic": float(group["train_ic"].mean()),
                "mean_oos_ic_when_selected": (
                    float(selected["ic"].mean()) if len(selected) else float("nan")
                ),
                "worst_oos_ic_when_selected": (
                    float(selected["ic"].min()) if len(selected) else float("nan")
                ),
                "sign_match_fraction_when_selected": (
                    float(selected["sign_matches_train"].mean())
                    if len(selected)
                    else float("nan")
                ),
                "mean_oos_quintile_spread_when_selected": (
                    float(selected["quintile_spread"].mean())
                    if len(selected)
                    else float("nan")
                ),
            }
        )
    stability_summary = pd.DataFrame(summary_rows).sort_values(
        ["selection_fraction", "sign_match_fraction_when_selected"],
        ascending=[False, False],
        na_position="last",
    )
    selected_oos = oos_statistics.loc[oos_statistics["selected_in_train"]]
    selected_train = train_statistics.loc[train_statistics["selected"]]
    repeated = stability_summary.loc[stability_summary["selected_folds"] >= 2]
    summary = {
        "folds": len(build.folds),
        "factors": len(catalog),
        "horizons": config.research.horizons,
        "hypotheses_per_fold": hypotheses_per_fold,
        "total_train_hypotheses": len(train_statistics),
        "selected_train_hypotheses": int(train_statistics["selected"].sum()),
        "by_significant_train_hypotheses": int(
            train_statistics["by_fdr_significant"].sum()
        ),
        "selected_train_hypotheses_passing_by_sensitivity": int(
            selected_train["by_fdr_significant"].sum()
        ),
        "selected_directional_train_hypotheses": int(
            selected_train["directional"].sum()
        ),
        "selected_risk_state_train_hypotheses": int(
            (~selected_train["directional"]).sum()
        ),
        "selected_oos_evaluations": len(selected_oos),
        "selected_directional_oos_evaluations": int(selected_oos["directional"].sum()),
        "selected_risk_state_oos_evaluations": int((~selected_oos["directional"]).sum()),
        "factor_horizons_selected_in_at_least_two_folds": len(repeated),
        "directional_factor_horizons_selected_in_at_least_two_folds": int(
            repeated["factor"].map(catalog["directional"]).sum()
        ),
        "selected_oos_sign_match_fraction": (
            float(selected_oos["sign_matches_train"].mean())
            if len(selected_oos)
            else 0.0
        ),
        "rebalance_interval_days": config.research.rebalance_interval_days,
        "bootstrap_block_days": config.research.bootstrap_block_days,
        "bootstrap_block_observations": int(
            np.ceil(
                config.research.bootstrap_block_days
                / config.research.rebalance_interval_days
            )
        ),
        "minimum_bootstrap_samples_for_fdr_resolution": minimum_resamples,
        "minimum_bootstrap_samples_for_by_fdr_resolution": minimum_by_resamples,
        "bootstrap_minimum_attainable_p_value": 1
        / (config.research.bootstrap_samples + 1),
        "bootstrap_mc_standard_error_at_first_bh_threshold": (
            monte_carlo_p_value_standard_error(
                config.research.factor_fdr_level / hypotheses_per_fold,
                config.research.bootstrap_samples,
            )
        ),
        "fdr_selection_method": "benjamini_hochberg",
        "by_arbitrary_dependence_adjustment_is_sensitivity_only": True,
        "observations_are_rebalance_eligible": True,
        "research_mode": config.research.research_mode,
        "interpretation": (
            "Exploratory factor diagnostics only. OOS windows are non-overlapping, selection is "
            "training-only, and no cost-adjusted portfolio claim is made."
        ),
    }
    return LongHorizonScreenResult(
        train_statistics, oos_statistics, stability_summary, summary
    )


def write_long_horizon_screen_artifacts(
    result: LongHorizonScreenResult,
    output_directory: str | Path,
) -> Path:
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    result.train_statistics.to_csv(output / "train_factor_statistics.csv", index=False)
    result.oos_statistics.to_csv(output / "oos_factor_statistics.csv", index=False)
    result.stability_summary.to_csv(output / "factor_stability_summary.csv", index=False)
    (output / "screen_summary.json").write_text(
        json.dumps(result.summary, indent=2, allow_nan=False), encoding="utf-8"
    )
    return output
