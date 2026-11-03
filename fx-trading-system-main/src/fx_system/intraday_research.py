"""Frozen construction of intraday FX research observations.

This module deliberately stops at an experiment table.  It does not choose a
direction, rank hypotheses, or claim a tradable result.  Every scheduled
observation is retained so missing quotes and spread-filter failures remain
visible to later audits.

Input frames contain UTC quote timestamps and ``bid``/``ask`` columns.  A
decision boundary splits information and execution: signal quotes must be
strictly earlier than the decision, while the entry is the first valid quote
strictly later than it and no more than five seconds away.  Exit quotes are the
first valid quote at or after the scheduled exit and are never silently
dropped merely because they arrived late.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Final, Literal
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .intraday_calendar import (
    EVENT_WINDOW_HALF_WIDTH,
    EventWindow,
    SessionWindow,
    event_window,
    fx_session_boundary,
    session_window,
    tzdb_info,
)
from .publication_calendar import PublicationCalendar, PublicationCalendarError

ENTRY_MAX_QUOTE_AGE: Final = timedelta(seconds=5)
FORMATION_MAX_QUOTE_AGE: Final = timedelta(seconds=5)
FIX_W_BOUNDARY_MAX_QUOTE_AGE: Final = timedelta(seconds=5)
LOCAL_PAPER_BOUNDARY_MAX_QUOTE_AGE: Final = timedelta(seconds=5)
SPREAD_LOOKBACK_DAYS: Final = 60
SPREAD_MIN_OBSERVATIONS: Final = 40
SPREAD_WARMUP_DAYS: Final = 60
SPREAD_QUANTILE: Final = 0.90

FIX_EVENTS: Final[tuple[str, ...]] = ("tokyo_fix", "ecb_fix", "wmr_fix")
LOCAL_SESSIONS: Final[tuple[str, ...]] = ("tokyo", "london", "new_york", "sydney")
LOCAL_PAPER_EXTENDED_WEEK_SYMBOLS: Final[frozenset[str]] = frozenset(
    {"USDJPY", "EURJPY", "AUDUSD"}
)

# The preregistered G9 foreign-currency legs, all standardized internally to
# USD per unit of foreign currency.  The values describe the frozen Dukascopy
# market symbol and whether that symbol must be inverted.
FIX_W_G9_LEGS: Final[Mapping[str, tuple[str, bool]]] = {
    "AUD": ("AUDUSD", False),
    "CAD": ("USDCAD", True),
    "CHF": ("USDCHF", True),
    "EUR": ("EURUSD", False),
    "GBP": ("GBPUSD", False),
    "JPY": ("USDJPY", True),
    "NOK": ("USDNOK", True),
    "NZD": ("NZDUSD", False),
    "SEK": ("USDSEK", True),
}
FIX_W_SEGMENT_SIGNS: Final[tuple[tuple[str, int], ...]] = (
    ("pre_tokyo", -1),
    ("post_tokyo", 1),
    ("pre_ecb", -1),
    ("post_wmr", 1),
)


@dataclass(frozen=True)
class FixWSegment:
    name: str
    sign: int
    start_time: datetime
    end_time: datetime

    def __post_init__(self) -> None:
        if self.sign not in {-1, 1}:
            raise ValueError("FIX-W segment sign must be -1 or +1")
        if self.start_time.tzinfo is None or self.end_time.tzinfo is None:
            raise ValueError("FIX-W segment boundaries must be timezone-aware")
        if not self.start_time < self.end_time:
            raise ValueError("FIX-W segment start must precede its end")


@dataclass(frozen=True)
class LocalPaperUnit:
    """One of Breedon--Ranaldo's fixed pair-by-local-session strategy units."""

    unit_id: str
    symbol: str
    session: str
    direction: Literal[-1, 1]
    overlap_close_session: str | None = None

    def __post_init__(self) -> None:
        if self.direction not in {-1, 1}:
            raise ValueError("LOCAL paper direction must be -1 or +1")
        if len(self.symbol) != 6 or not self.symbol.isalpha() or not self.symbol.isupper():
            raise ValueError("LOCAL paper symbols must be six uppercase letters")


LOCAL_PAPER_UNITS: Final[tuple[LocalPaperUnit, ...]] = (
    LocalPaperUnit("eurusd_europe_short", "EURUSD", "london", -1, "new_york"),
    LocalPaperUnit("eurusd_new_york_long", "EURUSD", "new_york", 1),
    LocalPaperUnit("usdjpy_tokyo_long", "USDJPY", "tokyo", 1),
    LocalPaperUnit("usdjpy_new_york_short", "USDJPY", "new_york", -1),
    LocalPaperUnit("gbpusd_europe_short", "GBPUSD", "london", -1, "new_york"),
    LocalPaperUnit("gbpusd_new_york_long", "GBPUSD", "new_york", 1),
    LocalPaperUnit("eurjpy_europe_short", "EURJPY", "london", -1),
    LocalPaperUnit("eurjpy_tokyo_long", "EURJPY", "tokyo", 1),
    LocalPaperUnit("usdchf_europe_long", "USDCHF", "london", 1, "new_york"),
    LocalPaperUnit("usdchf_new_york_short", "USDCHF", "new_york", -1),
    LocalPaperUnit("audusd_sydney_short", "AUDUSD", "sydney", -1),
    LocalPaperUnit("audusd_new_york_long", "AUDUSD", "new_york", 1),
)


@dataclass(frozen=True)
class _ExperimentWindow:
    family: str
    event: str
    local_date: date
    timezone: str
    decision_time: datetime
    scheduled_exit_time: datetime
    tzdb_identifier: str
    signal_start_time: datetime | None = None
    signal_end_time: datetime | None = None


def build_fix_window_experiments(
    quotes: Mapping[str, pd.DataFrame],
    local_dates: Iterable[date | datetime | str],
    *,
    events: Sequence[str] = FIX_EVENTS,
    publication_calendar: PublicationCalendar | None = None,
) -> pd.DataFrame:
    """Build individual five-minute fix-window observations.

    These are price-window primitives, not the four-segment FIX-W composite.
    Without ``publication_calendar`` they are exploratory civil-time
    templates.  Supplying a verified formal calendar uses actual event times
    and omits dates explicitly marked ``not_published``; missing dates fail
    closed rather than falling back to weekdays.
    """

    dates = tuple(local_dates)
    specifications = (
        _fix_specifications(dates, events)
        if publication_calendar is None
        else _published_fix_specifications(dates, events, publication_calendar)
    )
    return _construct_experiments(quotes, specifications)


def build_wmr_month_end_experiments(
    quotes: Mapping[str, pd.DataFrame],
    local_dates: Iterable[date | datetime | str],
    *,
    publication_calendar: PublicationCalendar,
) -> pd.DataFrame:
    """Build WMR fix-window rows with a verified actual-month-end indicator.

    Every requested calendar month must contain an explicit WMR row for every
    natural day.  This deliberately delegates to
    :meth:`PublicationCalendar.actual_wmr_month_end`, so a weekday heuristic
    can never substitute for the last actually published fix.
    """

    dates = tuple(local_dates)
    parsed_dates = [event_window("wmr_fix", value).local_date for value in dates]
    if len(parsed_dates) != len(set(parsed_dates)):
        raise ValueError("WMR month-end local_dates must be unique")
    month_ends = {
        (value.year, value.month): publication_calendar.actual_wmr_month_end(
            value.year, value.month
        )
        for value in parsed_dates
    }
    result = build_fix_window_experiments(
        quotes,
        dates,
        events=("wmr_fix",),
        publication_calendar=publication_calendar,
    )
    result["actual_wmr_month_end_date"] = result["local_date"].map(
        lambda value: month_ends[(value.year, value.month)].local_date
    )
    result["is_actual_wmr_month_end"] = (
        result["local_date"] == result["actual_wmr_month_end_date"]
    )
    return result


