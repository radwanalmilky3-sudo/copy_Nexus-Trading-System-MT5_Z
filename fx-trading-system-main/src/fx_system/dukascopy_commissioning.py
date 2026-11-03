"""Research-only commissioning of received EURUSD/GBPUSD SQLite files.

This module exercises real payload decoding, New York session boundaries and
intraday event quote selection before the complete formal universe arrives.
It never creates labels, returns, positions or a trading approval.  In
particular, sidecar verification here is not a substitute for the VPS batch
manifest required by the formal daily and event runners.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from .dukascopy_event_data import (
    load_tick_window,
    select_first_tick_at_or_after,
    select_last_tick_at_or_before,
)
from .dukascopy_intake import (
    build_intake_ledger,
    sha256_file,
    validate_sidecar_pair,
)
from .intraday_calendar import fx_session_bounds
from .models import CurrencyPair

COMMISSIONING_SYMBOLS: tuple[str, ...] = ("EURUSD", "GBPUSD")
DEFAULT_SESSION_DATES: tuple[date, ...] = (
    date(2025, 3, 3),
    date(2025, 3, 10),
    date(2025, 6, 2),
)
DEFAULT_EVENT_DATE = date(2025, 6, 3)
BOUNDARY_TOLERANCE = timedelta(seconds=5)
EVENT_WINDOW_HALF_WIDTH = timedelta(seconds=10)


def _utc_iso(value: object) -> str:
    return pd.Timestamp(value).tz_convert("UTC").isoformat()


def _date_value(value: date | str, label: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be an ISO date") from error


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON evidence {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"JSON evidence must be an object: {path}")
    return payload


def _sidecar_digest(path: Path) -> str:
    sidecar = Path(f"{path}.sha256")
    try:
        parts = sidecar.read_text(encoding="utf-8").strip().split(maxsplit=1)
    except (OSError, UnicodeError) as error:
        raise ValueError(f"cannot read SHA-256 sidecar {sidecar}: {error}") from error
    if len(parts) != 2 or len(parts[0]) != 64:
        raise ValueError(f"malformed SHA-256 sidecar: {sidecar}")
    return parts[0]


def _database_evidence(
    database_directory: Path,
    audit_directory: Path,
    symbol: str,
) -> dict[str, Any]:
    database = database_directory / f"{symbol}.sqlite"
    if not database.is_file():
        raise FileNotFoundError(database)
    sidecar_issues = validate_sidecar_pair(database)
    expected_sha256 = _sidecar_digest(database)
    actual_sha256 = sha256_file(database)
    info = _read_json(Path(f"{database}.json"))
    audit_path = audit_directory / f"{symbol}_dukascopy_audit.json"
    audit = _read_json(audit_path)
    audit_result = audit.get("result")
    audit_transport = audit.get("transport")
    audit_database = audit.get("database")
    audit_passed = isinstance(audit_result, dict) and audit_result.get("passed") is True
    audit_sha256 = (
        audit_transport.get("actual_file_sha256")
        if isinstance(audit_transport, dict)
        else None
    )
    audit_bytes = audit_database.get("bytes") if isinstance(audit_database, dict) else None
    sha256_matches = expected_sha256 == actual_sha256 == audit_sha256
    bytes_match = info.get("bytes") == database.stat().st_size == audit_bytes
    return {
        "symbol": symbol,
        "database_path": str(database.resolve()),
        "bytes": database.stat().st_size,
        "expected_sha256": expected_sha256,
        "actual_sha256": actual_sha256,
        "sha256_matches_sidecar_and_deep_audit": sha256_matches,
        "bytes_match_sidecar_and_deep_audit": bytes_match,
        "sidecar_contract_ok": not sidecar_issues,
        "sidecar_issues": sidecar_issues,
        "program_version": info.get("program_version"),
        "requested_start": (info.get("metadata") or {}).get("requested_start"),
        "requested_end_exclusive": (info.get("metadata") or {}).get(
            "requested_end_exclusive"
        ),
        "deep_audit_path": str(audit_path.resolve()),
        "deep_audit_passed": audit_passed,
        "formal_batch_manifest_verified": False,
    }


def _session_probe(database: Path, symbol: str, session_date: date) -> dict[str, Any]:
    bounds = fx_session_bounds(session_date)
    start = pd.Timestamp(bounds.start_utc)
    end = pd.Timestamp(bounds.end_utc)
    window = load_tick_window(
        database,
        start,
        end,
        symbol=symbol,
        include_sizes=False,
        require_transfer_verification=False,
    )
    if window.ticks.empty:
        open_delay: float | None = None
        close_age: float | None = None
    else:
        first_tick = pd.Timestamp(window.ticks.iloc[0]["timestamp"])
        last_tick = pd.Timestamp(window.ticks.iloc[-1]["timestamp"])
        open_delay = float((first_tick - start).total_seconds())
        close_age = float((end - last_tick).total_seconds())
    boundary_ok = (
        open_delay is not None
        and close_age is not None
        and open_delay <= BOUNDARY_TOLERANCE.total_seconds()
        and close_age <= BOUNDARY_TOLERANCE.total_seconds()
    )
    usable = window.complete and not window.no_data_hours_utc and boundary_ok
    return {
        "symbol": symbol,
        "session_start_local_date": session_date.isoformat(),
        "session_start_utc": _utc_iso(start),
        "session_end_utc": _utc_iso(end),
        "elapsed_hours": (end - start).total_seconds() / 3600,
        "end_utc_hour": end.hour,
        "expected_hours": len(window.expected_hours_utc),
        "decoded_hours": len(window.decoded_hours_utc),
        "no_data_hours": len(window.no_data_hours_utc),
        "missing_hours": len(window.missing_hours_utc),
        "payload_hashes_verified": window.payload_hashes_verified,
        "tick_count": len(window.ticks),
        "open_quote_delay_seconds": open_delay,
        "close_quote_age_seconds": close_age,
        "boundary_within_5_seconds": boundary_ok,
        "source_window_complete": window.complete,
        "session_usable_for_daily_commissioning": usable,
        "formal_transfer_verified": False,
    }


def _localized_boundary(
    event_date: date,
    local_time: time,
    timezone: str,
) -> pd.Timestamp:
    local = datetime.combine(event_date, local_time, tzinfo=ZoneInfo(timezone))
    return pd.Timestamp(local.astimezone(UTC))


def _event_boundaries(event_date: date) -> tuple[tuple[str, pd.Timestamp], ...]:
    return (
        (
            "tokyo_fix_0955",
            _localized_boundary(event_date, time(9, 55), "Asia/Tokyo"),
        ),
        (
            "wmr_london_1600",
            _localized_boundary(event_date, time(16), "Europe/London"),
        ),
        (
            "new_york_1700",
            _localized_boundary(event_date, time(17), "America/New_York"),
        ),
    )


def _duration_seconds(value: pd.Timedelta | None) -> float | None:
    return None if value is None else float(value.total_seconds())


def _event_probe(
    database: Path,
    symbol: str,
    event_id: str,
    boundary: pd.Timestamp,
) -> dict[str, Any]:
    start = boundary - EVENT_WINDOW_HALF_WIDTH
    end = boundary + EVENT_WINDOW_HALF_WIDTH
    window = load_tick_window(
        database,
        start,
        end,
        symbol=symbol,
        include_sizes=False,
        require_transfer_verification=False,
    )
    before = select_last_tick_at_or_before(
        window,
        boundary,
        maximum_quote_age=BOUNDARY_TOLERANCE,
    )
    after = select_first_tick_at_or_after(
        window,
        boundary,
        maximum_execution_delay=BOUNDARY_TOLERANCE,
    )
    ready = (
        window.complete
        and not window.no_data_hours_utc
        and before.accepted
        and after.accepted
    )
    return {
        "symbol": symbol,
        "event_id": event_id,
        "boundary_utc": _utc_iso(boundary),
        "window_start_utc": _utc_iso(start),
        "window_end_utc": _utc_iso(end),
        "source_window_complete": window.complete,
        "no_data_hours": len(window.no_data_hours_utc),
        "missing_hours": len(window.missing_hours_utc),
        "payload_hashes_verified": window.payload_hashes_verified,
        "tick_count": len(window.ticks),
        "last_at_or_before_accepted": before.accepted,
        "last_at_or_before_age_seconds": _duration_seconds(before.quote_age),
        "last_at_or_before_reason": before.rejection_reason,
        "first_at_or_after_accepted": after.accepted,
        "first_at_or_after_delay_seconds": _duration_seconds(after.execution_delay),
        "first_at_or_after_reason": after.rejection_reason,
        "boundary_ready": ready,
        "formal_transfer_verified": False,
    }


def run_two_symbol_commissioning(
    database_directory: str | Path,
    *,
    audit_directory: str | Path = "outputs/dukascopy_audit",
    intake_config_path: str | Path = "configs/dukascopy_intake_universe.yaml",
    symbols: tuple[str, ...] = COMMISSIONING_SYMBOLS,
    session_dates: tuple[date | str, ...] = DEFAULT_SESSION_DATES,
    event_date: date | str = DEFAULT_EVENT_DATE,
) -> dict[str, Any]:
    """Exercise two received databases without opening any outcome variable."""
    normalized = tuple(CurrencyPair.parse(symbol).symbol for symbol in symbols)
    if normalized != COMMISSIONING_SYMBOLS:
        raise ValueError(
            f"commissioning symbols must be exactly {COMMISSIONING_SYMBOLS!r}"
        )
    dates = tuple(_date_value(value, "session date") for value in session_dates)
    if not dates or len(dates) != len(set(dates)):
        raise ValueError("session_dates must contain unique dates")
    event_day = _date_value(event_date, "event_date")
    root = Path(database_directory).resolve()
    audit_root = Path(audit_directory).resolve()
    ledger = build_intake_ledger(root, config_path=intake_config_path)
    intake_by_symbol = {record.symbol: record for record in ledger.symbols}

    evidence = tuple(_database_evidence(root, audit_root, symbol) for symbol in normalized)
    sessions = tuple(
        _session_probe(root / f"{symbol}.sqlite", symbol, session_date)
        for symbol in normalized
        for session_date in dates
    )
    boundaries = _event_boundaries(event_day)
    events = tuple(
        _event_probe(root / f"{symbol}.sqlite", symbol, event_id, boundary)
        for symbol in normalized
        for event_id, boundary in boundaries
    )

    evidence_ok = all(
        item["sha256_matches_sidecar_and_deep_audit"]
        and item["bytes_match_sidecar_and_deep_audit"]
        and item["sidecar_contract_ok"]
        and item["deep_audit_passed"]
        for item in evidence
    )
    sessions_ok = all(item["session_usable_for_daily_commissioning"] for item in sessions)
    events_ok = all(item["boundary_ready"] for item in events)
    commissioning_passed = evidence_ok and sessions_ok and events_ok
    issues: list[str] = []
    if not evidence_ok:
        issues.append("database evidence gate failed")
    if not sessions_ok:
        issues.append("one or more New York session probes failed")
    if not events_ok:
        issues.append("one or more event boundary probes failed")
    if not ledger.full_intake_ready:
        issues.append("formal 14-symbol intake gate remains closed")
    if not ledger.slow_horizon_ready:
        issues.append("formal 12-symbol slow-horizon gate remains closed")
    if not ledger.fix_w_ready:
        issues.append("formal nine-leg FIX-W gate remains closed")

    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "mode": "two_symbol_research_only_commissioning",
        "symbols": list(normalized),
        "session_dates": [value.isoformat() for value in dates],
        "event_date": event_day.isoformat(),
        "database_evidence": list(evidence),
        "intake": {
            "ledger_verdict": ledger.verdict,
            "symbol_status": {
                symbol: intake_by_symbol[symbol].status for symbol in normalized
            },
            "slow_horizon_formal_ready": ledger.slow_horizon_ready,
            "fix_w_formal_ready": ledger.fix_w_ready,
            "full_14_formal_ready": ledger.full_intake_ready,
        },
        "session_probes": list(sessions),
        "event_probes": list(events),
        "checks": {
            "database_evidence_ok": evidence_ok,
            "session_boundaries_ok": sessions_ok,
            "event_boundaries_ok": events_ok,
        },
        "commissioning_verdict": (
            "commissioning_pass_research_only"
            if commissioning_passed
            else "commissioning_incomplete"
        ),
        "formal_research_ready": False,
        "return_labels_opened": False,
        "factor_outcome_evaluations_added": 0,
        "trading_approval": False,
        "issues": issues,
    }


def write_commissioning_report(report: dict[str, Any], output: str | Path) -> Path:
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return destination.resolve()


__all__ = [
    "COMMISSIONING_SYMBOLS",
    "DEFAULT_EVENT_DATE",
    "DEFAULT_SESSION_DATES",
    "run_two_symbol_commissioning",
    "write_commissioning_report",
]
