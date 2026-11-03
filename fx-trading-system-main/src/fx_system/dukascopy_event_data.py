"""Read-only event-window access to per-symbol Dukascopy SQLite databases.

The standalone downloader stores the original compressed ``bi5`` payload for
each UTC hour.  This module deliberately reads that format directly: event
studies can inspect narrow tick windows without first aggregating the complete
database, and without reconstructing or forward-filling quotes.
"""

from __future__ import annotations

import hashlib
import json
import lzma
import math
import re
import sqlite3
import struct
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd

from .data import DUKASCOPY_PRICE_DIVISORS

DATABASE_SCHEMA_VERSION = "1"
PARSER_VERSION = "dukascopy-bi5-v1"
PROVIDER = "dukascopy"
BASE_URL = "https://datafeed.dukascopy.com/datafeed"
TICK_RECORD = struct.Struct(">iiiff")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")

_METADATA_SCHEMA = (
    ("key", "TEXT", 1),
    ("value", "TEXT", 0),
)
_HOURS_SCHEMA = (
    ("hour_utc", "INTEGER", 1),
    ("status", "TEXT", 0),
    ("payload", "BLOB", 0),
    ("payload_sha256", "TEXT", 0),
    ("compressed_bytes", "INTEGER", 0),
    ("tick_count", "INTEGER", 0),
    ("first_offset_ms", "INTEGER", 0),
    ("last_offset_ms", "INTEGER", 0),
    ("http_status", "INTEGER", 0),
    ("retrieved_at", "TEXT", 0),
    ("source_url", "TEXT", 0),
)


class DukascopyEventDataError(ValueError):
    """Base class for event-data contract violations."""


class DatabaseContractError(DukascopyEventDataError):
    """The SQLite schema or metadata does not match the downloader contract."""


class HourStatusError(DukascopyEventDataError):
    """A relevant hourly row has inconsistent status metadata."""


class PayloadIntegrityError(DukascopyEventDataError):
    """A relevant compressed payload fails its hash or binary validation."""


class TransferIntegrityError(DukascopyEventDataError):
    """The transferred SQLite file does not match its manifest and sidecars."""


@dataclass(frozen=True)
class DukascopyDatabaseMetadata:
    """Validated immutable fields from the downloader metadata table."""

    symbol: str
    price_divisor: int
    provider: str
    base_url: str
    database_schema_version: str
    parser_version: str


@dataclass(frozen=True)
class DatabaseTransferVerification:
    """One-time whole-file verification receipt reusable by narrow windows."""

    database_path: Path
    manifest_path: Path
    sidecar_hash_path: Path
    sidecar_info_path: Path
    symbol: str
    bytes: int
    sha256: str
    database_mtime_ns: int
    manifest_sha256: str
    sidecar_hash_sha256: str
    sidecar_info_sha256: str


@dataclass(frozen=True)
class TickWindow:
    """Ticks and audit metadata for a half-open UTC interval ``[start, end)``."""

    ticks: pd.DataFrame
    database_path: Path
    metadata: DukascopyDatabaseMetadata
    start_utc: pd.Timestamp
    end_utc: pd.Timestamp
    expected_hours_utc: tuple[pd.Timestamp, ...]
    decoded_hours_utc: tuple[pd.Timestamp, ...]
    no_data_hours_utc: tuple[pd.Timestamp, ...]
    missing_hours_utc: tuple[pd.Timestamp, ...]
    payload_hashes_verified: int
    duplicate_timestamps_removed: int
    complete: bool
    transfer_verification: DatabaseTransferVerification | None


@dataclass(frozen=True)
class QuoteSelection:
    """An auditable quote candidate selected around a decision timestamp.

    A rejected result may retain the nearest observed quote for diagnosis, but
    callers must require ``accepted`` before treating it as executable.
    """

    selector: Literal["last_at_or_before", "first_at_or_after"]
    decision_timestamp: pd.Timestamp
    quote_timestamp: pd.Timestamp | None
    bid: float | None
    ask: float | None
    bid_size: float | None
    ask_size: float | None
    quote_age: pd.Timedelta | None
    execution_delay: pd.Timedelta | None
    maximum_quote_age: pd.Timedelta | None
    maximum_execution_delay: pd.Timedelta | None
    window_complete: bool
    accepted: bool
    rejection_reason: str | None


