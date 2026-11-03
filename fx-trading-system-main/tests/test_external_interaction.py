from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from fx_system.external_interaction import (
    ALL_HYPOTHESIS_COUNT,
    FORMAL_INTERACTION_SPECS,
    build_complete_date_panel,
    build_interaction_folds,
    build_outcome_blind_interaction_design,
    run_external_interaction_screen,
)


def _inputs(years: int = 6) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    start = pd.Timestamp("2016-01-01", tz="UTC")
    dates = pd.date_range(
        start,
        start + pd.DateOffset(years=years),
        inclusive="left",
        freq="D",
    )
    rows = []
    for number, symbol in enumerate(("EURUSD", "GBPUSD")):
        for position, date in enumerate(dates):
            rows.append(
                {
                    "_feature_time": date,
                    "_symbol": symbol,
                    "momentum_252d_skip_21d": np.sin(position / 23.0) + number * 0.1,
                    "vol_ratio_21_126": 1.0 + 0.2 * np.cos(position / 17.0),
                }
            )
    price = pd.DataFrame(rows)
    external = pd.DataFrame(
        {
            "decision_time": dates,
            "gscpi_risk_state_pit": np.sin(np.arange(len(dates)) / 41.0),
            "us_cpi_12m_log_inflation": np.cos(np.arange(len(dates)) / 31.0),
            "us_ip_6m_log_growth": np.sin(np.arange(len(dates)) / 19.0),
            "benchmark_publication_state": np.arange(len(dates)) % 8,
            "phillyfed_spf_release_state": np.arange(len(dates)) % 2,
        }
    )
    lineage_rows = []
    for date in dates:
        for feature in external.columns[1:]:
            lineage_rows.append(
                {
                    "decision_time": date,
                    "feature_name": feature,
                    "source_available_time": date - timedelta(hours=1),
                    "source_eligibility": "verified_strict_pit",
                    "feature_status": "ready",
                }
            )
    lineage = pd.DataFrame(lineage_rows)
    return price, external, lineage


def _with_labels(design_frame: pd.DataFrame) -> pd.DataFrame:
    result = design_frame.copy()
    position = result["_decision_time"].dt.dayofyear.to_numpy()
    result["_feature_time"] = result["_decision_time"]
    positions = result["_decision_time"].drop_duplicates().sort_values()
    eligible = {value: number % 21 == 0 for number, value in enumerate(positions)}
    result["_rebalance_eligible"] = result["_decision_time"].map(eligible)
    result["_forward_mid_return_21d"] = np.sin(position / 13.0) * 0.01
    result["_forward_mid_return_63d"] = np.cos(position / 29.0) * 0.02
    result["_label_end_time_21d"] = result["_decision_time"] + timedelta(days=21)
    result["_label_end_time_63d"] = result["_decision_time"] + timedelta(days=63)
    return result


def test_design_requires_both_symbols_and_keeps_only_complete_dates() -> None:
    price, external, lineage = _inputs(1)
    price = price.loc[~((price["_symbol"] == "GBPUSD") & (price["_feature_time"].dt.day == 3))]
    design = build_outcome_blind_interaction_design(price, external, external_lineage=lineage)
    assert len(design.frame) == 2 * (len(external) - 12)
    assert design.frame.groupby("_decision_time")["_symbol"].nunique().eq(2).all()
    assert tuple(design.external_features) == (
        "us_cpi_12m_log_inflation",
        "us_ip_6m_log_growth",
        "benchmark_publication_state",
        "phillyfed_spf_release_state",
    )


def test_future_available_time_is_rejected_before_join() -> None:
    price, external, lineage = _inputs(1)
    lineage.loc[lineage.index[0], "source_available_time"] = lineage.loc[
        lineage.index[0], "decision_time"
    ] + timedelta(minutes=1)
    with pytest.raises(ValueError, match="future availability"):
        build_outcome_blind_interaction_design(price, external, external_lineage=lineage)


def test_interaction_design_prefix_is_invariant_to_future_external_mutation() -> None:
    price, external, lineage = _inputs(2)
    cutoff = pd.Timestamp("2017-01-01", tz="UTC")
    baseline = build_outcome_blind_interaction_design(
        price, external, external_lineage=lineage
    ).frame
    changed_external = external.copy()
    future = changed_external["decision_time"] > cutoff
    changed_external.loc[future, "us_cpi_12m_log_inflation"] += 999.0
    changed_external.loc[future, "us_ip_6m_log_growth"] -= 999.0
    changed = build_outcome_blind_interaction_design(
        price, changed_external, external_lineage=lineage
    ).frame
    pd.testing.assert_frame_equal(
        baseline.loc[baseline["_decision_time"] <= cutoff].reset_index(drop=True),
        changed.loc[changed["_decision_time"] <= cutoff].reset_index(drop=True),
    )


def test_labels_are_closed_by_default_and_oos_mutation_cannot_change_training() -> None:
    price, external, lineage = _inputs(7)
    design = build_outcome_blind_interaction_design(price, external, external_lineage=lineage)
    labelled = build_complete_date_panel(design, _with_labels(design.frame))
    folds = build_interaction_folds(labelled)
    assert len(folds) == 1
    with pytest.raises(PermissionError, match="explicit authorization"):
        run_external_interaction_screen(labelled, folds)

    first = run_external_interaction_screen(
        labelled, folds, open_return_labels=True, bootstrap_samples=100
    )
    changed = labelled.copy()
    test_start = folds.iloc[0]["test_start"]
    test_rows = changed["_decision_time"] >= test_start
    changed.loc[test_rows, "_forward_mid_return_21d"] *= 100.0
    changed.loc[test_rows, "_forward_mid_return_63d"] *= -100.0
    second = run_external_interaction_screen(
        changed, folds, open_return_labels=True, bootstrap_samples=100
    )
    pd.testing.assert_frame_equal(
        first.train_statistics.reset_index(drop=True),
        second.train_statistics.reset_index(drop=True),
    )
    assert first.summary["hypotheses_per_fold"] == ALL_HYPOTHESIS_COUNT == 8
    assert len(FORMAL_INTERACTION_SPECS) == 4
    assert first.summary["trading_approval"] is False
