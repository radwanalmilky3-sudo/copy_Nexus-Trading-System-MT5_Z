from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fx_system.structured_event_controls import EVENT_CONTROL_FEATURES
from fx_system.structured_external_features import FORMAL_REGIME_FEATURES
from fx_system.structured_external_package import (
    FORMAL_STRUCTURED_FEATURES,
    combine_structured_external_panels,
)


def _values(features: tuple[str, ...]) -> pd.DataFrame:
    decisions = pd.date_range("2024-01-01", periods=2, freq="D", tz="UTC")
    frame = pd.DataFrame({"decision_time": decisions})
    for position, feature in enumerate(features, start=1):
        frame[feature] = [np.nan if position == 1 else float(position), float(position)]
    if features == EVENT_CONTROL_FEATURES:
        frame["benchmark_publication_state"] = [np.nan, 7.0]
        frame["phillyfed_spf_release_state"] = [0.0, 1.0]
    return frame


def _lineage(values: pd.DataFrame, features: tuple[str, ...]) -> pd.DataFrame:
    rows = []
    for _, value_row in values.iterrows():
        for feature in features:
            value = value_row[feature]
            ready = pd.notna(value)
            rows.append(
                {
                    "decision_time": value_row["decision_time"],
                    "feature_name": feature,
                    "feature_value": value,
                    "source_id": f"source_{feature}",
                    "source_available_time": (
                        value_row["decision_time"] - pd.Timedelta(1, unit="h")
                        if ready
                        else pd.NaT
                    ),
                    "source_eligibility": (
                        "verified_strict_pit" if ready else "unavailable"
                    ),
                    "feature_status": "ready" if ready else "unavailable",
                }
            )
    return pd.DataFrame(rows)


def test_combine_structured_external_panels_preserves_exact_values_and_lineage() -> None:
    regime_values = _values(FORMAL_REGIME_FEATURES)
    event_values = _values(EVENT_CONTROL_FEATURES)
    package = combine_structured_external_panels(
        regime_values,
        _lineage(regime_values, FORMAL_REGIME_FEATURES),
        event_values,
        _lineage(event_values, EVENT_CONTROL_FEATURES),
    )

    assert list(package.values.columns) == ["decision_time", *FORMAL_STRUCTURED_FEATURES]
    assert len(package.lineage) == 2 * len(FORMAL_STRUCTURED_FEATURES)
    assert package.lineage.groupby("feature_name").size().eq(2).all()
    assert set(package.lineage["lineage_kind"]) == {"regime", "event_control"}


def test_package_rejects_mismatched_decisions_values_and_future_lineage() -> None:
    regime_values = _values(FORMAL_REGIME_FEATURES)
    event_values = _values(EVENT_CONTROL_FEATURES)
    regime_lineage = _lineage(regime_values, FORMAL_REGIME_FEATURES)
    event_lineage = _lineage(event_values, EVENT_CONTROL_FEATURES)

    mismatched_decisions = event_values.copy()
    mismatched_decisions.loc[1, "decision_time"] += pd.Timedelta(24, unit="h")
    with pytest.raises(ValueError, match="exact decision keys"):
        combine_structured_external_panels(
            regime_values,
            regime_lineage,
            mismatched_decisions,
            event_lineage,
        )

    changed_lineage = regime_lineage.copy()
    changed_lineage.loc[
        changed_lineage["feature_name"].eq(FORMAL_REGIME_FEATURES[0])
        & changed_lineage["feature_status"].eq("ready"),
        "feature_value",
    ] += 1
    with pytest.raises(ValueError, match="lineage disagrees"):
        combine_structured_external_panels(
            regime_values,
            changed_lineage,
            event_values,
            event_lineage,
        )

    future_lineage = event_lineage.copy()
    ready = future_lineage["source_available_time"].notna()
    future_lineage.loc[ready, "source_available_time"] = (
        future_lineage.loc[ready, "decision_time"] + pd.Timedelta(1, unit="h")
    )
    with pytest.raises(ValueError, match="future source availability"):
        combine_structured_external_panels(
            regime_values,
            regime_lineage,
            event_values,
            future_lineage,
        )


def test_package_rejects_invalid_event_state_and_incomplete_lineage() -> None:
    regime_values = _values(FORMAL_REGIME_FEATURES)
    event_values = _values(EVENT_CONTROL_FEATURES)
    regime_lineage = _lineage(regime_values, FORMAL_REGIME_FEATURES)
    event_lineage = _lineage(event_values, EVENT_CONTROL_FEATURES)

    invalid_event = event_values.copy()
    invalid_event.loc[1, "benchmark_publication_state"] = 8
    invalid_lineage = _lineage(invalid_event, EVENT_CONTROL_FEATURES)
    with pytest.raises(ValueError, match="three-bit mask"):
        combine_structured_external_panels(
            regime_values,
            regime_lineage,
            invalid_event,
            invalid_lineage,
        )

    incomplete = event_lineage.iloc[:-1]
    with pytest.raises(ValueError, match="does not cover every"):
        combine_structured_external_panels(
            regime_values,
            regime_lineage,
            event_values,
            incomplete,
        )
