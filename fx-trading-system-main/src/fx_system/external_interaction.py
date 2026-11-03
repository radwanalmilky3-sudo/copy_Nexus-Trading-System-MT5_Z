"""Outcome-blind price x structured-external interaction research.

This module freezes the small interaction family from the second-layer
preregistration.  It deliberately separates feature preparation from outcome
screening: callers can build and audit the PIT design while return labels stay
closed.  The screen path requires an explicit acknowledgement and never
evaluates non-selected OOS hypotheses.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .research_controls import joint_date_mapping
from .statistical_validation import (
    benjamini_hochberg,
    benjamini_yekutieli,
    minimum_resamples_for_fdr,
)
from .structured_external_package import FORMAL_STRUCTURED_FEATURES

PRICE_FEATURES = ("momentum_252d_skip_21d", "vol_ratio_21_126")
STATE_FEATURES = ("us_cpi_12m_log_inflation", "us_ip_6m_log_growth")
EVENT_CONTROL_FEATURES = ("benchmark_publication_state", "phillyfed_spf_release_state")
REQUIRED_SYMBOLS = ("EURUSD", "GBPUSD")

FORMAL_INTERACTION_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "INT-01",
        "price_feature": "momentum_252d_skip_21d",
        "state_feature": "us_cpi_12m_log_inflation",
        "horizon_days": 63,
        "directional": True,
    },
    {
        "id": "INT-02",
        "price_feature": "momentum_252d_skip_21d",
        "state_feature": "us_ip_6m_log_growth",
        "horizon_days": 63,
        "directional": True,
    },
    {
        "id": "INT-03",
        "price_feature": "vol_ratio_21_126",
        "state_feature": "us_cpi_12m_log_inflation",
        "horizon_days": 21,
        "directional": False,
    },
    {
        "id": "INT-04",
        "price_feature": "vol_ratio_21_126",
        "state_feature": "us_ip_6m_log_growth",
        "horizon_days": 21,
        "directional": False,
    },
)
SHADOW_IDS = tuple(f"SHADOW-{index:02d}" for index in range(1, 5))
ALL_HYPOTHESIS_COUNT = len(FORMAL_INTERACTION_SPECS) * 2


@dataclass(frozen=True)
class InteractionDesign:
    """A complete-date, PIT-checked feature design without outcomes."""

    frame: pd.DataFrame
    decision_dates: pd.DatetimeIndex
    symbols: tuple[str, ...]
    external_features: tuple[str, ...]


@dataclass(frozen=True)
class InteractionScreenResult:
    train_statistics: pd.DataFrame
    oos_statistics: pd.DataFrame
    summary: dict[str, Any]


def _utc_dates(values: pd.Series | pd.Index, label: str) -> pd.Series:
    parsed = pd.to_datetime(values, utc=True, errors="coerce", format="mixed")
    if parsed.isna().any():
        raise ValueError(f"{label} contains invalid timestamps")
    return pd.Series(parsed).dt.normalize()


def _validate_external_package(
    external_values: pd.DataFrame,
    external_lineage: pd.DataFrame | None,
) -> pd.DataFrame:
    required = {"decision_time", *FORMAL_STRUCTURED_FEATURES}
    if set(external_values.columns) != required:
        raise ValueError("external values do not contain the exact five-feature package")
    values = external_values.copy()
    values["decision_time"] = pd.to_datetime(
        values["decision_time"], utc=True, errors="coerce", format="mixed"
    )
    if values["decision_time"].isna().any() or values["decision_time"].duplicated().any():
        raise ValueError("external decision keys must be valid and unique")
    values = values.sort_values("decision_time").reset_index(drop=True)
    for feature in FORMAL_STRUCTURED_FEATURES:
        values[feature] = pd.to_numeric(values[feature], errors="coerce")
        finite = values[feature].dropna().to_numpy(dtype=float)
        if not np.isfinite(finite).all():
            raise ValueError(f"external feature {feature} contains non-finite values")
    if external_lineage is not None:
        required_lineage = {
            "decision_time",
            "feature_name",
            "source_available_time",
            "source_eligibility",
            "feature_status",
        }
        if not required_lineage.issubset(external_lineage.columns):
            raise ValueError("external lineage is missing PIT audit columns")
        lineage = external_lineage.copy()
        lineage["decision_time"] = pd.to_datetime(
            lineage["decision_time"], utc=True, errors="coerce", format="mixed"
        )
        lineage["source_available_time"] = pd.to_datetime(
            lineage["source_available_time"], utc=True, errors="coerce", format="mixed"
        )
        if lineage[["decision_time", "feature_name"]].duplicated().any():
            raise ValueError("external lineage has duplicate decision/feature keys")
        ready = lineage["feature_status"].eq("ready")
        available = lineage["source_available_time"].notna()
        if not (lineage.loc[ready, "source_eligibility"].eq("verified_strict_pit").all()):
            raise ValueError("ready external lineage is not strict PIT")
        if not (
            lineage.loc[available, "source_available_time"]
            <= lineage.loc[available, "decision_time"]
        ).all():
            raise ValueError("external lineage contains future availability")
    return values


def build_outcome_blind_interaction_design(
    price_panel: pd.DataFrame,
    external_values: pd.DataFrame,
    *,
    external_lineage: pd.DataFrame | None = None,
    symbols: tuple[str, ...] = REQUIRED_SYMBOLS,
) -> InteractionDesign:
    """Join price factors to the verified external package without outcomes.

    A date is retained only when every requested symbol has every price factor,
    both formal states, and both event controls.  No value is forward-filled.
    The external package is validated before the join, so a future available
    time fails closed even when the value itself looks plausible.
    """
    if tuple(symbols) != REQUIRED_SYMBOLS:
        raise ValueError("the preregistered interaction family is fixed to EURUSD and GBPUSD")
    required_price = {"_feature_time", "_symbol", *PRICE_FEATURES}
    if not required_price.issubset(price_panel.columns):
        raise ValueError(
            f"price panel is missing columns {sorted(required_price - set(price_panel))}"
        )
    prices = price_panel.copy()
    prices["_symbol"] = prices["_symbol"].astype(str)
    if not set(prices["_symbol"]).issubset(set(symbols)):
        raise ValueError("price panel contains a symbol outside the preregistered pair")
    prices["_decision_time"] = _utc_dates(prices["_feature_time"], "price feature time")
    if prices.duplicated(["_decision_time", "_symbol"]).any():
        raise ValueError("price panel has duplicate symbol/decision-date keys")
    prices = prices[["_decision_time", "_symbol", *PRICE_FEATURES]]
    for feature in PRICE_FEATURES:
        prices[feature] = pd.to_numeric(prices[feature], errors="coerce")
        finite = prices[feature].dropna().to_numpy(dtype=float)
        if not np.isfinite(finite).all():
            raise ValueError(f"price feature {feature} contains non-finite values")

    external = _validate_external_package(external_values, external_lineage)
    external["_decision_time"] = external["decision_time"].dt.normalize()
    external = external.drop(columns=["decision_time"])
    all_features = [*STATE_FEATURES, *EVENT_CONTROL_FEATURES]
    joined = prices.merge(external, on="_decision_time", how="left", validate="many_to_one")
    complete = joined[[*PRICE_FEATURES, *all_features]].notna().all(axis=1)
    joined = joined.loc[complete].copy()
    counts = joined.groupby("_decision_time", sort=True)["_symbol"].nunique()
    complete_dates = counts[counts == len(symbols)].index
    joined = joined.loc[joined["_decision_time"].isin(complete_dates)].copy()
    joined = joined.sort_values(["_decision_time", "_symbol"]).reset_index(drop=True)
    dates = pd.DatetimeIndex(sorted(joined["_decision_time"].unique()), name="decision_time")
    if dates.empty:
        raise ValueError("no complete PIT interaction dates remain")
    return InteractionDesign(
        frame=joined,
        decision_dates=dates,
        symbols=tuple(symbols),
        external_features=tuple(all_features),
    )


def build_complete_date_panel(
    design: InteractionDesign,
    outcomes: pd.DataFrame,
    *,
    required_horizons: tuple[int, ...] = (21, 63),
) -> pd.DataFrame:
    """Attach labels only after explicit caller authorization.

    The same date mask is applied to both symbols and both horizons.  A date
    with any missing factor, state, event control, label or label end is removed
    for the whole interaction family.
    """
    if not isinstance(outcomes, pd.DataFrame):
        raise TypeError("outcomes must be a DataFrame")
    required = {"_feature_time", "_symbol", "_rebalance_eligible"}
    for horizon in required_horizons:
        required.update({f"_forward_mid_return_{horizon}d", f"_label_end_time_{horizon}d"})
    if not required.issubset(outcomes.columns):
        raise ValueError(f"outcomes are missing columns {sorted(required - set(outcomes))}")
    labels = outcomes[[*required]].copy()
    labels["_decision_time"] = _utc_dates(labels["_feature_time"], "outcome feature time")
    if labels.duplicated(["_decision_time", "_symbol"]).any():
        raise ValueError("outcomes have duplicate symbol/decision-date keys")
    joined = design.frame.merge(
        labels.drop(columns=["_feature_time"]),
        on=["_decision_time", "_symbol"],
        how="inner",
        validate="one_to_one",
    )
    required_label_columns = [
        "_rebalance_eligible",
        *[
            column
            for horizon in required_horizons
            for column in (
                f"_forward_mid_return_{horizon}d",
                f"_label_end_time_{horizon}d",
            )
        ],
    ]
    joined[required_label_columns] = joined[required_label_columns].replace(
        [np.inf, -np.inf], np.nan
    )
    for horizon in required_horizons:
        joined[f"_label_end_time_{horizon}d"] = pd.to_datetime(
            joined[f"_label_end_time_{horizon}d"], utc=True, errors="coerce"
        )
    complete = joined[required_label_columns].notna().all(axis=1)
    complete &= joined["_rebalance_eligible"].eq(True)
    joined = joined.loc[complete].copy()
    counts = joined.groupby("_decision_time", sort=True)["_symbol"].nunique()
    complete_dates = counts[counts == len(design.symbols)].index
    joined = joined.loc[joined["_decision_time"].isin(complete_dates)]
    return joined.sort_values(["_decision_time", "_symbol"]).reset_index(drop=True)


def build_interaction_folds(
    panel: pd.DataFrame,
    *,
    train_years: int = 5,
    test_years: int = 1,
    step_years: int = 1,
    maximum_horizon: int = 63,
) -> pd.DataFrame:
    """Build non-overlapping one-year OOS folds with a purged train end."""
    if panel.empty:
        raise ValueError("interaction panel cannot be empty")
    dates = pd.DatetimeIndex(sorted(panel["_decision_time"].unique()))
    first = dates.min()
    last = dates.max()
    rows: list[dict[str, Any]] = []
    test_start = first + pd.DateOffset(years=train_years)
    fold = 0
    label_end_column = f"_label_end_time_{maximum_horizon}d"
    while test_start + pd.DateOffset(years=test_years) <= last + timedelta(days=1):
        test_end = test_start + pd.DateOffset(years=test_years)
        train_start = test_start - pd.DateOffset(years=train_years)
        train_dates = dates[(dates >= train_start) & (dates < test_start)]
        test_dates = dates[(dates >= test_start) & (dates < test_end)]
        if label_end_column in panel:
            ends = pd.to_datetime(panel[label_end_column], utc=True, errors="coerce")
            train_mask = (
                (panel["_decision_time"] >= train_start)
                & (panel["_decision_time"] < test_start)
                & ends.lt(test_start)
            )
            train_dates = pd.DatetimeIndex(sorted(panel.loc[train_mask, "_decision_time"].unique()))
            test_mask = (
                (panel["_decision_time"] >= test_start)
                & (panel["_decision_time"] < test_end)
                & ends.lt(test_end)
            )
            test_dates = pd.DatetimeIndex(sorted(panel.loc[test_mask, "_decision_time"].unique()))
        if len(train_dates) and len(test_dates):
            rows.append(
                {
                    "fold": fold,
                    "train_start": train_start,
                    "train_end_exclusive": test_start,
                    "test_start": test_start,
                    "test_end_exclusive": test_end,
                    "train_dates": len(train_dates),
                    "test_dates": len(test_dates),
                    "purge_rule": f"label_end_time_{maximum_horizon}d < test_start",
                }
            )
            fold += 1
        test_start += pd.DateOffset(years=step_years)
    return pd.DataFrame(rows)


def _fit_ecdf(values: pd.Series) -> np.ndarray:
    clean = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    if len(clean) < 3 or not np.isfinite(clean).all() or np.unique(clean).size < 3:
        raise ValueError("ECDF requires at least three finite distinct training values")
    return np.sort(clean)


def _apply_ecdf(values: pd.Series, sorted_training: np.ndarray) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    result = pd.Series(np.nan, index=values.index, dtype=float)
    valid = numeric.notna()
    raw = numeric.loc[valid].to_numpy(dtype=float)
    left = np.searchsorted(sorted_training, raw, side="left")
    right = np.searchsorted(sorted_training, raw, side="right")
    midpoint = (left + right) / 2.0
    result.loc[valid] = 2.0 * ((midpoint + 0.5) / (len(sorted_training) + 1.0)) - 1.0
    return result


def _rank_fold(train: pd.DataFrame, test: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    train = train.copy()
    test = test.copy()
    for price in PRICE_FEATURES:
        for symbol in REQUIRED_SYMBOLS:
            mask_train = train["_symbol"].eq(symbol)
            mask_test = test["_symbol"].eq(symbol)
            ecdf = _fit_ecdf(train.loc[mask_train, price])
            train.loc[mask_train, f"_rank__{price}"] = _apply_ecdf(
                train.loc[mask_train, price], ecdf
            )
            test.loc[mask_test, f"_rank__{price}"] = _apply_ecdf(test.loc[mask_test, price], ecdf)
    for state in STATE_FEATURES:
        dates = train[["_decision_time", state]].drop_duplicates("_decision_time")
        ecdf = _fit_ecdf(dates[state])
        train.loc[:, f"_rank__{state}"] = _apply_ecdf(train[state], ecdf)
        test.loc[:, f"_rank__{state}"] = _apply_ecdf(test[state], ecdf)
    return train, test


def _bootstrap_score_p_value(
    scores: np.ndarray,
    *,
    samples: int,
    block_length: int,
    random_state: int,
) -> tuple[float, float]:
    clean = np.asarray(scores, dtype=float)
    clean = clean[np.isfinite(clean)]
    if len(clean) < max(6, block_length * 2):
        return float(np.mean(clean)) if len(clean) else 0.0, 1.0
    observed = float(np.mean(clean))
    centered = clean - observed
    block_length = min(block_length, len(centered) // 2)
    block_count = int(np.ceil(len(centered) / block_length))
    generator = np.random.default_rng(random_state)
    starts = generator.integers(0, len(centered), size=(samples, block_count))
    offsets = np.arange(block_length)
    indices = (starts[:, :, None] + offsets[None, None, :]) % len(centered)
    null = centered[indices.reshape(samples, -1)[:, : len(centered)]].mean(axis=1)
    p_value = float((1 + np.count_nonzero(np.abs(null) >= abs(observed))) / (samples + 1))
    return observed, p_value


def _interaction_statistic(
    frame: pd.DataFrame,
    spec: dict[str, Any],
    *,
    external_override: pd.Series | None = None,
    bootstrap_samples: int = 2_000,
    block_length: int = 3,
    random_state: int = 42,
) -> dict[str, Any]:
    price_col = f"_rank__{spec['price_feature']}"
    state_col = (
        external_override.name
        if external_override is not None
        else f"_rank__{spec['state_feature']}"
    )
    outcome_col = f"_forward_mid_return_{spec['horizon_days']}d"
    values = frame[
        ["_decision_time", "_symbol", price_col, state_col, outcome_col, *EVENT_CONTROL_FEATURES]
    ].copy()
    values["outcome"] = (
        values[outcome_col].abs() if not spec["directional"] else values[outcome_col]
    )
    values["interaction"] = values[price_col] * values[state_col]
    values = values.replace([np.inf, -np.inf], np.nan).dropna()
    if values.empty:
        return {"coverage": 0.0, "dates": 0, "gamma": 0.0, "p_value": 1.0}
    # Frisch-Waugh-Lovell residualization controls main effects, symbol fixed
    # effect, and preregistered nuisance event states before testing gamma.
    symbol_dummy = values["_symbol"].eq("GBPUSD").astype(float)
    controls = np.column_stack(
        [
            np.ones(len(values)),
            values[price_col].to_numpy(float),
            values[state_col].to_numpy(float),
            symbol_dummy.to_numpy(float),
            values["benchmark_publication_state"].to_numpy(float),
            values["phillyfed_spf_release_state"].to_numpy(float),
        ]
    )
    interaction = values["interaction"].to_numpy(float)
    outcome = values["outcome"].to_numpy(float)
    x_residual = interaction - controls @ np.linalg.lstsq(controls, interaction, rcond=None)[0]
    y_residual = outcome - controls @ np.linalg.lstsq(controls, outcome, rcond=None)[0]
    denominator = float(np.dot(x_residual, x_residual))
    if denominator <= 1e-12:
        return {"coverage": 0.0, "dates": 0, "gamma": 0.0, "p_value": 1.0}
    values["score"] = x_residual * y_residual
    scores = values.groupby("_decision_time", sort=True)["score"].sum().to_numpy(float)
    gamma = float(scores.sum() / denominator)
    _observed, p_value = _bootstrap_score_p_value(
        scores,
        samples=bootstrap_samples,
        block_length=block_length,
        random_state=random_state,
    )
    return {
        "coverage": float(len(values) / max(len(frame), 1)),
        "dates": int(len(scores)),
        "gamma": gamma,
        "absolute_gamma": abs(gamma),
        "p_value": p_value,
        "valid_rows": int(len(values)),
    }


def _shadow_state(train: pd.DataFrame, feature: str, random_state: int) -> pd.Series:
    dates = (
        train[["_decision_time", feature]]
        .drop_duplicates("_decision_time")
        .sort_values("_decision_time")
    )
    values = dates[feature].to_numpy(float)
    if len(values) < 4:
        raise ValueError("matched shadow state needs at least four training dates")
    mapping = joint_date_mapping(len(values), method="circular_shift", random_state=random_state)
    shadow = pd.Series(
        values[mapping], index=dates["_decision_time"], name=f"_rank__{feature}__shadow"
    )
    return train["_decision_time"].map(shadow)


def run_external_interaction_screen(
    panel: pd.DataFrame,
    folds: pd.DataFrame,
    *,
    open_return_labels: bool = False,
    bootstrap_samples: int = 2_000,
    block_length: int = 3,
    random_state: int = 42,
    fdr_level: float = 0.10,
) -> InteractionScreenResult:
    """Run the fixed 4+4 family; refuse unless labels are explicitly opened."""
    if not open_return_labels:
        raise PermissionError(
            "interaction screen refuses to open return labels without explicit authorization"
        )
    required = {"_decision_time", "_symbol", *PRICE_FEATURES, *STATE_FEATURES}
    if not required.issubset(panel.columns):
        raise ValueError(f"interaction panel missing columns {sorted(required - set(panel))}")
    minimum_bootstrap = minimum_resamples_for_fdr(ALL_HYPOTHESIS_COUNT, fdr_level)
    if bootstrap_samples < minimum_bootstrap:
        raise ValueError(
            "bootstrap_samples cannot resolve the eight-hypothesis BH family: "
            f"configured={bootstrap_samples}, required>={minimum_bootstrap}"
        )
    train_rows: list[dict[str, Any]] = []
    oos_rows: list[dict[str, Any]] = []
    for _, fold in folds.iterrows():
        fold_number = int(fold["fold"])
        train = panel.loc[
            (panel["_decision_time"] >= fold["train_start"])
            & (panel["_decision_time"] < fold["train_end_exclusive"])
        ].copy()
        test = panel.loc[
            (panel["_decision_time"] >= fold["test_start"])
            & (panel["_decision_time"] < fold["test_end_exclusive"])
        ].copy()
        train, test = _rank_fold(train, test)
        for shadow_number, spec in enumerate(FORMAL_INTERACTION_SPECS):
            shadow = _shadow_state(train, spec["state_feature"], random_state + shadow_number)
            shadow_column = f"_rank__{spec['state_feature']}__shadow"
            train[shadow_column] = shadow.to_numpy()
            shadow_spec = {**spec, "id": SHADOW_IDS[shadow_number]}
            statistic = _interaction_statistic(
                train,
                shadow_spec,
                external_override=train[shadow_column],
                bootstrap_samples=bootstrap_samples,
                block_length=block_length,
                random_state=random_state + fold_number * ALL_HYPOTHESIS_COUNT + shadow_number,
            )
            statistic.update(
                {"fold": fold_number, "hypothesis_id": SHADOW_IDS[shadow_number], "shadow": True}
            )
            train_rows.append(statistic)
        formal_rows = []
        for spec_number, spec in enumerate(FORMAL_INTERACTION_SPECS):
            statistic = _interaction_statistic(
                train,
                spec,
                bootstrap_samples=bootstrap_samples,
                block_length=block_length,
                random_state=random_state + fold_number * ALL_HYPOTHESIS_COUNT + 4 + spec_number,
            )
            statistic.update({"fold": fold_number, "hypothesis_id": spec["id"], "shadow": False})
            formal_rows.append(statistic)
            train_rows.append(statistic)
        fold_frame = pd.DataFrame(
            [
                *formal_rows,
                *[
                    row
                    for row in train_rows
                    if row.get("fold") == fold_number and row.get("shadow")
                ],
            ]
        )
        fold_frame["bh_q_value"] = benjamini_hochberg(fold_frame["p_value"].fillna(1.0))
        fold_frame["by_q_value"] = benjamini_yekutieli(fold_frame["p_value"].fillna(1.0))
        for row in train_rows:
            if row["fold"] == fold_number:
                matched = fold_frame.loc[fold_frame["hypothesis_id"] == row["hypothesis_id"]].iloc[
                    0
                ]
                row["bh_q_value"] = float(matched["bh_q_value"])
                row["by_q_value"] = float(matched["by_q_value"])
                row["selected"] = bool(
                    (not row["shadow"])
                    and row["coverage"] >= 0.60
                    and row["bh_q_value"] <= fdr_level
                )
        selected = [row for row in formal_rows if row.get("selected", False)]
        for row in selected:
            spec = next(
                item for item in FORMAL_INTERACTION_SPECS if item["id"] == row["hypothesis_id"]
            )
            statistic = _interaction_statistic(
                test,
                spec,
                bootstrap_samples=bootstrap_samples,
                block_length=block_length,
                random_state=random_state + 10000 + fold_number,
            )
            statistic.update(
                {
                    "fold": fold_number,
                    "hypothesis_id": row["hypothesis_id"],
                    "selected_in_train": True,
                }
            )
            oos_rows.append(statistic)
    train_frame = pd.DataFrame(train_rows)
    oos_frame = pd.DataFrame(oos_rows)
    summary = {
        "hypotheses_per_fold": ALL_HYPOTHESIS_COUNT,
        "formal_hypotheses": len(FORMAL_INTERACTION_SPECS),
        "matched_shadow_hypotheses": len(SHADOW_IDS),
        "folds": int(len(folds)),
        "train_rows": int(len(train_frame)),
        "oos_rows": int(len(oos_frame)),
        "return_labels_opened": True,
        "factor_outcome_evaluations_added": int(len(train_frame) + len(oos_frame)),
        "trading_approval": False,
        "verdict": (
            "external_interaction_candidate_requires_new_forward"
            if bool(train_frame.get("selected", pd.Series(dtype=bool)).any())
            else "empty_external_interaction_model"
        ),
    }
    return InteractionScreenResult(train_frame, oos_frame, summary)


def write_external_interaction_artifacts(
    result: InteractionScreenResult,
    output_directory: str | Path,
    *,
    input_sha256: dict[str, str],
) -> Path:
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    result.train_statistics.to_csv(output / "train_interaction_statistics.csv", index=False)
    result.oos_statistics.to_csv(output / "oos_interaction_statistics.csv", index=False)
    manifest = {
        "schema_version": 1,
        "stage": "structured_external_interaction_screen",
        "inputs": input_sha256,
        "specifications": [dict(spec) for spec in FORMAL_INTERACTION_SPECS],
        "shadow_ids": list(SHADOW_IDS),
        **result.summary,
        "formal_net_returns_ready": False,
    }
    path = output / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return output


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "ALL_HYPOTHESIS_COUNT",
    "EVENT_CONTROL_FEATURES",
    "FORMAL_INTERACTION_SPECS",
    "InteractionDesign",
    "InteractionScreenResult",
    "PRICE_FEATURES",
    "REQUIRED_SYMBOLS",
    "SHADOW_IDS",
    "STATE_FEATURES",
    "build_complete_date_panel",
    "build_interaction_folds",
    "build_outcome_blind_interaction_design",
    "run_external_interaction_screen",
    "sha256_file",
    "write_external_interaction_artifacts",
]
