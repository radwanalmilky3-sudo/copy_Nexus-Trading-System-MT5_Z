"""Strict point-in-time feature extraction from macroeconomic vintages.

The Philadelphia Fed RTDSM files contain complete histories as they appeared
in each release vintage.  Index bases can change between vintages, so growth
rates in this module are always calculated from two levels in the *same*
vintage.  No latest-vintage history is spliced into an earlier decision.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype

CPI_SERIES_ID = "US_CPI_SA_RTDSM"
IP_SERIES_ID = "US_IP_TOTAL_SA_RTDSM"

ASOF_FEATURE_COLUMNS = [
    "decision_time",
    "feature_name",
    "feature_value",
    "series_id",
    "lookback_months",
    "observation_time",
    "baseline_observation_time",
    "source_vintage_label",
    "source_available_time",
    "source_quality",
    "source_eligibility",
    "unit",
]

RTDSMEligibilityMode = Literal["all_pit", "verified_only"]
RTDSM_ELIGIBILITY_COLUMN = "external_eligibility"
RTDSM_STRICT_POLICIES = frozenset(
    {
        "after_rtdsm_mid_quarter_vintage_date",
        "after_verified_g17_release_date",
    }
)
RTDSM_CONSERVATIVE_POLICIES = frozenset(
    {
        "after_unresolved_ip_vintage_month",
        "legacy_unspecified",
    }
)


@dataclass(frozen=True)
class _FeatureSpecification:
    series_id: str
    name: str
    lookback_months: int


@dataclass(frozen=True)
class _VintageLookup:
    """Pre-grouped vintages for logarithmic as-of selection."""

    available_nanoseconds: np.ndarray
    vintages: tuple[pd.DataFrame, ...]


_FEATURES = (
    _FeatureSpecification(CPI_SERIES_ID, "us_cpi_12m_log_inflation", 12),
    _FeatureSpecification(IP_SERIES_ID, "us_ip_6m_log_growth", 6),
)

_REQUIRED_COLUMNS = {
    "observation_time",
    "vintage_label",
    "available_time",
    "series_id",
    "value",
    "quality",
    "pit_eligible",
}


def classify_rtdsm_vintage_eligibility(vintages: pd.DataFrame) -> pd.DataFrame:
    """Classify each RTDSM row without consulting prices or outcomes.

    The downloader deliberately marks unresolved IP months PIT-eligible after a
    conservative next-month delay.  That is safe for exploratory as-of joins,
    but it is not the same evidence grade as a verified G.17 release date.
    """
    if not isinstance(vintages, pd.DataFrame):
        raise TypeError("vintages must be a pandas DataFrame")
    required = {"series_id", "pit_eligible"}
    missing = required - set(vintages.columns)
    if missing:
        raise ValueError(f"RTDSM vintages are missing columns {sorted(missing)}")
    result = vintages.copy()
    if not is_bool_dtype(result["pit_eligible"].dtype):
        raise ValueError("RTDSM pit_eligible must be boolean")
    if result["pit_eligible"].isna().any():
        raise ValueError("RTDSM vintages contain a missing pit_eligible value")
    policies = (
        result["availability_policy"].astype("string").fillna("").str.strip()
        if "availability_policy" in result
        else pd.Series("legacy_unspecified", index=result.index, dtype="string")
    )
    policies = policies.mask(policies.eq(""), "legacy_unspecified")
    known = RTDSM_STRICT_POLICIES | RTDSM_CONSERVATIVE_POLICIES
    unknown = set(policies.unique()) - known
    if unknown:
        raise ValueError(f"RTDSM vintages contain unknown availability policies {sorted(unknown)}")
    eligibility = pd.Series("ineligible", index=result.index, dtype="string")
    strict = result["pit_eligible"] & policies.isin(RTDSM_STRICT_POLICIES)
    conservative = result["pit_eligible"] & policies.isin(RTDSM_CONSERVATIVE_POLICIES)
    eligibility.loc[strict] = "verified_strict_pit"
    eligibility.loc[conservative] = "conservative_pit"
    result["availability_policy"] = policies
    result[RTDSM_ELIGIBILITY_COLUMN] = eligibility
    return result


def rtdsm_eligibility_audit(vintages: pd.DataFrame) -> dict[str, object]:
    classified = classify_rtdsm_vintage_eligibility(vintages)
    counts = classified[RTDSM_ELIGIBILITY_COLUMN].value_counts().sort_index()
    policy_counts = classified["availability_policy"].value_counts().sort_index()
    strict = classified.loc[
        classified[RTDSM_ELIGIBILITY_COLUMN].eq("verified_strict_pit")
    ]
    return {
        "rows": len(classified),
        "counts_by_eligibility": {str(key): int(value) for key, value in counts.items()},
        "counts_by_policy": {str(key): int(value) for key, value in policy_counts.items()},
        "strict_series": sorted(str(value) for value in strict["series_id"].unique()),
        "return_labels_opened": False,
        "factor_outcome_evaluations_added": 0,
        "trading_approval": False,
    }


def _normalize_vintages(
    vintages: pd.DataFrame,
    *,
    eligibility_mode: RTDSMEligibilityMode = "all_pit",
) -> pd.DataFrame:
    if not isinstance(vintages, pd.DataFrame):
        raise TypeError("vintages must be a pandas DataFrame")
    missing = _REQUIRED_COLUMNS - set(vintages.columns)
    if missing:
        raise ValueError(f"RTDSM vintages are missing columns {sorted(missing)}")
    if vintages.empty:
        raise ValueError("RTDSM vintages cannot be empty")

    if eligibility_mode not in {"all_pit", "verified_only"}:
        raise ValueError("eligibility_mode must be all_pit or verified_only")
    result = classify_rtdsm_vintage_eligibility(vintages)
    if eligibility_mode == "verified_only":
        result = result.loc[
            result[RTDSM_ELIGIBILITY_COLUMN].eq("verified_strict_pit")
        ].copy()
        if result.empty:
            raise ValueError("RTDSM contains no verified-strict PIT rows")
    for column in ("observation_time", "available_time"):
        result[column] = pd.to_datetime(
            result[column], utc=True, errors="coerce", format="mixed"
        )
        if result[column].isna().any():
            raise ValueError(f"RTDSM vintages contain a missing or invalid {column}")

    for column in ("vintage_label", "series_id", "quality"):
        result[column] = result[column].astype("string").str.strip()
        if result[column].isna().any() or result[column].eq("").any():
            raise ValueError(f"RTDSM vintages contain a missing or empty {column}")

    if not result["pit_eligible"].all():
        raise ValueError("RTDSM vintages contain a row that is not PIT eligible")

    contains_boolean_value = result["value"].map(
        lambda value: isinstance(value, (bool, np.bool_))
    ).any()
    if is_bool_dtype(result["value"].dtype) or contains_boolean_value:
        raise ValueError("RTDSM values must be numeric index levels, not booleans")
    result["value"] = pd.to_numeric(result["value"], errors="coerce")
    if result["value"].isna().any() or not np.isfinite(result["value"]).all():
        raise ValueError("RTDSM vintages contain a missing or non-finite value")

    duplicate_key = ["observation_time", "vintage_label", "series_id"]
    if result.duplicated(duplicate_key).any():
        raise ValueError(f"RTDSM vintages contain duplicate key {duplicate_key}")
    if (result["observation_time"] >= result["available_time"]).any():
        raise ValueError(
            "RTDSM vintages contain a future observation at or after available_time"
        )

    wanted = {spec.series_id for spec in _FEATURES}
    result = result.loc[result["series_id"].isin(wanted)].copy()
    missing_series = wanted - set(result["series_id"])
    if missing_series:
        raise ValueError(f"RTDSM vintages are missing series {sorted(missing_series)}")
    if (result["value"] <= 0).any():
        raise ValueError("RTDSM CPI and IP index levels must be strictly positive")

    vintage_key = ["series_id", "vintage_label"]
    for metadata in ("available_time", "quality", RTDSM_ELIGIBILITY_COLUMN):
        counts = result.groupby(vintage_key, sort=False)[metadata].nunique(dropna=False)
        if counts.gt(1).any():
            raise ValueError(
                f"RTDSM vintage has inconsistent {metadata}; source vintage is ambiguous"
            )

    labels_per_availability = result.groupby(
        ["series_id", "available_time"], sort=False
    )["vintage_label"].nunique()
    if labels_per_availability.gt(1).any():
        raise ValueError(
            "RTDSM series has multiple source vintages at one available_time"
        )

    # The source is monthly.  Two timestamps in one calendar month would make
    # an exact lag month ambiguous even if their day-level timestamps differ.
    result["_observation_month"] = (
        result["observation_time"].dt.tz_localize(None).dt.to_period("M")
    )
    month_key = ["series_id", "vintage_label", "_observation_month"]
    if result.duplicated(month_key).any():
        raise ValueError("RTDSM vintage contains duplicate monthly observation keys")

    return result.sort_values(
        ["series_id", "available_time", "vintage_label", "observation_time"]
    ).reset_index(drop=True)


def _normalize_decision_times(
    decision_times: Sequence[object] | pd.Series | pd.Index,
) -> pd.DatetimeIndex:
    if isinstance(decision_times, (str, bytes)):
        raise TypeError("decision_times must be a sequence of timestamps")
    try:
        raw = pd.Index(decision_times)
    except (TypeError, ValueError) as error:
        raise TypeError("decision_times must be a sequence of timestamps") from error
    if raw.empty:
        raise ValueError("decision_times cannot be empty")
    normalized = pd.DatetimeIndex(
        pd.to_datetime(raw, utc=True, errors="coerce", format="mixed"),
        name="decision_time",
    )
    if normalized.hasnans:
        raise ValueError("decision_times contain a missing or invalid timestamp")
    if normalized.has_duplicates:
        raise ValueError("decision_times contain duplicate keys")
    return normalized.sort_values()


def _within_vintage_feature(
    vintage: pd.DataFrame,
    *,
    specification: _FeatureSpecification,
    decision_time: pd.Timestamp,
) -> dict[str, object]:
    latest = vintage.iloc[-1]
    baseline_month = latest["_observation_month"] - specification.lookback_months
    baseline = vintage.loc[vintage["_observation_month"] == baseline_month]
    if len(baseline) != 1:
        label = str(latest["vintage_label"])
        raise ValueError(
            f"{specification.name} lacks its exact {specification.lookback_months}-month "
            f"baseline in source vintage {label!r} at decision {decision_time.isoformat()}"
        )
    baseline_row = baseline.iloc[0]
    feature_value = 100.0 * (
        np.log(float(latest["value"])) - np.log(float(baseline_row["value"]))
    )
    if not np.isfinite(feature_value):
        raise ValueError(f"{specification.name} produced a non-finite feature value")

    return {
        "decision_time": decision_time,
        "feature_name": specification.name,
        "feature_value": feature_value,
        "series_id": specification.series_id,
        "lookback_months": specification.lookback_months,
        "observation_time": latest["observation_time"],
        "baseline_observation_time": baseline_row["observation_time"],
        "source_vintage_label": str(latest["vintage_label"]),
        "source_available_time": latest["available_time"],
        "source_quality": str(latest["quality"]),
        "source_eligibility": str(latest[RTDSM_ELIGIBILITY_COLUMN]),
        "unit": "percent_log_change",
    }


def _build_vintage_lookups(
    vintages: pd.DataFrame,
) -> dict[str, _VintageLookup]:
    """Group each series once so decisions never rescan the long source table."""

    lookups: dict[str, _VintageLookup] = {}
    for specification in _FEATURES:
        series = vintages.loc[vintages["series_id"] == specification.series_id]
        available_nanoseconds: list[int] = []
        groups: list[pd.DataFrame] = []
        for available_time, vintage in series.groupby("available_time", sort=True):
            # _normalize_vintages has already proved that one availability maps
            # to exactly one source label.  Keeping the check here makes this
            # private boundary fail closed if it is ever reused independently.
            if vintage["vintage_label"].nunique() != 1:
                raise ValueError(
                    f"{specification.series_id} has an ambiguous source vintage at "
                    f"{available_time}"
                )
            available_nanoseconds.append(pd.Timestamp(available_time).value)
            groups.append(vintage.sort_values("observation_time").reset_index(drop=True))
        if not groups:
            raise ValueError(f"RTDSM vintages are missing series {specification.series_id!r}")
        lookups[specification.series_id] = _VintageLookup(
            available_nanoseconds=np.asarray(available_nanoseconds, dtype=np.int64),
            vintages=tuple(groups),
        )
    return lookups


def extract_rtdsm_asof_features(
    vintages: pd.DataFrame,
    decision_times: Sequence[object] | pd.Series | pd.Index,
    *,
    eligibility_mode: RTDSMEligibilityMode = "all_pit",
) -> pd.DataFrame:
    """Extract strict as-of CPI inflation and IP growth features.

    For each decision and series, the selected source is the single newest
    vintage whose ``available_time`` is no later than that decision.  CPI is a
    12-month log change and IP is a non-annualized 6-month log change; both are
    expressed in percentage points (``100 * log(level_t / level_t-k)``).

    The function intentionally fails the complete request rather than emitting
    a partial or forward-filled panel when a decision has no available vintage
    or when the selected vintage lacks its exact baseline month.
    """

    normalized = _normalize_vintages(vintages, eligibility_mode=eligibility_mode)
    decisions = _normalize_decision_times(decision_times)
    lookups = _build_vintage_lookups(normalized)
    output: list[dict[str, object]] = []
    feature_cache: dict[tuple[str, int], dict[str, object]] = {}

    for decision_time in decisions:
        for specification in _FEATURES:
            lookup = lookups[specification.series_id]
            position = int(
                np.searchsorted(
                    lookup.available_nanoseconds,
                    decision_time.value,
                    side="right",
                )
            ) - 1
            if position < 0:
                raise ValueError(
                    f"no {specification.series_id} vintage is available at decision "
                    f"{decision_time.isoformat()}"
                )
            cache_key = (specification.series_id, position)
            template = feature_cache.get(cache_key)
            if template is None:
                computed = _within_vintage_feature(
                    lookup.vintages[position],
                    specification=specification,
                    decision_time=decision_time,
                )
                template = {
                    key: value for key, value in computed.items() if key != "decision_time"
                }
                feature_cache[cache_key] = template
            output.append({"decision_time": decision_time, **template})

    result = pd.DataFrame(output, columns=ASOF_FEATURE_COLUMNS)
    return result.sort_values(["decision_time", "feature_name"]).reset_index(drop=True)
