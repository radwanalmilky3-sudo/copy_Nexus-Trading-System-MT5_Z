"""Formal New York-close daily bars from transferred Dukascopy SQLite files.

The standalone downloader stores the original compressed ``bi5`` payload for
each UTC hour.  This module is the read-only bridge from those transferred
databases to the daily bid/ask frames consumed by long-horizon research and to
the exact common-session quote matrices consumed by the portfolio ledger.

No missing hour or quote is filled.  A daily bar is emitted only when every
expected source hour contains a validated payload and the complete session
contains at least one quote.  An explicit ``no_data`` row proves transfer
completeness but cannot prove the missing hour's high, low, or volume, so that
session is also suppressed.  Integrity errors abort the run instead of being
converted to gaps.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .data import DUKASCOPY_PRICE_DIVISORS, QUOTE_COLUMNS, REQUIRED_COLUMNS
from .dukascopy_event_data import (
    BASE_URL,
    PARSER_VERSION,
    PROVIDER,
    DatabaseTransferVerification,
    load_tick_window,
    verify_database_transfer,
)
from .intraday_calendar import FX_SESSION_TIMEZONE, fx_session_bounds
from .models import CurrencyPair
from .portfolio import CommonSessionCalendar

_DAILY_COLUMNS = (
    *REQUIRED_COLUMNS,
    *QUOTE_COLUMNS,
    "session_open_quote_time",
    "session_close_quote_time",
    "volume",
    "tick_count",
)
DAILY_BOUNDARY_MAX_QUOTE_AGE = timedelta(seconds=5)


@dataclass(frozen=True)
class DukascopyDailyRun:
    """Per-symbol daily frames and immutable extraction evidence from one run.

    ``daily_data`` preserves symbol-specific suppressions for audit.  Formal
    cross-symbol factor work must pass the run through
    :func:`build_common_daily_data` before using those frames.
    """

    daily_data: dict[str, pd.DataFrame]
    session_audit: pd.DataFrame
    transfer_audit: pd.DataFrame
    requested_session_start_dates: tuple[date, ...]


@dataclass(frozen=True)
class PortfolioCloseInputs:
    """Exact common-session close quotes ready for :func:`run_portfolio`."""

    calendar: CommonSessionCalendar
    mid_prices: pd.DataFrame
    bids: pd.DataFrame
    asks: pd.DataFrame


def _calendar_date(value: date | datetime | str, label: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be an ISO calendar date") from error
    return parsed


def ny_close_session_start_dates(
    start: date | datetime | str,
    end: date | datetime | str,
) -> tuple[date, ...]:
    """Return Sunday-through-Thursday New York session starts in ``[start, end)``.

    A session beginning at 17:00 New York on Sunday is the Monday FX trading
    session.  Friday and Saturday starts are excluded rather than producing
    weekend fragments.  Public holidays are not guessed here: verified
    ``no_data`` source rows and observed ticks determine whether a bar exists.
    """

    first = _calendar_date(start, "start")
    stop = _calendar_date(end, "end")
    if first >= stop:
        raise ValueError("start must be earlier than the exclusive end date")
    days = (stop - first).days
    return tuple(
        current
        for offset in range(days)
        if (current := first + timedelta(days=offset)).weekday() in {0, 1, 2, 3, 6}
    )


def _canonical_symbols(symbols: Iterable[str]) -> tuple[str, ...]:
    if isinstance(symbols, (str, bytes)):
        raise ValueError("symbols must be an iterable of currency pairs")
    normalized = tuple(CurrencyPair.parse(symbol).symbol for symbol in symbols)
    if not normalized:
        raise ValueError("symbols cannot be empty")
    if len(normalized) != len(set(normalized)):
        raise ValueError("symbols must be unique after normalization")
    return normalized


def _empty_daily_frame() -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            column: pd.Series(
                dtype=(
                    "datetime64[ns, UTC]"
                    if column in {"session_open_quote_time", "session_close_quote_time"}
                    else "float64"
                )
            )
            for column in _DAILY_COLUMNS
        }
    )
    frame.index = pd.DatetimeIndex([], tz="UTC", name="timestamp")
    return frame


def _aggregate_complete_session(ticks: pd.DataFrame, end_utc: pd.Timestamp) -> dict[str, object]:
    bid = ticks["bid"].to_numpy(dtype=float)
    ask = ticks["ask"].to_numpy(dtype=float)
    mid = (bid + ask) / 2.0
    bid_size = ticks["bid_size"].to_numpy(dtype=float)
    ask_size = ticks["ask_size"].to_numpy(dtype=float)
    return {
        "timestamp": end_utc,
        "open": mid[0],
        "high": float(np.max(mid)),
        "low": float(np.min(mid)),
        "close": mid[-1],
        "bid_open": bid[0],
        "bid_high": float(np.max(bid)),
        "bid_low": float(np.min(bid)),
        "bid_close": bid[-1],
        "ask_open": ask[0],
        "ask_high": float(np.max(ask)),
        "ask_low": float(np.min(ask)),
        "ask_close": ask[-1],
        "session_open_quote_time": pd.Timestamp(ticks.iloc[0]["timestamp"]),
        "session_close_quote_time": pd.Timestamp(ticks.iloc[-1]["timestamp"]),
        "volume": float(np.sum(bid_size) + np.sum(ask_size)),
        "tick_count": len(ticks),
    }


def _daily_attrs(
    *,
    symbol: str,
    receipt: DatabaseTransferVerification,
    audit: pd.DataFrame,
) -> dict[str, object]:
    requested = int(audit["expected_hour_count"].sum())
    decoded = int(audit["decoded_hour_count"].sum())
    confirmed_no_data = int(audit["no_data_hour_count"].sum())
    missing = int(audit["missing_hour_count"].sum())
    return {
        "source_provider": PROVIDER,
        "source_symbol": symbol,
        "source_base_url": BASE_URL,
        "source_price_divisor": DUKASCOPY_PRICE_DIVISORS[symbol],
        "source_parser_version": PARSER_VERSION,
        "source_database_schema_version": "1",
        "source_database_sha256": receipt.sha256,
        "source_database_transfer_verified": True,
        "source_transfer_manifest_sha256": receipt.manifest_sha256,
        "source_requested_hours": requested,
        "source_available_hours": decoded,
        "source_no_data_hours": confirmed_no_data,
        "source_failed_hours": missing,
        "source_hour_coverage": (
            (decoded + confirmed_no_data) / requested if requested else 0.0
        ),
        "source_tick_count": int(audit["tick_count"].sum()),
        "source_volume_semantics": "sum_bid_ask_quote_size",
        "source_manifest_complete": missing == 0,
        "source_daily_session_timezone": FX_SESSION_TIMEZONE,
        "source_daily_session_boundary": "17:00",
        "source_daily_bar_timestamp": "session_end_utc",
        "source_daily_boundary_max_quote_age_seconds": (
            DAILY_BOUNDARY_MAX_QUOTE_AGE.total_seconds()
        ),
        "source_forward_filled": False,
        "price_mode": "bid_ask",
        "dropped_invalid_ohlc": 0,
    }


def _checkpoint_serialize(value: object) -> object:
    """JSON-safe form for a daily record/audit field (Timestamp/NaT/np/date types)."""
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, np.generic):
        value = value.item()
        return None if isinstance(value, float) and math.isnan(value) else value
    if isinstance(value, (list, tuple)):
        return [_checkpoint_serialize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _checkpoint_serialize(val) for key, val in value.items()}
    return value


def _checkpoint_open(path: Path) -> sqlite3.Connection:
    """Open (create) the per-session resume checkpoint."""
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS session_checkpoint (
            symbol TEXT NOT NULL,
            session_date TEXT NOT NULL,
            database_sha256 TEXT NOT NULL,
            record_json TEXT,
            audit_json TEXT NOT NULL,
            PRIMARY KEY (symbol, session_date)
        )
        """
    )
    connection.commit()
    return connection