def build_fix_w_leg_experiments(
    quotes: Mapping[str, pd.DataFrame],
    local_dates: Iterable[date | datetime | str],
    *,
    publication_calendar: PublicationCalendar,
) -> pd.DataFrame:
    """Build the four signed FIX-W segments for every frozen G9 USD leg.

    Market quotes are first converted to the common ``USD per foreign
    currency`` convention.  Thus an inverse market such as ``USDJPY`` becomes
    ``JPYUSD`` economically, with ``bid=1/original_ask`` and
    ``ask=1/original_bid``.  This side swap is required for executable returns.

    The external publication calendar is mandatory and must have been loaded
    for a formal experiment.  Dates explicitly marked ``not_published`` for
    Tokyo, ECB, or WMR generate no experiment; a missing row remains an error.
    """

    legs, _ = _build_fix_w_tables(
        quotes,
        tuple(local_dates),
        publication_calendar=publication_calendar,
    )
    return legs


def build_fix_w_composite_experiments(
    quotes: Mapping[str, pd.DataFrame],
    local_dates: Iterable[date | datetime | str],
    *,
    publication_calendar: PublicationCalendar,
) -> pd.DataFrame:
    """Build the preregistered equal-weight G9 four-segment FIX-W composite.

    The result has one row per eligible event date.  A composite return is
    populated only when all nine frozen legs have all four segment endpoints;
    partial cross-sections remain visible but cannot silently become a
    different portfolio.  The primary return columns use executable bid/ask
    sides and pay the spread again whenever the signed position changes.
    """

    _, composite = _build_fix_w_tables(
        quotes,
        tuple(local_dates),
        publication_calendar=publication_calendar,
    )
    return composite


def fix_w_segment_plan(
    local_date: date | datetime | str,
    *,
    publication_calendar: PublicationCalendar,
) -> tuple[FixWSegment, ...]:
    """Return the frozen eligible FIX-W segments without reading market data."""

    parsed_date = event_window("tokyo_fix", local_date).local_date
    prepared = _fix_w_segments(parsed_date, publication_calendar)
    return () if prepared is None else prepared[0]


