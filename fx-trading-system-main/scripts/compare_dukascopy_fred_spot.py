#!/usr/bin/env python3
"""Compare Dukascopy spot quotes with an independent FRED daily FX series."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import lzma
import math
import sqlite3
import struct
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from statistics import fmean, median
from zoneinfo import ZoneInfo

TICK_RECORD = struct.Struct(">iiiff")
PARSER_VERSION = "dukascopy-bi5-v1"
PROVIDER = "dukascopy"
TOP_LIMIT = 20


@dataclass(frozen=True)
class Reference:
    observation_date: date
    value: float
    target_epoch_ms: int


@dataclass(frozen=True)
class Match:
    observation_date: date
    target_epoch_ms: int
    quote_epoch_ms: int
    reference: float
    mid: float
    difference_bps: float


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata(connection: sqlite3.Connection) -> dict[str, str]:
    return {
        str(key): str(value)
        for key, value in connection.execute("SELECT key, value FROM metadata")
    }


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("database requested range must include a timezone")
    return parsed.astimezone(UTC)


def _load_references(
    path: Path,
    series_id: str,
    timezone: ZoneInfo,
    reference_time: time,
    start: datetime,
    end: datetime,
) -> tuple[list[Reference], dict[str, int]]:
    counters: Counter[str] = Counter()
    references: list[Reference] = []
    previous_date: date | None = None
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["observation_date", series_id]:
            raise ValueError(f"unexpected FRED CSV header: {reader.fieldnames!r}")
        for row in reader:
            counters["csv_rows"] += 1
            observation_date = date.fromisoformat(row["observation_date"])
            if previous_date is not None and observation_date <= previous_date:
                raise ValueError("FRED observation dates must be unique and sorted")
            previous_date = observation_date
            raw_value = row[series_id].strip()
            if raw_value in {"", "."}:
                counters["missing_values"] += 1
                continue
            value = float(raw_value)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"invalid FRED value for {observation_date}: {raw_value!r}")
            target = datetime.combine(observation_date, reference_time, tzinfo=timezone)
            target_utc = target.astimezone(UTC)
            if not start <= target_utc < end:
                counters["outside_database_range"] += 1
                continue
            references.append(
                Reference(
                    observation_date=observation_date,
                    value=value,
                    target_epoch_ms=int(target_utc.timestamp() * 1000),
                )
            )
    counters["eligible_values"] = len(references)
    return references, dict(sorted(counters.items()))


def _first_quote_at_or_after(
    payload: bytes,
    payload_sha256: object,
    target_offset_ms: int,
    divisor: int,
) -> tuple[int, float]:
    if not isinstance(payload_sha256, str):
        raise ValueError("sampled payload has no SHA-256")
    actual_hash = hashlib.sha256(payload).hexdigest()
    if actual_hash != payload_sha256.lower():
        raise ValueError("sampled payload SHA-256 mismatch")
    try:
        raw = lzma.decompress(payload)
    except lzma.LZMAError as error:
        raise ValueError("sampled payload is not valid LZMA") from error
    if not raw or len(raw) % TICK_RECORD.size:
        raise ValueError("sampled payload does not contain complete 20-byte ticks")
    previous_offset = -1
    for offset, ask_integer, bid_integer, ask_volume, bid_volume in TICK_RECORD.iter_unpack(raw):
        if offset < previous_offset or not 0 <= offset < 3_600_000:
            raise ValueError("sampled payload has invalid tick offsets")
        previous_offset = offset
        if bid_integer <= 0 or ask_integer < bid_integer:
            raise ValueError("sampled payload has invalid bid/ask")
        if not all(
            math.isfinite(value) and value >= 0 for value in (ask_volume, bid_volume)
        ):
            raise ValueError("sampled payload has invalid quote sizes")
        if offset >= target_offset_ms:
            return offset, (ask_integer + bid_integer) / (2.0 * divisor)
    raise ValueError("sampled hour has no quote at or after the reference time")


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = fmean(left)
    right_mean = fmean(right)
    covariance = math.fsum(
        (x - left_mean) * (y - right_mean) for x, y in zip(left, right, strict=True)
    )
    left_variance = math.fsum((x - left_mean) ** 2 for x in left)
    right_variance = math.fsum((y - right_mean) ** 2 for y in right)
    denominator = math.sqrt(left_variance * right_variance)
    return covariance / denominator if denominator else None


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 12)


def compare(
    database_path: Path,
    reference_path: Path,
    *,
    symbol: str,
    series_id: str,
    timezone_name: str = "America/New_York",
    reference_hour: int = 12,
    maximum_delay_seconds: float = 60.0,
) -> dict[str, object]:
    symbol = symbol.upper().replace("/", "").replace("_", "")
    if not 0 <= reference_hour <= 23:
        raise ValueError("reference_hour must be between 0 and 23")
    if maximum_delay_seconds < 0:
        raise ValueError("maximum_delay_seconds must be non-negative")
    timezone = ZoneInfo(timezone_name)
    connection = sqlite3.connect(f"{database_path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    try:
        metadata = _metadata(connection)
        expected = {
            "provider": PROVIDER,
            "parser_version": PARSER_VERSION,
            "symbol": symbol,
        }
        for key, value in expected.items():
            if metadata.get(key) != value:
                raise ValueError(f"database metadata {key} does not match {value!r}")
        divisor = int(metadata["price_divisor"])
        start = _parse_utc(metadata["requested_start"])
        end = _parse_utc(metadata["requested_end_exclusive"])
        references, reference_counts = _load_references(
            reference_path,
            series_id,
            timezone,
            time(reference_hour),
            start,
            end,
        )
        unmatched: Counter[str] = Counter()
        matches: list[Match] = []
        maximum_delay_ms = int(maximum_delay_seconds * 1000)
        for reference in references:
            hour_epoch = reference.target_epoch_ms // 3_600_000 * 3600
            target_offset_ms = reference.target_epoch_ms - hour_epoch * 1000
            row = connection.execute(
                "SELECT status, payload, payload_sha256 FROM hours WHERE hour_utc = ?",
                (hour_epoch,),
            ).fetchone()
            if row is None:
                unmatched["missing_hour"] += 1
                continue
            if row["status"] != "ok":
                unmatched[f"status_{row['status']}"] += 1
                continue
            payload_value = row["payload"]
            if not isinstance(payload_value, (bytes, bytearray, memoryview)):
                raise ValueError("sampled ok hour has no binary payload")
            offset, mid = _first_quote_at_or_after(
                bytes(payload_value),
                row["payload_sha256"],
                target_offset_ms,
                divisor,
            )
            delay_ms = offset - target_offset_ms
            if delay_ms > maximum_delay_ms:
                unmatched["maximum_quote_delay_exceeded"] += 1
                continue
            matches.append(
                Match(
                    observation_date=reference.observation_date,
                    target_epoch_ms=reference.target_epoch_ms,
                    quote_epoch_ms=hour_epoch * 1000 + offset,
                    reference=reference.value,
                    mid=mid,
                    difference_bps=math.log(mid / reference.value) * 10_000.0,
                )
            )
    finally:
        connection.close()

    differences = [match.difference_bps for match in matches]
    absolute_differences = [abs(value) for value in differences]
    levels_reference = [match.reference for match in matches]
    levels_dukascopy = [match.mid for match in matches]
    reference_returns = [
        math.log(current.reference / previous.reference)
        for previous, current in zip(matches, matches[1:], strict=False)
    ]
    dukascopy_returns = [
        math.log(current.mid / previous.mid)
        for previous, current in zip(matches, matches[1:], strict=False)
    ]
    largest = sorted(matches, key=lambda item: abs(item.difference_bps), reverse=True)[:TOP_LIMIT]
    return {
        "schema_version": 1,
        "comparison": "Dukascopy midpoint versus FRED daily spot reference",
        "database": str(database_path.resolve()),
        "symbol": symbol,
        "database_range": {"start_utc": start.isoformat(), "end_exclusive_utc": end.isoformat()},
        "reference": {
            "path": str(reference_path.resolve()),
            "sha256": _sha256_file(reference_path),
            "series_id": series_id,
            "timezone": timezone_name,
            "local_hour": reference_hour,
            "selection": "first Dukascopy quote at or after the reference clock time",
            "maximum_delay_seconds": maximum_delay_seconds,
            "counts": reference_counts,
        },
        "matched_observations": len(matches),
        "unmatched": dict(sorted(unmatched.items())),
        "level_correlation": _rounded(_pearson(levels_reference, levels_dukascopy)),
        "consecutive_observation_return_correlation": _rounded(
            _pearson(reference_returns, dukascopy_returns)
        ),
        "signed_difference_bps": {
            "mean": _rounded(fmean(differences) if differences else None),
            "median": _rounded(median(differences) if differences else None),
            "minimum": _rounded(min(differences) if differences else None),
            "maximum": _rounded(max(differences) if differences else None),
        },
        "absolute_difference_bps": {
            "mean": _rounded(fmean(absolute_differences) if absolute_differences else None),
            "median": _rounded(median(absolute_differences) if absolute_differences else None),
            "p95": _rounded(_quantile(absolute_differences, 0.95)),
            "p99": _rounded(_quantile(absolute_differences, 0.99)),
            "maximum": _rounded(max(absolute_differences) if absolute_differences else None),
        },
        "largest_absolute_differences": [
            {
                "observation_date": match.observation_date.isoformat(),
                "target_utc": datetime.fromtimestamp(
                    match.target_epoch_ms / 1000, tz=UTC
                ).isoformat(),
                "quote_utc": datetime.fromtimestamp(
                    match.quote_epoch_ms / 1000, tz=UTC
                ).isoformat(),
                "reference": match.reference,
                "dukascopy_mid": match.mid,
                "difference_bps": _rounded(match.difference_bps),
            }
            for match in largest
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("reference_csv", type=Path)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--series-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timezone", default="America/New_York")
    parser.add_argument("--reference-hour", type=int, default=12)
    parser.add_argument("--maximum-delay-seconds", type=float, default=60.0)
    args = parser.parse_args()
    report = compare(
        args.database,
        args.reference_csv,
        symbol=args.symbol,
        series_id=args.series_id,
        timezone_name=args.timezone,
        reference_hour=args.reference_hour,
        maximum_delay_seconds=args.maximum_delay_seconds,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"matched={report['matched_observations']} report={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
