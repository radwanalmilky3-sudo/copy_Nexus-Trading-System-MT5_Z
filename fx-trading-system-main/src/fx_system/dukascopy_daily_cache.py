"""Hash-anchored SQLite cache for outcome-blind Dukascopy daily aggregation.

The raw per-symbol databases remain the source of truth.  This module stores
only the daily bars and extraction audits already produced by
``run_dukascopy_daily_from_sqlite``.  A cache can be loaded only when its own
whole-file hash is intact and every source database still matches a formal
transfer receipt.  No return, label, position or factor-result field is part
of the cache contract.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .dukascopy_daily import DukascopyDailyRun
from .dukascopy_event_data import (
    PARSER_VERSION,
    DatabaseTransferVerification,
    TransferIntegrityError,
    verify_database_transfer,
)

DAILY_CACHE_SCHEMA_VERSION = 1
DAILY_CACHE_BUILDER_VERSION = "dukascopy-daily-cache-v1"
_DAILY_FIELDS = (
    "open",
    "high",
    "low",
    "close",
    "bid_open",
    "bid_high",
    "bid_low",
    "bid_close",
    "ask_open",
    "ask_high",
    "ask_low",
    "ask_close",
    "volume",
)
_DAILY_COLUMNS = (
    "symbol",
    "timestamp_ns",
    *_DAILY_FIELDS,
    "session_open_quote_time_ns",
    "session_close_quote_time_ns",
    "tick_count",
)
_SESSION_AUDIT_COLUMNS = (
    "symbol",
    "session_start_local_date",
    "session_end_local_date",
    "session_start_utc_ns",
    "session_end_utc_ns",
    "elapsed_hours",
    "expected_hour_count",
    "decoded_hour_count",
    "no_data_hour_count",
    "missing_hour_count",
    "missing_hours",
    "payload_hashes_verified",
    "duplicate_timestamps_removed",
    "tick_count",
    "session_open_quote_time_ns",
    "session_close_quote_time_ns",
    "open_quote_delay_seconds",
    "close_quote_age_seconds",
    "boundary_quote_max_age_seconds",
    "source_window_complete",
    "daily_bar_emitted",
    "suppression_reason",
    "database_sha256",
)
_TRANSFER_AUDIT_COLUMNS = (
    "symbol",
    "database_path",
    "bytes",
    "database_sha256",
    "database_mtime_ns",
    "manifest_path",
    "manifest_sha256",
    "sidecar_hash_sha256",
    "sidecar_info_sha256",
    "transfer_verified",
)
_EXPECTED_TABLES = {
    "cache_contract",
    "daily_bars",
    "session_audit",
    "transfer_audit",
}


class DukascopyDailyCacheError(ValueError):
    """A daily cache or its source-receipt chain violates the contract."""


@dataclass(frozen=True)
class DukascopyDailyCacheReceipt:
    """Immutable evidence for one materialized daily cache."""

    cache_path: Path
    sha256_path: Path
    receipt_path: Path
    bytes: int
    sha256: str
    symbols: tuple[str, ...]
    session_count: int
    daily_bar_count: int
    source_database_sha256: Mapping[str, str]


def _sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DukascopyDailyCacheError(f"cannot read {label}: {path}") from error
    if not isinstance(value, dict):
        raise DukascopyDailyCacheError(f"{label} must contain a JSON object")
    return value


def _atomic_write_text(path: Path, value: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def _timestamp_ns(value: object, label: str, *, allow_missing: bool = False) -> int | None:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        if allow_missing:
            return None
        raise DukascopyDailyCacheError(f"{label} cannot be missing")
    if timestamp.tzinfo is None:
        raise DukascopyDailyCacheError(f"{label} must include a timezone")
    return int(timestamp.tz_convert("UTC").value)


def _optional_float(value: object, label: str) -> float | None:
    if pd.isna(value):
        return None
    number = float(value)
    if not math.isfinite(number):
        raise DukascopyDailyCacheError(f"{label} must be finite or missing")
    return number


def _required_float(value: object, label: str) -> float:
    number = _optional_float(value, label)
    if number is None:
        raise DukascopyDailyCacheError(f"{label} cannot be missing")
    return number


def _strict_int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool):
        raise DukascopyDailyCacheError(f"{label} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise DukascopyDailyCacheError(f"{label} must be an integer") from error
    if number != value or number < minimum:
        raise DukascopyDailyCacheError(f"{label} must be an integer >= {minimum}")
    return number


def _daily_attrs(run: DukascopyDailyRun, symbols: tuple[str, ...]) -> dict[str, object]:
    attrs: dict[str, object] = {}
    for symbol in symbols:
        symbol_attrs = dict(run.daily_data[symbol].attrs)
        try:
            _canonical_json(symbol_attrs)
        except (TypeError, ValueError) as error:
            raise DukascopyDailyCacheError(
                f"{symbol}: daily frame attributes are not JSON serializable"
            ) from error
        attrs[symbol] = symbol_attrs
    return attrs


def _source_contract(run: DukascopyDailyRun, symbols: tuple[str, ...]) -> dict[str, object]:
    audit = run.transfer_audit
    if tuple(audit.columns) != _TRANSFER_AUDIT_COLUMNS:
        raise DukascopyDailyCacheError("transfer audit columns do not match the cache contract")
    if set(audit["symbol"]) != set(symbols) or len(audit) != len(symbols):
        raise DukascopyDailyCacheError("transfer audit must contain exactly one row per symbol")
    sources: dict[str, object] = {}
    for row in audit.itertuples(index=False):
        symbol = str(row.symbol)
        if row.transfer_verified is not True:
            raise DukascopyDailyCacheError(f"{symbol}: source transfer is not verified")
        sources[symbol] = {
            "database_file": Path(str(row.database_path)).name,
            "bytes": _strict_int(row.bytes, f"{symbol}.bytes"),
            "database_sha256": str(row.database_sha256),
            "database_mtime_ns": _strict_int(
                row.database_mtime_ns, f"{symbol}.database_mtime_ns"
            ),
            "manifest_file": Path(str(row.manifest_path)).name,
            "manifest_sha256": str(row.manifest_sha256),
            "sidecar_hash_sha256": str(row.sidecar_hash_sha256),
            "sidecar_info_sha256": str(row.sidecar_info_sha256),
        }
    return sources


def _validate_run(run: DukascopyDailyRun) -> tuple[str, ...]:
    if not isinstance(run, DukascopyDailyRun):
        raise TypeError("run must be a DukascopyDailyRun")
    symbols = tuple(sorted(run.daily_data))
    if not symbols:
        raise DukascopyDailyCacheError("daily run contains no symbols")
    expected_sessions = tuple(run.requested_session_start_dates)
    if not expected_sessions or any(not isinstance(value, date) for value in expected_sessions):
        raise DukascopyDailyCacheError("requested session dates must be non-empty dates")
    if tuple(sorted(set(expected_sessions))) != expected_sessions:
        raise DukascopyDailyCacheError("requested session dates must be unique and increasing")
    if tuple(run.session_audit.columns) != (
        "symbol",
        "session_start_local_date",
        "session_end_local_date",
        "session_start_utc",
        "session_end_utc",
        "elapsed_hours",
        "expected_hour_count",
        "decoded_hour_count",
        "no_data_hour_count",
        "missing_hour_count",
        "missing_hours",
        "payload_hashes_verified",
        "duplicate_timestamps_removed",
        "tick_count",
        "session_open_quote_time",
        "session_close_quote_time",
        "open_quote_delay_seconds",
        "close_quote_age_seconds",
        "boundary_quote_max_age_seconds",
        "source_window_complete",
        "daily_bar_emitted",
        "suppression_reason",
        "database_sha256",
    ):
        raise DukascopyDailyCacheError("session audit columns do not match the cache contract")
    expected_keys = {(symbol, value) for symbol in symbols for value in expected_sessions}
    observed_keys = set(
        zip(
            run.session_audit["symbol"],
            run.session_audit["session_start_local_date"],
            strict=True,
        )
    )
    if observed_keys != expected_keys or len(run.session_audit) != len(expected_keys):
        raise DukascopyDailyCacheError(
            "session audit is not the requested symbol/session rectangle"
        )
    for symbol in symbols:
        frame = run.daily_data[symbol]
        if list(frame.columns) != [
            *_DAILY_FIELDS[:4],
            *_DAILY_FIELDS[4:12],
            "session_open_quote_time",
            "session_close_quote_time",
            "volume",
            "tick_count",
        ]:
            raise DukascopyDailyCacheError(f"{symbol}: daily frame columns are unexpected")
        if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
            raise DukascopyDailyCacheError(f"{symbol}: daily index must be timezone-aware")
        if not frame.index.is_unique or not frame.index.is_monotonic_increasing:
            raise DukascopyDailyCacheError(f"{symbol}: daily index must be unique and increasing")
    _source_contract(run, symbols)
    return symbols


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE cache_contract (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            contract_json TEXT NOT NULL
        );
        CREATE TABLE daily_bars (
            symbol TEXT NOT NULL,
            timestamp_ns INTEGER NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            bid_open REAL NOT NULL,
            bid_high REAL NOT NULL,
            bid_low REAL NOT NULL,
            bid_close REAL NOT NULL,
            ask_open REAL NOT NULL,
            ask_high REAL NOT NULL,
            ask_low REAL NOT NULL,
            ask_close REAL NOT NULL,
            volume REAL NOT NULL,
            session_open_quote_time_ns INTEGER NOT NULL,
            session_close_quote_time_ns INTEGER NOT NULL,
            tick_count INTEGER NOT NULL CHECK (tick_count > 0),
            PRIMARY KEY (symbol, timestamp_ns)
        );
        CREATE TABLE session_audit (
            symbol TEXT NOT NULL,
            session_start_local_date TEXT NOT NULL,
            session_end_local_date TEXT NOT NULL,
            session_start_utc_ns INTEGER NOT NULL,
            session_end_utc_ns INTEGER NOT NULL,
            elapsed_hours REAL NOT NULL,
            expected_hour_count INTEGER NOT NULL,
            decoded_hour_count INTEGER NOT NULL,
            no_data_hour_count INTEGER NOT NULL,
            missing_hour_count INTEGER NOT NULL,
            missing_hours TEXT NOT NULL,
            payload_hashes_verified INTEGER NOT NULL,
            duplicate_timestamps_removed INTEGER NOT NULL,
            tick_count INTEGER NOT NULL,
            session_open_quote_time_ns INTEGER,
            session_close_quote_time_ns INTEGER,
            open_quote_delay_seconds REAL,
            close_quote_age_seconds REAL,
            boundary_quote_max_age_seconds REAL NOT NULL,
            source_window_complete INTEGER NOT NULL CHECK (source_window_complete IN (0, 1)),
            daily_bar_emitted INTEGER NOT NULL CHECK (daily_bar_emitted IN (0, 1)),
            suppression_reason TEXT,
            database_sha256 TEXT NOT NULL,
            PRIMARY KEY (symbol, session_start_local_date)
        );
        CREATE TABLE transfer_audit (
            symbol TEXT PRIMARY KEY,
            database_path TEXT NOT NULL,
            bytes INTEGER NOT NULL,
            database_sha256 TEXT NOT NULL,
            database_mtime_ns INTEGER NOT NULL,
            manifest_path TEXT NOT NULL,
            manifest_sha256 TEXT NOT NULL,
            sidecar_hash_sha256 TEXT NOT NULL,
            sidecar_info_sha256 TEXT NOT NULL,
            transfer_verified INTEGER NOT NULL CHECK (transfer_verified = 1)
        );
        """
    )