def _checkpoint_restore_timestamp(value: object) -> object:
    if value is None:
        return pd.NaT
    return pd.Timestamp(value)


def _checkpoint_restore_record(record: dict[str, object]) -> dict[str, object]:
    """Restore native types (Timestamp/float) from a JSON-serialized record."""
    restored = dict(record)
    for key in ("timestamp", "session_open_quote_time", "session_close_quote_time"):
        if key in restored:
            restored[key] = _checkpoint_restore_timestamp(restored[key])
    return restored


def _checkpoint_restore_audit(audit: dict[str, object]) -> dict[str, object]:
    """Restore native types (date/Timestamp/float) from a JSON-serialized audit."""
    restored = dict(audit)
    for key in ("session_start_local_date", "session_end_local_date"):
        if key in restored and restored[key] is not None:
            restored[key] = date.fromisoformat(str(restored[key]))
    for key in ("session_start_utc", "session_end_utc"):
        if key in restored:
            restored[key] = _checkpoint_restore_timestamp(restored[key])
    for key in ("session_open_quote_time", "session_close_quote_time"):
        if key in restored:
            restored[key] = _checkpoint_restore_timestamp(restored[key])
    for key in ("open_quote_delay_seconds", "close_quote_age_seconds"):
        if key in restored and restored[key] is None:
            restored[key] = np.nan
    return restored


