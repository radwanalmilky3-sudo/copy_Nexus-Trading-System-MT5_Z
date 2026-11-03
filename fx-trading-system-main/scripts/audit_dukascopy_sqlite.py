#!/usr/bin/env python3
"""Read-only, streaming integrity audit for a Dukascopy per-symbol SQLite database.

The downloader stores original compressed bi5 payloads one UTC hour at a time.
This tool validates that storage contract and summarizes quote microstructure
without aggregating or modifying the source database.
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import lzma
import math
import re
import sqlite3
import struct
import sys
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

TOOL_VERSION = "1.0.0"
DATABASE_SCHEMA_VERSION = "1"
PARSER_VERSION = "dukascopy-bi5-v1"
PROVIDER = "dukascopy"
BASE_URL = "https://datafeed.dukascopy.com/datafeed"
TICK_RECORD = struct.Struct(">iiiff")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
ISSUE_SAMPLE_LIMIT = 8
TOP_ITEM_LIMIT = 20

PRICE_DIVISORS = {
    "AUDCAD": 100_000,
    "AUDCHF": 100_000,
    "AUDJPY": 1_000,
    "AUDNZD": 100_000,
    "AUDUSD": 100_000,
    "CADCHF": 100_000,
    "CADJPY": 1_000,
    "CHFJPY": 1_000,
    "EURAUD": 100_000,
    "EURCAD": 100_000,
    "EURCHF": 100_000,
    "EURGBP": 100_000,
    "EURJPY": 1_000,
    "EURNZD": 100_000,
    "EURUSD": 100_000,
    "GBPAUD": 100_000,
    "GBPCAD": 100_000,
    "GBPCHF": 100_000,
    "GBPJPY": 1_000,
    "GBPNZD": 100_000,
    "GBPUSD": 100_000,
    "NZDCAD": 100_000,
    "NZDCHF": 100_000,
    "NZDJPY": 1_000,
    "NZDUSD": 100_000,
    "USDCAD": 100_000,
    "USDCHF": 100_000,
    "USDJPY": 1_000,
    "USDNOK": 100_000,
    "USDSEK": 100_000,
}

METADATA_SCHEMA = (
    ("key", "TEXT", 1),
    ("value", "TEXT", 0),
)
HOURS_SCHEMA = (
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

WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
SPREAD_PIP_LABELS = (
    "<0.10",
    "0.10-0.24",
    "0.25-0.49",
    "0.50-0.99",
    "1.00-1.99",
    "2.00-4.99",
    "5.00-9.99",
    "10.00-24.99",
    ">=25.00",
)
GAP_LABELS = (
    "0ms",
    "1-9ms",
    "10-99ms",
    "100-999ms",
    "1-9.999s",
    "10-59.999s",
    "60-299.999s",
    ">=300s",
)


@dataclass(frozen=True)
class StressWindow:
    name: str
    start_epoch: int
    end_epoch: int
    description: str


def _epoch(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


STRESS_WINDOWS = (
    StressWindow(
        "brexit_referendum",
        _epoch("2016-06-23T00:00:00Z"),
        _epoch("2016-06-25T00:00:00Z"),
        "UK EU referendum vote and result",
    ),
    StressWindow(
        "covid_march_2020",
        _epoch("2020-03-09T00:00:00Z"),
        _epoch("2020-03-21T00:00:00Z"),
        "COVID-19 global market stress",
    ),
    StressWindow(
        "uk_mini_budget",
        _epoch("2022-09-23T00:00:00Z"),
        _epoch("2022-09-27T00:00:00Z"),
        "UK mini-budget and sterling dislocation",
    ),
)


@dataclass
class RunningStats:
    count: int = 0
    total: float = 0.0
    minimum: float | None = None
    maximum: float | None = None

    def add(self, value: float) -> None:
        self.count += 1
        self.total += value
        self.minimum = value if self.minimum is None else min(self.minimum, value)
        self.maximum = value if self.maximum is None else max(self.maximum, value)

    def merge(self, other: RunningStats) -> None:
        if other.count == 0:
            return
        self.count += other.count
        self.total += other.total
        self.minimum = other.minimum if self.minimum is None else min(self.minimum, other.minimum)
        self.maximum = other.maximum if self.maximum is None else max(self.maximum, other.maximum)

    def as_dict(self) -> dict[str, float | int | None]:
        if self.count == 0:
            return {"count": 0, "minimum": None, "maximum": None, "mean": None}
        return {
            "count": self.count,
            "minimum": _rounded(self.minimum),
            "maximum": _rounded(self.maximum),
            "mean": _rounded(self.total / self.count),
        }


@dataclass
class QuoteStats:
    count: int = 0
    mid: RunningStats = field(default_factory=RunningStats)
    spread_pips: RunningStats = field(default_factory=RunningStats)
    spread_bps: RunningStats = field(default_factory=RunningStats)
    spread_histogram: list[int] = field(default_factory=lambda: [0] * len(SPREAD_PIP_LABELS))

    def add(self, bid_integer: int, ask_integer: int, divisor: int) -> tuple[float, float, float]:
        spread_pips = (ask_integer - bid_integer) * 10_000.0 / divisor
        mid = (ask_integer + bid_integer) / (2.0 * divisor)
        spread_bps = (ask_integer - bid_integer) * 10_000.0 / ((ask_integer + bid_integer) / 2.0)
        self.count += 1
        self.mid.add(mid)
        self.spread_pips.add(spread_pips)
        self.spread_bps.add(spread_bps)
        self.spread_histogram[_spread_pip_bucket(spread_pips)] += 1
        return mid, spread_pips, spread_bps

    def merge(self, other: QuoteStats) -> None:
        self.count += other.count
        self.mid.merge(other.mid)
        self.spread_pips.merge(other.spread_pips)
        self.spread_bps.merge(other.spread_bps)
        for index, value in enumerate(other.spread_histogram):
            self.spread_histogram[index] += value

    def as_dict(self) -> dict[str, object]:
        return {
            "valid_quote_ticks": self.count,
            "mid": self.mid.as_dict(),
            "spread_pips": self.spread_pips.as_dict(),
            "spread_bps": self.spread_bps.as_dict(),
            "spread_pips_histogram": dict(
                zip(SPREAD_PIP_LABELS, self.spread_histogram, strict=True)
            ),
        }


@dataclass
class GapStats:
    values: RunningStats = field(default_factory=RunningStats)
    buckets: list[int] = field(default_factory=lambda: [0] * len(GAP_LABELS))

    def add(self, gap_ms: int) -> int:
        bucket = _gap_bucket(gap_ms)
        self.values.add(float(gap_ms))
        self.buckets[bucket] += 1
        return bucket

    def as_dict(self) -> dict[str, object]:
        return {
            "milliseconds": self.values.as_dict(),
            "histogram": dict(zip(GAP_LABELS, self.buckets, strict=True)),
        }


@dataclass
class JumpStats:
    signed_bps: RunningStats = field(default_factory=RunningStats)
    absolute_bps: RunningStats = field(default_factory=RunningStats)
    absolute_by_gap: list[RunningStats] = field(
        default_factory=lambda: [RunningStats() for _ in GAP_LABELS]
    )

    def add(self, gap_bucket: int, signed_bps: float) -> None:
        absolute_bps = abs(signed_bps)
        self.signed_bps.add(signed_bps)
        self.absolute_bps.add(absolute_bps)
        self.absolute_by_gap[gap_bucket].add(absolute_bps)

    def as_dict(self) -> dict[str, object]:
        return {
            "signed_bps": self.signed_bps.as_dict(),
            "absolute_bps": self.absolute_bps.as_dict(),
            "absolute_bps_by_intertick_gap": {
                label: stats.as_dict()
                for label, stats in zip(GAP_LABELS, self.absolute_by_gap, strict=True)
            },
        }


@dataclass
class IssueCollector:
    counts: Counter[str] = field(default_factory=Counter)
    severity_counts: Counter[str] = field(default_factory=Counter)
    examples: dict[str, list[dict[str, object]]] = field(default_factory=dict)

    def add(
        self,
        severity: str,
        code: str,
        message: str,
        *,
        hour_epoch: int | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        if severity not in {"error", "warning"}:
            raise ValueError(f"unknown issue severity: {severity}")
        self.counts[code] += 1
        self.severity_counts[severity] += 1
        samples = self.examples.setdefault(code, [])
        if len(samples) >= ISSUE_SAMPLE_LIMIT:
            return
        sample: dict[str, object] = {"severity": severity, "message": message}
        if hour_epoch is not None:
            sample["hour_utc"] = _iso_hour(hour_epoch)
        if details:
            sample["details"] = details
        samples.append(sample)

    @property
    def passed(self) -> bool:
        return self.severity_counts["error"] == 0

    def as_dict(self) -> dict[str, object]:
        return {
            "error_count": self.severity_counts["error"],
            "warning_count": self.severity_counts["warning"],
            "counts_by_code": dict(sorted(self.counts.items())),
            "examples": {key: self.examples[key] for key in sorted(self.examples)},
        }


@dataclass
class TopItems:
    limit: int = TOP_ITEM_LIMIT
    heap: list[tuple[float, int, dict[str, object]]] = field(default_factory=list)
    sequence: int = 0

    def qualifies(self, value: float) -> bool:
        return len(self.heap) < self.limit or value > self.heap[0][0]

    def add(self, value: float, item: dict[str, object]) -> None:
        self.sequence += 1
        candidate = (value, self.sequence, item)
        if len(self.heap) < self.limit:
            heapq.heappush(self.heap, candidate)
        elif value > self.heap[0][0]:
            heapq.heapreplace(self.heap, candidate)

    def as_list(self) -> list[dict[str, object]]:
        return [item for _, _, item in sorted(self.heap, reverse=True)]


@dataclass
class NoDataRuns:
    segments: list[dict[str, object]] = field(default_factory=list)
    start_epoch: int | None = None
    last_epoch: int | None = None
    count: int = 0

    def add(self, hour_epoch: int) -> None:
        if self.last_epoch is not None and hour_epoch == self.last_epoch + 3600:
            self.last_epoch = hour_epoch
            self.count += 1
            return
        self._finish()
        self.start_epoch = hour_epoch
        self.last_epoch = hour_epoch
        self.count = 1

    def _finish(self) -> None:
        if self.start_epoch is None or self.last_epoch is None:
            return
        self.segments.append(
            {
                "start_utc": _iso_hour(self.start_epoch),
                "end_exclusive_utc": _iso_hour(self.last_epoch + 3600),
                "hours": self.count,
            }
        )
        self.start_epoch = None
        self.last_epoch = None
        self.count = 0

    def finish(self) -> None:
        self._finish()


@dataclass
class StressSummary:
    window: StressWindow
    candidate_hours_in_audit_range: int
    ok_hours: int = 0
    no_data_hours: int = 0
    missing_hours: int = 0
    other_status_hours: int = 0
    tick_records: int = 0
    quote_stats: QuoteStats = field(default_factory=QuoteStats)

    def as_dict(self) -> dict[str, object]:
        return {
            "description": self.window.description,
            "start_utc": _iso_hour(self.window.start_epoch),
            "end_exclusive_utc": _iso_hour(self.window.end_epoch),
            "candidate_hours_in_audit_range": self.candidate_hours_in_audit_range,
            "ok_hours": self.ok_hours,
            "no_data_hours": self.no_data_hours,
            "missing_hours": self.missing_hours,
            "other_status_hours": self.other_status_hours,
            "tick_records": self.tick_records,
            "quotes": self.quote_stats.as_dict(),
        }


@dataclass
class PayloadResult:
    tick_records: int = 0
    valid_quote_ticks: int = 0
    uncompressed_bytes: int = 0
    duplicate_offsets: int = 0
    quote_stats: QuoteStats = field(default_factory=QuoteStats)


@dataclass
class TickTracker:
    timestamp_ms: int | None = None
    mid: float | None = None


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 12)


def _iso_hour(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_timestamp_ms(epoch_ms: int) -> str:
    return datetime.fromtimestamp(epoch_ms / 1000, tz=UTC).isoformat().replace(
        "+00:00", "Z"
    )


def _normalize_symbol(value: str) -> str:
    symbol = value.upper().replace("/", "").replace("_", "").strip()
    if symbol not in PRICE_DIVISORS:
        raise ValueError(f"unsupported or missing price divisor for symbol {value!r}")
    return symbol


def _candidate_market_hour(hour: datetime) -> bool:
    weekday = hour.weekday()
    return weekday < 4 or (weekday == 4 and hour.hour < 22) or (weekday == 6 and hour.hour >= 21)


def _iter_candidate_hours(start_epoch: int, end_epoch: int) -> Iterator[int]:
    current = start_epoch
    while current < end_epoch:
        if _candidate_market_hour(datetime.fromtimestamp(current, tz=UTC)):
            yield current
        current += 3600


def _count_candidate_hours(start_epoch: int, end_epoch: int) -> int:
    return sum(1 for _ in _iter_candidate_hours(start_epoch, end_epoch))


def _source_url(symbol: str, hour_epoch: int) -> str:
    hour = datetime.fromtimestamp(hour_epoch, tz=UTC)
    return (
        f"{BASE_URL}/{symbol}/{hour.year:04d}/{hour.month - 1:02d}/{hour.day:02d}/"
        f"{hour.hour:02d}h_ticks.bi5"
    )


def _spread_pip_bucket(value: float) -> int:
    if value < 0.10:
        return 0
    if value < 0.25:
        return 1
    if value < 0.50:
        return 2
    if value < 1.00:
        return 3
    if value < 2.00:
        return 4
    if value < 5.00:
        return 5
    if value < 10.00:
        return 6
    if value < 25.00:
        return 7
    return 8


def _gap_bucket(value: int) -> int:
    if value == 0:
        return 0
    if value < 10:
        return 1
    if value < 100:
        return 2
    if value < 1_000:
        return 3
    if value < 10_000:
        return 4
    if value < 60_000:
        return 5
    if value < 300_000:
        return 6
    return 7


def _is_strict_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_hour_metadata(value: object, key: str) -> int:
    if not isinstance(value, str):
        raise ValueError(f"metadata {key} must be an ISO-8601 UTC hour")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"metadata {key} must include a timezone")
    parsed = parsed.astimezone(UTC)
    if parsed.minute or parsed.second or parsed.microsecond:
        raise ValueError(f"metadata {key} must be aligned to an hour")
    return int(parsed.timestamp())


def _open_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _table_schema(connection: sqlite3.Connection, table: str) -> list[tuple[str, str, int, int]]:
    return [
        (str(row[1]), str(row[2]).upper(), int(row[3]), int(row[5]))
        for row in connection.execute(f"PRAGMA table_info({table})")
    ]


def _validate_table_schema(
    connection: sqlite3.Connection,
    table: str,
    expected: tuple[tuple[str, str, int], ...],
    required_not_null: tuple[str, ...],
    issues: IssueCollector,
) -> bool:
    observed = _table_schema(connection, table)
    compact = tuple((name, type_name, primary_key) for name, type_name, _, primary_key in observed)
    valid = True
    if compact != expected:
        issues.add(
            "error",
            "schema_mismatch",
            f"{table} columns do not match database schema version 1",
            details={"table": table, "observed": [list(item) for item in compact]},
        )
        valid = False
    not_null = {name: bool(value) for name, _, value, _ in observed}
    missing = [name for name in required_not_null if not not_null.get(name, False)]
    if missing:
        issues.add(
            "error",
            "schema_not_null_mismatch",
            f"{table} required NOT NULL columns are absent",
            details={"table": table, "columns": missing},
        )
        valid = False
    return valid


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata_values(connection: sqlite3.Connection) -> dict[str, str]:
    return {
        str(row["key"]): str(row["value"])
        for row in connection.execute("SELECT key, value FROM metadata")
    }


def _stress_names(hour_epoch: int) -> tuple[str, ...]:
    return tuple(
        window.name
        for window in STRESS_WINDOWS
        if window.start_epoch <= hour_epoch < window.end_epoch
    )


def _payload_error(
    issues: IssueCollector,
    code: str,
    message: str,
    hour_epoch: int,
    details: dict[str, object] | None = None,
) -> None:
    issues.add("error", code, message, hour_epoch=hour_epoch, details=details)


def _validate_common_hour_fields(
    row: sqlite3.Row,
    hour_epoch: int,
    symbol: str,
    issues: IssueCollector,
) -> None:
    retrieved_at = row["retrieved_at"]
    if not isinstance(retrieved_at, str) or not retrieved_at.strip():
        _payload_error(
            issues,
            "invalid_retrieved_at",
            "retrieved_at must be a non-empty string",
            hour_epoch,
        )
    else:
        try:
            parsed = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
        except ValueError:
            _payload_error(
                issues,
                "invalid_retrieved_at",
                "retrieved_at is not ISO-8601",
                hour_epoch,
            )
        else:
            if parsed.tzinfo is None:
                _payload_error(
                    issues,
                    "invalid_retrieved_at",
                    "retrieved_at must include a timezone",
                    hour_epoch,
                )
    expected_url = _source_url(symbol, hour_epoch)
    if row["source_url"] != expected_url:
        _payload_error(
            issues,
            "source_url_mismatch",
            "source_url does not match the downloader's frozen Dukascopy path",
            hour_epoch,
            {"expected": expected_url, "actual": row["source_url"]},
        )


def _validate_no_data_row(row: sqlite3.Row, hour_epoch: int, issues: IssueCollector) -> None:
    invalid: list[str] = []
    if row["payload"] is not None:
        invalid.append("payload")
    if row["payload_sha256"] is not None:
        invalid.append("payload_sha256")
    if row["compressed_bytes"] != 0:
        invalid.append("compressed_bytes")
    if row["tick_count"] != 0:
        invalid.append("tick_count")
    if row["first_offset_ms"] is not None:
        invalid.append("first_offset_ms")
    if row["last_offset_ms"] is not None:
        invalid.append("last_offset_ms")
    if invalid:
        _payload_error(
            issues,
            "inconsistent_no_data_fields",
            "no_data row contains payload or non-empty tick fields",
            hour_epoch,
            {"fields": invalid},
        )
    status = row["http_status"]
    if not _is_strict_integer(status) or status not in {200, 404}:
        _payload_error(
            issues,
            "invalid_no_data_http_status",
            "no_data row must record HTTP 200 or 404",
            hour_epoch,
            {"actual": status},
        )


def _audit_ok_payload(
    row: sqlite3.Row,
    *,
    hour_epoch: int,
    divisor: int,
    issues: IssueCollector,
    payload_counts: Counter[str],
    tick_counts: Counter[str],
    tracker: TickTracker,
    gap_stats: GapStats,
    jump_stats: JumpStats,
    widest_spreads: TopItems,
    largest_gaps: TopItems,
    largest_jumps: TopItems,
) -> PayloadResult:
    result = PayloadResult()
    payload_counts["ok_rows"] += 1
    http_status = row["http_status"]
    if not _is_strict_integer(http_status) or http_status != 200:
        _payload_error(
            issues,
            "invalid_ok_http_status",
            "ok row must record HTTP 200",
            hour_epoch,
            {"actual": http_status},
        )
    payload_value = row["payload"]
    if not isinstance(payload_value, (bytes, bytearray, memoryview)):
        payload_counts["missing_or_invalid_payload"] += 1
        _payload_error(issues, "missing_ok_payload", "ok row has no binary payload", hour_epoch)
        return result
    payload = bytes(payload_value)
    expected_bytes = row["compressed_bytes"]
    if not _is_strict_integer(expected_bytes) or expected_bytes != len(payload):
        payload_counts["compressed_byte_mismatches"] += 1
        _payload_error(
            issues,
            "compressed_bytes_mismatch",
            "compressed_bytes does not equal the payload length",
            hour_epoch,
            {"expected": expected_bytes, "actual": len(payload)},
        )
    payload_counts["compressed_bytes"] += len(payload)
    expected_hash = row["payload_sha256"]
    actual_hash = hashlib.sha256(payload).hexdigest()
    payload_counts["sha256_checked"] += 1
    if (
        not isinstance(expected_hash, str)
        or SHA256_PATTERN.fullmatch(expected_hash.lower()) is None
    ):
        payload_counts["sha256_invalid_metadata"] += 1
        _payload_error(
            issues,
            "invalid_payload_sha256",
            "payload_sha256 is not a SHA-256 digest",
            hour_epoch,
        )
    elif expected_hash.lower() != actual_hash:
        payload_counts["sha256_mismatches"] += 1
        _payload_error(
            issues,
            "payload_sha256_mismatch",
            "payload SHA-256 does not match the row metadata",
            hour_epoch,
            {"expected": expected_hash.lower(), "actual": actual_hash},
        )
    else:
        payload_counts["sha256_matches"] += 1
    try:
        raw = lzma.decompress(payload)
    except lzma.LZMAError as error:
        payload_counts["lzma_errors"] += 1
        _payload_error(
            issues,
            "invalid_lzma_payload",
            "payload cannot be decompressed as LZMA bi5",
            hour_epoch,
            {"error": str(error)},
        )
        return result
    payload_counts["lzma_decoded_rows"] += 1
    payload_counts["uncompressed_bytes"] += len(raw)
    result.uncompressed_bytes = len(raw)
    if not raw:
        payload_counts["empty_ok_payloads"] += 1
        _payload_error(
            issues,
            "empty_ok_payload",
            "ok payload decompresses to zero records",
            hour_epoch,
        )
        return result
    if len(raw) % TICK_RECORD.size:
        payload_counts["invalid_record_lengths"] += 1
        _payload_error(
            issues,
            "invalid_tick_record_length",
            "decompressed payload is not a multiple of 20 bytes",
            hour_epoch,
            {"uncompressed_bytes": len(raw)},
        )
        return result
    payload_counts["record_shape_valid_rows"] += 1
    first_offset: int | None = None
    last_offset: int | None = None
    previous_offset = -1
    for offset, ask_integer, bid_integer, ask_volume, bid_volume in TICK_RECORD.iter_unpack(raw):
        result.tick_records += 1
        tick_counts["records"] += 1
        offset_valid = True
        if offset < 0 or offset >= 3_600_000:
            tick_counts["invalid_offset"] += 1
            offset_valid = False
        if offset < previous_offset:
            tick_counts["unordered_offset"] += 1
            offset_valid = False
        elif offset == previous_offset:
            tick_counts["duplicate_offset"] += 1
            result.duplicate_offsets += 1
        if first_offset is None:
            first_offset = offset
        previous_offset = offset
        last_offset = offset
        bid_valid = bid_integer > 0
        ask_valid = ask_integer >= bid_integer
        volume_valid = (
            math.isfinite(ask_volume)
            and math.isfinite(bid_volume)
            and ask_volume >= 0.0
            and bid_volume >= 0.0
        )
        if bid_integer == 0:
            tick_counts["zero_bid"] += 1
        if ask_integer == 0:
            tick_counts["zero_ask"] += 1
        if not bid_valid:
            tick_counts["bid_nonpositive"] += 1
        if ask_integer <= 0:
            tick_counts["ask_nonpositive"] += 1
        if not ask_valid:
            tick_counts["crossed_quote"] += 1
        if not volume_valid:
            tick_counts["invalid_volume"] += 1
        if not (offset_valid and bid_valid and ask_valid and volume_valid):
            tick_counts["invalid_quote_records"] += 1
            continue
        mid, spread_pips, spread_bps = result.quote_stats.add(bid_integer, ask_integer, divisor)
        result.valid_quote_ticks += 1
        timestamp_ms = hour_epoch * 1000 + offset
        if widest_spreads.qualifies(spread_pips):
            widest_spreads.add(
                spread_pips,
                {
                    "timestamp_utc": _iso_timestamp_ms(timestamp_ms),
                    "bid": _rounded(bid_integer / divisor),
                    "ask": _rounded(ask_integer / divisor),
                    "spread_pips": _rounded(spread_pips),
                    "spread_bps": _rounded(spread_bps),
                },
            )
        if tracker.timestamp_ms is not None and tracker.mid is not None:
            gap_ms = timestamp_ms - tracker.timestamp_ms
            if gap_ms < 0:
                tick_counts["global_timestamp_regression"] += 1
            else:
                bucket = gap_stats.add(gap_ms)
                if largest_gaps.qualifies(float(gap_ms)):
                    largest_gaps.add(
                        float(gap_ms),
                        {
                            "previous_timestamp_utc": _iso_timestamp_ms(
                                tracker.timestamp_ms
                            ),
                            "timestamp_utc": _iso_timestamp_ms(timestamp_ms),
                            "gap_ms": gap_ms,
                        },
                    )
                signed_jump_bps = math.log(mid / tracker.mid) * 10_000.0
                jump_stats.add(bucket, signed_jump_bps)
                absolute_jump_bps = abs(signed_jump_bps)
                if largest_jumps.qualifies(absolute_jump_bps):
                    largest_jumps.add(
                        absolute_jump_bps,
                        {
                            "previous_timestamp_utc": _iso_timestamp_ms(
                                tracker.timestamp_ms
                            ),
                            "timestamp_utc": _iso_timestamp_ms(timestamp_ms),
                            "gap_ms": gap_ms,
                            "previous_mid": _rounded(tracker.mid),
                            "mid": _rounded(mid),
                            "jump_bps": _rounded(signed_jump_bps),
                            "absolute_jump_bps": _rounded(absolute_jump_bps),
                        },
                    )
        tracker.timestamp_ms = timestamp_ms
        tracker.mid = mid
    stored_tick_count = row["tick_count"]
    if not _is_strict_integer(stored_tick_count) or stored_tick_count != result.tick_records:
        payload_counts["tick_count_mismatches"] += 1
        _payload_error(
            issues,
            "tick_count_mismatch",
            "tick_count does not equal the decoded 20-byte record count",
            hour_epoch,
            {"expected": stored_tick_count, "actual": result.tick_records},
        )
    first_stored = row["first_offset_ms"]
    last_stored = row["last_offset_ms"]
    if (
        not _is_strict_integer(first_stored)
        or not _is_strict_integer(last_stored)
        or first_stored != first_offset
        or last_stored != last_offset
    ):
        payload_counts["offset_field_mismatches"] += 1
        _payload_error(
            issues,
            "offset_field_mismatch",
            "first_offset_ms or last_offset_ms does not match decoded records",
            hour_epoch,
            {
                "expected_first": first_stored,
                "actual_first": first_offset,
                "expected_last": last_stored,
                "actual_last": last_offset,
            },
        )
    return result


def _coverage_bounds(
    connection: sqlite3.Connection,
    metadata: dict[str, str],
    issues: IssueCollector,
) -> tuple[int, int, str] | None:
    start_value = metadata.get("requested_start")
    end_value = metadata.get("requested_end_exclusive")
    if start_value is not None or end_value is not None:
        if start_value is None or end_value is None:
            issues.add(
                "error",
                "incomplete_requested_range_metadata",
                "requested_start and requested_end_exclusive must either both be present "
                "or both be absent",
            )
            return None
        try:
            start = _parse_hour_metadata(start_value, "requested_start")
            end = _parse_hour_metadata(end_value, "requested_end_exclusive")
        except ValueError as error:
            issues.add("error", "invalid_requested_range_metadata", str(error))
            return None
        if start >= end:
            issues.add(
                "error",
                "invalid_requested_range_metadata",
                "requested_start must be earlier than requested_end_exclusive",
            )
            return None
        return start, end, "metadata"
    bounds = connection.execute("SELECT MIN(hour_utc), MAX(hour_utc) FROM hours").fetchone()
    if bounds is None or bounds[0] is None or bounds[1] is None:
        issues.add("error", "empty_hours_table", "hours table has no rows")
        return None
    if not _is_strict_integer(bounds[0]) or not _is_strict_integer(bounds[1]):
        issues.add("error", "invalid_hour_utc", "hours bounds are not integer epoch seconds")
        return None
    issues.add(
        "warning",
        "coverage_bounds_derived_from_rows",
        "requested range metadata is absent; coverage is bounded by stored rows",
    )
    return int(bounds[0]), int(bounds[1]) + 3600, "derived_from_rows"


def _check_metadata_counts(
    metadata: dict[str, str],
    *,
    expected_hours: int,
    ok_hours: int,
    no_data_hours: int,
    missing_hours: int,
    issues: IssueCollector,
) -> None:
    actual = {
        "expected_hours": expected_hours,
        "completed_hours": ok_hours + no_data_hours,
        "ok_hours": ok_hours,
        "no_data_hours": no_data_hours,
        "missing_hours": missing_hours,
    }
    for key, expected in actual.items():
        value = metadata.get(key)
        if value is None:
            issues.add(
                "warning",
                "missing_summary_metadata",
                f"metadata {key} is absent",
                details={"key": key},
            )
            continue
        try:
            observed = int(value)
        except ValueError:
            issues.add(
                "error",
                "invalid_summary_metadata",
                f"metadata {key} is not an integer",
                details={"key": key, "actual": value},
            )
            continue
        if observed != expected:
            issues.add(
                "error",
                "summary_metadata_mismatch",
                f"metadata {key} does not match audited rows",
                details={"key": key, "expected": expected, "actual": observed},
            )


def _base_report(path: Path, symbol: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "tool": "audit_dukascopy_sqlite",
        "tool_version": TOOL_VERSION,
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "database": {
            "path": str(path.resolve()),
            "bytes": path.stat().st_size if path.exists() else None,
            "requested_symbol": symbol,
        },
    }


def audit_database(
    database_path: str | Path,
    symbol: str,
    *,
    expected_file_sha256: str | None = None,
) -> dict[str, object]:
    """Audit one database without writing to it or retaining all ticks in memory."""

    path = Path(database_path)
    normalized_symbol = _normalize_symbol(symbol)
    issues = IssueCollector()
    report = _base_report(path, normalized_symbol)
    transport: dict[str, object] = {"file_sha256_checked": False}
    if expected_file_sha256 is not None:
        expected = expected_file_sha256.strip().lower()
        if SHA256_PATTERN.fullmatch(expected) is None:
            raise ValueError("expected_file_sha256 must be a lowercase or uppercase SHA-256 digest")
        if path.is_file():
            actual = _file_sha256(path)
            transport = {
                "file_sha256_checked": True,
                "expected_file_sha256": expected,
                "actual_file_sha256": actual,
                "matched": actual == expected,
            }
            if actual != expected:
                issues.add(
                    "error",
                    "file_sha256_mismatch",
                    "database file does not match the supplied whole-file SHA-256",
                    details={"expected": expected, "actual": actual},
                )
    report["transport"] = transport
    if not path.is_file():
        issues.add("error", "database_not_found", f"database does not exist: {path}")
        report["result"] = {"passed": False}
        report["issues"] = issues.as_dict()
        return report
    try:
        connection = _open_read_only(path)
    except sqlite3.Error as error:
        issues.add(
            "error",
            "sqlite_open_error",
            "cannot open SQLite database read-only",
            details={"error": str(error)},
        )
        report["result"] = {"passed": False}
        report["issues"] = issues.as_dict()
        return report
    try:
        quick_check = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
        report["database"] = {
            **report["database"],
            "sqlite_quick_check": quick_check,
        }
        if quick_check != ["ok"]:
            issues.add(
                "error",
                "sqlite_quick_check_failed",
                "SQLite PRAGMA quick_check did not return ok",
                details={"result": quick_check},
            )
        table_names = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        missing_tables = sorted({"metadata", "hours"} - table_names)
        if missing_tables:
            issues.add(
                "error",
                "missing_required_table",
                "required downloader table is absent",
                details={"tables": missing_tables},
            )
            report["result"] = {"passed": False}
            report["issues"] = issues.as_dict()
            return report
        schema_valid = _validate_table_schema(
            connection,
            "metadata",
            METADATA_SCHEMA,
            ("value",),
            issues,
        )
        schema_valid &= _validate_table_schema(
            connection,
            "hours",
            HOURS_SCHEMA,
            ("status", "compressed_bytes", "tick_count", "retrieved_at", "source_url"),
            issues,
        )
        extras = sorted(table_names - {"metadata", "hours"})
        if extras:
            issues.add(
                "warning",
                "unexpected_sqlite_tables",
                "database contains tables outside the downloader contract",
                details={"tables": extras},
            )
        report["contract"] = {
            "schema_valid": schema_valid,
            "metadata_schema": [list(item) for item in METADATA_SCHEMA],
            "hours_schema": [list(item) for item in HOURS_SCHEMA],
        }
        if not schema_valid:
            report["result"] = {"passed": False}
            report["issues"] = issues.as_dict()
            return report
        metadata = _metadata_values(connection)
        report["metadata"] = dict(sorted(metadata.items()))
        expected_metadata = {
            "database_schema_version": DATABASE_SCHEMA_VERSION,
            "parser_version": PARSER_VERSION,
            "provider": PROVIDER,
            "base_url": BASE_URL,
            "symbol": normalized_symbol,
            "price_divisor": str(PRICE_DIVISORS[normalized_symbol]),
        }
        metadata_valid = True
        for key, expected in expected_metadata.items():
            observed = metadata.get(key)
            if observed != expected:
                issues.add(
                    "error",
                    "metadata_mismatch",
                    f"metadata {key} does not match the downloader contract",
                    details={"key": key, "expected": expected, "actual": observed},
                )
                metadata_valid = False
        report["contract"] = {**report["contract"], "metadata_valid": metadata_valid}
        if not metadata_valid:
            report["result"] = {"passed": False}
            report["issues"] = issues.as_dict()
            return report
        bounds = _coverage_bounds(connection, metadata, issues)
        if bounds is None:
            report["result"] = {"passed": False}
            report["issues"] = issues.as_dict()
            return report
        start_epoch, end_epoch, bounds_source = bounds
        expected_iter = iter(_iter_candidate_hours(start_epoch, end_epoch))
        current_expected = next(expected_iter, None)
        expected_hours = _count_candidate_hours(start_epoch, end_epoch)
        stress = {
            window.name: StressSummary(
                window=window,
                candidate_hours_in_audit_range=_count_candidate_hours(
                    max(start_epoch, window.start_epoch), min(end_epoch, window.end_epoch)
                )
                if max(start_epoch, window.start_epoch) < min(end_epoch, window.end_epoch)
                else 0,
            )
            for window in STRESS_WINDOWS
        }
        coverage_statuses: Counter[str] = Counter()
        all_statuses: Counter[str] = Counter()
        no_data_by_year: Counter[str] = Counter()
        no_data_by_weekday: Counter[str] = Counter()
        no_data_by_hour: Counter[str] = Counter()
        no_data_runs = NoDataRuns()
        missing_hours = 0
        missing_samples: list[str] = []
        unexpected_rows = 0
        unexpected_samples: list[str] = []
        payload_counts: Counter[str] = Counter()
        tick_counts: Counter[str] = Counter()
        all_quotes = QuoteStats()
        quotes_by_year: dict[str, QuoteStats] = {}
        quotes_by_weekday: dict[str, QuoteStats] = {}
        quotes_by_utc_hour: dict[str, QuoteStats] = {}
        gap_stats = GapStats()
        jump_stats = JumpStats()
        widest_spreads = TopItems()
        largest_gaps = TopItems()
        largest_jumps = TopItems()
        tracker = TickTracker()

        def note_missing(hour_epoch: int) -> None:
            nonlocal missing_hours
            missing_hours += 1
            if len(missing_samples) < ISSUE_SAMPLE_LIMIT:
                missing_samples.append(_iso_hour(hour_epoch))
            issues.add(
                "error",
                "missing_candidate_hour",
                "candidate FX market hour is absent from the database",
                hour_epoch=hour_epoch,
            )
            for name in _stress_names(hour_epoch):
                stress[name].missing_hours += 1

        query = (
            "SELECT hour_utc, status, payload, payload_sha256, compressed_bytes, tick_count, "
            "first_offset_ms, last_offset_ms, http_status, retrieved_at, source_url "
            "FROM hours ORDER BY hour_utc"
        )
        for row in connection.execute(query):
            row_hour = row["hour_utc"]
            if not _is_strict_integer(row_hour):
                issues.add(
                    "error",
                    "invalid_hour_utc",
                    "hour_utc must be an integer UTC epoch second",
                    details={"actual": row_hour},
                )
                continue
            hour_epoch = int(row_hour)
            while current_expected is not None and current_expected < hour_epoch:
                note_missing(current_expected)
                current_expected = next(expected_iter, None)
            in_coverage = current_expected == hour_epoch
            if in_coverage:
                current_expected = next(expected_iter, None)
            else:
                unexpected_rows += 1
                if len(unexpected_samples) < ISSUE_SAMPLE_LIMIT:
                    unexpected_samples.append(_iso_hour(hour_epoch))
                issues.add(
                    "error",
                    "unexpected_hour_row",
                    "hours row lies outside the requested candidate FX-hour calendar",
                    hour_epoch=hour_epoch,
                )
            if hour_epoch % 3600:
                issues.add(
                    "error",
                    "unaligned_hour_utc",
                    "hour_utc is not aligned to a full UTC hour",
                    hour_epoch=hour_epoch,
                )
            if not _candidate_market_hour(datetime.fromtimestamp(hour_epoch, tz=UTC)):
                issues.add(
                    "error",
                    "non_market_hour_row",
                    "hours row is outside the downloader's FX market-week calendar",
                    hour_epoch=hour_epoch,
                )
            status = row["status"]
            if not isinstance(status, str) or status not in {"ok", "no_data"}:
                all_statuses[str(status)] += 1
                if in_coverage:
                    coverage_statuses["other"] += 1
                issues.add(
                    "error",
                    "invalid_hour_status",
                    "status must be exactly ok or no_data",
                    hour_epoch=hour_epoch,
                    details={"actual": status},
                )
                for name in _stress_names(hour_epoch):
                    stress[name].other_status_hours += 1
                continue
            all_statuses[status] += 1
            _validate_common_hour_fields(row, hour_epoch, normalized_symbol, issues)
            if in_coverage:
                coverage_statuses[status] += 1
            matching_stress = _stress_names(hour_epoch) if in_coverage else ()
            if status == "no_data":
                _validate_no_data_row(row, hour_epoch, issues)
                if in_coverage:
                    no_data_runs.add(hour_epoch)
                    hour = datetime.fromtimestamp(hour_epoch, tz=UTC)
                    no_data_by_year[str(hour.year)] += 1
                    no_data_by_weekday[WEEKDAY_NAMES[hour.weekday()]] += 1
                    no_data_by_hour[f"{hour.hour:02d}"] += 1
                    for name in matching_stress:
                        stress[name].no_data_hours += 1
                continue
            payload_result = _audit_ok_payload(
                row,
                hour_epoch=hour_epoch,
                divisor=PRICE_DIVISORS[normalized_symbol],
                issues=issues,
                payload_counts=payload_counts,
                tick_counts=tick_counts,
                tracker=tracker,
                gap_stats=gap_stats,
                jump_stats=jump_stats,
                widest_spreads=widest_spreads,
                largest_gaps=largest_gaps,
                largest_jumps=largest_jumps,
            )
            if not in_coverage:
                continue
            for name in matching_stress:
                stress[name].ok_hours += 1
                stress[name].tick_records += payload_result.tick_records
                stress[name].quote_stats.merge(payload_result.quote_stats)
            all_quotes.merge(payload_result.quote_stats)
            hour = datetime.fromtimestamp(hour_epoch, tz=UTC)
            year_key = str(hour.year)
            weekday_key = WEEKDAY_NAMES[hour.weekday()]
            utc_hour_key = f"{hour.hour:02d}"
            quotes_by_year.setdefault(year_key, QuoteStats()).merge(payload_result.quote_stats)
            quotes_by_weekday.setdefault(weekday_key, QuoteStats()).merge(
                payload_result.quote_stats
            )
            quotes_by_utc_hour.setdefault(utc_hour_key, QuoteStats()).merge(
                payload_result.quote_stats
            )
        while current_expected is not None:
            note_missing(current_expected)
            current_expected = next(expected_iter, None)
        no_data_runs.finish()
        _check_metadata_counts(
            metadata,
            expected_hours=expected_hours,
            ok_hours=coverage_statuses["ok"],
            no_data_hours=coverage_statuses["no_data"],
            missing_hours=missing_hours,
            issues=issues,
        )
        report["coverage"] = {
            "bounds_source": bounds_source,
            "start_utc": _iso_hour(start_epoch),
            "end_exclusive_utc": _iso_hour(end_epoch),
            "expected_candidate_hours": expected_hours,
            "ok_hours": coverage_statuses["ok"],
            "no_data_hours": coverage_statuses["no_data"],
            "other_status_hours": coverage_statuses["other"],
            "missing_hours": missing_hours,
            "missing_hour_samples": missing_samples,
            "unexpected_rows": unexpected_rows,
            "unexpected_hour_samples": unexpected_samples,
            "all_rows_by_status": dict(sorted(all_statuses.items())),
            "completed_fraction": _rounded(
                (coverage_statuses["ok"] + coverage_statuses["no_data"]) / expected_hours
                if expected_hours
                else 0.0
            ),
        }
        report["no_data"] = {
            "count": coverage_statuses["no_data"],
            "share_of_candidate_hours": _rounded(
                coverage_statuses["no_data"] / expected_hours if expected_hours else 0.0
            ),
            "by_year": dict(sorted(no_data_by_year.items())),
            "by_weekday": {name: no_data_by_weekday[name] for name in WEEKDAY_NAMES},
            "by_utc_hour": {f"{hour:02d}": no_data_by_hour[f"{hour:02d}"] for hour in range(24)},
            "continuous_segments": no_data_runs.segments,
            "longest_continuous_segment_hours": max(
                (int(segment["hours"]) for segment in no_data_runs.segments), default=0
            ),
        }
        report["payloads"] = {
            "ok_rows_seen": payload_counts["ok_rows"],
            "compressed_bytes_from_payloads": payload_counts["compressed_bytes"],
            "uncompressed_bytes": payload_counts["uncompressed_bytes"],
            "sha256_checked": payload_counts["sha256_checked"],
            "sha256_matches": payload_counts["sha256_matches"],
            "sha256_mismatches": payload_counts["sha256_mismatches"],
            "sha256_invalid_metadata": payload_counts["sha256_invalid_metadata"],
            "lzma_decoded_rows": payload_counts["lzma_decoded_rows"],
            "lzma_errors": payload_counts["lzma_errors"],
            "record_shape_valid_rows": payload_counts["record_shape_valid_rows"],
            "invalid_record_lengths": payload_counts["invalid_record_lengths"],
            "empty_ok_payloads": payload_counts["empty_ok_payloads"],
            "tick_count_mismatches": payload_counts["tick_count_mismatches"],
            "offset_field_mismatches": payload_counts["offset_field_mismatches"],
        }
        report["ticks"] = {
            "records": tick_counts["records"],
            "valid_quote_ticks": all_quotes.count,
            "invalid_quote_records": tick_counts["invalid_quote_records"],
            "invalid_offset": tick_counts["invalid_offset"],
            "unordered_offset": tick_counts["unordered_offset"],
            "duplicate_offset": tick_counts["duplicate_offset"],
            "zero_bid": tick_counts["zero_bid"],
            "zero_ask": tick_counts["zero_ask"],
            "bid_nonpositive": tick_counts["bid_nonpositive"],
            "ask_nonpositive": tick_counts["ask_nonpositive"],
            "crossed_quote": tick_counts["crossed_quote"],
            "invalid_volume": tick_counts["invalid_volume"],
            "global_timestamp_regression": tick_counts["global_timestamp_regression"],
        }
        report["market"] = {
            "quotes": all_quotes.as_dict(),
            "widest_spreads": widest_spreads.as_list(),
            "intertick_gaps": gap_stats.as_dict(),
            "largest_intertick_gaps": largest_gaps.as_list(),
            "single_tick_log_jumps": jump_stats.as_dict(),
            "largest_single_tick_log_jumps": largest_jumps.as_list(),
            "by_year": {key: quotes_by_year[key].as_dict() for key in sorted(quotes_by_year)},
            "by_weekday": {
                key: quotes_by_weekday[key].as_dict()
                for key in WEEKDAY_NAMES
                if key in quotes_by_weekday
            },
            "by_utc_hour": {
                key: quotes_by_utc_hour[key].as_dict() for key in sorted(quotes_by_utc_hour)
            },
        }
        report["stress_windows"] = {key: stress[key].as_dict() for key in sorted(stress)}
    except sqlite3.Error as error:
        issues.add(
            "error",
            "sqlite_query_error",
            "SQLite audit query failed",
            details={"error": str(error)},
        )
    finally:
        connection.close()
    report["result"] = {"passed": issues.passed}
    report["issues"] = issues.as_dict()
    return report


def write_report(report: dict[str, object], output_dir: str | Path, symbol: str) -> Path:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / f"{_normalize_symbol(symbol)}_dukascopy_audit.json"
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path, help="Per-symbol Dukascopy SQLite database")
    parser.add_argument("--symbol", required=True, help="Expected symbol, for example GBPUSD")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/dukascopy_audit"),
        help="Directory for the human-readable JSON report",
    )
    parser.add_argument(
        "--expected-file-sha256",
        help="Optional whole-file SHA-256 to verify before the SQLite audit",
    )
    parser.add_argument("--stdout", action="store_true", help="Also print the full JSON report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = audit_database(
            args.database,
            args.symbol,
            expected_file_sha256=args.expected_file_sha256,
        )
        output = write_report(report, args.output_dir, args.symbol)
    except (OSError, ValueError) as error:
        print(f"audit failed before a report could be written: {error}", file=sys.stderr)
        return 2
    if args.stdout:
        print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    result = report["result"]
    passed = isinstance(result, dict) and result.get("passed") is True
    print(f"audit={'PASS' if passed else 'FAIL'} report={output}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