def _daily_rows(run: DukascopyDailyRun, symbols: tuple[str, ...]) -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    for symbol in symbols:
        for timestamp, values in run.daily_data[symbol].iterrows():
            rows.append(
                (
                    symbol,
                    _timestamp_ns(timestamp, f"{symbol}.timestamp"),
                    *(
                        _required_float(values[field], f"{symbol}.{field}")
                        for field in _DAILY_FIELDS
                    ),
                    _timestamp_ns(
                        values["session_open_quote_time"],
                        f"{symbol}.session_open_quote_time",
                    ),
                    _timestamp_ns(
                        values["session_close_quote_time"],
                        f"{symbol}.session_close_quote_time",
                    ),
                    _strict_int(values["tick_count"], f"{symbol}.tick_count", minimum=1),
                )
            )
    return rows


def _session_rows(run: DukascopyDailyRun) -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    for row in run.session_audit.itertuples(index=False):
        rows.append(
            (
                str(row.symbol),
                row.session_start_local_date.isoformat(),
                row.session_end_local_date.isoformat(),
                _timestamp_ns(row.session_start_utc, "session_start_utc"),
                _timestamp_ns(row.session_end_utc, "session_end_utc"),
                _required_float(row.elapsed_hours, "elapsed_hours"),
                _strict_int(row.expected_hour_count, "expected_hour_count"),
                _strict_int(row.decoded_hour_count, "decoded_hour_count"),
                _strict_int(row.no_data_hour_count, "no_data_hour_count"),
                _strict_int(row.missing_hour_count, "missing_hour_count"),
                str(row.missing_hours),
                _strict_int(row.payload_hashes_verified, "payload_hashes_verified"),
                _strict_int(
                    row.duplicate_timestamps_removed, "duplicate_timestamps_removed"
                ),
                _strict_int(row.tick_count, "tick_count"),
                _timestamp_ns(
                    row.session_open_quote_time,
                    "session_open_quote_time",
                    allow_missing=True,
                ),
                _timestamp_ns(
                    row.session_close_quote_time,
                    "session_close_quote_time",
                    allow_missing=True,
                ),
                _optional_float(row.open_quote_delay_seconds, "open_quote_delay_seconds"),
                _optional_float(row.close_quote_age_seconds, "close_quote_age_seconds"),
                _required_float(
                    row.boundary_quote_max_age_seconds,
                    "boundary_quote_max_age_seconds",
                ),
                int(bool(row.source_window_complete)),
                int(bool(row.daily_bar_emitted)),
                None if pd.isna(row.suppression_reason) else str(row.suppression_reason),
                str(row.database_sha256),
            )
        )
    return rows