def _checkpoint_load(
    connection: sqlite3.Connection,
    symbols: tuple[str, ...],
    receipts: dict[str, DatabaseTransferVerification],
) -> dict[tuple[str, str], tuple[dict[str, object] | None, dict[str, object]]]:
    """Return cached (record, audit) for sessions whose source SHA still matches."""
    cached: dict[tuple[str, str], tuple[dict[str, object] | None, dict[str, object]]] = {}
    for symbol in symbols:
        expected_sha = receipts[symbol].sha256
        rows = connection.execute(
            "SELECT session_date, database_sha256, record_json, audit_json "
            "FROM session_checkpoint WHERE symbol = ?",
            (symbol,),
        ).fetchall()
        for session_date, stored_sha, record_json, audit_json in rows:
            if stored_sha != expected_sha:
                continue  # source DB changed -> redo this session
            record = (
                _checkpoint_restore_record(json.loads(record_json))
                if record_json
                else None
            )
            audit = _checkpoint_restore_audit(json.loads(audit_json))
            cached[(symbol, session_date)] = (record, audit)
    return cached


def _checkpoint_store(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    session_date: date,
    database_sha256: str,
    record: dict[str, object] | None,
    audit: dict[str, object],
) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO session_checkpoint "
        "(symbol, session_date, database_sha256, record_json, audit_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            symbol,
            session_date.isoformat(),
            database_sha256,
            json.dumps(_checkpoint_serialize(record)) if record is not None else None,
            json.dumps(_checkpoint_serialize(audit)),
        ),
    )
    connection.commit()