def _utc_timestamp(value: object, label: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError(f"{label} must be a finite timestamp")
    if timestamp.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return timestamp.tz_convert("UTC")


def _nonnegative_duration(value: object, label: str) -> pd.Timedelta:
    # Pandas 2.x emits an upstream NumPy generic-timedelta deprecation for
    # otherwise explicit strings such as ``"2s"`` under NumPy 2.4.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="The 'generic' unit for NumPy timedelta is deprecated.*",
            category=DeprecationWarning,
        )
        duration = pd.Timedelta(value)
    if pd.isna(duration) or duration < pd.Timedelta(0, unit="ns"):
        raise ValueError(f"{label} must be a finite non-negative duration")
    return duration


def _candidate_market_hour(timestamp: pd.Timestamp) -> bool:
    """Mirror the deliberately broad FX-week request rule in the downloader."""

    weekday = timestamp.weekday()
    return weekday < 4 or (weekday == 4 and timestamp.hour < 22) or (
        weekday == 6 and timestamp.hour >= 21
    )


def _expected_hours(start: pd.Timestamp, end: pd.Timestamp) -> tuple[pd.Timestamp, ...]:
    hours = pd.date_range(start.floor("h"), end.ceil("h"), freq="1h", inclusive="left")
    return tuple(hour for hour in hours if hour < end and _candidate_market_hour(hour))