def _transfer_rows(run: DukascopyDailyRun) -> list[tuple[object, ...]]:
    return [
        (
            str(row.symbol),
            str(row.database_path),
            _strict_int(row.bytes, "bytes"),
            str(row.database_sha256),
            _strict_int(row.database_mtime_ns, "database_mtime_ns"),
            str(row.manifest_path),
            str(row.manifest_sha256),
            str(row.sidecar_hash_sha256),
            str(row.sidecar_info_sha256),
            1,
        )
        for row in run.transfer_audit.itertuples(index=False)
    ]


def write_dukascopy_daily_cache(
    run: DukascopyDailyRun,
    cache_path: str | Path,
    *,
    overwrite: bool = False,
) -> DukascopyDailyCacheReceipt:
    """Atomically persist daily bars plus extraction/transfer audit evidence."""

    symbols = _validate_run(run)
    path = Path(cache_path).resolve()
    if path.suffix.lower() not in {".sqlite", ".db"}:
        raise DukascopyDailyCacheError("daily cache path must end in .sqlite or .db")
    path.parent.mkdir(parents=True, exist_ok=True)
    sha256_path = Path(f"{path}.sha256")
    receipt_path = Path(f"{path}.json")
    artifacts = (path, sha256_path, receipt_path)
    if not overwrite and any(value.exists() for value in artifacts):
        raise FileExistsError("daily cache or sidecar already exists")
    if any(value.is_symlink() for value in artifacts if value.exists()):
        raise DukascopyDailyCacheError("daily cache artifacts cannot be symlinks")

    daily_rows = _daily_rows(run, symbols)
    session_rows = _session_rows(run)
    source_contract = _source_contract(run, symbols)
    contract = {
        "schema_version": DAILY_CACHE_SCHEMA_VERSION,
        "builder_version": DAILY_CACHE_BUILDER_VERSION,
        "source_parser_version": PARSER_VERSION,
        "symbols": list(symbols),
        "requested_session_start_dates": [
            value.isoformat() for value in run.requested_session_start_dates
        ],
        "daily_attrs": _daily_attrs(run, symbols),
        "source_databases": source_contract,
        "row_counts": {
            "daily_bars": len(daily_rows),
            "session_audit": len(session_rows),
            "transfer_audit": len(symbols),
        },
        "contains_returns": False,
        "contains_labels": False,
        "contains_positions": False,
        "return_labels_opened": False,
        "factor_outcome_evaluations_added": 0,
        "trading_approval": False,
    }
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.exists():
        raise DukascopyDailyCacheError(f"orphan temporary cache exists: {temporary}")
    try:
        with sqlite3.connect(temporary) as connection:
            _create_schema(connection)
            connection.execute(
                "INSERT INTO cache_contract VALUES (1, ?)", (_canonical_json(contract),)
            )
            connection.executemany(
                f"INSERT INTO daily_bars VALUES ({','.join('?' for _ in _DAILY_COLUMNS)})",
                daily_rows,
            )
            connection.executemany(
                "INSERT INTO session_audit VALUES "
                f"({','.join('?' for _ in _SESSION_AUDIT_COLUMNS)})",
                session_rows,
            )
            connection.executemany(
                "INSERT INTO transfer_audit VALUES "
                f"({','.join('?' for _ in _TRANSFER_AUDIT_COLUMNS)})",
                _transfer_rows(run),
            )
            check = connection.execute("PRAGMA integrity_check").fetchone()
            if check != ("ok",):
                raise DukascopyDailyCacheError("new daily cache failed SQLite integrity_check")
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    digest = _sha256_file(path)
    byte_count = path.stat().st_size
    receipt_payload = {
        "schema_version": DAILY_CACHE_SCHEMA_VERSION,
        "builder_version": DAILY_CACHE_BUILDER_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "file": path.name,
        "bytes": byte_count,
        "sha256": digest,
        "integrity": "ok",
        "contract": contract,
    }
    _atomic_write_text(sha256_path, f"{digest}  {path.name}\n")
    _atomic_write_text(receipt_path, json.dumps(receipt_payload, indent=2, sort_keys=True) + "\n")
    return _receipt(path, receipt_payload)