def run_dukascopy_daily_from_sqlite(
    database_directory: str | Path,
    symbols: Iterable[str],
    start: date | datetime | str,
    end: date | datetime | str,
    *,
    transfer_manifest_path: str | Path | None = None,
    checkpoint_path: str | Path | None = None,
    boundary_max_quote_age: timedelta | None = DAILY_BOUNDARY_MAX_QUOTE_AGE,
) -> DukascopyDailyRun:
    """Build 17:00-New-York daily bid/ask bars from transferred SQLite files.

    ``start`` and exclusive ``end`` refer to the local date on which each FX
    session begins.  Every requested database is transfer-verified before any
    hourly payload is decoded.  The whole-file hash is therefore calculated
    once per symbol, while every decoded hourly payload retains its own hash
    verification through :func:`load_tick_window`.

    ``boundary_max_quote_age`` controls whether a complete session with ticks
    is suppressed when its first/last quote is farther than this window from
    the session boundary.  ``None`` disables the check: every complete session
    emits a bar regardless of boundary tick timing (the actual delay/age is
    still recorded in the audit).  This is appropriate for factor-only research
    where OHLC validity matters more than sub-second boundary precision; the
    portfolio ledger can apply its own stricter filter later.
    """

    root = Path(database_directory).resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    normalized_symbols = _canonical_symbols(symbols)
    session_dates = ny_close_session_start_dates(start, end)
    if not session_dates:
        raise ValueError("date range contains no Sunday-through-Thursday FX sessions")
    manifest = (
        Path(transfer_manifest_path).resolve()
        if transfer_manifest_path is not None
        else root / "_sqlite_manifest.json"
    )

    receipts: dict[str, DatabaseTransferVerification] = {}
    transfer_rows: list[dict[str, object]] = []
    # Verify every closed database before decoding any payload from any symbol.
    for symbol in normalized_symbols:
        receipt = verify_database_transfer(
            root / f"{symbol}.sqlite",
            manifest,
            symbol=symbol,
        )
        receipts[symbol] = receipt
        transfer_rows.append(
            {
                "symbol": symbol,
                "database_path": str(receipt.database_path),
                "bytes": receipt.bytes,
                "database_sha256": receipt.sha256,
                "database_mtime_ns": receipt.database_mtime_ns,
                "manifest_path": str(receipt.manifest_path),
                "manifest_sha256": receipt.manifest_sha256,
                "sidecar_hash_sha256": receipt.sidecar_hash_sha256,
                "sidecar_info_sha256": receipt.sidecar_info_sha256,
                "transfer_verified": True,
            }
        )

    checkpoint_connection: sqlite3.Connection | None = None
    cached: dict[tuple[str, str], tuple[dict[str, object] | None, dict[str, object]]] = {}
    if checkpoint_path is not None:
        checkpoint_connection = _checkpoint_open(Path(checkpoint_path))
        cached = _checkpoint_load(checkpoint_connection, normalized_symbols, receipts)

    records_by_symbol: dict[str, list[dict[str, object]]] = {
        symbol: [] for symbol in normalized_symbols
    }
    audit_rows: list[dict[str, object]] = []
    for symbol, receipt in receipts.items():
        for session_date in session_dates:
            cache_key = (symbol, session_date.isoformat())
            if cache_key in cached:
                record, audit = cached[cache_key]
                audit_rows.append(audit)
                if record is not None:
                    records_by_symbol[symbol].append(record)
                continue
            bounds = fx_session_bounds(session_date)
            start_utc = pd.Timestamp(bounds.start_utc)
            end_utc = pd.Timestamp(bounds.end_utc)
            window = load_tick_window(
                receipt.database_path,
                start_utc,
                end_utc,
                symbol=symbol,
                include_sizes=True,
                transfer_verification=receipt,
                require_transfer_verification=True,
            )
            if window.ticks.empty:
                open_quote_time = pd.NaT
                close_quote_time = pd.NaT
                open_quote_delay_seconds = np.nan
                close_quote_age_seconds = np.nan
            else:
                open_quote_time = pd.Timestamp(window.ticks.iloc[0]["timestamp"])
                close_quote_time = pd.Timestamp(window.ticks.iloc[-1]["timestamp"])
                open_quote_delay_seconds = float(
                    (open_quote_time - start_utc).total_seconds()
                )
                close_quote_age_seconds = float(
                    (end_utc - close_quote_time).total_seconds()
                )
            record: dict[str, object] | None = None
            if not window.complete:
                emitted = False
                suppression_reason: str | None = "missing_source_hours"
            elif window.no_data_hours_utc:
                emitted = False
                suppression_reason = "confirmed_no_data_hours"
            elif window.ticks.empty:
                emitted = False
                suppression_reason = "no_ticks"
            elif (
                boundary_max_quote_age is not None
                and (
                    open_quote_delay_seconds > boundary_max_quote_age.total_seconds()
                    or close_quote_age_seconds > boundary_max_quote_age.total_seconds()
                )
            ):
                emitted = False
                suppression_reason = "boundary_quote_outside_threshold"
            else:
                emitted = True
                suppression_reason = None
                record = _aggregate_complete_session(window.ticks, end_utc)
                records_by_symbol[symbol].append(record)
            audit = {
                "symbol": symbol,
                "session_start_local_date": session_date,
                "session_end_local_date": session_date + timedelta(days=1),
                "session_start_utc": start_utc,
                "session_end_utc": end_utc,
                "elapsed_hours": (end_utc - start_utc).total_seconds() / 3600,
                "expected_hour_count": len(window.expected_hours_utc),
                "decoded_hour_count": len(window.decoded_hours_utc),
                "no_data_hour_count": len(window.no_data_hours_utc),
                "missing_hour_count": len(window.missing_hours_utc),
                "missing_hours": "|".join(
                    value.isoformat() for value in window.missing_hours_utc
                ),
                "payload_hashes_verified": window.payload_hashes_verified,
                "duplicate_timestamps_removed": window.duplicate_timestamps_removed,
                "tick_count": len(window.ticks),
                "session_open_quote_time": open_quote_time,
                "session_close_quote_time": close_quote_time,
                "open_quote_delay_seconds": open_quote_delay_seconds,
                "close_quote_age_seconds": close_quote_age_seconds,
                "boundary_quote_max_age_seconds": (
                    boundary_max_quote_age.total_seconds()
                    if boundary_max_quote_age is not None
                    else None
                ),
                "source_window_complete": window.complete,
                "daily_bar_emitted": emitted,
                "suppression_reason": suppression_reason,
                "database_sha256": receipt.sha256,
            }
            audit_rows.append(audit)
            if checkpoint_connection is not None:
                _checkpoint_store(
                    checkpoint_connection,
                    symbol=symbol,
                    session_date=session_date,
                    database_sha256=receipt.sha256,
                    record=record,
                    audit=audit,
                )

    session_audit = pd.DataFrame(audit_rows).sort_values(
        ["session_start_local_date", "symbol"]
    ).reset_index(drop=True)
    daily_data: dict[str, pd.DataFrame] = {}
    for symbol in normalized_symbols:
        records = records_by_symbol[symbol]
        if records:
            frame = pd.DataFrame.from_records(records).set_index("timestamp")
            frame.index = pd.DatetimeIndex(
                pd.to_datetime(frame.index, utc=True), name="timestamp"
            )
            frame = frame.loc[:, list(_DAILY_COLUMNS)].sort_index()
        else:
            frame = _empty_daily_frame()
        symbol_audit = session_audit.loc[session_audit["symbol"] == symbol]
        frame.attrs.update(
            _daily_attrs(symbol=symbol, receipt=receipts[symbol], audit=symbol_audit)
        )
        daily_data[symbol] = frame

    return DukascopyDailyRun(
        daily_data=daily_data,
        session_audit=session_audit,
        transfer_audit=pd.DataFrame(transfer_rows).sort_values("symbol").reset_index(drop=True),
        requested_session_start_dates=session_dates,
    )


