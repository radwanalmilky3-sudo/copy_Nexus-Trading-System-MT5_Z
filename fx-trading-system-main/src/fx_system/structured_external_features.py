"""Strict point-in-time feature extraction for structured external factor sources."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from fx_system.macro_vintages import extract_rtdsm_asof_features

GSCPI_REQUIRED_COLUMNS = frozenset(
    {
        "observation_time",
        "available_time",
        "vintage_label",
        "series_id",
        "value",
        "provider",
        "quality",
    }
)
GSCPI_SERIES_ID = "GSCPI"
GSCPI_QUALITY = "verified_monthly_vintage_from_2022"
FORMAL_REGIME_FEATURES = (
    "gscpi_risk_state_pit",
    "us_cpi_12m_log_inflation",
    "us_ip_6m_log_growth",
)
FORMAL_REGIME_SOURCE_IDS = {
    "gscpi_risk_state_pit": "nyfed_gscpi_preserved_vintages",
    "us_cpi_12m_log_inflation": "phillyfed_rtdsm_verified_rows",
    "us_ip_6m_log_growth": "phillyfed_rtdsm_verified_rows",
}
FORMAL_REGIME_MAXIMUM_STALENESS_DAYS = {
    "gscpi_risk_state_pit": 75,
    "us_cpi_12m_log_inflation": 120,
    "us_ip_6m_log_growth": 75,
}


@dataclass(frozen=True)
class StructuredExternalRegimePanel:
    """Outcome-blind values and their row-level point-in-time lineage."""

    values: pd.DataFrame
    lineage: pd.DataFrame


def _decision_index(decision_times: Sequence[object]) -> pd.DatetimeIndex:
    if isinstance(decision_times, (str, bytes)):
        raise TypeError("decision_times must be a sequence")
    values = pd.DatetimeIndex(
        pd.to_datetime(pd.Index(decision_times), utc=True, errors="coerce", format="mixed"),
        name="decision_time",
    )
    if values.empty or values.hasnans or values.has_duplicates:
        raise ValueError("decision_times must be non-empty, valid, and unique")
    return values.sort_values()


def normalize_gscpi_vintages(vintages: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(vintages, pd.DataFrame):
        raise TypeError("vintages must be a pandas DataFrame")
    missing = GSCPI_REQUIRED_COLUMNS - set(vintages.columns)
    if missing:
        raise ValueError(f"GSCPI vintages are missing columns {sorted(missing)}")
    if vintages.empty:
        raise ValueError("GSCPI vintages cannot be empty")
    result = vintages.copy()
    for column in ("observation_time", "available_time"):
        result[column] = pd.to_datetime(
            result[column], utc=True, errors="coerce", format="mixed"
        )
        if result[column].isna().any():
            raise ValueError(f"GSCPI vintages contain invalid {column}")
    for column in ("vintage_label", "series_id", "provider", "quality"):
        result[column] = result[column].astype("string").str.strip()
        if result[column].isna().any() or result[column].eq("").any():
            raise ValueError(f"GSCPI vintages contain blank {column}")
    if not result["series_id"].eq(GSCPI_SERIES_ID).all():
        raise ValueError("GSCPI vintage file contains another series")
    if not result["quality"].eq(GSCPI_QUALITY).all():
        raise ValueError("GSCPI vintage rows are not verified preserved vintages")
    result["value"] = pd.to_numeric(result["value"], errors="coerce")
    if result["value"].isna().any() or not np.isfinite(result["value"]).all():
        raise ValueError("GSCPI vintages contain non-finite values")
    if (result["observation_time"] >= result["available_time"]).any():
        raise ValueError("GSCPI observation_time must precede available_time")
    key = ["observation_time", "available_time", "series_id"]
    if result.duplicated(key).any():
        raise ValueError(f"GSCPI vintages contain duplicate key {key}")
    labels = result.groupby("available_time", sort=False)["vintage_label"].nunique()
    if labels.gt(1).any():
        raise ValueError("one GSCPI available_time maps to multiple vintage labels")
    return result.sort_values(
        ["available_time", "observation_time", "vintage_label"]
    ).reset_index(drop=True)


def build_gscpi_release_features(vintages: pd.DataFrame) -> pd.DataFrame:
    """Build one row per preserved release without crossing vintage boundaries."""
    normalized = normalize_gscpi_vintages(vintages)
    latest = (
        normalized.groupby("available_time", as_index=False, sort=True)
        .tail(1)
        .sort_values("available_time")
        .reset_index(drop=True)
    )
    latest = latest.rename(
        columns={
            "observation_time": "source_observation_time",
            "available_time": "source_available_time",
            "value": "gscpi_level",
            "quality": "source_quality",
            "vintage_label": "source_vintage_label",
        }
    )
    latest["gscpi_change_6_vintages"] = latest["gscpi_level"].diff(6)
    latest["gscpi_risk_state_pit"] = (
        latest["gscpi_level"] + latest["gscpi_change_6_vintages"]
    )
    return latest[
        [
            "source_observation_time",
            "source_available_time",
            "source_vintage_label",
            "source_quality",
            "gscpi_level",
            "gscpi_change_6_vintages",
            "gscpi_risk_state_pit",
        ]
    ]


def extract_gscpi_asof_features(
    vintages: pd.DataFrame,
    decision_times: Sequence[object],
    *,
    maximum_staleness_days: int = 75,
    require_complete: bool = False,
) -> pd.DataFrame:
    if maximum_staleness_days <= 0:
        raise ValueError("maximum_staleness_days must be positive")
    decisions = _decision_index(decision_times)
    releases = build_gscpi_release_features(vintages)
    left = pd.DataFrame({"decision_time": decisions})
    result = pd.merge_asof(
        left,
        releases,
        left_on="decision_time",
        right_on="source_available_time",
        direction="backward",
        allow_exact_matches=True,
    )
    result["source_staleness_days"] = (
        result["decision_time"] - result["source_available_time"]
    ).dt.total_seconds() / 86400.0
    stale = result["source_staleness_days"].gt(maximum_staleness_days)
    insufficient_history = (
        result["source_available_time"].notna()
        & result["gscpi_risk_state_pit"].isna()
    )
    result["feature_status"] = np.select(
        [result["source_available_time"].isna(), stale, insufficient_history],
        ["unavailable", "stale", "insufficient_history"],
        default="ready",
    )
    feature_columns = [
        "gscpi_level",
        "gscpi_change_6_vintages",
        "gscpi_risk_state_pit",
    ]
    result.loc[stale, feature_columns] = np.nan
    result["source_eligibility"] = np.where(
        result["source_available_time"].notna(), "verified_strict_pit", "unavailable"
    )
    if require_complete and result[feature_columns].isna().any(axis=None):
        raise ValueError("GSCPI feature is unavailable or lacks six prior vintages")
    return result


def build_structured_external_regime_panel(
    gscpi_vintages: pd.DataFrame,
    rtdsm_vintages: pd.DataFrame,
    decision_times: Sequence[object],
    *,
    require_complete: bool = False,
) -> StructuredExternalRegimePanel:
    """Build the three formal structured regime features without using outcomes.

    The wide ``values`` frame has one row per decision.  The long ``lineage``
    frame has one row per decision and feature, preserving the exact source
    vintage, observation, availability, staleness, and eligibility used.
    Stale values fail closed to missing while their source lineage remains
    visible for audit.
    """

    decisions = _decision_index(decision_times)
    gscpi = extract_gscpi_asof_features(
        gscpi_vintages,
        decisions,
        maximum_staleness_days=FORMAL_REGIME_MAXIMUM_STALENESS_DAYS[
            "gscpi_risk_state_pit"
        ],
    )
    rtdsm = extract_rtdsm_asof_features(
        rtdsm_vintages,
        decisions,
        eligibility_mode="verified_only",
    )

    rtdsm["source_staleness_days"] = (
        rtdsm["decision_time"] - rtdsm["source_available_time"]
    ).dt.total_seconds() / 86400.0
    rtdsm["maximum_staleness_days"] = rtdsm["feature_name"].map(
        FORMAL_REGIME_MAXIMUM_STALENESS_DAYS
    )
    if rtdsm["maximum_staleness_days"].isna().any():
        raise RuntimeError("RTDSM extractor emitted an unregistered feature")
    rtdsm["feature_status"] = np.where(
        rtdsm["source_staleness_days"].gt(rtdsm["maximum_staleness_days"]),
        "stale",
        "ready",
    )
    rtdsm.loc[rtdsm["feature_status"].eq("stale"), "feature_value"] = np.nan

    values = pd.DataFrame({"decision_time": decisions})
    values["gscpi_risk_state_pit"] = gscpi["gscpi_risk_state_pit"].to_numpy()
    rtdsm_values = rtdsm.pivot(
        index="decision_time", columns="feature_name", values="feature_value"
    ).reindex(decisions)
    for feature_name in FORMAL_REGIME_FEATURES[1:]:
        values[feature_name] = rtdsm_values[feature_name].to_numpy()

    gscpi_lineage = pd.DataFrame(
        {
            "decision_time": gscpi["decision_time"],
            "feature_name": "gscpi_risk_state_pit",
            "feature_value": gscpi["gscpi_risk_state_pit"],
            "source_id": FORMAL_REGIME_SOURCE_IDS["gscpi_risk_state_pit"],
            "series_id": GSCPI_SERIES_ID,
            "source_observation_time": gscpi["source_observation_time"],
            "baseline_observation_time": pd.NaT,
            "source_available_time": gscpi["source_available_time"],
            "source_vintage_label": gscpi["source_vintage_label"],
            "source_quality": gscpi["source_quality"],
            "source_eligibility": gscpi["source_eligibility"],
            "source_staleness_days": gscpi["source_staleness_days"],
            "maximum_staleness_days": FORMAL_REGIME_MAXIMUM_STALENESS_DAYS[
                "gscpi_risk_state_pit"
            ],
            "feature_status": gscpi["feature_status"],
            "unit": "gscpi_level_plus_six_vintage_change",
        }
    )
    rtdsm_lineage = rtdsm.rename(
        columns={"observation_time": "source_observation_time"}
    ).copy()
    rtdsm_lineage["source_id"] = rtdsm_lineage["feature_name"].map(
        FORMAL_REGIME_SOURCE_IDS
    )
    lineage_columns = [
        "decision_time",
        "feature_name",
        "feature_value",
        "source_id",
        "series_id",
        "source_observation_time",
        "baseline_observation_time",
        "source_available_time",
        "source_vintage_label",
        "source_quality",
        "source_eligibility",
        "source_staleness_days",
        "maximum_staleness_days",
        "feature_status",
        "unit",
    ]
    lineage = pd.concat(
        [gscpi_lineage[lineage_columns], rtdsm_lineage[lineage_columns]],
        ignore_index=True,
    ).sort_values(["decision_time", "feature_name"], ignore_index=True)

    available = lineage["source_available_time"].notna()
    if not (
        lineage.loc[available, "source_available_time"]
        <= lineage.loc[available, "decision_time"]
    ).all():
        raise RuntimeError("structured external panel selected future information")
    if not lineage.loc[
        lineage["feature_status"].eq("ready"), "source_eligibility"
    ].eq("verified_strict_pit").all():
        raise RuntimeError("ready structured feature is not verified-strict PIT")
    if require_complete and values[list(FORMAL_REGIME_FEATURES)].isna().any(axis=None):
        raise ValueError("structured external regime panel is incomplete")
    return StructuredExternalRegimePanel(values=values, lineage=lineage)


__all__ = [
    "FORMAL_REGIME_FEATURES",
    "FORMAL_REGIME_MAXIMUM_STALENESS_DAYS",
    "FORMAL_REGIME_SOURCE_IDS",
    "StructuredExternalRegimePanel",
    "build_structured_external_regime_panel",
    "build_gscpi_release_features",
    "extract_gscpi_asof_features",
    "normalize_gscpi_vintages",
]