def _receipt(path: Path, payload: Mapping[str, Any]) -> DukascopyDailyCacheReceipt:
    contract = payload["contract"]
    sources = contract["source_databases"]
    return DukascopyDailyCacheReceipt(
        cache_path=path,
        sha256_path=Path(f"{path}.sha256"),
        receipt_path=Path(f"{path}.json"),
        bytes=int(payload["bytes"]),
        sha256=str(payload["sha256"]),
        symbols=tuple(contract["symbols"]),
        session_count=len(contract["requested_session_start_dates"]),
        daily_bar_count=int(contract["row_counts"]["daily_bars"]),
        source_database_sha256={
            symbol: str(value["database_sha256"]) for symbol, value in sources.items()
        },
    )


def _verify_cache_artifacts(path: Path) -> tuple[dict[str, Any], str]:
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    sha256_path = Path(f"{path}.sha256")
    receipt_path = Path(f"{path}.json")
    if not sha256_path.is_file() or not receipt_path.is_file():
        raise DukascopyDailyCacheError("daily cache requires .sha256 and .json sidecars")
    receipt = _read_json_object(receipt_path, "daily cache receipt")
    try:
        sidecar_parts = sha256_path.read_text(encoding="utf-8").strip().split(maxsplit=1)
    except (OSError, UnicodeError) as error:
        raise DukascopyDailyCacheError("cannot read daily cache SHA-256 sidecar") from error
    actual = _sha256_file(path)
    if (
        len(sidecar_parts) != 2
        or sidecar_parts[1] != path.name
        or sidecar_parts[0] != actual
        or receipt.get("sha256") != actual
        or receipt.get("file") != path.name
        or receipt.get("bytes") != path.stat().st_size
        or receipt.get("integrity") != "ok"
    ):
        raise DukascopyDailyCacheError("daily cache hash/size sidecars disagree")
    contract = receipt.get("contract")
    if not isinstance(contract, dict):
        raise DukascopyDailyCacheError("daily cache receipt has no contract object")
    required = {
        "schema_version": DAILY_CACHE_SCHEMA_VERSION,
        "builder_version": DAILY_CACHE_BUILDER_VERSION,
        "source_parser_version": PARSER_VERSION,
        "contains_returns": False,
        "contains_labels": False,
        "contains_positions": False,
        "return_labels_opened": False,
        "factor_outcome_evaluations_added": 0,
        "trading_approval": False,
    }
    if any(contract.get(key) != value for key, value in required.items()):
        raise DukascopyDailyCacheError("daily cache semantic contract is incompatible")
    return receipt, actual


