from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from fx_system.intraday_calendar import (
    EVENT_WINDOW_HALF_WIDTH,
    daily_event_windows,
    event_window,
    fx_session_boundary,
    fx_session_bounds,
    session_window,
    tzdb_info,
)


def test_frozen_event_local_times_and_five_minute_windows() -> None:
    windows = daily_event_windows(date(2025, 1, 15))

    assert windows["tokyo_fix"].center_utc == datetime(2025, 1, 15, 0, 55, tzinfo=UTC)
    assert windows["ecb_fix"].center_utc == datetime(2025, 1, 15, 13, 15, tzinfo=UTC)
    assert windows["wmr_fix"].center_utc == datetime(2025, 1, 15, 16, 0, tzinfo=UTC)
    for window in windows.values():
        assert window.start_utc == window.center_utc - EVENT_WINDOW_HALF_WIDTH
        assert window.end_utc == window.center_utc + EVENT_WINDOW_HALF_WIDTH
        assert window.duration == timedelta(minutes=5)


def test_event_construction_uses_iana_dst_for_each_local_date() -> None:
    winter_ecb = event_window("ecb_fix", "2025-01-15")
    summer_ecb = event_window("ecb_fix", "2025-07-15")
    winter_wmr = event_window("wmr_fix", "2025-01-15")
    summer_wmr = event_window("wmr_fix", "2025-07-15")
    winter_tokyo = event_window("tokyo_fix", "2025-01-15")
    summer_tokyo = event_window("tokyo_fix", "2025-07-15")

    assert winter_ecb.center_utc.hour == 13
    assert summer_ecb.center_utc.hour == 12
    assert winter_wmr.center_utc.hour == 16
    assert summer_wmr.center_utc.hour == 15
    assert winter_tokyo.center_utc.hour == summer_tokyo.center_utc.hour == 0


def test_frozen_session_bounds_include_us_europe_dst_mismatch_weeks() -> None:
    # On 21 March 2025 New York has switched to daylight time, while London has not.
    london_mismatch = session_window("london", "2025-03-21")
    new_york_mismatch = session_window("new_york", "2025-03-21")
    # By 4 April both regions are on daylight time.
    london_summer = session_window("london", "2025-04-04")
    new_york_summer = session_window("new_york", "2025-04-04")

    assert london_mismatch.start_utc == datetime(2025, 3, 21, 7, tzinfo=UTC)
    assert new_york_mismatch.start_utc == datetime(2025, 3, 21, 12, tzinfo=UTC)
    assert london_summer.start_utc == datetime(2025, 4, 4, 6, tzinfo=UTC)
    assert new_york_summer.start_utc == datetime(2025, 4, 4, 12, tzinfo=UTC)


def test_frozen_session_lengths_and_alias_windows() -> None:
    tokyo = session_window("tokyo", "2025-06-02")
    asia = session_window("asia_formation", "2025-06-02")
    london = session_window("london", "2025-06-02")
    response = session_window("london_response", "2025-06-02")
    new_york = session_window("new_york", "2025-06-02")

    assert (tokyo.start_utc, tokyo.end_utc) == (asia.start_utc, asia.end_utc)
    assert tokyo.duration == timedelta(hours=7)
    assert london.duration == timedelta(hours=8)
    assert response.duration == timedelta(hours=3)
    assert new_york.duration == timedelta(hours=8)
    assert response.start_utc == london.start_utc


def test_fx_session_boundaries_are_localized_independently_across_us_dst() -> None:
    before = fx_session_boundary("2025-03-08")
    after = fx_session_boundary("2025-03-09")
    bounds = fx_session_bounds("2025-03-08")

    assert before == datetime(2025, 3, 8, 22, tzinfo=UTC)
    assert after == datetime(2025, 3, 9, 21, tzinfo=UTC)
    assert bounds.start_utc == before
    assert bounds.end_utc == after
    assert bounds.duration == timedelta(hours=23)


def test_utc_results_round_trip_to_frozen_local_clock_times() -> None:
    wmr = event_window("wmr_fix", "2025-10-24")
    new_york = session_window("new_york", "2025-10-24")

    assert wmr.center_utc.astimezone(ZoneInfo("Europe/London")).time().replace(
        tzinfo=None
    ) == datetime.strptime("16:00", "%H:%M").time()
    assert new_york.start_utc.astimezone(ZoneInfo("America/New_York")).time().replace(
        tzinfo=None
    ) == datetime.strptime("08:00", "%H:%M").time()


def test_tzdb_reproducibility_identifier_is_exposed_on_outputs() -> None:
    info = tzdb_info()
    window = event_window("wmr_fix", "2025-01-15")

    assert info.source
    assert info.identifier
    assert window.tzdb == info


@pytest.mark.parametrize(
    ("builder", "bad_name"),
    [(event_window, "london_fix"), (session_window, "newyork")],
)
def test_unknown_calendar_definition_is_rejected(builder, bad_name) -> None:
    with pytest.raises(ValueError, match="unknown"):
        builder(bad_name, "2025-01-15")


def test_calendar_does_not_guess_holidays_or_publication_dates() -> None:
    # Civil templates are intentionally constructed even on a weekend.
    saturday = event_window("wmr_fix", "2025-01-18")

    assert saturday.local_date.weekday() == 5
