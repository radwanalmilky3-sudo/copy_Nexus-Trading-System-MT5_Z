#!/usr/bin/env python3
"""Archive the public OANDA Corporation daily-financing table.

The public page exposes roughly one year of daily indicative/finalized financing
rates without an account token. This script stores the provider-native JSON and
a normalized CSV, but deliberately does not convert USD charges to pips or call
the data OIS/forward points. The public division/trading-group values may differ
from a user's own account terms.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

BASE_URL = "https://labs-api.oanda.com/v1/financing-rates"
SOURCE_PAGE = "https://www.oanda.com/us-en/trading/financing-fees/"
DOWNLOADER_VERSION = "oanda-public-financing-v1"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
DEFAULT_SYMBOLS = (
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "AUDUSD",
    "NZDUSD",
    "USDCAD",
    "EURGBP",
    "EURJPY",
    "GBPJPY",
    "AUDJPY",
    "CADJPY",
)
REQUIRED_RATE_FIELDS = {
    "currency",
    "days",
    "instrument",
    "longCharge",
    "longRate",
    "shortCharge",
    "shortRate",
    "units",
}


def _parse_timestamp(value: object, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"invalid {label}: {value!r}") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(UTC)


def _finite_decimal(value: object, label: str) -> str:
    text = str(value)
    try:
        number = float(text)
    except ValueError as error:
        raise ValueError(f"invalid {label}: {value!r}") from error
    if not math.isfinite(number):
        raise ValueError(f"non-finite {label}: {value!r}")
    return text


def validate_response(
    payload: bytes,
    *,
    requested_date: date,
    division_id: int,
    trading_group_id: int,
    required_symbols: set[str],
) -> tuple[dict[str, Any], list[dict[str, object]]]:
    if not payload or len(payload) > MAX_RESPONSE_BYTES:
        raise ValueError("empty or oversized OANDA financing response")
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("OANDA financing response is not valid JSON") from error
    if not isinstance(document, dict):
        raise ValueError("OANDA financing response must be an object")
    if document.get("divisionId") != division_id:
        raise ValueError("OANDA financing response divisionId mismatch")
    if document.get("tradingGroupId") != trading_group_id:
        raise ValueError("OANDA financing response tradingGroupId mismatch")
    effective_time = _parse_timestamp(document.get("timestamp"), "source timestamp")
    if effective_time.date() != requested_date:
        raise ValueError("OANDA financing source timestamp does not match requested date")
    rates = document.get("financingRates")
    if not isinstance(rates, list) or not rates:
        raise ValueError("OANDA financing response contains no rates")

    normalized: list[dict[str, object]] = []
    seen: set[str] = set()
    for number, rate in enumerate(rates):
        if not isinstance(rate, dict) or not REQUIRED_RATE_FIELDS <= set(rate):
            raise ValueError(f"OANDA financing rate {number} has an invalid schema")
        instrument = str(rate["instrument"]).upper()
        if not instrument or "/" not in instrument:
            raise ValueError(f"OANDA financing rate {number} has an invalid instrument")
        symbol = instrument.replace("/", "")
        if symbol in seen:
            raise ValueError(f"duplicate OANDA financing instrument {instrument}")
        seen.add(symbol)
        try:
            days = int(rate["days"])
            units = int(rate["units"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid days/units for {instrument}") from error
        # Holiday settlement can legitimately create a long rollover. The
        # public table showed 11 days for USD/CNH around Lunar New Year 2026.
        if not 0 <= days <= 20 or units <= 0:
            raise ValueError(f"out-of-range days/units for {instrument}")
        normalized.append(
            {
                "requested_date": requested_date.isoformat(),
                "effective_time": effective_time.isoformat(),
                "instrument": instrument,
                "symbol": symbol,
                "days": days,
                "annualized_long_rate": _finite_decimal(
                    rate["longRate"], f"{instrument} longRate"
                ),
                "annualized_short_rate": _finite_decimal(
                    rate["shortRate"], f"{instrument} shortRate"
                ),
                "long_charge": _finite_decimal(rate["longCharge"], f"{instrument} longCharge"),
                "short_charge": _finite_decimal(
                    rate["shortCharge"], f"{instrument} shortCharge"
                ),
                "charge_currency": str(rate["currency"]).upper(),
                "units": units,
            }
        )
    missing = required_symbols - seen
    if missing:
        raise ValueError(f"OANDA financing response is missing required symbols {sorted(missing)}")
    return document, [row for row in normalized if str(row["symbol"]) in required_symbols]


def _request_url(requested_date: date, division_id: int, trading_group_id: int) -> str:
    query = urllib.parse.urlencode(
        {
            "divisionId": division_id,
            "tradingGroupId": trading_group_id,
            "time": f"{requested_date.isoformat()}T05:00:00.000Z",
        }
    )
    return f"{BASE_URL}?{query}"


def _fetch(url: str, *, timeout: float, retries: int) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"{DOWNLOADER_VERSION} (+public research archive)"},
    )
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
                if len(payload) > MAX_RESPONSE_BYTES:
                    raise ValueError("OANDA financing response exceeds maximum size")
                return payload
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, ValueError) as error:
            last_error = error
            if attempt < retries:
                time.sleep(0.5 * (2**attempt))
    assert last_error is not None
    raise last_error


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(payload)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json(path: Path, value: object) -> None:
    _atomic_write(
        path,
        (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
    )


def _one_year_window_start(today: date) -> date:
    try:
        anniversary = today.replace(year=today.year - 1)
    except ValueError:  # February 29
        anniversary = today.replace(year=today.year - 1, day=28)
    return anniversary + timedelta(days=1)


def _dates(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _write_normalized_csv(rows: list[dict[str, object]], path: Path) -> str:
    columns = [
        "requested_date",
        "effective_time",
        "instrument",
        "symbol",
        "days",
        "annualized_long_rate",
        "annualized_short_rate",
        "long_charge",
        "short_charge",
        "charge_currency",
        "units",
        "retrieved_at",
        "raw_sha256",
    ]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    payload = buffer.getvalue().encode("utf-8")
    _atomic_write(path, payload)
    return hashlib.sha256(payload).hexdigest()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    today = datetime.now(UTC).date()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/oanda_financing_us"))
    parser.add_argument(
        "--start-date", type=date.fromisoformat, default=_one_year_window_start(today)
    )
    parser.add_argument("--end-date", type=date.fromisoformat, default=today - timedelta(days=1))
    parser.add_argument("--division-id", type=int, default=1)
    parser.add_argument("--trading-group-id", type=int, default=1)
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--delay-seconds", type=float, default=0.15)
    parser.add_argument("--refresh", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    today = datetime.now(UTC).date()
    earliest = _one_year_window_start(today)
    if args.start_date < earliest or args.end_date >= today or args.end_date < args.start_date:
        print(
            f"date range must satisfy {earliest} <= start <= end < {today}",
            file=sys.stderr,
        )
        return 2
    if args.division_id <= 0 or args.trading_group_id <= 0:
        print("division and trading-group IDs must be positive", file=sys.stderr)
        return 2
    if args.timeout <= 0 or not 0 <= args.retries <= 10 or args.delay_seconds < 0:
        print("invalid timeout, retries, or delay", file=sys.stderr)
        return 2
    symbols = {item.strip().upper().replace("/", "") for item in args.symbols.split(",")}
    if not symbols or any(len(symbol) != 6 or not symbol.isalpha() for symbol in symbols):
        print("--symbols must contain comma-separated six-letter FX symbols", file=sys.stderr)
        return 2

    root = args.output.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    files: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    requested_dates = _dates(args.start_date, args.end_date)
    for number, requested_date in enumerate(requested_dates, start=1):
        path = root / "raw" / str(requested_date.year) / f"{requested_date.isoformat()}.json"
        url = _request_url(requested_date, args.division_id, args.trading_group_id)
        status = "cached"
        try:
            if path.exists() and not args.refresh:
                payload = path.read_bytes()
                retrieved_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()
            else:
                payload = _fetch(url, timeout=args.timeout, retries=args.retries)
                validate_response(
                    payload,
                    requested_date=requested_date,
                    division_id=args.division_id,
                    trading_group_id=args.trading_group_id,
                    required_symbols=symbols,
                )
                _atomic_write(path, payload)
                retrieved_at = datetime.now(UTC).isoformat()
                status = "downloaded"
                if args.delay_seconds:
                    time.sleep(args.delay_seconds)
            _document, selected = validate_response(
                payload,
                requested_date=requested_date,
                division_id=args.division_id,
                trading_group_id=args.trading_group_id,
                required_symbols=symbols,
            )
            digest = hashlib.sha256(payload).hexdigest()
            for row in selected:
                row["retrieved_at"] = retrieved_at
                row["raw_sha256"] = digest
                rows.append(row)
            files.append(
                {
                    "requested_date": requested_date.isoformat(),
                    "status": status,
                    "url": url,
                    "path": path.relative_to(root).as_posix(),
                    "bytes": len(payload),
                    "sha256": digest,
                    "selected_rows": len(selected),
                }
            )
            if number == 1 or number % 25 == 0 or number == len(requested_dates):
                print(
                    f"[{number:>3}/{len(requested_dates)}] {requested_date} {status}",
                    flush=True,
                )
        except Exception as error:  # retain other dates and make gaps explicit
            errors.append(
                {"requested_date": requested_date.isoformat(), "url": url, "error": str(error)}
            )
            print(f"[failed] {requested_date}: {error}", file=sys.stderr, flush=True)

    rows.sort(key=lambda row: (str(row["effective_time"]), str(row["symbol"])))
    csv_path = root / "normalized" / "financing_history.csv"
    csv_digest = _write_normalized_csv(rows, csv_path)
    manifest = {
        "schema_version": 1,
        "downloader_version": DOWNLOADER_VERSION,
        "source_page": SOURCE_PAGE,
        "api_endpoint": BASE_URL,
        "division_id": args.division_id,
        "trading_group_id": args.trading_group_id,
        "symbols": sorted(symbols),
        "requested_start": args.start_date.isoformat(),
        "requested_end": args.end_date.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "successful_dates": len(files),
        "failed_dates": len(errors),
        "rows": len(rows),
        "normalized_csv": csv_path.relative_to(root).as_posix(),
        "normalized_csv_sha256": csv_digest,
        "files": files,
        "errors": errors,
        "limitations": [
            "This is the public OANDA Corporation division/trading-group table.",
            "The current date is omitted because its displayed rates are indicative before close.",
            "Public rates may differ from finalized account-specific financing charges.",
            "Charges are preserved in the source currency and are not converted to pips.",
            "The data is broker financing, not OIS or outright forward points.",
        ],
    }
    _write_json(root / "manifest.json", manifest)
    print(
        f"Completed {len(files)}/{len(requested_dates)} dates, {len(rows)} rows; "
        f"csv={csv_path}",
        flush=True,
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