def build_portfolio_close_inputs(run: DukascopyDailyRun) -> PortfolioCloseInputs:
    """Create strict common-date close matrices without intersection or filling.

    Unlike :meth:`CommonSessionCalendar.from_market_data`, this adapter checks
    the full requested symbol-by-session audit rectangle first.  A missing
    SQLite row or a symbol-specific suppressed bar stops construction.  A
    session is excluded only when *every* requested symbol has an intact
    transfer but lacks a complete quote day (for example, a common holiday).
    """

    if not isinstance(run, DukascopyDailyRun):
        raise TypeError("run must be a DukascopyDailyRun")
    symbols = tuple(sorted(run.daily_data))
    if not symbols:
        raise ValueError("daily run contains no symbols")
    expected_audit_rows = len(symbols) * len(run.requested_session_start_dates)
    if len(run.session_audit) != expected_audit_rows:
        raise ValueError("session audit does not cover the requested symbol/session rectangle")
    expected_audit_keys = {
        (symbol, session_date)
        for symbol in symbols
        for session_date in run.requested_session_start_dates
    }
    observed_audit_keys = set(
        zip(
            run.session_audit["symbol"],
            run.session_audit["session_start_local_date"],
            strict=True,
        )
    )
    if observed_audit_keys != expected_audit_keys:
        raise ValueError("session audit keys do not match the requested symbol/session rectangle")
    if run.session_audit["missing_hour_count"].astype(int).gt(0).any():
        failures = run.session_audit.loc[
            run.session_audit["missing_hour_count"].astype(int).gt(0),
            ["symbol", "session_start_local_date"],
        ]
        raise ValueError(
            "portfolio inputs reject missing SQLite source hours: "
            + ", ".join(
                f"{row.symbol}@{row.session_start_local_date}"
                for row in failures.itertuples()
            )
        )
    non_closure_suppressions = run.session_audit.loc[
        run.session_audit["suppression_reason"].notna()
        & ~run.session_audit["suppression_reason"].isin(
            {"confirmed_no_data_hours", "no_ticks"}
        ),
        ["symbol", "session_start_local_date", "suppression_reason"],
    ]
    if not non_closure_suppressions.empty:
        raise ValueError(
            "portfolio inputs reject non-holiday daily suppressions: "
            + ", ".join(
                f"{row.symbol}@{row.session_start_local_date}:{row.suppression_reason}"
                for row in non_closure_suppressions.itertuples()
            )
        )
    emitted_by_session = run.session_audit.groupby(
        "session_end_local_date", sort=True
    )["daily_bar_emitted"].agg(["sum", "count"])
    partial = emitted_by_session.loc[
        (emitted_by_session["sum"] > 0)
        & (emitted_by_session["sum"] < emitted_by_session["count"])
    ]
    if not partial.empty:
        raise ValueError(
            "portfolio inputs reject symbol-specific incomplete sessions: "
            + ", ".join(value.isoformat() for value in partial.index)
        )
    expected = {
        pd.Timestamp(session_date, tz="UTC")
        for session_date in emitted_by_session.index[emitted_by_session["sum"] > 0]
    }
    if not expected:
        raise ValueError("no complete common New York-close sessions are available")
    series_by_field: dict[str, dict[str, pd.Series]] = {
        "close": {},
        "bid_close": {},
        "ask_close": {},
    }
    for symbol in symbols:
        frame = run.daily_data[symbol]
        normalized = frame.copy()
        normalized.index = normalized.index.normalize()
        if normalized.index.has_duplicates:
            raise ValueError(f"{symbol}: duplicate normalized New York-close sessions")
        observed = set(normalized.index)
        if observed != expected:
            missing = sorted(expected - observed)
            unexpected = sorted(observed - expected)
            raise ValueError(
                f"{symbol}: portfolio inputs require every audited common session; "
                f"missing={[value.date().isoformat() for value in missing]}, "
                f"unexpected={[value.date().isoformat() for value in unexpected]}"
            )
        for field in series_by_field:
            series_by_field[field][symbol] = normalized[field]

    matrices = {
        field: pd.DataFrame(values).sort_index().rename_axis("session")
        for field, values in series_by_field.items()
    }
    calendar = CommonSessionCalendar(matrices["close"].index, symbols=symbols)
    return PortfolioCloseInputs(
        calendar=calendar,
        mid_prices=matrices["close"],
        bids=matrices["bid_close"],
        asks=matrices["ask_close"],
    )