def _verify_source_receipts(
    contract: Mapping[str, Any],
    database_directory: Path,
    transfer_manifest_path: Path,
    receipts: Mapping[str, DatabaseTransferVerification] | None,
) -> dict[str, DatabaseTransferVerification]:
    sources = contract.get("source_databases")
    symbols = contract.get("symbols")
    if not isinstance(sources, dict) or not isinstance(symbols, list):
        raise DukascopyDailyCacheError("daily cache source contract is malformed")
    if set(sources) != set(symbols):
        raise DukascopyDailyCacheError("daily cache source symbols disagree")
    verified: dict[str, DatabaseTransferVerification] = {}
    if receipts is not None and set(receipts) != set(symbols):
        raise DukascopyDailyCacheError(
            "provided transfer receipts must match cache symbols exactly"
        )
    for symbol in symbols:
        source = sources[symbol]
        if not isinstance(source, dict):
            raise DukascopyDailyCacheError(f"{symbol}: malformed source contract")
        expected_path = database_directory / str(source.get("database_file"))
        if receipts is None:
            current = verify_database_transfer(
                expected_path,
                transfer_manifest_path,
                symbol=symbol,
            )
        else:
            current = receipts[symbol]
            stat = expected_path.stat()
            if (
                current.database_path != expected_path.resolve()
                or current.manifest_path != transfer_manifest_path.resolve()
                or current.symbol != symbol
                or stat.st_size != current.bytes
                or stat.st_mtime_ns != current.database_mtime_ns
                or _sha256_file(current.manifest_path) != current.manifest_sha256
                or _sha256_file(current.sidecar_hash_path) != current.sidecar_hash_sha256
                or _sha256_file(current.sidecar_info_path) != current.sidecar_info_sha256
            ):
                raise TransferIntegrityError(
                    f"{symbol}: provided transfer receipt no longer matches source artifacts"
                )
        expected = {
            "bytes": current.bytes,
            "database_sha256": current.sha256,
            "database_mtime_ns": current.database_mtime_ns,
            "manifest_sha256": current.manifest_sha256,
            "sidecar_hash_sha256": current.sidecar_hash_sha256,
            "sidecar_info_sha256": current.sidecar_info_sha256,
        }
        if any(source.get(key) != value for key, value in expected.items()):
            raise DukascopyDailyCacheError(
                f"{symbol}: current formal transfer receipt differs from cached source receipt"
            )
        verified[symbol] = current
    return verified


