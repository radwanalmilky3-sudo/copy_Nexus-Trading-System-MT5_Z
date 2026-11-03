"""Formal, fail-closed intraday research runners over transferred SQLite ticks.

The runner in this module is intentionally an orchestration layer.  It verifies
each multi-gigabyte database once, extracts only the narrow quote neighborhoods
needed by a frozen experiment, and delegates return construction to
``intraday_research``.  It does not estimate a direction or inspect profitability.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd

from .dukascopy_event_data import (
    DatabaseTransferVerification,
    load_tick_window,
    verify_database_transfer,
)
from .intraday_calendar import event_window
from .intraday_research import (
    FIX_W_BOUNDARY_MAX_QUOTE_AGE,
    FIX_W_G9_LEGS,
    build_fix_w_composite_experiments,
    build_fix_w_leg_experiments,
    fix_w_segment_plan,
)
from .publication_calendar import PublicationCalendar

_TICK_RESOLUTION_MARGIN: Final = pd.Timedelta(1, unit="ms")


@dataclass(frozen=True)
class FixWSQLiteRun:
    """Auditable tables from a formal FIX-W SQLite extraction run."""

    leg_experiments: pd.DataFrame
    composite_experiments: pd.DataFrame
    extraction_audit: pd.DataFrame
    transfer_audit: pd.DataFrame


def fix_w_candidate_return_series(
    run: FixWSQLiteRun,
    *,
    spread_filtered: bool = True,
) -> pd.Series:
    """Return the registered FIX-W long-pattern series without dropping gaps."""

    if not isinstance(run, FixWSQLiteRun):
        raise TypeError("run must be a FixWSQLiteRun")
    if not isinstance(spread_filtered, bool):
        raise ValueError("spread_filtered must be a boolean")
    frame = run.composite_experiments
    column = (
        "filtered_executable_long_log_return"
        if spread_filtered
        else "executable_long_log_return"
    )
    if frame.empty:
        result = pd.Series([], dtype="float64", name="intraday_fix_w_composite")
        result.index = pd.DatetimeIndex([], tz="UTC", name="event_date")
        return result
    missing = {"local_date", column} - set(frame.columns)
    if missing:
        raise ValueError(f"FIX-W run is missing return columns {sorted(missing)}")
    index = pd.DatetimeIndex(pd.to_datetime(frame["local_date"], utc=True))
    if not index.is_unique:
        raise ValueError("FIX-W run contains duplicate event dates")
    result = pd.Series(
        pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float),
        index=index,
        name="intraday_fix_w_composite",
    ).sort_index()
    result.index.name = "event_date"
    result.attrs = {
        "direction": "registered_four_segment_long_pattern",
        "spread_filtered": spread_filtered,
        "missing_returns_dropped": False,
        "research_only": True,
    }
    return result


def run_fix_w_from_sqlite(
    database_dir: str | Path,
    local_dates: Iterable[date | datetime | str],
    *,
    publication_calendar: PublicationCalendar,
    transfer_manifest_path: str | Path | None = None,
) -> FixWSQLiteRun:
    """Extract and construct the preregistered FIX-W G9 experiment.

    All nine frozen databases must pass their whole-file transfer contract
    before any payload is decoded.  Six unique boundary neighborhoods are then
    read per eligible event date.  Missing SQLite hours suppress the affected
    leg and the complete G9 composite; explicit ``no_data`` hours remain
    complete source records but naturally yield missing boundary quotes.
    """

    root = Path(database_dir).resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    manifest_path = (
        Path(transfer_manifest_path).resolve()
        if transfer_manifest_path is not None
        else root / "_sqlite_manifest.json"
    )
    parsed_dates = [event_window("tokyo_fix", value).local_date for value in local_dates]
    if len(parsed_dates) != len(set(parsed_dates)):
        raise ValueError("FIX-W runner local_dates must be unique")
    plans = {
        local_date: fix_w_segment_plan(
            local_date, publication_calendar=publication_calendar
        )
        for local_date in parsed_dates
    }
    eligible_plans = {key: value for key, value in plans.items() if value}
    if not eligible_plans:
        return FixWSQLiteRun(
            leg_experiments=pd.DataFrame(),
            composite_experiments=pd.DataFrame(),
            extraction_audit=pd.DataFrame(),
            transfer_audit=pd.DataFrame(),
        )

    receipts: dict[str, DatabaseTransferVerification] = {}
    transfer_rows: list[dict[str, object]] = []
    for _, (symbol, _) in FIX_W_G9_LEGS.items():
        database_path = root / f"{symbol}.sqlite"
        receipt = verify_database_transfer(
            database_path,
            manifest_path,
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

    audit_rows: list[dict[str, object]] = []
    quote_chunks: dict[str, list[pd.DataFrame]] = {symbol: [] for symbol in receipts}
    source_complete_by_date_symbol: dict[tuple[date, str], bool] = {}
    source_missing_by_date_symbol: dict[tuple[date, str], str] = {}
    for local_date, segments in eligible_plans.items():
        boundaries: dict[pd.Timestamp, list[str]] = {}
        for segment in segments:
            boundaries.setdefault(pd.Timestamp(segment.start_time), []).append(
                f"{segment.name}:start"
            )
            boundaries.setdefault(pd.Timestamp(segment.end_time), []).append(
                f"{segment.name}:end"
            )

        for symbol, receipt in receipts.items():
            extracted: list[pd.DataFrame] = []
            symbol_complete = True
            missing_hours: set[str] = set()
            for boundary, roles in sorted(boundaries.items()):
                start = boundary - FIX_W_BOUNDARY_MAX_QUOTE_AGE
                end = (
                    boundary
                    + FIX_W_BOUNDARY_MAX_QUOTE_AGE
                    + _TICK_RESOLUTION_MARGIN
                )
                window = load_tick_window(
                    receipt.database_path,
                    start,
                    end,
                    symbol=symbol,
                    transfer_verification=receipt,
                    require_transfer_verification=True,
                )
                extracted.append(window.ticks[["timestamp", "bid", "ask"]])
                symbol_complete &= window.complete
                missing_hours.update(value.isoformat() for value in window.missing_hours_utc)
                audit_rows.append(
                    {
                        "local_date": local_date,
                        "symbol": symbol,
                        "boundary_time": boundary,
                        "boundary_roles": "|".join(sorted(roles)),
                        "window_start": window.start_utc,
                        "window_end": window.end_utc,
                        "expected_hour_count": len(window.expected_hours_utc),
                        "decoded_hour_count": len(window.decoded_hours_utc),
                        "no_data_hour_count": len(window.no_data_hours_utc),
                        "missing_hour_count": len(window.missing_hours_utc),
                        "missing_hours": "|".join(
                            value.isoformat() for value in window.missing_hours_utc
                        ),
                        "payload_hashes_verified": window.payload_hashes_verified,
                        "duplicate_timestamps_removed": (
                            window.duplicate_timestamps_removed
                        ),
                        "window_complete": window.complete,
                        "database_sha256": receipt.sha256,
                    }
                )
            key = (local_date, symbol)
            source_complete_by_date_symbol[key] = symbol_complete
            source_missing_by_date_symbol[key] = "|".join(sorted(missing_hours))
            # A partially transferred event day contributes no quote to either
            # returns or the rolling spread history.  The audit rows above keep
            # the exact failure visible.
            if symbol_complete:
                quote_chunks[symbol].extend(extracted)

    quote_frames: dict[str, pd.DataFrame] = {}
    for symbol, chunks in quote_chunks.items():
        if not chunks:
            quote_frames[symbol] = pd.DataFrame(
                {
                    "timestamp": pd.Series([], dtype="datetime64[ns, UTC]"),
                    "bid": pd.Series([], dtype="float64"),
                    "ask": pd.Series([], dtype="float64"),
                }
            )
            continue
        combined = pd.concat(chunks, ignore_index=True)
        combined = combined.sort_values("timestamp", kind="stable")
        quote_frames[symbol] = combined.drop_duplicates(
            "timestamp", keep="last"
        ).reset_index(drop=True)

    eligible_dates = list(eligible_plans)
    legs = build_fix_w_leg_experiments(
        quote_frames,
        eligible_dates,
        publication_calendar=publication_calendar,
    )
    legs["source_window_complete"] = [
        source_complete_by_date_symbol[(row.local_date, row.market_symbol)]
        for row in legs.itertuples()
    ]
    legs["source_missing_hours"] = [
        source_missing_by_date_symbol[(row.local_date, row.market_symbol)]
        for row in legs.itertuples()
    ]
    legs["database_sha256"] = legs["market_symbol"].map(
        {symbol: receipt.sha256 for symbol, receipt in receipts.items()}
    )
    incomplete_leg_mask = ~legs["source_window_complete"].astype(bool)
    if incomplete_leg_mask.any():
        return_columns = [column for column in legs if column.endswith("_log_return")]
        legs.loc[incomplete_leg_mask, return_columns] = np.nan
        legs.loc[incomplete_leg_mask, "complete_segment_count"] = 0
        legs.loc[incomplete_leg_mask, "spread_filter_pass"] = False
        legs.loc[incomplete_leg_mask, "spread_filter_status"] = (
            "incomplete_source_window"
        )
        legs.loc[incomplete_leg_mask, "sample_status"] = "incomplete_source_window"

    composites = build_fix_w_composite_experiments(
        quote_frames,
        eligible_dates,
        publication_calendar=publication_calendar,
    )
    incomplete_symbols_by_date = {
        local_date: sorted(
            symbol
            for symbol in receipts
            if not source_complete_by_date_symbol[(local_date, symbol)]
        )
        for local_date in eligible_dates
    }
    composites["source_window_complete"] = composites["local_date"].map(
        lambda value: not incomplete_symbols_by_date[value]
    )
    composites["source_incomplete_symbols"] = composites["local_date"].map(
        lambda value: ",".join(incomplete_symbols_by_date[value])
    )
    composites["database_sha256_set"] = "|".join(
        f"{symbol}:{receipts[symbol].sha256}" for symbol in sorted(receipts)
    )
    for index, row in composites.iterrows():
        incomplete_symbols = incomplete_symbols_by_date[row["local_date"]]
        if not incomplete_symbols:
            continue
        return_columns = [
            column for column in composites if column.endswith("_log_return")
        ]
        composites.loc[index, return_columns] = np.nan
        date_legs = legs.loc[legs["local_date"] == row["local_date"]]
        ready_currencies = set(
            date_legs.loc[
                date_legs["source_window_complete"].astype(bool)
                & (date_legs["complete_segment_count"] == 4),
                "foreign_currency",
            ]
        )
        composites.at[index, "return_ready_leg_count"] = len(ready_currencies)
        composites.at[index, "missing_legs"] = ",".join(
            sorted(set(FIX_W_G9_LEGS) - ready_currencies)
        )
        composites.at[index, "spread_filter_pass_leg_count"] = int(
            (
                date_legs["source_window_complete"].astype(bool)
                & date_legs["spread_filter_pass"].astype(bool)
            ).sum()
        )
        composites.at[index, "spread_filter_pass"] = False
        composites.at[index, "spread_filter_status"] = "incomplete_source_window"
        composites.at[index, "sample_status"] = "incomplete_source_window"

    return FixWSQLiteRun(
        leg_experiments=legs.sort_values(
            ["local_date", "foreign_currency"], ignore_index=True
        ),
        composite_experiments=composites.sort_values("local_date", ignore_index=True),
        extraction_audit=pd.DataFrame(audit_rows).sort_values(
            ["local_date", "symbol", "boundary_time"], ignore_index=True
        ),
        transfer_audit=pd.DataFrame(transfer_rows).sort_values(
            "symbol", ignore_index=True
        ),
    )


__all__ = [
    "FixWSQLiteRun",
    "fix_w_candidate_return_series",
    "run_fix_w_from_sqlite",
]