def _common_emitted_sessions(run: DukascopyDailyRun) -> tuple[tuple[str, ...], set[pd.Timestamp]]:
    """Derive common sessions from the cache's build-time emit verdicts.

    The daily cache already decided, at build time and with full tick access,
    which sessions emit an execution-grade bar (``daily_bar_emitted=True``) and
    which are suppressed (boundary imprecision, no-data, no-ticks).  Those
    verdicts live in ``run.session_audit`` and ``run.daily_data`` already contains
    only the emitted bars.  Re-deriving the verdict from raw ticks (as
    :func:`build_portfolio_close_inputs` does) is redundant and stricter in a way
    that is incompatible with real Dukascopy boundary quotes; it also mis-flags
    sessions the cache already correctly excluded.

    This helper trusts the cache's own emit verdicts and returns the sessions
    where *every* symbol emitted a bar, without re-imposing the strict portfolio
    gate.  Integrity is preserved because suppressed sessions are simply absent
    from ``run.daily_data`` rather than filled.
    """
    if not isinstance(run, DukascopyDailyRun):
        raise TypeError("run must be a DukascopyDailyRun")
    symbols = tuple(sorted(run.daily_data))
    if not symbols:
        raise ValueError("daily run contains no symbols")
    audit = run.session_audit
    if audit.empty:
        raise ValueError("daily run contains no session audit rows")
    emitted = audit.loc[audit["daily_bar_emitted"].astype(bool)]
    emitted_by_session = emitted.groupby("session_end_local_date", sort=True).size()
    common_end_dates = set(
        emitted_by_session.loc[emitted_by_session == len(symbols)].index
    )
    if not common_end_dates:
        raise ValueError("no common emitted New York-close sessions are available")
    common_close_timestamps: set[pd.Timestamp] = set()
    for symbol in symbols:
        frame = run.daily_data[symbol]
        if frame.empty:
            raise ValueError(f"{symbol}: emitted daily data is empty")
        # Map each common session end-date to the bar timestamp actually stored
        # for that symbol so the real 17:00-New-York close is preserved.
        for ts in frame.index:
            end_date = pd.Timestamp(ts).date() if hasattr(pd.Timestamp(ts), "date") else None
            if end_date in common_end_dates:
                common_close_timestamps.add(pd.Timestamp(ts).normalize())
    if not common_close_timestamps:
        raise ValueError("could not resolve common session close timestamps")
    return symbols, common_close_timestamps