def _open_read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json_object(path: Path, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TransferIntegrityError(f"cannot read {label}: {path}") from error
    if not isinstance(payload, dict):
        raise TransferIntegrityError(f"{label} must contain a JSON object: {path}")
    return payload


def _manifest_database_entry(
    manifest: dict[str, object],
    database_path: Path,
    expected_symbol: str | None,
) -> tuple[str, dict[str, object]]:
    if manifest.get("schema_version") != 1:
        raise TransferIntegrityError("transfer manifest schema_version must be 1")
    if manifest.get("parser_version") != PARSER_VERSION:
        raise TransferIntegrityError(
            f"transfer manifest parser_version must be {PARSER_VERSION!r}"
        )
    databases = manifest.get("databases")
    if not isinstance(databases, dict):
        raise TransferIntegrityError("transfer manifest databases must be an object")
    if expected_symbol is not None:
        symbol = expected_symbol.upper().replace("/", "")
        entry_value = databases.get(symbol)
        matches = [(symbol, entry_value)] if entry_value is not None else []
    else:
        matches = [
            (str(symbol).upper(), entry)
            for symbol, entry in databases.items()
            if isinstance(entry, dict) and entry.get("file") == database_path.name
        ]
    if len(matches) != 1:
        raise TransferIntegrityError(
            f"transfer manifest must identify exactly one entry for {database_path.name}"
        )
    symbol, entry_value = matches[0]
    if not isinstance(entry_value, dict):
        raise TransferIntegrityError(f"transfer manifest entry for {symbol} must be an object")
    entry = {str(key): value for key, value in entry_value.items()}
    if entry.get("file") != database_path.name:
        raise TransferIntegrityError(
            f"transfer manifest file for {symbol} does not match {database_path.name}"
        )
    return symbol, entry


def _require_transfer_entry_fields(
    entry: dict[str, object],
    *,
    symbol: str,
    database_path: Path,
) -> tuple[int, str]:
    expected_bytes = entry.get("bytes")
    expected_hash = entry.get("sha256")
    if (
        not isinstance(expected_bytes, int)
        or isinstance(expected_bytes, bool)
        or expected_bytes < 0
    ):
        raise TransferIntegrityError(f"transfer manifest bytes for {symbol} is invalid")
    if not isinstance(expected_hash, str) or _SHA256_PATTERN.fullmatch(expected_hash) is None:
        raise TransferIntegrityError(f"transfer manifest SHA-256 for {symbol} is invalid")
    if entry.get("integrity") != "ok":
        raise TransferIntegrityError(f"transfer manifest does not record integrity=ok for {symbol}")
    metadata = entry.get("metadata")
    if not isinstance(metadata, dict):
        raise TransferIntegrityError(f"transfer manifest metadata for {symbol} is missing")
    required_metadata = {
        "database_schema_version": DATABASE_SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "provider": PROVIDER,
        "base_url": BASE_URL,
        "symbol": symbol,
    }
    for key, expected in required_metadata.items():
        if str(metadata.get(key)) != expected:
            raise TransferIntegrityError(
                f"transfer manifest metadata {key} for {symbol} does not match {expected!r}"
            )
    actual_bytes = database_path.stat().st_size
    if actual_bytes != expected_bytes:
        raise TransferIntegrityError(
            f"{database_path}: size does not match transfer manifest "
            f"({actual_bytes} != {expected_bytes})"
        )
    return expected_bytes, expected_hash


def verify_database_transfer(
    database_path: str | Path,
    transfer_manifest_path: str | Path,
    *,
    symbol: str | None = None,
) -> DatabaseTransferVerification:
    """Verify one closed SQLite file against all VPS transfer artifacts.

    The adjacent ``.sha256`` and ``.json`` sidecars and the directory-level
    transfer manifest must independently agree on filename, byte length,
    symbol, parser contract, and whole-file SHA-256.  SQLite ``quick_check`` and
    the event-reader schema contract are then re-run locally.  The returned
    immutable receipt can be passed to many :func:`load_tick_window` calls, so
    multi-gigabyte whole-file hashing happens once rather than once per event.
    """

    path = Path(database_path).resolve()
    manifest_path = Path(transfer_manifest_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    hash_path = Path(f"{path}.sha256")
    info_path = Path(f"{path}.json")
    if not hash_path.is_file():
        raise TransferIntegrityError(f"database SHA-256 sidecar is required: {hash_path}")
    if not info_path.is_file():
        raise TransferIntegrityError(f"database JSON sidecar is required: {info_path}")

    manifest = _load_json_object(manifest_path, "transfer manifest")
    manifest_symbol, entry = _manifest_database_entry(manifest, path, symbol)
    expected_bytes, expected_hash = _require_transfer_entry_fields(
        entry, symbol=manifest_symbol, database_path=path
    )

    try:
        hash_parts = hash_path.read_text(encoding="utf-8").strip().split(maxsplit=1)
    except (OSError, UnicodeError) as error:
        raise TransferIntegrityError(
            f"cannot read database SHA-256 sidecar: {hash_path}"
        ) from error
    if len(hash_parts) != 2 or _SHA256_PATTERN.fullmatch(hash_parts[0]) is None:
        raise TransferIntegrityError(f"malformed database SHA-256 sidecar: {hash_path}")
    sidecar_filename = hash_parts[1].lstrip("*")
    if hash_parts[0] != expected_hash or sidecar_filename != path.name:
        raise TransferIntegrityError("database SHA-256 sidecar disagrees with transfer manifest")

    info = _load_json_object(info_path, "database JSON sidecar")
    required_info = {
        "schema_version": 1,
        "symbol": manifest_symbol,
        "file": path.name,
        "bytes": expected_bytes,
        "sha256": expected_hash,
        "integrity": "ok",
    }
    for key, expected in required_info.items():
        if info.get(key) != expected:
            raise TransferIntegrityError(
                f"database JSON sidecar {key} disagrees with transfer manifest"
            )
    info_metadata = info.get("metadata")
    if not isinstance(info_metadata, dict):
        raise TransferIntegrityError("database JSON sidecar is missing database metadata")
    required_info_metadata = {
        "database_schema_version": DATABASE_SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "provider": PROVIDER,
        "base_url": BASE_URL,
        "symbol": manifest_symbol,
    }
    for key, expected in required_info_metadata.items():
        if str(info_metadata.get(key)) != expected:
            raise TransferIntegrityError(
                f"database JSON sidecar metadata {key} is incompatible"
            )

    before = path.stat()
    actual_hash = _sha256_file(path)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise TransferIntegrityError(f"database changed while hashing: {path}")
    if actual_hash != expected_hash:
        raise TransferIntegrityError(f"{path}: whole-database SHA-256 mismatch")

    connection = _open_read_only(path)
    try:
        metadata = _validate_database_contract(connection, path, manifest_symbol)
        quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
    finally:
        connection.close()
    if metadata.symbol != manifest_symbol:
        raise TransferIntegrityError("database symbol disagrees with transfer manifest")
    if quick_check != "ok":
        raise TransferIntegrityError(f"{path}: SQLite quick_check failed: {quick_check}")
    return DatabaseTransferVerification(
        database_path=path,
        manifest_path=manifest_path,
        sidecar_hash_path=hash_path,
        sidecar_info_path=info_path,
        symbol=manifest_symbol,
        bytes=expected_bytes,
        sha256=actual_hash,
        database_mtime_ns=after.st_mtime_ns,
        manifest_sha256=_sha256_file(manifest_path),
        sidecar_hash_sha256=_sha256_file(hash_path),
        sidecar_info_sha256=_sha256_file(info_path),
    )


def _validate_transfer_receipt(
    database_path: Path,
    receipt: DatabaseTransferVerification | None,
    *,
    expected_symbol: str | None,
    required: bool,
) -> None:
    if receipt is None:
        if required:
            raise TransferIntegrityError(
                "a DatabaseTransferVerification receipt is required for formal event data"
            )
        return
    if not isinstance(receipt, DatabaseTransferVerification):
        raise TypeError("transfer_verification must be a DatabaseTransferVerification")
    resolved = database_path.resolve()
    if receipt.database_path != resolved:
        raise TransferIntegrityError("transfer verification receipt belongs to another database")
    stat = resolved.stat()
    if stat.st_size != receipt.bytes or stat.st_mtime_ns != receipt.database_mtime_ns:
        raise TransferIntegrityError("database changed after whole-file transfer verification")
    if expected_symbol is not None:
        canonical = expected_symbol.upper().replace("/", "")
        if canonical != receipt.symbol:
            raise TransferIntegrityError(
                "requested symbol disagrees with transfer verification receipt"
            )


def _validate_table_schema(
    connection: sqlite3.Connection,
    table: str,
    expected: tuple[tuple[str, str, int], ...],
) -> None:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    observed = tuple((str(row[1]), str(row[2]).upper(), int(row[5])) for row in rows)
    if observed != expected:
        raise DatabaseContractError(
            f"{table} schema does not match database schema version 1: {observed!r}"
        )
    not_null = {str(row[1]): bool(row[3]) for row in rows}
    required_not_null = {
        "metadata": ("value",),
        "hours": (
            "status",
            "compressed_bytes",
            "tick_count",
            "retrieved_at",
            "source_url",
        ),
    }[table]
    absent = [column for column in required_not_null if not not_null[column]]
    if absent:
        raise DatabaseContractError(f"{table} columns must be NOT NULL: {absent}")


def _validate_database_contract(
    connection: sqlite3.Connection,
    path: Path,
    expected_symbol: str | None,
) -> DukascopyDatabaseMetadata:
    _validate_table_schema(connection, "metadata", _METADATA_SCHEMA)
    _validate_table_schema(connection, "hours", _HOURS_SCHEMA)
    values = {
        str(row["key"]): str(row["value"])
        for row in connection.execute("SELECT key, value FROM metadata")
    }
    expected_values = {
        "database_schema_version": DATABASE_SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "provider": PROVIDER,
        "base_url": BASE_URL,
    }
    for key, expected in expected_values.items():
        if values.get(key) != expected:
            raise DatabaseContractError(
                f"{path}: metadata {key}={values.get(key)!r}, expected {expected!r}"
            )
    symbol = values.get("symbol", "").upper()
    if expected_symbol is not None and symbol != expected_symbol.upper().replace("/", ""):
        raise DatabaseContractError(
            f"{path}: metadata symbol={symbol!r}, expected {expected_symbol!r}"
        )
    try:
        expected_divisor = DUKASCOPY_PRICE_DIVISORS[symbol]
        divisor = int(values["price_divisor"])
    except (KeyError, ValueError) as error:
        raise DatabaseContractError(f"{path}: invalid symbol/price_divisor metadata") from error
    if divisor != expected_divisor:
        raise DatabaseContractError(
            f"{path}: price_divisor={divisor}, expected {expected_divisor} for {symbol}"
        )
    return DukascopyDatabaseMetadata(
        symbol=symbol,
        price_divisor=divisor,
        provider=values["provider"],
        base_url=values["base_url"],
        database_schema_version=values["database_schema_version"],
        parser_version=values["parser_version"],
    )


def _validate_no_data_hour(row: sqlite3.Row, hour: pd.Timestamp) -> None:
    if any(
        (
            row["payload"] is not None,
            row["payload_sha256"] is not None,
            int(row["compressed_bytes"]) != 0,
            int(row["tick_count"]) != 0,
            row["first_offset_ms"] is not None,
            row["last_offset_ms"] is not None,
        )
    ):
        raise HourStatusError(f"{hour}: inconsistent no_data hour fields")


def _decode_ok_hour(
    row: sqlite3.Row,
    hour: pd.Timestamp,
    divisor: int,
    start: pd.Timestamp,
    end: pd.Timestamp,
    include_sizes: bool,
) -> tuple[list[dict[str, object]], int]:
    payload_value = row["payload"]
    expected_hash = row["payload_sha256"]
    if payload_value is None or not isinstance(expected_hash, str):
        raise HourStatusError(f"{hour}: ok hour is missing payload/hash")
    payload = bytes(payload_value)
    if int(row["compressed_bytes"]) != len(payload):
        raise HourStatusError(f"{hour}: compressed_bytes does not match payload length")
    actual_hash = hashlib.sha256(payload).hexdigest()
    if not expected_hash or actual_hash != expected_hash.lower():
        raise PayloadIntegrityError(f"{hour}: payload SHA-256 mismatch")
    try:
        raw = lzma.decompress(payload)
    except lzma.LZMAError as error:
        raise PayloadIntegrityError(f"{hour}: invalid LZMA payload") from error
    if not raw or len(raw) % TICK_RECORD.size:
        raise PayloadIntegrityError(f"{hour}: invalid decompressed bi5 payload length")

    records: list[dict[str, object]] = []
    previous_offset = -1
    first_offset: int | None = None
    ticks = 0
    duplicates = 0
    last_in_window_offset: int | None = None
    for offset, ask_integer, bid_integer, ask_size, bid_size in TICK_RECORD.iter_unpack(raw):
        if offset < 0 or offset >= 3_600_000 or offset < previous_offset:
            raise PayloadIntegrityError(f"{hour}: invalid or unordered tick offset")
        if bid_integer <= 0 or ask_integer < bid_integer:
            raise PayloadIntegrityError(f"{hour}: invalid or crossed bid/ask quote")
        if not all(
            (
                math.isfinite(ask_size),
                math.isfinite(bid_size),
                ask_size >= 0,
                bid_size >= 0,
            )
        ):
            raise PayloadIntegrityError(f"{hour}: invalid bid/ask size")
        if first_offset is None:
            first_offset = offset
        previous_offset = offset
        ticks += 1
        timestamp = hour + pd.Timedelta(offset, unit="ms")
        if start <= timestamp < end:
            record: dict[str, object] = {
                "timestamp": timestamp,
                "bid": bid_integer / divisor,
                "ask": ask_integer / divisor,
            }
            if include_sizes:
                record["bid_size"] = float(bid_size)
                record["ask_size"] = float(ask_size)
            if last_in_window_offset == offset:
                records[-1] = record
                duplicates += 1
            else:
                records.append(record)
            last_in_window_offset = offset

    if ticks != int(row["tick_count"]):
        raise PayloadIntegrityError(f"{hour}: tick_count does not match payload")
    if first_offset != row["first_offset_ms"] or previous_offset != row["last_offset_ms"]:
        raise PayloadIntegrityError(f"{hour}: first/last tick offsets do not match payload")
    return records, duplicates


def load_tick_window(
    database_path: str | Path,
    start: object,
    end: object,
    *,
    symbol: str | None = None,
    include_sizes: bool = False,
    transfer_verification: DatabaseTransferVerification | None = None,
    require_transfer_verification: bool = False,
) -> TickWindow:
    """Load and validate ticks in a half-open UTC event window.

    Only hourly rows intersecting the interval under the downloader's broad FX
    week calendar are fetched and decoded.  A recorded ``no_data`` hour is
    complete-but-empty; an absent expected row makes ``complete`` false.  No
    quote is synthesized at a boundary or across an empty/missing hour.
    """

    path = Path(database_path)
    _validate_transfer_receipt(
        path,
        transfer_verification,
        expected_symbol=symbol,
        required=require_transfer_verification,
    )
    start_utc = _utc_timestamp(start, "start")
    end_utc = _utc_timestamp(end, "end")
    if start_utc >= end_utc:
        raise ValueError("start must be earlier than end")
    expected_hours = _expected_hours(start_utc, end_utc)
    expected_epoch = {int(hour.timestamp()): hour for hour in expected_hours}

    connection = _open_read_only(path)
    try:
        metadata = _validate_database_contract(connection, path, symbol)
        if expected_hours:
            first_epoch = min(expected_epoch)
            last_epoch = max(expected_epoch)
            rows = connection.execute(
                "SELECT hour_utc, status, payload, payload_sha256, compressed_bytes, "
                "tick_count, first_offset_ms, last_offset_ms "
                "FROM hours WHERE hour_utc >= ? AND hour_utc <= ? ORDER BY hour_utc",
                (first_epoch, last_epoch),
            ).fetchall()
        else:
            rows = []
    finally:
        connection.close()

    row_by_epoch: dict[int, sqlite3.Row] = {}
    for row in rows:
        hour_epoch = int(row["hour_utc"])
        if hour_epoch in expected_epoch:
            row_by_epoch[hour_epoch] = row

    tick_records: list[dict[str, object]] = []
    decoded: list[pd.Timestamp] = []
    no_data: list[pd.Timestamp] = []
    missing: list[pd.Timestamp] = []
    duplicates = 0
    hashes_verified = 0
    for hour_epoch, hour in expected_epoch.items():
        row = row_by_epoch.get(hour_epoch)
        if row is None:
            missing.append(hour)
            continue
        status = str(row["status"])
        if status == "no_data":
            _validate_no_data_hour(row, hour)
            no_data.append(hour)
        elif status == "ok":
            records, removed = _decode_ok_hour(
                row,
                hour,
                metadata.price_divisor,
                start_utc,
                end_utc,
                include_sizes,
            )
            tick_records.extend(records)
            duplicates += removed
            hashes_verified += 1
            decoded.append(hour)
        else:
            raise HourStatusError(f"{hour}: unsupported hour status {status!r}")

    columns = ["timestamp", "bid", "ask"]
    if include_sizes:
        columns.extend(("bid_size", "ask_size"))
    ticks = pd.DataFrame.from_records(tick_records, columns=columns)
    if ticks.empty:
        ticks = ticks.astype({"bid": "float64", "ask": "float64"})
        ticks["timestamp"] = pd.Series([], dtype="datetime64[ns, UTC]")
        if include_sizes:
            ticks = ticks.astype({"bid_size": "float64", "ask_size": "float64"})
    else:
        ticks = ticks.sort_values("timestamp", kind="stable").reset_index(drop=True)
        if ticks["timestamp"].duplicated().any() or not ticks["timestamp"].is_monotonic_increasing:
            raise PayloadIntegrityError("decoded ticks are not strictly ordered and unique")
        if (ticks["ask"] < ticks["bid"]).any():
            raise PayloadIntegrityError("decoded ticks contain crossed bid/ask quotes")

    complete = not missing
    ticks.attrs.update(
        {
            "source_provider": PROVIDER,
            "source_symbol": metadata.symbol,
            "source_parser_version": metadata.parser_version,
            "window_start_utc": start_utc.isoformat(),
            "window_end_utc": end_utc.isoformat(),
            "window_complete": complete,
            "forward_filled": False,
            "database_transfer_verified": transfer_verification is not None,
            "database_sha256": (
                transfer_verification.sha256 if transfer_verification is not None else None
            ),
        }
    )
    return TickWindow(
        ticks=ticks,
        database_path=path,
        metadata=metadata,
        start_utc=start_utc,
        end_utc=end_utc,
        expected_hours_utc=expected_hours,
        decoded_hours_utc=tuple(decoded),
        no_data_hours_utc=tuple(no_data),
        missing_hours_utc=tuple(missing),
        payload_hashes_verified=hashes_verified,
        duplicate_timestamps_removed=duplicates,
        complete=complete,
        transfer_verification=transfer_verification,
    )


def _candidate_values(row: pd.Series) -> tuple[float, float, float | None, float | None]:
    bid_size = float(row["bid_size"]) if "bid_size" in row else None
    ask_size = float(row["ask_size"]) if "ask_size" in row else None
    return float(row["bid"]), float(row["ask"]), bid_size, ask_size


def _require_decision_covered(
    window: TickWindow, decision: pd.Timestamp, *, allow_right_boundary: bool
) -> None:
    right_covered = (
        decision <= window.end_utc if allow_right_boundary else decision < window.end_utc
    )
    if decision < window.start_utc or not right_covered:
        interval = "[start, end]" if allow_right_boundary else "[start, end)"
        raise ValueError(f"decision_timestamp must be covered by the window {interval}")


def select_last_tick_at_or_before(
    window: TickWindow,
    decision_timestamp: object,
    *,
    maximum_quote_age: object,
) -> QuoteSelection:
    """Select the last observed quote at/before a decision, with a staleness gate."""

    decision = _utc_timestamp(decision_timestamp, "decision_timestamp")
    _require_decision_covered(window, decision, allow_right_boundary=True)
    maximum_age = _nonnegative_duration(maximum_quote_age, "maximum_quote_age")
    eligible = window.ticks.loc[window.ticks["timestamp"] <= decision]
    if eligible.empty:
        return QuoteSelection(
            "last_at_or_before",
            decision,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            maximum_age,
            None,
            window.complete,
            False,
            "no_tick_at_or_before_decision",
        )
    row = eligible.iloc[-1]
    quote_timestamp = pd.Timestamp(row["timestamp"])
    age = decision - quote_timestamp
    bid, ask, bid_size, ask_size = _candidate_values(row)
    reason = None
    if not window.complete:
        reason = "incomplete_window"
    elif age > maximum_age:
        reason = "maximum_quote_age_exceeded"
    return QuoteSelection(
        "last_at_or_before",
        decision,
        quote_timestamp,
        bid,
        ask,
        bid_size,
        ask_size,
        age,
        None,
        maximum_age,
        None,
        window.complete,
        reason is None,
        reason,
    )


def select_first_tick_at_or_after(
    window: TickWindow,
    decision_timestamp: object,
    *,
    maximum_execution_delay: object,
) -> QuoteSelection:
    """Select the first observed quote at/after a decision, with a delay gate."""

    decision = _utc_timestamp(decision_timestamp, "decision_timestamp")
    _require_decision_covered(window, decision, allow_right_boundary=False)
    maximum_delay = _nonnegative_duration(
        maximum_execution_delay, "maximum_execution_delay"
    )
    eligible = window.ticks.loc[window.ticks["timestamp"] >= decision]
    if eligible.empty:
        return QuoteSelection(
            "first_at_or_after",
            decision,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            maximum_delay,
            window.complete,
            False,
            "no_tick_at_or_after_decision",
        )
    row = eligible.iloc[0]
    quote_timestamp = pd.Timestamp(row["timestamp"])
    delay = quote_timestamp - decision
    bid, ask, bid_size, ask_size = _candidate_values(row)
    reason = None
    if not window.complete:
        reason = "incomplete_window"
    elif delay > maximum_delay:
        reason = "maximum_execution_delay_exceeded"
    return QuoteSelection(
        "first_at_or_after",
        decision,
        quote_timestamp,
        bid,
        ask,
        bid_size,
        ask_size,
        None,
        delay,
        None,
        maximum_delay,
        window.complete,
        reason is None,
        reason,
    )