def _build_fix_w_tables(
    quotes: Mapping[str, pd.DataFrame],
    local_dates: Sequence[date | datetime | str],
    *,
    publication_calendar: PublicationCalendar,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not isinstance(publication_calendar, PublicationCalendar):
        raise TypeError("publication_calendar must be a PublicationCalendar")
    if not publication_calendar.formal_experiment:
        raise PublicationCalendarError(
            "FIX-W formal experiments require a verified formal publication calendar"
        )
    if not publication_calendar.manifest_verified:
        raise PublicationCalendarError(
            "FIX-W formal experiments require a hash-verified calendar source manifest"
        )

    canonical_quotes: dict[str, pd.DataFrame] = {}
    for raw_symbol, frame in quotes.items():
        symbol = str(raw_symbol).replace("/", "").upper()
        if symbol in canonical_quotes:
            raise ValueError(f"duplicate canonical quote symbol {symbol!r}")
        canonical_quotes[symbol] = frame
    required_symbols = {market_symbol for market_symbol, _ in FIX_W_G9_LEGS.values()}
    missing_symbols = sorted(required_symbols - set(canonical_quotes))
    if missing_symbols:
        raise ValueError(
            "FIX-W requires the complete frozen G9 USD universe; missing "
            f"{missing_symbols}"
        )

    normalized: dict[str, pd.DataFrame] = {}
    for currency, (market_symbol, inverted) in FIX_W_G9_LEGS.items():
        frame = _normalize_quotes(canonical_quotes[market_symbol], symbol=market_symbol)
        normalized[currency] = _standardize_usd_per_foreign(frame, inverted=inverted)

    parsed_dates = [event_window("tokyo_fix", value).local_date for value in local_dates]
    if len(parsed_dates) != len(set(parsed_dates)):
        raise ValueError("FIX-W local_dates must be unique")

    leg_rows: list[dict[str, object]] = []
    eligible_dates: list[tuple[date, tuple[FixWSegment, ...], dict[str, object]]] = []
    for local_date in parsed_dates:
        prepared = _fix_w_segments(local_date, publication_calendar)
        if prepared is None:
            continue
        segments, calendar_fields = prepared
        eligible_dates.append((local_date, segments, calendar_fields))
        for currency, frame in normalized.items():
            market_symbol, inverted = FIX_W_G9_LEGS[currency]
            leg_rows.append(
                _build_fix_w_leg_row(
                    currency,
                    market_symbol,
                    inverted,
                    frame,
                    local_date,
                    segments,
                    calendar_fields,
                )
            )

    if not leg_rows:
        return _empty_fix_w_leg_table(), _empty_fix_w_composite_table()

    legs = pd.DataFrame(leg_rows).sort_values(
        ["local_date", "foreign_currency"], ignore_index=True
    )
    legs = _apply_fix_w_spread_filter(legs)
    composite_rows = [
        _aggregate_fix_w_date(legs.loc[legs["local_date"] == local_date], local_date, fields)
        for local_date, _, fields in eligible_dates
    ]
    composites = pd.DataFrame(composite_rows).sort_values("local_date", ignore_index=True)
    return legs, composites


def _standardize_usd_per_foreign(
    quotes: pd.DataFrame, *, inverted: bool
) -> pd.DataFrame:
    if not inverted:
        return quotes
    result = quotes.copy()
    original_bid = result["bid"].copy()
    original_ask = result["ask"].copy()
    result["bid"] = 1.0 / original_ask
    result["ask"] = 1.0 / original_bid
    result["_mid"] = (result["bid"] + result["ask"]) / 2
    return result


def _fix_w_segments(
    local_date: date,
    publication_calendar: PublicationCalendar,
) -> tuple[tuple[FixWSegment, ...], dict[str, object]] | None:
    events = {
        name: publication_calendar.event_on(name, local_date)
        for name in ("tokyo_fix", "ecb_fix", "wmr_fix")
    }
    if any(not event.was_published for event in events.values()):
        return None
    if any(event.quality != "verified" for event in events.values()):
        raise PublicationCalendarError(
            f"FIX-W requires verified event rows on {local_date.isoformat()}"
        )

    tokyo = events["tokyo_fix"].event_time_utc
    ecb = events["ecb_fix"].event_time_utc
    wmr = events["wmr_fix"].event_time_utc
    if tokyo is None or ecb is None or wmr is None:  # Defensive after was_published.
        raise PublicationCalendarError("published FIX-W event unexpectedly lacks a timestamp")
    berlin_open = _local_clock_to_utc(local_date, time(8), "Europe/Berlin")
    segments = (
        FixWSegment(
            "pre_tokyo", -1, fx_session_boundary(local_date - timedelta(days=1)), tokyo
        ),
        FixWSegment("post_tokyo", 1, tokyo, berlin_open),
        FixWSegment("pre_ecb", -1, berlin_open, ecb),
        FixWSegment(
            "post_wmr", 1, wmr + timedelta(minutes=2, seconds=30), fx_session_boundary(local_date)
        ),
    )
    expected = dict(FIX_W_SEGMENT_SIGNS)
    if {segment.name: segment.sign for segment in segments} != expected:
        raise RuntimeError("FIX-W segment definitions diverged from the frozen registry")
    fields: dict[str, object] = {
        "tokyo_fix_time": pd.Timestamp(tokyo),
        "ecb_fix_time": pd.Timestamp(ecb),
        "wmr_fix_time": pd.Timestamp(wmr),
        "wmr_status": events["wmr_fix"].status,
        "calendar_knowledge_cutoff": pd.Timestamp(publication_calendar.knowledge_cutoff),
        "tzdb_identifier": tzdb_info().identifier,
    }
    return segments, fields


def _local_clock_to_utc(local_date: date, clock: time, timezone: str) -> datetime:
    zone = ZoneInfo(timezone)
    local = datetime.combine(local_date, clock, tzinfo=zone)
    utc = local.astimezone(UTC)
    if utc.astimezone(zone).replace(tzinfo=None) != datetime.combine(local_date, clock):
        raise ValueError(f"nonexistent local FIX-W boundary {local_date} {clock} {timezone}")
    alternate = local.replace(fold=1)
    if alternate.utcoffset() != local.utcoffset():
        raise ValueError(f"ambiguous local FIX-W boundary {local_date} {clock} {timezone}")
    return utc


def _build_fix_w_leg_row(
    currency: str,
    market_symbol: str,
    inverted: bool,
    quotes: pd.DataFrame,
    local_date: date,
    segments: Sequence[FixWSegment],
    calendar_fields: Mapping[str, object],
) -> dict[str, object]:
    row: dict[str, object] = {
        "family": "FIX-W",
        "event": "fix_w_composite",
        "local_date": local_date,
        "foreign_currency": currency,
        "market_symbol": market_symbol,
        "standardized_symbol": f"{currency}USD",
        "quote_orientation": "inverted_to_usd_per_foreign" if inverted else "usd_per_foreign",
        **calendar_fields,
        "segment_count": len(segments),
        "complete_segment_count": 0,
        "gross_mid_log_return": np.nan,
        "executable_long_log_return": np.nan,
        "executable_short_log_return": np.nan,
        "sample_status": "missing_segment_quote",
        "research_only": True,
    }
    gross_returns: list[float] = []
    long_returns: list[float] = []
    short_returns: list[float] = []
    missing_start = False
    missing_end = False
    for segment in segments:
        prefix = segment.name
        start_boundary = pd.Timestamp(segment.start_time)
        end_boundary = pd.Timestamp(segment.end_time)
        start_quote = _first_valid_quote(
            quotes,
            after=start_boundary,
            strictly_after=True,
            no_later_than=start_boundary + ENTRY_MAX_QUOTE_AGE,
        )
        end_quote = _last_valid_quote(
            quotes,
            before=end_boundary + pd.Timedelta(1, unit="ns"),
            no_earlier_than=end_boundary - FIX_W_BOUNDARY_MAX_QUOTE_AGE,
        )
        row.update(
            {
                f"{prefix}_sign": segment.sign,
                f"{prefix}_start_time": start_boundary,
                f"{prefix}_end_time": end_boundary,
                f"{prefix}_start_quote_time": pd.NaT,
                f"{prefix}_end_quote_time": pd.NaT,
                f"{prefix}_start_quote_age_seconds": np.nan,
                f"{prefix}_start_bid": np.nan,
                f"{prefix}_start_ask": np.nan,
                f"{prefix}_start_mid": np.nan,
                f"{prefix}_start_spread_bps": np.nan,
                f"{prefix}_end_quote_age_seconds": np.nan,
                f"{prefix}_gross_signed_log_return": np.nan,
                f"{prefix}_executable_long_log_return": np.nan,
                f"{prefix}_executable_short_log_return": np.nan,
                f"{prefix}_status": "missing_start",
            }
        )
        if start_quote is None:
            missing_start = True
            continue
        row.update(
            {
                f"{prefix}_start_quote_time": start_quote.name,
                f"{prefix}_start_quote_age_seconds": float(
                    (start_quote.name - start_boundary).total_seconds()
                ),
                f"{prefix}_start_bid": float(start_quote["bid"]),
                f"{prefix}_start_ask": float(start_quote["ask"]),
                f"{prefix}_start_mid": float(start_quote["_mid"]),
                f"{prefix}_start_spread_bps": float(
                    (float(start_quote["ask"]) - float(start_quote["bid"]))
                    / float(start_quote["_mid"])
                    * 10_000
                ),
                f"{prefix}_status": "missing_end",
            }
        )
        if end_quote is None:
            missing_end = True
            continue

        end_age = float((end_boundary - end_quote.name).total_seconds())
        start_mid = float(start_quote["_mid"])
        end_mid = float(end_quote["_mid"])
        gross = float(segment.sign * np.log(end_mid / start_mid))
        if segment.sign == 1:
            executable_long = float(np.log(float(end_quote["bid"]) / float(start_quote["ask"])))
            executable_short = float(np.log(float(start_quote["bid"]) / float(end_quote["ask"])))
        else:
            executable_long = float(np.log(float(start_quote["bid"]) / float(end_quote["ask"])))
            executable_short = float(np.log(float(end_quote["bid"]) / float(start_quote["ask"])))
        row.update(
            {
                f"{prefix}_end_quote_time": end_quote.name,
                f"{prefix}_end_quote_age_seconds": end_age,
                f"{prefix}_gross_signed_log_return": gross,
                f"{prefix}_executable_long_log_return": executable_long,
                f"{prefix}_executable_short_log_return": executable_short,
                f"{prefix}_status": "complete",
            }
        )
        gross_returns.append(gross)
        long_returns.append(executable_long)
        short_returns.append(executable_short)

    row["complete_segment_count"] = len(gross_returns)
    if len(gross_returns) == len(segments):
        row.update(
            {
                "gross_mid_log_return": float(sum(gross_returns)),
                "executable_long_log_return": float(sum(long_returns)),
                "executable_short_log_return": float(sum(short_returns)),
                "sample_status": "complete",
            }
        )
    elif missing_start:
        row["sample_status"] = "missing_segment_start"
    elif missing_end:
        row["sample_status"] = "missing_segment_end"
    return row


def _apply_fix_w_spread_filter(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply the frozen past-only q90 gate to every FIX-W segment entry."""

    result = frame.copy()
    result["event_day_ordinal"] = -1
    for name, _ in FIX_W_SEGMENT_SIGNS:
        result[f"{name}_spread_history_count"] = 0
        result[f"{name}_spread_q90_bps"] = np.nan
        result[f"{name}_spread_filter_pass"] = False
        result[f"{name}_spread_filter_status"] = "warmup"

    for _, indices in result.groupby("market_symbol", sort=False).groups.items():
        ordered = result.loc[list(indices)].sort_values("local_date")
        for ordinal, (index, row) in enumerate(ordered.iterrows()):
            result.at[index, "event_day_ordinal"] = ordinal
            for name, _ in FIX_W_SEGMENT_SIGNS:
                history = ordered.iloc[
                    max(0, ordinal - SPREAD_LOOKBACK_DAYS) : ordinal
                ]
                history_values = history[f"{name}_start_spread_bps"].dropna()
                count = int(len(history_values))
                result.at[index, f"{name}_spread_history_count"] = count
                if ordinal < SPREAD_WARMUP_DAYS:
                    continue
                status_column = f"{name}_spread_filter_status"
                if count < SPREAD_MIN_OBSERVATIONS:
                    result.at[index, status_column] = "insufficient_history"
                    continue
                threshold = float(history_values.quantile(SPREAD_QUANTILE))
                result.at[index, f"{name}_spread_q90_bps"] = threshold
                current = row[f"{name}_start_spread_bps"]
                if not np.isfinite(current):
                    result.at[index, status_column] = "missing_entry_spread"
                    continue
                passed = bool(float(current) <= threshold)
                result.at[index, f"{name}_spread_filter_pass"] = passed
                result.at[index, status_column] = "pass" if passed else "reject"

    segment_status_columns = [
        f"{name}_spread_filter_status" for name, _ in FIX_W_SEGMENT_SIGNS
    ]
    segment_pass_columns = [
        f"{name}_spread_filter_pass" for name, _ in FIX_W_SEGMENT_SIGNS
    ]
    result["spread_filter_pass"] = result[segment_pass_columns].all(axis=1)

    def combined_status(row: pd.Series) -> str:
        statuses = {str(row[column]) for column in segment_status_columns}
        if statuses == {"pass"}:
            return "pass"
        for priority in (
            "reject",
            "missing_entry_spread",
            "insufficient_history",
            "warmup",
        ):
            if priority in statuses:
                return priority
        raise RuntimeError(f"unexpected FIX-W spread statuses: {sorted(statuses)}")

    result["spread_filter_status"] = result.apply(combined_status, axis=1)
    result["spread_filter_rejected_segments"] = result.apply(
        lambda row: ",".join(
            name
            for name, _ in FIX_W_SEGMENT_SIGNS
            if row[f"{name}_spread_filter_status"] != "pass"
        ),
        axis=1,
    )
    for direction in ("long", "short"):
        source = f"executable_{direction}_log_return"
        result[f"filtered_{source}"] = result[source].where(
            result["spread_filter_pass"]
        )
    result["event_day_ordinal"] = result["event_day_ordinal"].astype(int)
    return result


def _aggregate_fix_w_date(
    legs: pd.DataFrame,
    local_date: date,
    calendar_fields: Mapping[str, object],
) -> dict[str, object]:
    expected_count = len(FIX_W_G9_LEGS)
    ready = legs[legs["complete_segment_count"] == len(FIX_W_SEGMENT_SIGNS)]
    missing = sorted(set(FIX_W_G9_LEGS) - set(ready["foreign_currency"]))
    row: dict[str, object] = {
        "family": "FIX-W",
        "event": "fix_w_g9_equal_weight",
        "local_date": local_date,
        **calendar_fields,
        "expected_leg_count": expected_count,
        "return_ready_leg_count": int(len(ready)),
        "missing_legs": ",".join(missing),
        "gross_mid_log_return": np.nan,
        "executable_long_log_return": np.nan,
        "executable_short_log_return": np.nan,
        "filtered_executable_long_log_return": np.nan,
        "filtered_executable_short_log_return": np.nan,
        "spread_filter_pass_leg_count": int(legs["spread_filter_pass"].sum()),
        "spread_filter_pass": False,
        "spread_filter_status": "incomplete_g9_cross_section",
        "sample_status": "incomplete_g9_cross_section",
        "research_only": True,
    }
    for name, _ in FIX_W_SEGMENT_SIGNS:
        row[f"{name}_gross_signed_log_return"] = np.nan
        row[f"{name}_executable_long_log_return"] = np.nan
        row[f"{name}_executable_short_log_return"] = np.nan
    if len(ready) != expected_count:
        return row

    row.update(
        {
            "gross_mid_log_return": float(ready["gross_mid_log_return"].mean()),
            "executable_long_log_return": float(
                ready["executable_long_log_return"].mean()
            ),
            "executable_short_log_return": float(
                ready["executable_short_log_return"].mean()
            ),
            "sample_status": "complete",
        }
    )
    spread_pass = bool(ready["spread_filter_pass"].all())
    spread_statuses = set(ready["spread_filter_status"].astype(str))
    if spread_pass:
        spread_status = "pass"
    else:
        spread_status = next(
            status
            for status in (
                "reject",
                "missing_entry_spread",
                "insufficient_history",
                "warmup",
            )
            if status in spread_statuses
        )
    row["spread_filter_pass"] = spread_pass
    row["spread_filter_status"] = spread_status
    if spread_pass:
        row["filtered_executable_long_log_return"] = float(
            ready["filtered_executable_long_log_return"].mean()
        )
        row["filtered_executable_short_log_return"] = float(
            ready["filtered_executable_short_log_return"].mean()
        )
    for name, _ in FIX_W_SEGMENT_SIGNS:
        for measure in (
            "gross_signed_log_return",
            "executable_long_log_return",
            "executable_short_log_return",
        ):
            column = f"{name}_{measure}"
            row[column] = float(ready[column].mean())
    return row


def _empty_fix_w_leg_table() -> pd.DataFrame:
    base = [
        "family",
        "event",
        "local_date",
        "foreign_currency",
        "market_symbol",
        "standardized_symbol",
        "quote_orientation",
        "tokyo_fix_time",
        "ecb_fix_time",
        "wmr_fix_time",
        "wmr_status",
        "calendar_knowledge_cutoff",
        "tzdb_identifier",
        "segment_count",
        "complete_segment_count",
        "gross_mid_log_return",
        "executable_long_log_return",
        "executable_short_log_return",
        "filtered_executable_long_log_return",
        "filtered_executable_short_log_return",
        "spread_filter_pass",
        "spread_filter_status",
        "spread_filter_rejected_segments",
        "event_day_ordinal",
        "sample_status",
        "research_only",
    ]
    segment_columns: list[str] = []
    for name, _ in FIX_W_SEGMENT_SIGNS:
        segment_columns.extend(
            [
                f"{name}_sign",
                f"{name}_start_time",
                f"{name}_end_time",
                f"{name}_start_quote_time",
                f"{name}_end_quote_time",
                f"{name}_start_quote_age_seconds",
                f"{name}_start_bid",
                f"{name}_start_ask",
                f"{name}_start_mid",
                f"{name}_start_spread_bps",
                f"{name}_end_quote_age_seconds",
                f"{name}_gross_signed_log_return",
                f"{name}_executable_long_log_return",
                f"{name}_executable_short_log_return",
                f"{name}_status",
                f"{name}_spread_history_count",
                f"{name}_spread_q90_bps",
                f"{name}_spread_filter_pass",
                f"{name}_spread_filter_status",
            ]
        )
    return pd.DataFrame(columns=[*base, *segment_columns])


def _empty_fix_w_composite_table() -> pd.DataFrame:
    columns = [
        "family",
        "event",
        "local_date",
        "tokyo_fix_time",
        "ecb_fix_time",
        "wmr_fix_time",
        "wmr_status",
        "calendar_knowledge_cutoff",
        "tzdb_identifier",
        "expected_leg_count",
        "return_ready_leg_count",
        "missing_legs",
        "gross_mid_log_return",
        "executable_long_log_return",
        "executable_short_log_return",
        "filtered_executable_long_log_return",
        "filtered_executable_short_log_return",
        "spread_filter_pass_leg_count",
        "spread_filter_pass",
        "spread_filter_status",
        "sample_status",
        "research_only",
    ]
    for name, _ in FIX_W_SEGMENT_SIGNS:
        columns.extend(
            [
                f"{name}_gross_signed_log_return",
                f"{name}_executable_long_log_return",
                f"{name}_executable_short_log_return",
            ]
        )
    return pd.DataFrame(columns=columns)


def build_local_session_experiments(
    quotes: Mapping[str, pd.DataFrame],
    local_dates: Iterable[date | datetime | str],
    *,
    sessions: Sequence[str] = LOCAL_SESSIONS,
) -> pd.DataFrame:
    """Build generic exploratory LOCAL session observations.

    This broad symbol-by-session Cartesian product is not the paper's fixed
    12-unit panel.  Formal Breedon--Ranaldo replication uses
    :func:`build_local_paper_panel`.
    """

    return _construct_experiments(quotes, _local_specifications(tuple(local_dates), sessions))


def build_local_paper_panel(
    quotes: Mapping[str, pd.DataFrame],
    local_dates: Iterable[date | datetime | str],
) -> pd.DataFrame:
    """Build the frozen 12-unit Breedon--Ranaldo LOCAL replication panel.

    The paper reports pair-session units rather than a combined portfolio.  All
    supplied natural dates remain visible and holidays are not filtered.  Its
    UTC working-week rule excludes Saturday 00:00--Sunday 00:00 for ordinary
    crosses, but the JPY/AUD crosses reopen at Saturday 18:00.  A unit is
    complete only when both boundaries are inside that pair's working week and
    have a prevailing quote no more than five seconds old.  The primary return
    crosses the executable bid/ask; signed midquote return is secondary.

    For the Europe legs that overlap New York, the exit is New York's 08:00
    local open (the paper's open-to-open rule), not Europe's 15:00 close.
    ``Europe/London`` implements the paper's Dublin-equivalent civil clock.
    """

    parsed_dates = tuple(session_window("new_york", value).local_date for value in local_dates)
    if len(parsed_dates) != len(set(parsed_dates)):
        raise ValueError("LOCAL paper local_dates must be unique")
    if not parsed_dates:
        return _empty_local_paper_panel()

    required_symbols = {unit.symbol for unit in LOCAL_PAPER_UNITS}
    missing = sorted(required_symbols - set(quotes))
    if missing:
        raise ValueError(
            "LOCAL paper panel requires the complete frozen six-pair universe; "
            f"missing {missing}"
        )
    normalized = {
        symbol: _normalize_quotes(quotes[symbol], symbol=symbol)
        for symbol in sorted(required_symbols)
    }
    rows = [
        _build_local_paper_row(unit, local_date, normalized[unit.symbol])
        for local_date in parsed_dates
        for unit in LOCAL_PAPER_UNITS
    ]
    return pd.DataFrame(rows).sort_values(
        ["local_date", "paper_unit_ordinal"], ignore_index=True
    )


def build_local_portfolio_extension(panel: pd.DataFrame) -> pd.DataFrame:
    """Combine a complete LOCAL paper panel into the frozen project extension.

    This is explicitly not a portfolio from the paper.  Each pair owns one
    fixed one-sixth capital sleeve, compounds its two directed session returns,
    and otherwise holds cash.  A date with any missing unit has no portfolio
    return; remaining sleeves are never renormalized.
    """

    required_columns = {
        "local_date",
        "paper_unit_id",
        "symbol",
        "sample_status",
        "gross_signed_mid_log_return",
        "executable_log_return",
    }
    missing_columns = required_columns - set(panel)
    if missing_columns:
        raise ValueError(
            f"LOCAL paper panel is missing columns {sorted(missing_columns)}"
        )
    if panel.empty:
        return _empty_local_portfolio_extension()

    expected_ids = tuple(unit.unit_id for unit in LOCAL_PAPER_UNITS)
    expected_id_set = set(expected_ids)
    expected_pairs = tuple(sorted({unit.symbol for unit in LOCAL_PAPER_UNITS}))
    if panel.duplicated(["local_date", "paper_unit_id"]).any():
        raise ValueError("LOCAL paper panel contains duplicate date/unit rows")

    rows: list[dict[str, object]] = []
    for local_date, group in panel.groupby("local_date", sort=True, dropna=False):
        ids = set(group["paper_unit_id"].astype(str))
        if ids != expected_id_set or len(group) != len(expected_ids):
            raise ValueError(
                f"LOCAL paper panel date {local_date!r} does not contain exactly "
                "the frozen 12 units"
            )
        ordered = group.set_index("paper_unit_id").loc[list(expected_ids)]
        for unit in LOCAL_PAPER_UNITS:
            if str(ordered.at[unit.unit_id, "symbol"]) != unit.symbol:
                raise ValueError(
                    f"LOCAL paper unit {unit.unit_id!r} has the wrong symbol"
                )

        complete = ordered["sample_status"].eq("complete")
        missing_units = tuple(ordered.index[~complete].astype(str))
        row: dict[str, object] = {
            "family": "LOCAL-PORTFOLIO",
            "local_date": local_date,
            "expected_unit_count": len(expected_ids),
            "complete_unit_count": int(complete.sum()),
            "missing_units": ",".join(missing_units),
            "expected_sleeve_count": len(expected_pairs),
            "pair_sleeve_weight": 1.0 / len(expected_pairs),
            "maximum_gross_notional": 1.0,
            "missing_unit_renormalized": False,
            "gross_mid_simple_return": np.nan,
            "gross_mid_log_return": np.nan,
            "executable_simple_return": np.nan,
            "executable_log_return": np.nan,
            "sample_status": "incomplete_12_unit_panel",
            "paper_replication": False,
            "research_only": True,
        }
        for symbol in expected_pairs:
            row[f"{symbol.lower()}_gross_mid_simple_return"] = np.nan
            row[f"{symbol.lower()}_executable_simple_return"] = np.nan

        if complete.all():
            gross = pd.to_numeric(
                ordered["gross_signed_mid_log_return"], errors="coerce"
            )
            executable = pd.to_numeric(
                ordered["executable_log_return"], errors="coerce"
            )
            if not np.isfinite(gross).all() or not np.isfinite(executable).all():
                raise ValueError("complete LOCAL paper rows must contain finite returns")
            pair_gross: list[float] = []
            pair_executable: list[float] = []
            for symbol in expected_pairs:
                symbol_rows = ordered.loc[ordered["symbol"].eq(symbol)]
                if len(symbol_rows) != 2:
                    raise ValueError(
                        f"LOCAL paper pair {symbol} must contain exactly two units"
                    )
                gross_simple = float(
                    np.expm1(symbol_rows["gross_signed_mid_log_return"].sum())
                )
                executable_simple = float(
                    np.expm1(symbol_rows["executable_log_return"].sum())
                )
                pair_gross.append(gross_simple)
                pair_executable.append(executable_simple)
                row[f"{symbol.lower()}_gross_mid_simple_return"] = gross_simple
                row[f"{symbol.lower()}_executable_simple_return"] = executable_simple

            gross_simple = float(np.mean(pair_gross))
            executable_simple = float(np.mean(pair_executable))
            if gross_simple <= -1 or executable_simple <= -1:
                raise ValueError("LOCAL portfolio sleeve return would make NAV non-positive")
            row.update(
                {
                    "gross_mid_simple_return": gross_simple,
                    "gross_mid_log_return": float(np.log1p(gross_simple)),
                    "executable_simple_return": executable_simple,
                    "executable_log_return": float(np.log1p(executable_simple)),
                    "sample_status": "complete",
                }
            )
        rows.append(row)
    return pd.DataFrame(rows).sort_values("local_date", ignore_index=True)


def build_asia_london_experiments(
    quotes: Mapping[str, pd.DataFrame],
    local_dates: Iterable[date | datetime | str],
) -> pd.DataFrame:
    """Build ASIA-LDN formation-signal and London-response observations.

    The Asia formation return uses only quotes in ``[08:00, 15:00)`` Tokyo
    time.  The response entry occurs strictly after 07:00 London time and the
    scheduled exit is 10:00 London time.  On dates where the two endpoints
    touch in UTC, the half-open signal window still prevents leakage.
    """

    return _construct_experiments(quotes, _asia_london_specifications(tuple(local_dates)))


def _asia_london_specifications(
    local_dates: Sequence[date | datetime | str],
) -> list[_ExperimentWindow]:
    specifications: list[_ExperimentWindow] = []
    for local_date in local_dates:
        formation = session_window("asia_formation", local_date)
        response = session_window("london_response", local_date)
        if formation.end_utc > response.start_utc:
            raise ValueError(
                "asia formation must finish no later than the London response decision"
            )
        specifications.append(
            _ExperimentWindow(
                family="ASIA-LDN",
                event="asia_formation_london_response",
                local_date=response.local_date,
                timezone=response.timezone,
                decision_time=response.start_utc,
                scheduled_exit_time=response.end_utc,
                tzdb_identifier=response.tzdb.identifier,
                signal_start_time=formation.start_utc,
                signal_end_time=formation.end_utc,
            )
        )
    return specifications


def build_intraday_experiment_table(
    quotes: Mapping[str, pd.DataFrame],
    local_dates: Iterable[date | datetime | str],
    *,
    publication_calendar: PublicationCalendar | None = None,
) -> pd.DataFrame:
    """Build fix-window primitives plus frozen LOCAL and ASIA-LDN rows.

    A supplied publication calendar governs only the named fix events.  The
    generic LOCAL rows returned here remain exploratory.  The formal
    Breedon--Ranaldo panel is built separately because its primary specification
    includes holidays when boundary quotes exist and uses pair-specific
    open-to-open endpoints.
    """

    dates = tuple(local_dates)
    specifications = [
        *(
            _fix_specifications(dates, FIX_EVENTS)
            if publication_calendar is None
            else _published_fix_specifications(dates, FIX_EVENTS, publication_calendar)
        ),
        *_local_specifications(dates, LOCAL_SESSIONS),
        *_asia_london_specifications(dates),
    ]
    # Normalize a potentially large tick history once, rather than once per family.
    return _construct_experiments(quotes, specifications)


def _fix_specifications(
    local_dates: Sequence[date | datetime | str], events: Sequence[str]
) -> list[_ExperimentWindow]:
    return [
        _fix_specification(event_window(event, local_date))
        for local_date in local_dates
        for event in events
    ]


def _published_fix_specifications(
    local_dates: Sequence[date | datetime | str],
    events: Sequence[str],
    publication_calendar: PublicationCalendar,
) -> list[_ExperimentWindow]:
    if not isinstance(publication_calendar, PublicationCalendar):
        raise TypeError("publication_calendar must be a PublicationCalendar")
    if not publication_calendar.formal_experiment:
        raise PublicationCalendarError(
            "formal fix experiments require a verified formal publication calendar"
        )
    if not publication_calendar.manifest_verified:
        raise PublicationCalendarError(
            "formal fix experiments require a hash-verified calendar source manifest"
        )
    specifications: list[_ExperimentWindow] = []
    for local_date_value in local_dates:
        for name in events:
            # Validate the named event even when the calendar happens not to
            # contain it, preserving the public API's useful unknown-name error.
            local_date = event_window(name, local_date_value).local_date
            published = publication_calendar.event_on(name, local_date)
            if not published.was_published:
                continue
            if published.quality != "verified" or published.event_time_utc is None:
                raise PublicationCalendarError(
                    f"formal fix experiment lacks a verified timestamp for {name!r} "
                    f"on {local_date.isoformat()}"
                )
            center = published.event_time_utc
            specifications.append(
                _ExperimentWindow(
                    family="FIX-WINDOW",
                    event=name,
                    local_date=local_date,
                    timezone=published.timezone,
                    decision_time=center - EVENT_WINDOW_HALF_WIDTH,
                    scheduled_exit_time=center + EVENT_WINDOW_HALF_WIDTH,
                    tzdb_identifier=tzdb_info().identifier,
                )
            )
    return specifications


def _local_specifications(
    local_dates: Sequence[date | datetime | str], sessions: Sequence[str]
) -> list[_ExperimentWindow]:
    return [
        _local_specification(session_window(name, local_date))
        for local_date in local_dates
        for name in sessions
    ]


def _fix_specification(window: EventWindow) -> _ExperimentWindow:
    return _ExperimentWindow(
        family="FIX-WINDOW",
        event=window.name,
        local_date=window.local_date,
        timezone=window.timezone,
        decision_time=window.start_utc,
        scheduled_exit_time=window.end_utc,
        tzdb_identifier=window.tzdb.identifier,
    )


def _local_specification(window: SessionWindow) -> _ExperimentWindow:
    return _ExperimentWindow(
        family="LOCAL",
        event=f"local_{window.name}",
        local_date=window.local_date,
        timezone=window.timezone,
        decision_time=window.start_utc,
        scheduled_exit_time=window.end_utc,
        tzdb_identifier=window.tzdb.identifier,
    )


def _build_local_paper_row(
    unit: LocalPaperUnit,
    local_date: date,
    quotes: pd.DataFrame,
) -> dict[str, object]:
    window = session_window(unit.session, local_date)
    start_time = pd.Timestamp(window.start_utc)
    end_time = pd.Timestamp(window.end_utc)
    endpoint_rule = "open_to_close"
    if unit.overlap_close_session is not None:
        counterpart = session_window(unit.overlap_close_session, local_date)
        counterpart_open = pd.Timestamp(counterpart.start_utc)
        if not start_time < counterpart_open < end_time:
            raise ValueError(
                f"LOCAL paper overlap rule is invalid for {unit.unit_id} on {local_date}"
            )
        end_time = counterpart_open
        endpoint_rule = "open_to_counterpart_open"

    entry_in_working_week = _local_paper_boundary_in_working_week(
        unit.symbol, start_time
    )
    exit_in_working_week = _local_paper_boundary_in_working_week(unit.symbol, end_time)
    entry = (
        _last_prevailing_quote(
            quotes,
            boundary=start_time,
            maximum_age=LOCAL_PAPER_BOUNDARY_MAX_QUOTE_AGE,
        )
        if entry_in_working_week
        else None
    )
    exit_quote = (
        _last_prevailing_quote(
            quotes,
            boundary=end_time,
            maximum_age=LOCAL_PAPER_BOUNDARY_MAX_QUOTE_AGE,
        )
        if exit_in_working_week
        else None
    )
    if entry is not None and exit_quote is not None:
        sample_status = "complete"
    elif not entry_in_working_week and not exit_in_working_week:
        sample_status = "paper_weekend_excluded"
    elif not entry_in_working_week:
        sample_status = "paper_weekend_excluded_entry"
    elif not exit_in_working_week:
        sample_status = "paper_weekend_excluded_exit"
    elif entry is None and exit_quote is None:
        sample_status = "missing_both_boundaries"
    elif entry is None:
        sample_status = "missing_entry"
    else:
        sample_status = "missing_exit"
    session_label = "europe" if unit.session == "london" else unit.session
    row: dict[str, object] = {
        "family": "LOCAL-PAPER",
        "paper_unit_id": unit.unit_id,
        "paper_unit_ordinal": LOCAL_PAPER_UNITS.index(unit),
        "symbol": unit.symbol,
        "paper_session": session_label,
        "iana_timezone": window.timezone,
        "local_date": local_date,
        "direction": unit.direction,
        "direction_label": "long_base" if unit.direction == 1 else "short_base",
        "direction_source": "paper_stated_base_counter_rule",
        "eurjpy_table_sign_canary": unit.symbol == "EURJPY",
        "eurjpy_reciprocal_executable_log_return": np.nan,
        "eurjpy_reciprocal_invariance_error": np.nan,
        "endpoint_rule": endpoint_rule,
        "scheduled_entry_time": start_time,
        "scheduled_exit_time": end_time,
        "entry_in_paper_working_week": entry_in_working_week,
        "exit_in_paper_working_week": exit_in_working_week,
        "boundary_max_quote_age_seconds": (
            LOCAL_PAPER_BOUNDARY_MAX_QUOTE_AGE.total_seconds()
        ),
        "entry_time": pd.NaT,
        "entry_quote_age_seconds": np.nan,
        "entry_bid": np.nan,
        "entry_ask": np.nan,
        "entry_mid": np.nan,
        "exit_time": pd.NaT,
        "exit_quote_age_seconds": np.nan,
        "exit_bid": np.nan,
        "exit_ask": np.nan,
        "exit_mid": np.nan,
        "raw_mid_log_return": np.nan,
        "gross_signed_mid_log_return": np.nan,
        "executable_long_log_return": np.nan,
        "executable_short_log_return": np.nan,
        "executable_log_return": np.nan,
        "entry_status": (
            "missing_prevailing_quote_within_5s"
            if entry_in_working_week
            else "paper_weekend_excluded"
        ),
        "exit_status": (
            "missing_prevailing_quote_within_5s"
            if exit_in_working_week
            else "paper_weekend_excluded"
        ),
        "sample_status": sample_status,
        "holiday_filter_applied": False,
        "weekend_filter_applied": not (
            entry_in_working_week and exit_in_working_week
        ),
        "paper_replication": True,
        "research_only": True,
        "tzdb_identifier": window.tzdb.identifier,
    }
    if entry is not None:
        row.update(
            {
                "entry_time": entry.name,
                "entry_quote_age_seconds": float((start_time - entry.name).total_seconds()),
                "entry_bid": float(entry["bid"]),
                "entry_ask": float(entry["ask"]),
                "entry_mid": float(entry["_mid"]),
                "entry_status": "complete",
            }
        )
    if exit_quote is not None:
        row.update(
            {
                "exit_time": exit_quote.name,
                "exit_quote_age_seconds": float(
                    (end_time - exit_quote.name).total_seconds()
                ),
                "exit_bid": float(exit_quote["bid"]),
                "exit_ask": float(exit_quote["ask"]),
                "exit_mid": float(exit_quote["_mid"]),
                "exit_status": "complete",
            }
        )
    if entry is not None and exit_quote is not None:
        raw_mid = float(np.log(float(exit_quote["_mid"]) / float(entry["_mid"])))
        executable_long = float(
            np.log(float(exit_quote["bid"]) / float(entry["ask"]))
        )
        executable_short = float(
            np.log(float(entry["bid"]) / float(exit_quote["ask"]))
        )
        executable = executable_long if unit.direction == 1 else executable_short
        row.update(
            {
                "raw_mid_log_return": raw_mid,
                "gross_signed_mid_log_return": unit.direction * raw_mid,
                "executable_long_log_return": executable_long,
                "executable_short_log_return": executable_short,
                "executable_log_return": executable,
            }
        )
        if unit.symbol == "EURJPY":
            reciprocal_entry_bid = 1.0 / float(entry["ask"])
            reciprocal_entry_ask = 1.0 / float(entry["bid"])
            reciprocal_exit_bid = 1.0 / float(exit_quote["ask"])
            reciprocal_exit_ask = 1.0 / float(exit_quote["bid"])
            reciprocal_direction = -unit.direction
            reciprocal_executable = (
                float(np.log(reciprocal_exit_bid / reciprocal_entry_ask))
                if reciprocal_direction == 1
                else float(np.log(reciprocal_entry_bid / reciprocal_exit_ask))
            )
            row.update(
                {
                    "eurjpy_reciprocal_executable_log_return": reciprocal_executable,
                    "eurjpy_reciprocal_invariance_error": (
                        reciprocal_executable - executable
                    ),
                }
            )
    return row


def _local_paper_boundary_in_working_week(
    symbol: str, boundary: pd.Timestamp
) -> bool:
    """Apply the paper's pair-specific UTC weekend exclusion to one boundary."""

    utc_boundary = boundary.tz_convert("UTC")
    if utc_boundary.dayofweek != 5:
        return True
    if symbol in LOCAL_PAPER_EXTENDED_WEEK_SYMBOLS:
        return utc_boundary.time() >= time(18, 0)
    return False


def _last_prevailing_quote(
    quotes: pd.DataFrame,
    *,
    boundary: pd.Timestamp,
    maximum_age: timedelta,
) -> pd.Series | None:
    """Return the last valid quote at or before a boundary within ``maximum_age``."""

    earliest = boundary - maximum_age
    start = int(quotes.index.searchsorted(earliest, side="left"))
    stop = int(quotes.index.searchsorted(boundary, side="right"))
    valid = quotes["_valid_quote"].to_numpy(dtype=bool, copy=False)
    for position in range(stop - 1, start - 1, -1):
        if valid[position]:
            return quotes.iloc[position]
    return None


def _construct_experiments(
    quotes: Mapping[str, pd.DataFrame],
    specifications: Sequence[_ExperimentWindow],
) -> pd.DataFrame:
    if not quotes or not specifications:
        return _empty_experiment_table()
    identities = [(item.family, item.event, item.decision_time) for item in specifications]
    if len(identities) != len(set(identities)):
        raise ValueError("experiment local_dates and event definitions must be unique")
    normalized = {
        str(symbol): _normalize_quotes(frame, symbol=str(symbol))
        for symbol, frame in sorted(quotes.items())
    }
    rows: list[dict[str, object]] = []
    for specification in specifications:
        for symbol, frame in normalized.items():
            rows.append(_build_row(symbol, frame, specification))
    result = pd.DataFrame(rows)
    result = _apply_frozen_spread_filter(result)
    return result.sort_values(["decision_time", "symbol", "family", "event"], ignore_index=True)


def _normalize_quotes(frame: pd.DataFrame, *, symbol: str) -> pd.DataFrame:
    missing = {"bid", "ask"} - set(frame.columns)
    if missing:
        raise ValueError(f"{symbol}: quote frame is missing columns {sorted(missing)}")
    result = frame.copy()
    if "timestamp" in result.columns:
        raw_index = pd.DatetimeIndex(pd.to_datetime(result.pop("timestamp")))
    else:
        raw_index = pd.DatetimeIndex(pd.to_datetime(result.index))
    if raw_index.tz is None:
        raise ValueError(f"{symbol}: quote timestamps must be timezone-aware UTC")
    if any(offset != timedelta(0) for offset in raw_index.map(lambda value: value.utcoffset())):
        raise ValueError(f"{symbol}: quote timestamps must be expressed in UTC")
    result.index = raw_index.tz_convert("UTC")
    result.index.name = "timestamp"
    if result.index.has_duplicates:
        raise ValueError(f"{symbol}: quote timestamps must be unique")
    result = result.sort_index()
    result["bid"] = pd.to_numeric(result["bid"], errors="coerce")
    result["ask"] = pd.to_numeric(result["ask"], errors="coerce")
    finite = np.isfinite(result["bid"]) & np.isfinite(result["ask"])
    invalid = finite & (
        (result["bid"] <= 0) | (result["ask"] <= 0) | (result["ask"] < result["bid"])
    )
    if invalid.any():
        timestamp = result.index[int(np.flatnonzero(invalid.to_numpy())[0])]
        raise ValueError(f"{symbol}: invalid or crossed quote at {timestamp.isoformat()}")
    result["_valid_quote"] = finite
    result["_mid"] = (result["bid"] + result["ask"]) / 2
    return result


def _build_row(
    symbol: str,
    quotes: pd.DataFrame,
    specification: _ExperimentWindow,
) -> dict[str, object]:
    decision = pd.Timestamp(specification.decision_time)
    scheduled_exit = pd.Timestamp(specification.scheduled_exit_time)
    entry = _first_valid_quote(
        quotes,
        after=decision,
        strictly_after=True,
        no_later_than=decision + ENTRY_MAX_QUOTE_AGE,
    )
    exit_quote = _first_valid_quote(quotes, after=scheduled_exit)

    signal_first: pd.Series | None = None
    signal_last: pd.Series | None = None
    if specification.signal_start_time is not None:
        signal_start = pd.Timestamp(specification.signal_start_time)
        signal_end = pd.Timestamp(specification.signal_end_time)
        signal_first = _first_valid_quote(
            quotes,
            after=signal_start,
            no_later_than=min(signal_start + FORMATION_MAX_QUOTE_AGE, signal_end),
            upper_bound_is_exclusive=signal_start + FORMATION_MAX_QUOTE_AGE >= signal_end,
        )
        signal_last = _last_valid_quote(
            quotes,
            before=signal_end,
            no_earlier_than=max(signal_start, signal_end - FORMATION_MAX_QUOTE_AGE),
        )

    row: dict[str, object] = {
        "family": specification.family,
        "event": specification.event,
        "symbol": symbol,
        "local_date": specification.local_date,
        "timezone": specification.timezone,
        "tzdb_identifier": specification.tzdb_identifier,
        "signal_start_time": _as_utc_timestamp(specification.signal_start_time),
        "signal_end_time": _as_utc_timestamp(specification.signal_end_time),
        "decision_time": decision,
        "scheduled_exit_time": scheduled_exit,
        "decision_local_15m_slot": _local_fifteen_minute_slot(
            specification.decision_time, specification.timezone
        ),
        "entry_time": pd.NaT,
        "entry_quote_age_seconds": np.nan,
        "entry_bid": np.nan,
        "entry_ask": np.nan,
        "entry_mid": np.nan,
        "entry_spread": np.nan,
        "entry_spread_bps": np.nan,
        "exit_time": pd.NaT,
        "exit_delay_seconds": np.nan,
        "exit_bid": np.nan,
        "exit_ask": np.nan,
        "exit_mid": np.nan,
        "signal_first_quote_time": pd.NaT,
        "signal_last_quote_time": pd.NaT,
        "signal_start_quote_age_seconds": np.nan,
        "signal_end_quote_age_seconds": np.nan,
        "signal_mid_log_return": np.nan,
        "gross_mid_log_return": np.nan,
        "executable_long_log_return": np.nan,
        "executable_short_log_return": np.nan,
        "entry_status": "missing_quote_within_5s",
        "exit_status": "missing",
        "signal_status": "not_applicable",
        "sample_status": "missing_entry",
        "research_only": True,
    }

    if (
        signal_first is not None
        and signal_last is not None
        and signal_first.name < signal_last.name
    ):
        first_mid = float(signal_first["_mid"])
        last_mid = float(signal_last["_mid"])
        row.update(
            {
                "signal_first_quote_time": signal_first.name,
                "signal_last_quote_time": signal_last.name,
                "signal_start_quote_age_seconds": float(
                    (
                        signal_first.name
                        - pd.Timestamp(specification.signal_start_time)
                    ).total_seconds()
                ),
                "signal_end_quote_age_seconds": float(
                    (
                        pd.Timestamp(specification.signal_end_time)
                        - signal_last.name
                    ).total_seconds()
                ),
                "signal_mid_log_return": float(np.log(last_mid / first_mid)),
                "signal_status": "complete",
            }
        )
    elif specification.signal_start_time is not None:
        row["signal_status"] = "missing_boundary_quote_within_5s"

    if entry is not None:
        entry_mid = float(entry["_mid"])
        entry_spread = float(entry["ask"] - entry["bid"])
        row.update(
            {
                "entry_time": entry.name,
                "entry_quote_age_seconds": float((entry.name - decision).total_seconds()),
                "entry_bid": float(entry["bid"]),
                "entry_ask": float(entry["ask"]),
                "entry_mid": entry_mid,
                "entry_spread": entry_spread,
                "entry_spread_bps": entry_spread / entry_mid * 10_000,
                "entry_status": "complete",
            }
        )

    if exit_quote is not None:
        delay = float((exit_quote.name - scheduled_exit).total_seconds())
        row.update(
            {
                "exit_time": exit_quote.name,
                "exit_delay_seconds": delay,
                "exit_bid": float(exit_quote["bid"]),
                "exit_ask": float(exit_quote["ask"]),
                "exit_mid": float(exit_quote["_mid"]),
                "exit_status": "on_time" if delay == 0 else "delayed",
            }
        )

    signal_complete = row["signal_status"] in {"complete", "not_applicable"}
    if entry is not None and exit_quote is not None:
        row.update(
            {
                "gross_mid_log_return": float(
                    np.log(float(exit_quote["_mid"]) / float(entry["_mid"]))
                ),
                "executable_long_log_return": float(
                    np.log(float(exit_quote["bid"]) / float(entry["ask"]))
                ),
                "executable_short_log_return": float(
                    np.log(float(entry["bid"]) / float(exit_quote["ask"]))
                ),
                "sample_status": (
                    "missing_signal"
                    if not signal_complete
                    else ("complete" if row["exit_status"] == "on_time" else "delayed_exit")
                ),
            }
        )
    elif entry is not None:
        row["sample_status"] = "missing_signal" if not signal_complete else "missing_exit"
    return row


def _first_valid_quote(
    quotes: pd.DataFrame,
    *,
    after: pd.Timestamp,
    strictly_after: bool = False,
    no_later_than: pd.Timestamp | None = None,
    upper_bound_is_exclusive: bool = False,
) -> pd.Series | None:
    start_side = "right" if strictly_after else "left"
    start = int(quotes.index.searchsorted(after, side=start_side))
    stop = len(quotes)
    if no_later_than is not None:
        stop_side = "left" if upper_bound_is_exclusive else "right"
        stop = int(quotes.index.searchsorted(no_later_than, side=stop_side))
    valid = quotes["_valid_quote"].to_numpy(dtype=bool, copy=False)
    for position in range(start, stop):
        if valid[position]:
            return quotes.iloc[position]
    return None


def _last_valid_quote(
    quotes: pd.DataFrame,
    *,
    before: pd.Timestamp,
    no_earlier_than: pd.Timestamp,
) -> pd.Series | None:
    start = int(quotes.index.searchsorted(no_earlier_than, side="left"))
    stop = int(quotes.index.searchsorted(before, side="left"))
    valid = quotes["_valid_quote"].to_numpy(dtype=bool, copy=False)
    for position in range(stop - 1, start - 1, -1):
        if valid[position]:
            return quotes.iloc[position]
    return None


def _apply_frozen_spread_filter(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply the preregistered past-only 60-day, q90 spread filter.

    ``local_dates`` supplied by the caller define the eligible event-day
    sequence.  The first 60 scheduled days are always warm-up.  Thereafter the
    threshold uses valid entry spreads from the preceding 60 scheduled days
    only and requires at least 40 observations.
    """

    result = frame.copy()
    result["spread_history_count"] = 0
    result["spread_q90_bps"] = np.nan
    result["spread_filter_pass"] = False
    result["spread_filter_status"] = "warmup"
    result["event_day_ordinal"] = -1
    keys = ["symbol", "event", "decision_local_15m_slot"]
    for _, indices in result.groupby(keys, sort=False).groups.items():
        ordered = result.loc[list(indices)].sort_values(["decision_time", "local_date"])
        for ordinal, (index, row) in enumerate(ordered.iterrows()):
            result.at[index, "event_day_ordinal"] = ordinal
            history = ordered.iloc[max(0, ordinal - SPREAD_LOOKBACK_DAYS) : ordinal]
            history_values = history["entry_spread_bps"].dropna()
            count = int(len(history_values))
            result.at[index, "spread_history_count"] = count
            if ordinal < SPREAD_WARMUP_DAYS:
                continue
            if count < SPREAD_MIN_OBSERVATIONS:
                result.at[index, "spread_filter_status"] = "insufficient_history"
                continue
            threshold = float(history_values.quantile(SPREAD_QUANTILE))
            result.at[index, "spread_q90_bps"] = threshold
            current = row["entry_spread_bps"]
            if not np.isfinite(current):
                result.at[index, "spread_filter_status"] = "missing_entry_spread"
                continue
            passed = bool(float(current) <= threshold)
            result.at[index, "spread_filter_pass"] = passed
            result.at[index, "spread_filter_status"] = "pass" if passed else "reject"
    result["event_day_ordinal"] = result["event_day_ordinal"].astype(int)
    return result


def _local_fifteen_minute_slot(value: datetime, timezone: str) -> str:
    local = value.astimezone(ZoneInfo(timezone))
    minute = local.minute - local.minute % 15
    return f"{local.hour:02d}:{minute:02d}"


def _as_utc_timestamp(value: datetime | None) -> pd.Timestamp | pd.NaT:
    return pd.NaT if value is None else pd.Timestamp(value)


def _empty_local_paper_panel() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "family",
            "paper_unit_id",
            "paper_unit_ordinal",
            "symbol",
            "paper_session",
            "iana_timezone",
            "local_date",
            "direction",
            "direction_label",
            "direction_source",
            "eurjpy_table_sign_canary",
            "eurjpy_reciprocal_executable_log_return",
            "eurjpy_reciprocal_invariance_error",
            "endpoint_rule",
            "scheduled_entry_time",
            "scheduled_exit_time",
            "entry_in_paper_working_week",
            "exit_in_paper_working_week",
            "boundary_max_quote_age_seconds",
            "entry_time",
            "entry_quote_age_seconds",
            "entry_bid",
            "entry_ask",
            "entry_mid",
            "exit_time",
            "exit_quote_age_seconds",
            "exit_bid",
            "exit_ask",
            "exit_mid",
            "raw_mid_log_return",
            "gross_signed_mid_log_return",
            "executable_long_log_return",
            "executable_short_log_return",
            "executable_log_return",
            "entry_status",
            "exit_status",
            "sample_status",
            "holiday_filter_applied",
            "weekend_filter_applied",
            "paper_replication",
            "research_only",
            "tzdb_identifier",
        ]
    )


def _empty_local_portfolio_extension() -> pd.DataFrame:
    pairs = sorted({unit.symbol for unit in LOCAL_PAPER_UNITS})
    pair_columns = [
        f"{symbol.lower()}_{kind}_simple_return"
        for symbol in pairs
        for kind in ("gross_mid", "executable")
    ]
    return pd.DataFrame(
        columns=[
            "family",
            "local_date",
            "expected_unit_count",
            "complete_unit_count",
            "missing_units",
            "expected_sleeve_count",
            "pair_sleeve_weight",
            "maximum_gross_notional",
            "missing_unit_renormalized",
            "gross_mid_simple_return",
            "gross_mid_log_return",
            "executable_simple_return",
            "executable_log_return",
            "sample_status",
            "paper_replication",
            "research_only",
            *pair_columns,
        ]
    )


def _empty_experiment_table() -> pd.DataFrame:
    columns = [
        "family",
        "event",
        "symbol",
        "local_date",
        "timezone",
        "tzdb_identifier",
        "signal_start_time",
        "signal_end_time",
        "decision_time",
        "scheduled_exit_time",
        "decision_local_15m_slot",
        "entry_time",
        "entry_quote_age_seconds",
        "entry_bid",
        "entry_ask",
        "entry_mid",
        "entry_spread",
        "entry_spread_bps",
        "exit_time",
        "exit_delay_seconds",
        "exit_bid",
        "exit_ask",
        "exit_mid",
        "signal_first_quote_time",
        "signal_last_quote_time",
        "signal_start_quote_age_seconds",
        "signal_end_quote_age_seconds",
        "signal_mid_log_return",
        "gross_mid_log_return",
        "executable_long_log_return",
        "executable_short_log_return",
        "entry_status",
        "exit_status",
        "signal_status",
        "sample_status",
        "research_only",
        "spread_history_count",
        "spread_q90_bps",
        "spread_filter_pass",
        "spread_filter_status",
        "event_day_ordinal",
    ]
    return pd.DataFrame(columns=columns)


__all__ = [
    "ENTRY_MAX_QUOTE_AGE",
    "FIX_EVENTS",
    "FIX_W_BOUNDARY_MAX_QUOTE_AGE",
    "FIX_W_G9_LEGS",
    "FixWSegment",
    "FORMATION_MAX_QUOTE_AGE",
    "LOCAL_PAPER_BOUNDARY_MAX_QUOTE_AGE",
    "LOCAL_PAPER_EXTENDED_WEEK_SYMBOLS",
    "LOCAL_PAPER_UNITS",
    "LOCAL_SESSIONS",
    "LocalPaperUnit",
    "SPREAD_LOOKBACK_DAYS",
    "SPREAD_MIN_OBSERVATIONS",
    "SPREAD_QUANTILE",
    "SPREAD_WARMUP_DAYS",
    "build_asia_london_experiments",
    "build_fix_window_experiments",
    "build_fix_w_composite_experiments",
    "build_fix_w_leg_experiments",
    "build_intraday_experiment_table",
    "build_local_paper_panel",
    "build_local_portfolio_extension",
    "build_local_session_experiments",
    "build_wmr_month_end_experiments",
    "fix_w_segment_plan",
]
