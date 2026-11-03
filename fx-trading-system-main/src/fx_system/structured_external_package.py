"""Integrity-preserving composition of formal structured external features."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from fx_system.structured_event_controls import EVENT_CONTROL_FEATURES
from fx_system.structured_external_features import FORMAL_REGIME_FEATURES

FORMAL_STRUCTURED_FEATURES = (*FORMAL_REGIME_FEATURES, *EVENT_CONTROL_FEATURES)


@dataclass(frozen=True)
class StructuredExternalFeaturePackage:
    """Five formal feature values and their unified row-level lineage."""

    values: pd.DataFrame
    lineage: pd.DataFrame


def _normalize_values(
    frame: pd.DataFrame,
    *,
    expected_features: tuple[str, ...],
    panel_name: str,
) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"{panel_name} values must be a pandas DataFrame")
    expected_columns = {"decision_time", *expected_features}
    if set(frame.columns) != expected_columns:
        raise ValueError(f"{panel_name} values do not contain the exact feature columns")
    result = frame.copy()
    result["decision_time"] = pd.to_datetime(
        result["decision_time"], utc=True, errors="coerce", format="mixed"
    )
    if (
        result.empty
        or result["decision_time"].isna().any()
        or result["decision_time"].duplicated().any()
    ):
        raise ValueError(f"{panel_name} values contain invalid decision keys")
    result = result.sort_values("decision_time").reset_index(drop=True)
    for feature in expected_features:
        if result[feature].map(lambda value: isinstance(value, (bool, np.bool_))).any():
            raise ValueError(f"{panel_name} feature {feature} contains booleans")
        result[feature] = pd.to_numeric(result[feature], errors="coerce")
        finite = result[feature].dropna()
        if not np.isfinite(finite).all():
            raise ValueError(f"{panel_name} feature {feature} contains non-finite values")
    return result[["decision_time", *expected_features]]


def _normalize_lineage(
    frame: pd.DataFrame,
    *,
    expected_features: tuple[str, ...],
    decisions: pd.DatetimeIndex,
    panel_name: str,
) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"{panel_name} lineage must be a pandas DataFrame")
    required = {
        "decision_time",
        "feature_name",
        "feature_value",
        "source_id",
        "source_available_time",
        "source_eligibility",
        "feature_status",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{panel_name} lineage is missing columns {sorted(missing)}")
    result = frame.copy()
    result["decision_time"] = pd.to_datetime(
        result["decision_time"], utc=True, errors="coerce", format="mixed"
    )
    result["source_available_time"] = pd.to_datetime(
        result["source_available_time"], utc=True, errors="coerce", format="mixed"
    )
    if result["decision_time"].isna().any():
        raise ValueError(f"{panel_name} lineage contains invalid decision_time")
    if set(result["feature_name"]) != set(expected_features):
        raise ValueError(f"{panel_name} lineage feature set is incompatible")
    if result.duplicated(["decision_time", "feature_name"]).any():
        raise ValueError(f"{panel_name} lineage contains duplicate decision/feature keys")
    expected_keys = pd.MultiIndex.from_product(
        [decisions, expected_features], names=["decision_time", "feature_name"]
    )
    actual_keys = pd.MultiIndex.from_frame(
        result[["decision_time", "feature_name"]]
    )
    if set(actual_keys) != set(expected_keys):
        raise ValueError(f"{panel_name} lineage does not cover every decision/feature key")
    available = result["source_available_time"].notna()
    if not (
        result.loc[available, "source_available_time"]
        <= result.loc[available, "decision_time"]
    ).all():
        raise ValueError(f"{panel_name} lineage contains future source availability")
    ready = result["feature_status"].eq("ready")
    if not result.loc[ready, "source_eligibility"].eq("verified_strict_pit").all():
        raise ValueError(f"{panel_name} ready lineage is not verified-strict PIT")
    return result.sort_values(["decision_time", "feature_name"]).reset_index(drop=True)


def _verify_lineage_values(
    values: pd.DataFrame,
    lineage: pd.DataFrame,
    features: tuple[str, ...],
    *,
    panel_name: str,
) -> None:
    indexed = lineage.set_index(["decision_time", "feature_name"])["feature_value"]
    for feature in features:
        lineage_values = pd.to_numeric(
            indexed.xs(feature, level="feature_name"), errors="coerce"
        ).reindex(values["decision_time"])
        actual = values.set_index("decision_time")[feature]
        if not np.allclose(
            actual.to_numpy(dtype=float),
            lineage_values.to_numpy(dtype=float),
            rtol=0,
            atol=1e-12,
            equal_nan=True,
        ):
            raise ValueError(f"{panel_name} lineage disagrees with feature {feature}")


def combine_structured_external_panels(
    regime_values: pd.DataFrame,
    regime_lineage: pd.DataFrame,
    event_values: pd.DataFrame,
    event_lineage: pd.DataFrame,
) -> StructuredExternalFeaturePackage:
    """Combine exact child panels without calculating or filling any feature."""

    normalized_regime_values = _normalize_values(
        regime_values,
        expected_features=FORMAL_REGIME_FEATURES,
        panel_name="regime",
    )
    normalized_event_values = _normalize_values(
        event_values,
        expected_features=EVENT_CONTROL_FEATURES,
        panel_name="event",
    )
    regime_decisions = pd.DatetimeIndex(normalized_regime_values["decision_time"])
    event_decisions = pd.DatetimeIndex(normalized_event_values["decision_time"])
    if not regime_decisions.equals(event_decisions):
        raise ValueError("regime and event panels do not share exact decision keys")
    normalized_regime_lineage = _normalize_lineage(
        regime_lineage,
        expected_features=FORMAL_REGIME_FEATURES,
        decisions=regime_decisions,
        panel_name="regime",
    )
    normalized_event_lineage = _normalize_lineage(
        event_lineage,
        expected_features=EVENT_CONTROL_FEATURES,
        decisions=event_decisions,
        panel_name="event",
    )
    _verify_lineage_values(
        normalized_regime_values,
        normalized_regime_lineage,
        FORMAL_REGIME_FEATURES,
        panel_name="regime",
    )
    _verify_lineage_values(
        normalized_event_values,
        normalized_event_lineage,
        EVENT_CONTROL_FEATURES,
        panel_name="event",
    )

    benchmark = normalized_event_values["benchmark_publication_state"].dropna()
    if not benchmark.between(0, 7).all() or not np.equal(benchmark % 1, 0).all():
        raise ValueError("benchmark publication state is not a valid three-bit mask")
    spf = normalized_event_values["phillyfed_spf_release_state"].dropna()
    if not spf.isin([0, 1]).all():
        raise ValueError("SPF release state is not binary")

    values = normalized_regime_values.merge(
        normalized_event_values,
        on="decision_time",
        how="inner",
        validate="one_to_one",
    )[["decision_time", *FORMAL_STRUCTURED_FEATURES]]
    normalized_regime_lineage["lineage_kind"] = "regime"
    normalized_event_lineage["lineage_kind"] = "event_control"
    lineage = pd.concat(
        [normalized_regime_lineage, normalized_event_lineage],
        ignore_index=True,
        sort=False,
    ).sort_values(["decision_time", "feature_name"], ignore_index=True)
    return StructuredExternalFeaturePackage(values=values, lineage=lineage)


__all__ = [
    "FORMAL_STRUCTURED_FEATURES",
    "StructuredExternalFeaturePackage",
    "combine_structured_external_panels",
]
