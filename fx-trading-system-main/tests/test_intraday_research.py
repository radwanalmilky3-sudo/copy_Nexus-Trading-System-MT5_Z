from __future__ import annotations

from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from fx_system.intraday_calendar import event_window, fx_session_boundary, session_window
from fx_system.intraday_research import (
    FIX_W_G9_LEGS,
    LOCAL_PAPER_UNITS,
    _local_paper_boundary_in_working_week,
    build_asia_london_experiments,
    build_fix_w_composite_experiments,
    build_fix_w_leg_experiments,
    build_fix_window_experiments,
    build_local_paper_panel,
    build_local_portfolio_extension,
    build_wmr_month_end_experiments,
)
from fx_system.publication_calendar import (
    PublicationCalendar,
    PublicationCalendarError,
    PublicationEvent,
)


def _quotes(records: list[tuple[datetime, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "bid": [record[1] for record in records],
            "ask": [record[2] for record in records],
        },
        index=pd.DatetimeIndex([record[0] for record in records], name="timestamp"),
    ).sort_index()


def _fix_quotes(
    local_dates: list[date],
    spreads: list[float],
    *,
    event: str = "wmr_fix",
) -> pd.DataFrame:
    records: list[tuple[datetime, float, float]] = []
    for local_date, spread in zip(local_dates, spreads, strict=True):
        window = event_window(event, local_date)
        records.extend(
            [
                (
                    window.start_utc + timedelta(seconds=1),
                    1.0 - spread / 2,
                    1.0 + spread / 2,
                ),
                (window.end_utc, 1.0001 - spread / 2, 1.0001 + spread / 2),
            ]
        )
    return _quotes(records)


def _formal_event_calendar(
    local_date: date,
    *,
    statuses: dict[str, str] | None = None,
    wmr_hour: int = 16,
    formal_experiment: bool = True,
) -> PublicationCalendar:
    statuses = statuses or {}
    events: list[PublicationEvent] = []
    for name in ("tokyo_fix", "ecb_fix", "wmr_fix"):
        window = event_window(name, local_date)
        scheduled = window.center_utc
        status = statuses.get(
            name, "early_time" if name == "wmr_fix" and wmr_hour != 16 else "published"
        )
        if name == "wmr_fix" and wmr_hour != 16 and status != "not_published":
            scheduled = datetime(
                local_date.year,
                local_date.month,
                local_date.day,
                wmr_hour,
                tzinfo=ZoneInfo("Europe/London"),
            ).astimezone(UTC)
        local_clock = scheduled.astimezone(ZoneInfo(window.timezone)).time().replace(tzinfo=None)
        events.append(
            PublicationEvent(
                event_name=name,
                local_date=local_date,
                status=status,  # type: ignore[arg-type]
                local_time=local_clock,
                timezone=window.timezone,
                source_url="https://calendar.example.test/official",
                quality="verified",
                retrieved_at=datetime(2026, 1, 2, tzinfo=UTC),
                scheduled_time_utc=scheduled,
            )
        )
    return PublicationCalendar(
        tuple(events),
        knowledge_cutoff=datetime(2026, 1, 3, tzinfo=UTC),
        formal_experiment=formal_experiment,
        manifest_verified=formal_experiment,
    )


def _combined_formal_event_calendar(local_dates: list[date]) -> PublicationCalendar:
    events = tuple(
        event
        for local_date in local_dates
        for event in _formal_event_calendar(local_date).events
    )
    return PublicationCalendar(
        events,
        knowledge_cutoff=datetime(2026, 1, 3, tzinfo=UTC),
        formal_experiment=True,
        manifest_verified=True,
    )


def _complete_wmr_calendar(
    year: int,
    month: int,
    *,
    published_days: set[int],
) -> PublicationCalendar:
    events: list[PublicationEvent] = []
    for day in range(1, monthrange(year, month)[1] + 1):
        local_date = date(year, month, day)
        window = event_window("wmr_fix", local_date)
        events.append(
            PublicationEvent(
                event_name="wmr_fix",
                local_date=local_date,
                status="published" if day in published_days else "not_published",
                local_time=window.center_utc.astimezone(
                    ZoneInfo(window.timezone)
                ).time().replace(tzinfo=None),
                timezone=window.timezone,
                source_url="https://calendar.example.test/official",
                quality="verified",
                retrieved_at=datetime(2026, 1, 2, tzinfo=UTC),
                scheduled_time_utc=window.center_utc,
            )
        )
    return PublicationCalendar(
        tuple(events),
        knowledge_cutoff=datetime(2026, 1, 3, tzinfo=UTC),
        formal_experiment=True,
        manifest_verified=True,
    )


def _fix_w_standardized_records(
    local_date: date,
    *,
    wmr_hour: int = 16,
    spread: float = 0.0002,
) -> list[tuple[datetime, float, float]]:
    tokyo = event_window("tokyo_fix", local_date).center_utc
    ecb = event_window("ecb_fix", local_date).center_utc
    berlin_open = datetime(
        local_date.year,
        local_date.month,
        local_date.day,
        8,
        tzinfo=ZoneInfo("Europe/Berlin"),
    ).astimezone(UTC)
    wmr = datetime(
        local_date.year,
        local_date.month,
        local_date.day,
        wmr_hour,
        tzinfo=ZoneInfo("Europe/London"),
    ).astimezone(UTC)
    boundaries = [
        (fx_session_boundary(local_date - timedelta(days=1)), tokyo, 1.00, 1.01),
        (tokyo, berlin_open, 1.01, 1.02),
        (berlin_open, ecb, 1.02, 1.03),
        (wmr + timedelta(minutes=2, seconds=30), fx_session_boundary(local_date), 1.03, 1.04),
    ]
    records: list[tuple[datetime, float, float]] = []
    for start, end, start_mid, end_mid in boundaries:
        records.extend(
            [
                (start + timedelta(seconds=1), start_mid - spread / 2, start_mid + spread / 2),
                (end, end_mid - spread / 2, end_mid + spread / 2),
            ]
        )
    return records


def _fix_w_g9_quotes(
    local_date: date,
    *,
    wmr_hour: int = 16,
    spread: float = 0.0002,
) -> dict[str, pd.DataFrame]:
    standardized = _fix_w_standardized_records(
        local_date, wmr_hour=wmr_hour, spread=spread
    )
    result: dict[str, pd.DataFrame] = {}
    for _, (market_symbol, inverted) in FIX_W_G9_LEGS.items():
        records = standardized
        if inverted:
            records = [
                (timestamp, 1.0 / standardized_ask, 1.0 / standardized_bid)
                for timestamp, standardized_bid, standardized_ask in standardized
            ]
        result[market_symbol] = _quotes(records)
    return result


def _local_paper_quotes(local_date: date) -> dict[str, pd.DataFrame]:
    boundaries: dict[str, set[datetime]] = {
        unit.symbol: set() for unit in LOCAL_PAPER_UNITS
    }
    for unit in LOCAL_PAPER_UNITS:
        window = session_window(unit.session, local_date)
        end = window.end_utc
        if unit.overlap_close_session is not None:
            end = session_window(unit.overlap_close_session, local_date).start_utc
        boundaries[unit.symbol].update(
            {
                window.start_utc - timedelta(seconds=1),
                end - timedelta(seconds=1),
            }
        )
    result: dict[str, pd.DataFrame] = {}
    for symbol, timestamps in boundaries.items():
        records = []
        for ordinal, timestamp in enumerate(sorted(timestamps)):
            mid = 1.0 + ordinal * 0.01
            records.append((timestamp, mid - 0.0001, mid + 0.0001))
        result[symbol] = _quotes(records)
    return result


def test_local_paper_panel_freezes_twelve_units_overlap_rule_and_directions() -> None:
    local_date = date(2025, 12, 25)  # Holidays are retained when quotes are supplied.
    quotes = _local_paper_quotes(local_date)
    new_york_open = session_window("new_york", local_date).start_utc
    quotes["EURUSD"] = pd.concat(
        [
            quotes["EURUSD"],
            _quotes(
                [
                    (
                        new_york_open + timedelta(seconds=1),
                        9.9998,
                        10.0002,
                    )
                ]
            ),
        ]
    ).sort_index()

    panel = build_local_paper_panel(quotes, [local_date])

    assert len(panel) == 12
    expected_units = {
        "eurusd_europe_short": ("EURUSD", "london", -1, "new_york"),
        "eurusd_new_york_long": ("EURUSD", "new_york", 1, None),
        "usdjpy_tokyo_long": ("USDJPY", "tokyo", 1, None),
        "usdjpy_new_york_short": ("USDJPY", "new_york", -1, None),
        "gbpusd_europe_short": ("GBPUSD", "london", -1, "new_york"),
        "gbpusd_new_york_long": ("GBPUSD", "new_york", 1, None),
        "eurjpy_europe_short": ("EURJPY", "london", -1, None),
        "eurjpy_tokyo_long": ("EURJPY", "tokyo", 1, None),
        "usdchf_europe_long": ("USDCHF", "london", 1, "new_york"),
        "usdchf_new_york_short": ("USDCHF", "new_york", -1, None),
        "audusd_sydney_short": ("AUDUSD", "sydney", -1, None),
        "audusd_new_york_long": ("AUDUSD", "new_york", 1, None),
    }
    actual_units = {
        unit.unit_id: (
            unit.symbol,
            unit.session,
            unit.direction,
            unit.overlap_close_session,
        )
        for unit in LOCAL_PAPER_UNITS
    }
    assert actual_units == expected_units
    assert set(panel["paper_unit_id"]) == set(expected_units)
    assert set(panel["sample_status"]) == {"complete"}
    assert not panel["holiday_filter_applied"].any()
    assert not panel["weekend_filter_applied"].any()
    europe = panel.set_index("paper_unit_id").loc["eurusd_europe_short"]
    assert europe["endpoint_rule"] == "open_to_counterpart_open"
    assert europe["scheduled_exit_time"] == pd.Timestamp(new_york_open)
    assert europe["exit_time"] == pd.Timestamp(new_york_open - timedelta(seconds=1))
    assert europe["direction"] == -1
    assert europe["executable_log_return"] == pytest.approx(
        np.log(europe["entry_bid"] / europe["exit_ask"])
    )
    new_york = panel.set_index("paper_unit_id").loc["eurusd_new_york_long"]
    assert new_york["direction"] == 1
    assert new_york["executable_log_return"] == pytest.approx(
        np.log(new_york["exit_bid"] / new_york["entry_ask"])
    )
    eurjpy = panel.set_index("paper_unit_id").loc["eurjpy_europe_short"]
    assert eurjpy["endpoint_rule"] == "open_to_close"
    assert bool(eurjpy["eurjpy_table_sign_canary"])
    assert eurjpy["eurjpy_reciprocal_executable_log_return"] == pytest.approx(
        eurjpy["executable_log_return"], abs=1e-15
    )
    assert eurjpy["eurjpy_reciprocal_invariance_error"] == pytest.approx(
        0.0, abs=1e-15
    )
    reciprocal_entry_bid = 1.0 / eurjpy["entry_ask"]
    reciprocal_exit_ask = 1.0 / eurjpy["exit_bid"]
    reciprocal_short_after_wrong_direction_flip = np.log(
        reciprocal_entry_bid / reciprocal_exit_ask
    )
    assert reciprocal_short_after_wrong_direction_flip == pytest.approx(
        eurjpy["executable_long_log_return"]
    )
    assert reciprocal_short_after_wrong_direction_flip != pytest.approx(
        eurjpy["executable_log_return"]
    )


def test_local_paper_panel_applies_pair_specific_utc_working_week_boundaries() -> None:
    saturday_open = pd.Timestamp("2025-01-18T00:00:00Z")
    extended_reopen = pd.Timestamp("2025-01-18T18:00:00Z")
    ordinary_reopen = pd.Timestamp("2025-01-19T00:00:00Z")
    assert not _local_paper_boundary_in_working_week("EURUSD", saturday_open)
    assert not _local_paper_boundary_in_working_week("EURUSD", extended_reopen)
    assert _local_paper_boundary_in_working_week("EURUSD", ordinary_reopen)
    assert not _local_paper_boundary_in_working_week(
        "EURJPY", extended_reopen - timedelta(microseconds=1)
    )
    assert _local_paper_boundary_in_working_week("EURJPY", extended_reopen)

    saturday = date(2025, 1, 18)
    saturday_panel = build_local_paper_panel(
        _local_paper_quotes(saturday), [saturday]
    ).set_index("paper_unit_id")

    tokyo = saturday_panel.loc["usdjpy_tokyo_long"]
    assert bool(tokyo["entry_in_paper_working_week"])
    assert not bool(tokyo["exit_in_paper_working_week"])
    assert tokyo["sample_status"] == "paper_weekend_excluded_exit"
    new_york = saturday_panel.loc["usdjpy_new_york_short"]
    assert not bool(new_york["entry_in_paper_working_week"])
    assert bool(new_york["exit_in_paper_working_week"])
    assert new_york["sample_status"] == "paper_weekend_excluded_entry"
    assert saturday_panel["weekend_filter_applied"].all()
    assert not saturday_panel["holiday_filter_applied"].any()

    # JPY/AUD crosses reopen at Saturday 18:00 UTC, so their Sunday-local
    # Tokyo/Sydney sessions can begin on Saturday night without being dropped.
    sunday = date(2025, 1, 19)
    sunday_panel = build_local_paper_panel(_local_paper_quotes(sunday), [sunday])
    assert set(sunday_panel["sample_status"]) == {"complete"}
    assert not sunday_panel["weekend_filter_applied"].any()


def test_local_portfolio_extension_uses_fixed_sleeves_and_never_renormalizes() -> None:
    local_date = date(2025, 1, 15)
    quotes = _local_paper_quotes(local_date)
    panel = build_local_paper_panel(quotes, [local_date])

    result = build_local_portfolio_extension(panel).iloc[0]

    expected_pair_returns = []
    for symbol, group in panel.groupby("symbol"):
        assert symbol in {unit.symbol for unit in LOCAL_PAPER_UNITS}
        expected_pair_returns.append(float(np.expm1(group["executable_log_return"].sum())))
    assert result["sample_status"] == "complete"
    assert result["expected_unit_count"] == 12
    assert result["expected_sleeve_count"] == 6
    assert result["pair_sleeve_weight"] == pytest.approx(1 / 6)
    assert result["maximum_gross_notional"] == pytest.approx(1.0)
    assert not bool(result["missing_unit_renormalized"])
    assert result["executable_simple_return"] == pytest.approx(
        np.mean(expected_pair_returns)
    )

    eurjpy_start = session_window("london", local_date).start_utc - timedelta(seconds=1)
    quotes["EURJPY"] = quotes["EURJPY"].drop(pd.Timestamp(eurjpy_start))
    incomplete_panel = build_local_paper_panel(quotes, [local_date])
    incomplete = build_local_portfolio_extension(incomplete_panel).iloc[0]
    assert incomplete["sample_status"] == "incomplete_12_unit_panel"
    assert incomplete["complete_unit_count"] == 11
    assert incomplete["missing_units"] == "eurjpy_europe_short"
    assert pd.isna(incomplete["executable_simple_return"])
    assert not bool(incomplete["missing_unit_renormalized"])


def test_local_paper_panel_requires_the_frozen_six_pairs() -> None:
    local_date = date(2025, 1, 15)
    quotes = _local_paper_quotes(local_date)
    quotes.pop("AUDUSD")

    with pytest.raises(ValueError, match="complete frozen six-pair.*AUDUSD"):
        build_local_paper_panel(quotes, [local_date])


def test_fix_w_terminal_new_york_close_uses_last_pre_boundary_tick() -> None:
    local_date = date(2025, 1, 17)  # Friday; there is no valid post-close weekend tick.
    calendar = _formal_event_calendar(local_date)
    quotes = _fix_w_g9_quotes(local_date)
    new_york_close = fx_session_boundary(local_date)
    for symbol, frame in quotes.items():
        assert frame.index[-1] == new_york_close
        shifted = frame.copy()
        shifted.index = pd.DatetimeIndex(
            [*shifted.index[:-1], new_york_close - timedelta(seconds=1)],
            name="timestamp",
        )
        quotes[symbol] = shifted

    legs = build_fix_w_leg_experiments(
        quotes, [local_date], publication_calendar=calendar
    )

    assert set(legs["sample_status"]) == {"complete"}
    assert set(legs["post_wmr_end_quote_age_seconds"]) == {1.0}
    assert (legs["post_wmr_end_quote_time"] < pd.Timestamp(new_york_close)).all()


def test_fix_w_spread_gate_has_sixty_day_warmup_and_past_only_q90() -> None:
    dates = [date(2025, 1, 1) + timedelta(days=offset) for offset in range(62)]
    calendar = _combined_formal_event_calendar(dates)

    def build(spreads: list[float]) -> tuple[pd.DataFrame, pd.DataFrame]:
        chunks = [
            _fix_w_g9_quotes(day, spread=spread)
            for day, spread in zip(dates, spreads, strict=True)
        ]
        quotes = {
            symbol: pd.concat([chunk[symbol] for chunk in chunks]).sort_index()
            for symbol in chunks[0]
        }
        return (
            build_fix_w_leg_experiments(
                quotes, dates, publication_calendar=calendar
            ),
            build_fix_w_composite_experiments(
                quotes, dates, publication_calendar=calendar
            ),
        )

    ordinary = [0.0002] * len(dates)
    high_current = ordinary.copy()
    high_current[60] = 0.002
    high_future = ordinary.copy()
    high_future[61] = 0.01
    base_legs, base_composite = build(ordinary)
    current_legs, current_composite = build(high_current)
    future_legs, future_composite = build(high_future)

    eur = base_legs.loc[base_legs["foreign_currency"] == "EUR"].reset_index(drop=True)
    assert (eur.iloc[:60]["spread_filter_status"] == "warmup").all()
    assert not eur.iloc[:60]["spread_filter_pass"].any()
    assert eur.iloc[60]["pre_tokyo_spread_history_count"] == 60
    assert eur.iloc[60]["spread_filter_status"] == "pass"
    current_eur = current_legs.loc[
        current_legs["foreign_currency"] == "EUR"
    ].reset_index(drop=True)
    assert current_eur.iloc[60]["spread_filter_status"] == "reject"
    assert current_eur.iloc[60]["pre_tokyo_spread_q90_bps"] == pytest.approx(
        eur.iloc[60]["pre_tokyo_spread_q90_bps"]
    )
    assert future_legs.loc[
        (future_legs["foreign_currency"] == "EUR")
        & (future_legs["local_date"] == dates[60]),
        "spread_filter_status",
    ].iloc[0] == "pass"
    assert bool(base_composite.iloc[60]["spread_filter_pass"])
    assert pd.notna(base_composite.iloc[60]["filtered_executable_long_log_return"])
    assert current_composite.iloc[60]["spread_filter_status"] == "reject"
    assert pd.isna(
        current_composite.iloc[60]["filtered_executable_long_log_return"]
    )
    assert bool(future_composite.iloc[60]["spread_filter_pass"])


def test_fix_w_builds_exact_four_segments_and_equal_weight_g9_composite() -> None:
    local_date = date(2025, 1, 15)
    calendar = _formal_event_calendar(local_date)
    quotes = _fix_w_g9_quotes(local_date)

    legs = build_fix_w_leg_experiments(
        quotes, [local_date], publication_calendar=calendar
    )
    composite = build_fix_w_composite_experiments(
        quotes, [local_date], publication_calendar=calendar
    )

    expected_gross = -np.log(1.01 / 1.00) + np.log(1.02 / 1.01)
    expected_gross += -np.log(1.03 / 1.02) + np.log(1.04 / 1.03)
    assert len(legs) == 9
    assert set(legs["complete_segment_count"]) == {4}
    assert set(legs["sample_status"]) == {"complete"}
    assert set(legs["quote_orientation"]) == {
        "usd_per_foreign",
        "inverted_to_usd_per_foreign",
    }
    assert legs["gross_mid_log_return"].to_numpy() == pytest.approx(expected_gross)
    assert legs.loc[
        legs["foreign_currency"] == "EUR", "executable_long_log_return"
    ].iloc[0] == pytest.approx(
        legs.loc[
            legs["foreign_currency"] == "JPY", "executable_long_log_return"
        ].iloc[0]
    )
    assert list(legs.filter(regex=r"_(sign)$").iloc[0]) == [-1, 1, -1, 1]
    assert composite.iloc[0]["expected_leg_count"] == 9
    assert composite.iloc[0]["return_ready_leg_count"] == 9
    assert composite.iloc[0]["gross_mid_log_return"] == pytest.approx(expected_gross)
    assert composite.iloc[0]["sample_status"] == "complete"
    assert composite.iloc[0]["executable_long_log_return"] < expected_gross


def test_fix_w_requires_complete_frozen_g9_and_never_renormalizes_partial_universe() -> None:
    local_date = date(2025, 1, 15)
    calendar = _formal_event_calendar(local_date)
    quotes = _fix_w_g9_quotes(local_date)
    quotes.pop("USDNOK")

    with pytest.raises(ValueError, match="complete frozen G9.*USDNOK"):
        build_fix_w_composite_experiments(
            quotes, [local_date], publication_calendar=calendar
        )


def test_fix_w_retains_incomplete_date_but_suppresses_composite_return() -> None:
    local_date = date(2025, 1, 15)
    calendar = _formal_event_calendar(local_date)
    quotes = _fix_w_g9_quotes(local_date)
    quotes["USDJPY"] = quotes["USDJPY"].iloc[:-1]

    legs = build_fix_w_leg_experiments(
        quotes, [local_date], publication_calendar=calendar
    )
    composite = build_fix_w_composite_experiments(
        quotes, [local_date], publication_calendar=calendar
    )

    jpy = legs.loc[legs["foreign_currency"] == "JPY"].iloc[0]
    assert jpy["sample_status"] == "missing_segment_end"
    assert composite.iloc[0]["sample_status"] == "incomplete_g9_cross_section"
    assert composite.iloc[0]["return_ready_leg_count"] == 8
    assert composite.iloc[0]["missing_legs"] == "JPY"
    assert pd.isna(composite.iloc[0]["executable_long_log_return"])


def test_fix_w_publication_calendar_skips_not_published_and_uses_early_wmr_time() -> None:
    local_date = date(2025, 12, 31)
    quotes = _fix_w_g9_quotes(local_date, wmr_hour=13)
    early = _formal_event_calendar(local_date, wmr_hour=13)
    row = build_fix_w_leg_experiments(
        quotes, [local_date], publication_calendar=early
    ).iloc[0]

    assert row["wmr_fix_time"] == pd.Timestamp("2025-12-31 13:00:00Z")
    assert row["post_wmr_start_time"] == pd.Timestamp("2025-12-31 13:02:30Z")

    closed = _formal_event_calendar(
        local_date, statuses={"wmr_fix": "not_published"}, wmr_hour=13
    )
    assert build_fix_w_composite_experiments(
        quotes, [local_date], publication_calendar=closed
    ).empty


def test_fix_w_rejects_exploratory_unverified_calendar_contract() -> None:
    local_date = date(2025, 1, 15)
    calendar = _formal_event_calendar(local_date, formal_experiment=False)

    with pytest.raises(PublicationCalendarError, match="verified formal"):
        build_fix_w_composite_experiments(
            _fix_w_g9_quotes(local_date),
            [local_date],
            publication_calendar=calendar,
        )


def test_wmr_month_end_builder_uses_actual_publication_and_skips_closed_date() -> None:
    dates = [date(2025, 12, 30), date(2025, 12, 31)]
    calendar = _complete_wmr_calendar(2025, 12, published_days={30})
    quotes = _fix_quotes([dates[0]], [0.0002])

    result = build_wmr_month_end_experiments(
        {"EURUSD": quotes}, dates, publication_calendar=calendar
    )

    assert list(result["local_date"]) == [dates[0]]
    assert list(result["actual_wmr_month_end_date"]) == [dates[0]]
    assert bool(result.iloc[0]["is_actual_wmr_month_end"])


def test_wmr_month_end_builder_refuses_incomplete_natural_month_coverage() -> None:
    local_date = date(2025, 12, 30)
    calendar = PublicationCalendar(
        (_complete_wmr_calendar(2025, 12, published_days={30}).events[29],),
        knowledge_cutoff=datetime(2026, 1, 3, tzinfo=UTC),
        formal_experiment=True,
        manifest_verified=True,
    )

    with pytest.raises(PublicationCalendarError, match="coverage.*incomplete"):
        build_wmr_month_end_experiments(
            {"EURUSD": _fix_quotes([local_date], [0.0002])},
            [local_date],
            publication_calendar=calendar,
        )


def test_fix_windows_follow_london_dst_and_keep_the_same_local_slot() -> None:
    dates = [date(2025, 1, 15), date(2025, 7, 15)]
    frame = _fix_quotes(dates, [0.0002, 0.0002])

    result = build_fix_window_experiments({"EURUSD": frame}, dates, events=("wmr_fix",))

    assert list(result["decision_time"]) == [
        pd.Timestamp("2025-01-15 15:57:30Z"),
        pd.Timestamp("2025-07-15 14:57:30Z"),
    ]
    assert set(result["decision_local_15m_slot"]) == {"15:45"}
    assert set(result["timezone"]) == {"Europe/London"}


@pytest.mark.parametrize(
    ("exit_bid", "exit_ask", "long_positive", "short_positive"),
    [
        (1.1010, 1.1012, True, False),
        (1.0990, 1.0992, False, True),
    ],
)
def test_executable_long_and_short_returns_use_the_correct_quote_side(
    exit_bid: float,
    exit_ask: float,
    long_positive: bool,
    short_positive: bool,
) -> None:
    local_date = date(2025, 1, 15)
    window = event_window("wmr_fix", local_date)
    frame = _quotes(
        [
            (window.start_utc + timedelta(seconds=1), 1.1000, 1.1002),
            (window.end_utc, exit_bid, exit_ask),
        ]
    )

    row = build_fix_window_experiments({"EURUSD": frame}, [local_date], events=("wmr_fix",)).iloc[0]

    assert row["executable_long_log_return"] == pytest.approx(np.log(exit_bid / 1.1002))
    assert row["executable_short_log_return"] == pytest.approx(np.log(1.1000 / exit_ask))
    assert bool(row["executable_long_log_return"] > 0) is long_positive
    assert bool(row["executable_short_log_return"] > 0) is short_positive
    assert row["gross_mid_log_return"] == pytest.approx(
        np.log(((exit_bid + exit_ask) / 2) / 1.1001)
    )


def test_asia_signal_is_half_open_and_cannot_see_london_response_quotes() -> None:
    local_date = date(2025, 6, 2)
    formation = session_window("asia_formation", local_date)
    response = session_window("london_response", local_date)
    records = [
        (formation.start_utc + timedelta(seconds=1), 0.9999, 1.0001),
        (formation.end_utc - timedelta(seconds=1), 1.0099, 1.0101),
        # The exact decision quote is neither signal data nor a strictly post-decision entry.
        (response.start_utc, 4.9999, 5.0001),
        (response.start_utc + timedelta(seconds=1), 1.0199, 1.0201),
        (response.start_utc + timedelta(seconds=2), 1.0299, 1.0301),
        (response.end_utc, 1.0399, 1.0401),
    ]
    base = _quotes(records)
    changed = base.copy()
    changed.loc[changed.index == response.end_utc, ["bid", "ask"]] *= 3

    first = build_asia_london_experiments({"EURUSD": base}, [local_date]).iloc[0]
    second = build_asia_london_experiments({"EURUSD": changed}, [local_date]).iloc[0]

    assert first["signal_mid_log_return"] == pytest.approx(np.log(1.01 / 1.0))
    assert second["signal_mid_log_return"] == pytest.approx(first["signal_mid_log_return"])
    assert first["signal_start_quote_age_seconds"] == 1
    assert first["signal_end_quote_age_seconds"] == 1
    assert first["signal_last_quote_time"] < first["decision_time"]
    assert first["entry_time"] == pd.Timestamp(response.start_utc + timedelta(seconds=1))
    assert first["entry_time"] > first["decision_time"]
    assert first["gross_mid_log_return"] != pytest.approx(second["gross_mid_log_return"])


def test_asia_signal_requires_quotes_within_five_seconds_of_both_boundaries() -> None:
    local_date = date(2025, 6, 2)
    formation = session_window("asia_formation", local_date)
    response = session_window("london_response", local_date)
    frame = _quotes(
        [
            (formation.start_utc + timedelta(seconds=6), 0.9999, 1.0001),
            (formation.end_utc - timedelta(seconds=6), 1.0099, 1.0101),
            (response.start_utc + timedelta(seconds=1), 1.0199, 1.0201),
            (response.end_utc, 1.0299, 1.0301),
        ]
    )

    row = build_asia_london_experiments({"EURUSD": frame}, [local_date]).iloc[0]

    assert row["signal_status"] == "missing_boundary_quote_within_5s"
    assert row["sample_status"] == "missing_signal"
    assert pd.isna(row["signal_mid_log_return"])


def test_spread_q90_has_sixty_day_warmup_and_uses_only_prior_rows() -> None:
    dates = [date(2025, 1, 1) + timedelta(days=offset) for offset in range(62)]
    ordinary = 0.0002
    base_spreads = [ordinary] * len(dates)
    changed_current = base_spreads.copy()
    changed_current[60] = 0.002
    changed_future = base_spreads.copy()
    changed_future[61] = 0.01

    base = build_fix_window_experiments(
        {"EURUSD": _fix_quotes(dates, base_spreads)}, dates, events=("wmr_fix",)
    )
    current_changed = build_fix_window_experiments(
        {"EURUSD": _fix_quotes(dates, changed_current)}, dates, events=("wmr_fix",)
    )
    future_changed = build_fix_window_experiments(
        {"EURUSD": _fix_quotes(dates, changed_future)}, dates, events=("wmr_fix",)
    )

    assert (base.iloc[:60]["spread_filter_status"] == "warmup").all()
    assert not base.iloc[:60]["spread_filter_pass"].any()
    assert base.iloc[60]["spread_history_count"] == 60
    assert base.iloc[60]["spread_filter_status"] == "pass"
    assert current_changed.iloc[60]["spread_filter_status"] == "reject"
    assert current_changed.iloc[60]["spread_q90_bps"] == pytest.approx(
        base.iloc[60]["spread_q90_bps"]
    )
    assert future_changed.iloc[60]["spread_q90_bps"] == pytest.approx(
        base.iloc[60]["spread_q90_bps"]
    )
    assert future_changed.iloc[60]["spread_filter_status"] == "pass"


def test_late_or_missing_exit_is_recorded_without_deleting_the_sample() -> None:
    dates = [date(2025, 1, 15), date(2025, 1, 16)]
    first = event_window("wmr_fix", dates[0])
    second = event_window("wmr_fix", dates[1])
    frame = _quotes(
        [
            (first.start_utc + timedelta(seconds=1), 1.0, 1.0002),
            (first.end_utc + timedelta(seconds=90), 1.0001, 1.0003),
            (second.start_utc + timedelta(seconds=1), 1.0, 1.0002),
        ]
    )

    result = build_fix_window_experiments({"EURUSD": frame}, dates, events=("wmr_fix",))

    assert len(result) == 2
    assert result.iloc[0]["exit_status"] == "delayed"
    assert result.iloc[0]["exit_delay_seconds"] == 90
    assert result.iloc[0]["sample_status"] == "delayed_exit"
    assert result.iloc[1]["exit_status"] == "missing"
    assert result.iloc[1]["sample_status"] == "missing_exit"
    assert pd.isna(result.iloc[1]["gross_mid_log_return"])


def test_entry_must_be_strictly_post_decision_and_within_five_seconds() -> None:
    local_date = date(2025, 1, 15)
    window = event_window("wmr_fix", local_date)
    frame = _quotes(
        [
            (window.start_utc, 1.0, 1.0002),
            (window.start_utc + timedelta(seconds=6), 1.0, 1.0002),
            (window.end_utc, 1.0001, 1.0003),
        ]
    )

    row = build_fix_window_experiments({"EURUSD": frame}, [local_date], events=("wmr_fix",)).iloc[0]

    assert row["entry_status"] == "missing_quote_within_5s"
    assert row["sample_status"] == "missing_entry"
    assert pd.isna(row["entry_time"])


def test_quote_input_requires_explicit_utc_and_uncrossed_sides() -> None:
    local_date = date(2025, 1, 15)
    window = event_window("wmr_fix", local_date)
    naive = _quotes(
        [
            (
                datetime(2025, 1, 15, 15, 57, 31),
                1.0,
                1.0002,
            )
        ]
    )
    crossed = _quotes([(window.start_utc + timedelta(seconds=1), 1.0002, 1.0)])

    with pytest.raises(ValueError, match="timezone-aware UTC"):
        build_fix_window_experiments({"EURUSD": naive}, [local_date], events=("wmr_fix",))
    with pytest.raises(ValueError, match="crossed"):
        build_fix_window_experiments({"EURUSD": crossed}, [local_date], events=("wmr_fix",))


def test_timestamp_column_is_accepted_for_utc_tick_or_minute_quote_tables() -> None:
    local_date = date(2025, 1, 15)
    window = event_window("wmr_fix", local_date)
    frame = pd.DataFrame(
        {
            "timestamp": [
                window.start_utc + timedelta(seconds=1),
                window.end_utc,
            ],
            "bid": [1.0, 1.0001],
            "ask": [1.0002, 1.0003],
        }
    )

    result = build_fix_window_experiments({"EURUSD": frame}, [local_date], events=("wmr_fix",))

    assert result.iloc[0]["sample_status"] == "complete"
    assert result.iloc[0]["entry_quote_age_seconds"] == 1
    assert bool(result.iloc[0]["research_only"])