def _table_columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    return tuple(row[1] for row in connection.execute(f"PRAGMA table_info({table})"))


def _load_frames(
    connection: sqlite3.Connection,
    contract: Mapping[str, Any],
) -> DukascopyDailyRun:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if tables != _EXPECTED_TABLES:
        raise DukascopyDailyCacheError("daily cache table set is incompatible")
    expected_columns = {
        "cache_contract": ("singleton", "contract_json"),
        "daily_bars": _DAILY_COLUMNS,
        "session_audit": _SESSION_AUDIT_COLUMNS,
        "transfer_audit": _TRANSFER_AUDIT_COLUMNS,
    }
    if any(
        _table_columns(connection, table) != columns
        for table, columns in expected_columns.items()
    ):
        raise DukascopyDailyCacheError("daily cache table columns are incompatible")
    stored_contract_rows = connection.execute(
        "SELECT contract_json FROM cache_contract WHERE singleton = 1"
    ).fetchall()
    if len(stored_contract_rows) != 1 or stored_contract_rows[0][0] != _canonical_json(contract):
        raise DukascopyDailyCacheError("embedded daily cache contract disagrees with receipt")

    row_counts = contract.get("row_counts")
    if not isinstance(row_counts, dict):
        raise DukascopyDailyCacheError("daily cache row counts are missing")
    for table in ("daily_bars", "session_audit", "transfer_audit"):
        count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if count != row_counts.get(table):
            raise DukascopyDailyCacheError(f"daily cache {table} row count disagrees")

    symbols = tuple(contract["symbols"])
    attrs = contract.get("daily_attrs")
    if not isinstance(attrs, dict) or set(attrs) != set(symbols):
        raise DukascopyDailyCacheError("daily cache frame attributes are malformed")
    daily_data: dict[str, pd.DataFrame] = {}
    daily = pd.read_sql_query(
        "SELECT * FROM daily_bars ORDER BY symbol, timestamp_ns", connection
    )
    for symbol in symbols:
        selected = daily.loc[daily["symbol"] == symbol].drop(columns="symbol").copy()
        timestamps = pd.to_datetime(selected.pop("timestamp_ns"), unit="ns", utc=True)
        selected["session_open_quote_time"] = pd.to_datetime(
            selected.pop("session_open_quote_time_ns"), unit="ns", utc=True
        )
        selected["session_close_quote_time"] = pd.to_datetime(
            selected.pop("session_close_quote_time_ns"), unit="ns", utc=True
        )
        selected = selected[
            [
                *_DAILY_FIELDS[:4],
                *_DAILY_FIELDS[4:12],
                "session_open_quote_time",
                "session_close_quote_time",
                "volume",
                "tick_count",
            ]
        ]
        selected.index = pd.DatetimeIndex(timestamps, name="timestamp")
        selected.attrs.update(attrs[symbol])
        daily_data[symbol] = selected

    session = pd.read_sql_query(
        "SELECT * FROM session_audit ORDER BY session_start_local_date, symbol",
        connection,
    )
    session["session_start_local_date"] = session["session_start_local_date"].map(
        date.fromisoformat
    )
    session["session_end_local_date"] = session["session_end_local_date"].map(date.fromisoformat)
    for stored, restored in (
        ("session_start_utc_ns", "session_start_utc"),
        ("session_end_utc_ns", "session_end_utc"),
        ("session_open_quote_time_ns", "session_open_quote_time"),
        ("session_close_quote_time_ns", "session_close_quote_time"),
    ):
        values = session.pop(stored)
        session[restored] = pd.to_datetime(values, unit="ns", utc=True)
    for field in ("source_window_complete", "daily_bar_emitted"):
        session[field] = session[field].astype(bool)
    session = session[
        [
            "symbol",
            "session_start_local_date",
            "session_end_local_date",
            "session_start_utc",
            "session_end_utc",
            "elapsed_hours",
            "expected_hour_count",
            "decoded_hour_count",
            "no_data_hour_count",
            "missing_hour_count",
            "missing_hours",
            "payload_hashes_verified",
            "duplicate_timestamps_removed",
            "tick_count",
            "session_open_quote_time",
            "session_close_quote_time",
            "open_quote_delay_seconds",
            "close_quote_age_seconds",
            "boundary_quote_max_age_seconds",
            "source_window_complete",
            "daily_bar_emitted",
            "suppression_reason",
            "database_sha256",
        ]
    ]
    transfer = pd.read_sql_query(
        "SELECT * FROM transfer_audit ORDER BY symbol", connection
    )
    transfer["transfer_verified"] = transfer["transfer_verified"].astype(bool)
    requested = tuple(
        date.fromisoformat(value) for value in contract["requested_session_start_dates"]
    )
    run = DukascopyDailyRun(
        daily_data=daily_data,
        session_audit=session,
        transfer_audit=transfer,
        requested_session_start_dates=requested,
    )
    _validate_run(run)
    return run


