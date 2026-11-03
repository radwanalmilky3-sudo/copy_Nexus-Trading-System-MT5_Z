"""Strict, outcome-blind event controls for the structured external layer."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype

from fx_system.publication_calendar import PublicationCalendar

EVENT_CONTROL_FEATURES: Final = (
    "benchmark_publication_state",
    "phillyfed_spf_release_state",
)
EVENT_CONTROL_SOURCE_IDS: Final = {
    "benchmark_publication_state": "benchmark_publication_calendar",
    "phillyfed_spf_release_state": "phillyfed_spf_release_calendar",
}
BENCHMARK_EVENT_BITS: Final = {
    "tokyo_fix": 1,
    "ecb_fix": 2,
    "wmr_fix": 4,
}
EVENT_WINDOW = pd.Timedelta(24, unit="h")
EVENT_MAXIMUM_STALENESS_DAYS = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SPF_RELEASE_DATES_URL = (
    "https://www.philadelphiafed.org/-/media/FRBP/Assets/Surveys-And-Data/"
    "survey-of-professional-forecasters/spf-release-dates.txt"
)
_SPF_COLUMNS = frozenset(
    {
        "survey_period",
        "survey_year",
        "survey_quarter",
        "response_deadline_date",
        "news_release_date",
        "available_time",
        "availability_precision",
        "availability_policy",
        "provider",
        "date_evidence_quality",
        "values_vintage_quality",
        "value_strict_pit_eligible",
        "strict_intraday_eligible",
        "research_use_scope",
        "source_url",
        "raw_sha256",
    }
)


@dataclass(frozen=True)
class StructuredExternalEventPanel:
    """Daily event-control values, factor lineage, and component lineage."""

    values: pd.DataFrame
    lineage: pd.DataFrame
    components: pd.DataFrame


def _daily_decision_index(decision_times: Sequence[object]) -> pd.DatetimeIndex:
    if isinstance(decision_times, (str, bytes)):
        raise TypeError("decision_times must be a sequence")
    raw = pd.Index(decision_times)
    for value in raw:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            raise ValueError("event-control decision_times must be timezone-aware")
    values = pd.DatetimeIndex(
        pd.to_datetime(pd.Index(decision_times), utc=True, errors="coerce", format="mixed"),
        name="decision_time",
    )
    if values.empty or values.hasnans or values.has_duplicates:
        raise ValueError("decision_times must be non-empty, valid, and unique")
    values = values.sort_values()
    if not (
        (values.hour == 0)
        & (values.minute == 0)
        & (values.second == 0)
        & (values.microsecond == 0)
    ).all():
        raise ValueError("event-control decision_times must be anchored at 00:00 UTC")
    if len(values) > 1 and not values.to_series().diff().iloc[1:].eq(EVENT_WINDOW).all():
        raise ValueError("event-control decision_times must be a complete daily UTC sequence")
    return values


def normalize_spf_release_calendar(calendar: pd.DataFrame) -> pd.DataFrame:
    """Validate the complete official 2016--2025 date-only SPF release calendar."""

    if not isinstance(calendar, pd.DataFrame):
        raise TypeError("SPF release calendar must be a pandas DataFrame")
    missing = _SPF_COLUMNS - set(calendar.columns)
    extra = set(calendar.columns) - _SPF_COLUMNS
    if missing or extra:
        raise ValueError(
            f"SPF release calendar columns mismatch; missing={sorted(missing)}, "
            f"extra={sorted(extra)}"
        )
    if len(calendar) != 40:
        raise ValueError("SPF release calendar must contain exactly 40 quarterly rows")
    result = calendar.copy()
    result["available_time"] = pd.to_datetime(
        result["available_time"], utc=True, errors="coerce", format="mixed"
    )
    if result["available_time"].isna().any():
        raise ValueError("SPF release calendar contains invalid available_time")
    for column in ("response_deadline_date", "news_release_date"):
        date_only = result[column].astype(str).map(
            lambda value: bool(_DATE_ONLY.fullmatch(value))
        )
        if not date_only.all():
            raise ValueError(f"SPF {column} must use YYYY-MM-DD date-only values")
        parsed = pd.to_datetime(result[column], errors="coerce", format="mixed")
        if parsed.isna().any() or getattr(parsed.dt, "tz", None) is not None:
            raise ValueError(f"SPF release calendar contains invalid {column}")
        result[column] = parsed.dt.normalize()

    result["survey_year"] = pd.to_numeric(result["survey_year"], errors="coerce")
    result["survey_quarter"] = pd.to_numeric(result["survey_quarter"], errors="coerce")
    numeric_year = pd.to_numeric(result["survey_year"], errors="coerce")
    numeric_quarter = pd.to_numeric(result["survey_quarter"], errors="coerce")
    if (
        numeric_year.isna().any()
        or numeric_quarter.isna().any()
        or not numeric_year.eq(numeric_year.round()).all()
        or not numeric_quarter.eq(numeric_quarter.round()).all()
    ):
        raise ValueError("SPF survey year and quarter must be integers")
    result["survey_year"] = numeric_year
    result["survey_quarter"] = numeric_quarter
    expected = {
        (year, quarter)
        for year in range(2016, 2026)
        for quarter in range(1, 5)
    }
    actual = set(
        zip(
            result["survey_year"].astype(int),
            result["survey_quarter"].astype(int),
            strict=True,
        )
    )
    if actual != expected:
        raise ValueError("SPF release calendar does not cover each 2016--2025 quarter once")
    expected_period = result.apply(
        lambda row: f"{int(row['survey_year']):04d}-Q{int(row['survey_quarter'])}",
        axis=1,
    )
    if not result["survey_period"].astype(str).eq(expected_period).all():
        raise ValueError("SPF survey_period disagrees with year and quarter")
    if result.duplicated("survey_period").any() or result["available_time"].duplicated().any():
        raise ValueError("SPF release calendar contains duplicate periods or availability")
    if (result["response_deadline_date"] > result["news_release_date"]).any():
        raise ValueError("SPF response deadline follows its news release")

    release_next_day = result["news_release_date"] + pd.Timedelta(24, unit="h")
    expected_available = pd.DatetimeIndex(release_next_day).tz_localize(
        "America/New_York"
    ).tz_convert("UTC")
    if not result["available_time"].reset_index(drop=True).eq(
        pd.Series(expected_available)
    ).all():
        raise ValueError("SPF available_time is not the conservative next New York day")

    exact_values = {
        "availability_precision": "official_date_only_conservative_next_day",
        "availability_policy": "after_official_spf_news_release_date",
        "provider": "Federal Reserve Bank of Philadelphia",
        "date_evidence_quality": "verified_official_historical_release_date",
        "values_vintage_quality": (
            "current_consolidated_archive_with_errata_not_verified_as_published"
        ),
        "research_use_scope": (
            "release_event_calendar_or_exploratory_quarterly_us_macro_regime"
        ),
    }
    for column, expected_value in exact_values.items():
        if not result[column].astype(str).eq(expected_value).all():
            raise ValueError(f"SPF release calendar has unexpected {column}")
    for column in ("value_strict_pit_eligible", "strict_intraday_eligible"):
        if not is_bool_dtype(result[column].dtype) or result[column].any():
            raise ValueError(f"SPF {column} must be boolean false")
    if not result["raw_sha256"].astype(str).map(lambda value: bool(_SHA256.fullmatch(value))).all():
        raise ValueError("SPF release calendar has invalid raw_sha256")
    if not result["source_url"].astype(str).eq(SPF_RELEASE_DATES_URL).all():
        raise ValueError("SPF release calendar source_url is not the frozen official URL")
    return result.sort_values("available_time").reset_index(drop=True)


def _benchmark_event_frame(
    calendar: PublicationCalendar,
    *,
    require_verified_manifest: bool,
) -> pd.DataFrame:
    if not isinstance(calendar, PublicationCalendar):
        raise TypeError("benchmark calendar must be a PublicationCalendar")
    if require_verified_manifest and (
        not calendar.formal_experiment
        or not calendar.manifest_verified
        or calendar.manifest_path is None
        or calendar.calendar_sha256 is None
        or _SHA256.fullmatch(calendar.calendar_sha256) is None
    ):
        raise ValueError(
            "benchmark event control requires a formal experiment and verified source manifest"
        )
    if not calendar.events:
        raise ValueError("benchmark event calendar cannot be empty")
    rows = []
    for event in calendar.events:
        if event.event_name not in BENCHMARK_EVENT_BITS:
            raise ValueError(f"benchmark calendar contains unknown event {event.event_name!r}")
        if event.quality != "verified":
            raise ValueError("benchmark event control requires verified rows")
        if (
            event.scheduled_time_utc.tzinfo is None
            or event.scheduled_time_utc.utcoffset() is None
            or event.retrieved_at.tzinfo is None
            or event.retrieved_at.utcoffset() is None
            or event.retrieved_at > calendar.knowledge_cutoff
        ):
            raise ValueError("benchmark event calendar contains invalid time evidence")
        rows.append(
            {
                "component_id": event.event_name,
                "local_date": event.local_date,
                "event_status": event.status,
                "scheduled_time": pd.Timestamp(event.scheduled_time_utc),
                "component_value": int(event.was_published),
                "component_bit": BENCHMARK_EVENT_BITS[event.event_name],
                "source_url": event.source_url,
                "source_quality": event.quality,
                "source_retrieved_at": pd.Timestamp(event.retrieved_at),
            }
        )
    result = pd.DataFrame(rows).sort_values(
        ["scheduled_time", "component_id"], ignore_index=True
    )
    expected_names = set(BENCHMARK_EVENT_BITS)
    for local_date, group in result.groupby("local_date", sort=True):
        if len(group) != 3 or set(group["component_id"]) != expected_names:
            raise ValueError(f"benchmark calendar date {local_date} lacks an exact event trio")
    dates = pd.DatetimeIndex(sorted(result["local_date"].unique()))
    expected_dates = pd.date_range(dates.min(), dates.max(), freq="D")
    if not dates.equals(expected_dates):
        raise ValueError("benchmark calendar has a missing civil date")
    if result.duplicated(["component_id", "local_date"]).any():
        raise ValueError("benchmark calendar contains duplicate event/date keys")
    return result


def _activation_positions(
    event_times: pd.Series,
    decisions: pd.DatetimeIndex,
) -> np.ndarray:
    decision_ns = decisions.asi8
    event_ns = pd.DatetimeIndex(event_times).asi8
    positions = np.searchsorted(decision_ns, event_ns, side="left")
    valid = positions < len(decisions)
    lags = np.full(len(positions), np.iinfo(np.int64).max, dtype=np.int64)
    lags[valid] = decision_ns[positions[valid]] - event_ns[valid]
    valid &= lags >= 0
    valid &= lags <= int(EVENT_WINDOW.value)
    return np.where(valid, positions, -1)


def build_structured_external_event_panel(
    benchmark_calendar: PublicationCalendar,
    spf_release_calendar: pd.DataFrame,
    decision_times: Sequence[object],
    *,
    require_verified_manifest: bool = True,
) -> StructuredExternalEventPanel:
    """Build two non-directional event controls over trailing 24-hour windows."""

    decisions = _daily_decision_index(decision_times)
    benchmark = _benchmark_event_frame(
        benchmark_calendar,
        require_verified_manifest=require_verified_manifest,
    )
    spf = normalize_spf_release_calendar(spf_release_calendar)
    benchmark["_decision_position"] = _activation_positions(
        benchmark["scheduled_time"], decisions
    )
    spf["_decision_position"] = _activation_positions(spf["available_time"], decisions)

    values = pd.DataFrame({"decision_time": decisions})
    values["benchmark_publication_state"] = np.nan
    values["phillyfed_spf_release_state"] = 0.0
    benchmark_lineage: list[dict[str, object]] = []
    component_rows: list[dict[str, object]] = []
    expected_components = set(BENCHMARK_EVENT_BITS)

    grouped_benchmark = {
        int(position): group
        for position, group in benchmark.loc[benchmark["_decision_position"].ge(0)].groupby(
            "_decision_position", sort=True
        )
    }
    for position, decision in enumerate(decisions):
        group = grouped_benchmark.get(position)
        ready = (
            group is not None
            and len(group) == 3
            and set(group["component_id"]) == expected_components
        )
        window_start = decision - EVENT_WINDOW
        if ready:
            assert group is not None
            state = int((group["component_value"] * group["component_bit"]).sum())
            values.loc[position, "benchmark_publication_state"] = state
            latest = pd.Timestamp(group["scheduled_time"].max())
            earliest = pd.Timestamp(group["scheduled_time"].min())
            statuses = {
                str(row["component_id"]): str(row["event_status"])
                for _, row in group.sort_values("component_id").iterrows()
            }
            dates = sorted({str(value) for value in group["local_date"]})
            eligibility = "verified_strict_pit"
            feature_status = "ready"
            quality = "verified_calendar_manifest"
            label = ",".join(dates)
            staleness = (decision - latest).total_seconds() / 86400.0
            for _, row in group.sort_values("component_id").iterrows():
                component_rows.append(
                    {
                        "decision_time": decision,
                        "feature_name": "benchmark_publication_state",
                        "component_id": row["component_id"],
                        "component_value": int(row["component_value"]),
                        "event_status": row["event_status"],
                        "event_observation_time": row["scheduled_time"],
                        "event_observation_precision": "verified_event_time",
                        "source_available_time": row["scheduled_time"],
                        "source_availability_semantics": "event_occurrence_boundary",
                        "source_vintage_label": str(row["local_date"]),
                        "source_quality": row["source_quality"],
                        "source_eligibility": "verified_strict_pit",
                        "source_url": row["source_url"],
                        "source_retrieved_at": row["source_retrieved_at"],
                    }
                )
        else:
            state = np.nan
            earliest = pd.NaT
            latest = pd.NaT
            statuses = {}
            eligibility = "unavailable"
            feature_status = "unavailable"
            quality = pd.NA
            label = pd.NA
            staleness = np.nan
        benchmark_lineage.append(
            {
                "decision_time": decision,
                "feature_name": "benchmark_publication_state",
                "feature_value": state,
                "source_id": EVENT_CONTROL_SOURCE_IDS["benchmark_publication_state"],
                "series_id": "TOKYO_ECB_WMR_PUBLICATION_CALENDAR",
                "source_observation_time": earliest,
                "source_observation_precision": "verified_event_time" if ready else pd.NA,
                "baseline_observation_time": pd.NaT,
                "source_available_time": latest,
                "source_availability_semantics": (
                    "event_occurrence_boundary" if ready else pd.NA
                ),
                "source_vintage_label": label,
                "source_quality": quality,
                "source_eligibility": eligibility,
                "source_staleness_days": staleness,
                "maximum_staleness_days": EVENT_MAXIMUM_STALENESS_DAYS,
                "feature_status": feature_status,
                "unit": "publication_bitmask_tokyo_1_ecb_2_wmr_4",
                "event_window_start": window_start,
                "event_window_end": decision,
                "component_state_json": json.dumps(
                    statuses, sort_keys=True, separators=(",", ":")
                ),
            }
        )

    active_spf = spf.loc[spf["_decision_position"].ge(0)].copy()
    if active_spf["_decision_position"].duplicated().any():
        raise ValueError("multiple SPF releases activate in one daily decision window")
    spf_by_position = {
        int(row["_decision_position"]): row for _, row in active_spf.iterrows()
    }
    spf_lineage: list[dict[str, object]] = []
    coverage_start = pd.Timestamp("2016-01-01T00:00:00Z")
    coverage_end = pd.Timestamp("2026-01-01T00:00:00Z")
    for position, decision in enumerate(decisions):
        in_coverage = coverage_start < decision < coverage_end
        event = spf_by_position.get(position)
        state = float(event is not None) if in_coverage else np.nan
        values.loc[position, "phillyfed_spf_release_state"] = state
        if event is not None:
            available_time = pd.Timestamp(event["available_time"])
            observation_time = pd.Timestamp(event["news_release_date"]).tz_localize(
                "America/New_York"
            )
            label = str(event["survey_period"])
            staleness = (decision - available_time).total_seconds() / 86400.0
            component_state = {"release_available": True, "survey_period": label}
            component_rows.append(
                {
                    "decision_time": decision,
                    "feature_name": "phillyfed_spf_release_state",
                    "component_id": label,
                    "component_value": 1,
                    "event_status": "available_after_verified_release_date",
                    "event_observation_time": observation_time,
                    "event_observation_precision": "official_date_only",
                    "source_available_time": available_time,
                    "source_availability_semantics": "conservative_release_available_time",
                    "source_vintage_label": label,
                    "source_quality": event["date_evidence_quality"],
                    "source_eligibility": "verified_strict_pit",
                    "source_url": event["source_url"],
                    "source_retrieved_at": pd.NaT,
                }
            )
        else:
            available_time = pd.NaT
            observation_time = pd.NaT
            label = "no_release_in_window" if in_coverage else pd.NA
            staleness = np.nan
            component_state = {"release_available": False}
        spf_lineage.append(
            {
                "decision_time": decision,
                "feature_name": "phillyfed_spf_release_state",
                "feature_value": state,
                "source_id": EVENT_CONTROL_SOURCE_IDS["phillyfed_spf_release_state"],
                "series_id": "PHILLYFED_SPF_RELEASE_CALENDAR",
                "source_observation_time": observation_time,
                "source_observation_precision": (
                    "official_date_only" if event is not None else pd.NA
                ),
                "baseline_observation_time": pd.NaT,
                "source_available_time": available_time,
                "source_availability_semantics": (
                    "conservative_release_available_time" if event is not None else pd.NA
                ),
                "source_vintage_label": label,
                "source_quality": (
                    "verified_official_historical_release_date"
                    if in_coverage
                    else pd.NA
                ),
                "source_eligibility": (
                    "verified_strict_pit" if in_coverage else "unavailable"
                ),
                "source_staleness_days": staleness,
                "maximum_staleness_days": EVENT_MAXIMUM_STALENESS_DAYS,
                "feature_status": "ready" if in_coverage else "unavailable",
                "unit": "binary_release_availability_impulse",
                "event_window_start": decision - EVENT_WINDOW,
                "event_window_end": decision,
                "component_state_json": json.dumps(
                    component_state, sort_keys=True, separators=(",", ":")
                ),
            }
        )

    lineage = pd.DataFrame([*benchmark_lineage, *spf_lineage]).sort_values(
        ["decision_time", "feature_name"], ignore_index=True
    )
    component_columns = [
        "decision_time",
        "feature_name",
        "component_id",
        "component_value",
        "event_status",
        "event_observation_time",
        "event_observation_precision",
        "source_available_time",
        "source_availability_semantics",
        "source_vintage_label",
        "source_quality",
        "source_eligibility",
        "source_url",
        "source_retrieved_at",
    ]
    components = pd.DataFrame(component_rows, columns=component_columns).sort_values(
        ["decision_time", "feature_name", "component_id"], ignore_index=True
    )
    available = lineage["source_available_time"].notna()
    if not (
        lineage.loc[available, "source_available_time"]
        <= lineage.loc[available, "decision_time"]
    ).all():
        raise RuntimeError("event-control panel selected future information")
    if not lineage.loc[
        lineage["feature_status"].eq("ready"), "source_eligibility"
    ].eq("verified_strict_pit").all():
        raise RuntimeError("ready event control is not verified-strict PIT")
    return StructuredExternalEventPanel(
        values=values,
        lineage=lineage,
        components=components,
    )


__all__ = [
    "BENCHMARK_EVENT_BITS",
    "EVENT_CONTROL_FEATURES",
    "EVENT_CONTROL_SOURCE_IDS",
    "StructuredExternalEventPanel",
    "build_structured_external_event_panel",
    "normalize_spf_release_calendar",
]