def build_common_daily_data(run: DukascopyDailyRun) -> dict[str, pd.DataFrame]:
    """Return exact common-session OHLC frames for formal long-horizon research.

    The strict portfolio adapter performs the source-hour and audit-rectangle
    validation.  This function then retains only the sessions that are complete
    for every symbol, preserving each real 17:00-New-York close timestamp (21:00
    or 22:00 UTC) so a close is never backdated to midnight.
    """

    close_inputs = build_portfolio_close_inputs(run)
    common_dates = set(close_inputs.calendar.sessions)
    output: dict[str, pd.DataFrame] = {}
    expected_timestamps: pd.DatetimeIndex | None = None
    for symbol in close_inputs.calendar.symbols:
        source = run.daily_data[symbol]
        selected = source.loc[source.index.normalize().isin(common_dates)].copy()
        if len(selected) != len(common_dates):
            raise ValueError(
                f"{symbol}: formal daily data does not contain every common session"
            )
        if expected_timestamps is None:
            expected_timestamps = selected.index
        elif not selected.index.equals(expected_timestamps):
            raise ValueError(
                f"{symbol}: real New York close timestamps differ across symbols"
            )
        selected.attrs.update(source.attrs)
        selected.attrs["source_exact_common_sessions"] = True
        selected.attrs["source_common_session_count"] = len(common_dates)
        selected.attrs["source_common_session_missing_filled"] = False
        output[symbol] = selected
    return output


def build_common_daily_data_from_cache_audit(
    run: DukascopyDailyRun,
) -> dict[str, pd.DataFrame]:
    """Return common-session OHLC frames derived from the cache's emit verdicts.

    Unlike :func:`build_common_daily_data`, this path does not re-impose the
    strict portfolio gate (which treats any symbol-specific suppression as fatal
    and therefore yields no panel on real Dukascopy data).  Instead it trusts the
    cache's own build-time emit verdicts (``daily_bar_emitted``) and retains only
    the sessions where every symbol emitted an execution-grade bar.  Suppressed
    sessions are excluded, never filled, so integrity is preserved; each real
    17:00-New-York close timestamp is kept unchanged.
    """

    symbols, common_timestamps = _common_emitted_sessions(run)
    output: dict[str, pd.DataFrame] = {}
    expected_timestamps: pd.DatetimeIndex | None = None
    for symbol in symbols:
        source = run.daily_data[symbol]
        selected = source.loc[source.index.normalize().isin(common_timestamps)].copy()
        if len(selected) != len(common_timestamps):
            raise ValueError(
                f"{symbol}: formal daily data does not contain every common session"
            )
        if expected_timestamps is None:
            expected_timestamps = selected.index
        elif not selected.index.equals(expected_timestamps):
            raise ValueError(
                f"{symbol}: real New York close timestamps differ across symbols"
            )
        selected.attrs.update(source.attrs)
        selected.attrs["source_exact_common_sessions"] = True
        selected.attrs["source_common_session_count"] = len(common_timestamps)
        selected.attrs["source_common_session_missing_filled"] = False
        selected.attrs["source_common_session_source"] = "cache_audit_emit_verdicts"
        output[symbol] = selected
    return output


__all__ = [
    "DAILY_BOUNDARY_MAX_QUOTE_AGE",
    "DukascopyDailyRun",
    "PortfolioCloseInputs",
    "build_common_daily_data",
    "build_common_daily_data_from_cache_audit",
    "build_portfolio_close_inputs",
    "ny_close_session_start_dates",
    "run_dukascopy_daily_from_sqlite",
]