def load_dukascopy_daily_cache(
    cache_path: str | Path,
    database_directory: str | Path,
    *,
    transfer_manifest_path: str | Path | None = None,
    transfer_receipts: Mapping[str, DatabaseTransferVerification] | None = None,
) -> tuple[DukascopyDailyRun, DukascopyDailyCacheReceipt]:
    """Load a cache after verifying cache bytes and current formal sources.

    Passing receipts from an already verified runner avoids hashing each large
    source database again.  Without receipts, each database is fully verified
    once against the VPS manifest and sidecars before cached rows are trusted.
    """

    path = Path(cache_path).resolve()
    root = Path(database_directory).resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    manifest = (
        Path(transfer_manifest_path).resolve()
        if transfer_manifest_path is not None
        else root / "_sqlite_manifest.json"
    )
    receipt_payload, _ = _verify_cache_artifacts(path)
    contract = receipt_payload["contract"]
    _verify_source_receipts(contract, root, manifest, transfer_receipts)
    try:
        with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as connection:
            connection.execute("PRAGMA query_only = ON")
            check = connection.execute("PRAGMA quick_check").fetchone()
            if check != ("ok",):
                raise DukascopyDailyCacheError("daily cache failed SQLite quick_check")
            run = _load_frames(connection, contract)
    except sqlite3.DatabaseError as error:
        raise DukascopyDailyCacheError("cannot read daily cache SQLite") from error
    return run, _receipt(path, receipt_payload)


__all__ = [
    "DAILY_CACHE_BUILDER_VERSION",
    "DAILY_CACHE_SCHEMA_VERSION",
    "DukascopyDailyCacheError",
    "DukascopyDailyCacheReceipt",
    "load_dukascopy_daily_cache",
    "write_dukascopy_daily_cache",
]
