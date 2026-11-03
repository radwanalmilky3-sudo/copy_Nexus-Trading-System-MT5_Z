from __future__ import annotations

from datetime import UTC, date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from fx_system.publication_calendar import (
    PublicationCalendar,
    PublicationEvent,
)
from fx_system.structured_event_controls import (
    SPF_RELEASE_DATES_URL,
    build_structured_external_event_panel,
    normalize_spf_release_calendar,
)


def _benchmark_calendar(
    *,
    statuses: dict[tuple[date, str], str] | None = None,
    manifest_verified: bool = True,
) -> PublicationCalendar:
    statuses = statuses or {}
    definitions = {
        "tokyo_fix": (time(9, 55), "Asia/Tokyo"),
        "ecb_fix": (time(14, 15), "Europe/Berlin"),
        "wmr_fix": (time(16, 0), "Europe/London"),
    }
    events: list[PublicationEvent] = []
    for local_date in (date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3)):
        for event_name, (local_time, timezone) in definitions.items():
            status = statuses.get((local_date, event_name), "published")
            scheduled = datetime.combine(
                local_date, local_time, tzinfo=ZoneInfo(timezone)
            ).astimezone(UTC)
            events.append(
                PublicationEvent(
                    event_name=event_name,
                    local_date=local_date,
                    status=status,  # type: ignore[arg-type]
                    local_time=local_time,
                    timezone=timezone,
                    source_url="https://calendar.example.test/official",
                    quality="verified",
                    retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
                    scheduled_time_utc=scheduled,
                )
            )
    return PublicationCalendar(
        events=tuple(events),
        knowledge_cutoff=datetime(2026, 1, 2, tzinfo=UTC),
        formal_experiment=True,
        manifest_verified=manifest_verified,
        calendar_sha256="b" * 64 if manifest_verified else None,
        manifest_path=Path("manifest.json") if manifest_verified else None,
    )


def _spf_calendar() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for year in range(2016, 2026):
        for quarter, month in enumerate((2, 5, 8, 11), start=1):
            deadline = pd.Timestamp(year=year, month=month, day=7)
            release = pd.Timestamp(year=year, month=month, day=10)
            available = (release + pd.Timedelta(24, unit="h")).tz_localize(
                "America/New_York"
            ).tz_convert("UTC")
            rows.append(
                {
                    "survey_period": f"{year}-Q{quarter}",
                    "survey_year": year,
                    "survey_quarter": quarter,
                    "response_deadline_date": deadline.date().isoformat(),
                    "news_release_date": release.date().isoformat(),
                    "available_time": available.isoformat(),
                    "availability_precision": (
                        "official_date_only_conservative_next_day"
                    ),
                    "availability_policy": "after_official_spf_news_release_date",
                    "provider": "Federal Reserve Bank of Philadelphia",
                    "date_evidence_quality": (
                        "verified_official_historical_release_date"
                    ),
                    "values_vintage_quality": (
                        "current_consolidated_archive_with_errata_not_verified_as_published"
                    ),
                    "value_strict_pit_eligible": False,
                    "strict_intraday_eligible": False,
                    "research_use_scope": (
                        "release_event_calendar_or_exploratory_quarterly_us_macro_regime"
                    ),
                    "source_url": SPF_RELEASE_DATES_URL,
                    "raw_sha256": "a" * 64,
                }
            )
    return pd.DataFrame(rows)


def test_benchmark_bitmask_uses_only_events_completed_before_decision() -> None:
    statuses = {
        (date(2020, 1, 1), "ecb_fix"): "not_published",
        (date(2020, 1, 3), "tokyo_fix"): "not_published",
    }
    decisions = pd.date_range("2020-01-01", "2020-01-04", freq="D", tz="UTC")
    panel = build_structured_external_event_panel(
        _benchmark_calendar(statuses=statuses),
        _spf_calendar(),
        decisions,
    )

    assert pd.isna(panel.values.loc[0, "benchmark_publication_state"])
    assert panel.values.loc[1, "benchmark_publication_state"] == 5
    assert panel.values.loc[2, "benchmark_publication_state"] == 7
    assert panel.values.loc[3, "benchmark_publication_state"] == 6
    benchmark = panel.lineage.loc[
        panel.lineage["feature_name"].eq("benchmark_publication_state")
    ]
    ready = benchmark.loc[benchmark["feature_status"].eq("ready")]
    assert (ready["source_available_time"] <= ready["decision_time"]).all()
    assert ready["source_eligibility"].eq("verified_strict_pit").all()


def test_spf_impulse_waits_for_conservative_available_time() -> None:
    decisions = pd.date_range("2016-02-10", "2016-02-13", freq="D", tz="UTC")
    panel = build_structured_external_event_panel(
        _benchmark_calendar(),
        _spf_calendar(),
        decisions,
    )

    assert panel.values["phillyfed_spf_release_state"].tolist() == [0.0, 0.0, 1.0, 0.0]
    release = panel.lineage.loc[
        panel.lineage["feature_name"].eq("phillyfed_spf_release_state")
        & panel.lineage["feature_value"].eq(1)
    ].iloc[0]
    assert release["source_vintage_label"] == "2016-Q1"
    assert release["source_available_time"] <= release["decision_time"]
    assert release["component_state_json"] == (
        '{"release_available":true,"survey_period":"2016-Q1"}'
    )


def test_future_calendar_changes_cannot_rewrite_an_earlier_event_state() -> None:
    decisions = pd.date_range("2020-01-01", "2020-01-02", freq="D", tz="UTC")
    original = build_structured_external_event_panel(
        _benchmark_calendar(), _spf_calendar(), decisions
    )
    changed = build_structured_external_event_panel(
        _benchmark_calendar(
            statuses={(date(2020, 1, 3), "wmr_fix"): "not_published"}
        ),
        _spf_calendar(),
        decisions,
    )
    pd.testing.assert_frame_equal(original.values, changed.values)
    pd.testing.assert_frame_equal(original.lineage, changed.lineage)


def test_event_controls_fail_closed_on_manifest_coverage_and_schedule_errors() -> None:
    decisions = pd.date_range("2020-01-01", "2020-01-02", freq="D", tz="UTC")
    with pytest.raises(ValueError, match="verified source manifest"):
        build_structured_external_event_panel(
            _benchmark_calendar(manifest_verified=False),
            _spf_calendar(),
            decisions,
        )

    incomplete = _benchmark_calendar()
    incomplete = PublicationCalendar(
        events=incomplete.events[:-1],
        knowledge_cutoff=incomplete.knowledge_cutoff,
        formal_experiment=True,
        manifest_verified=True,
        calendar_sha256="b" * 64,
        manifest_path=Path("manifest.json"),
    )
    with pytest.raises(ValueError, match="lacks an exact event trio"):
        build_structured_external_event_panel(incomplete, _spf_calendar(), decisions)

    bad_spf = _spf_calendar()
    bad_spf.loc[0, "available_time"] = "2016-02-10T00:00:00Z"
    with pytest.raises(ValueError, match="conservative next New York day"):
        normalize_spf_release_calendar(bad_spf)


def test_event_controls_require_daily_unique_decision_boundaries() -> None:
    with pytest.raises(ValueError, match="complete daily UTC sequence"):
        build_structured_external_event_panel(
            _benchmark_calendar(),
            _spf_calendar(),
            ["2020-01-01T00:00:00Z", "2020-01-03T00:00:00Z"],
        )
