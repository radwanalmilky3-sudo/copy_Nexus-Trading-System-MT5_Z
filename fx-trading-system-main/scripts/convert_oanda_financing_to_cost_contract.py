#!/usr/bin/env python3
"""Convert the public OANDA US financing archive to a research-only cost contract.

OANDA ``longCharge``/``shortCharge`` values are totals for the event's ``days``.
This adapter divides those totals by both units and days, then preserves days as
``rollover_multiplier``. Multiplying the two contract fields reconstructs the
event total once, without double-counting holiday or weekend rollover.

The source was retrieved after its effective dates and is not account-specific.
Consequently the output quality is deliberately research-only and can never be
promoted to target-broker history merely because its hashes validate.
The adapter performs no network access and does not confirm or grant any right
to collect, reuse, backtest with, or redistribute OANDA data.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

CONVERTER_VERSION = "oanda-public-cost-contract-v1"
SOURCE_PAGE = "https://www.oanda.com/us-en/trading/financing-fees/"
SOURCE_ENDPOINT = "https://labs-api.oanda.com/v1/financing-rates"
SOURCE_NAME = "OANDA public financing-rates API"
BROKER_ENTITY = "OANDA Corporation"
ACCOUNT_CURRENCY = "USD"
TARGET_SYMBOLS = ("EURUSD", "GBPUSD")
QUOTE_QUALITY = "public_broker_history_retrieved_later_research_only"
RAW_SHA_PATTERN = re.compile(r"^[0-9a-f]{64}$")

OUTPUT_COLUMNS = (
    "symbol",
    "effective_time",
    "available_time",
    "long_financing",
    "short_financing",
    "unit",
    "day_count",
    "source",
    "provenance",
    "quote_quality",
    "version",
    "broker_entity",
    "account_currency",
    "triple_swap_weekday",
    "rollover_multiplier",
    "source_requested_date",
    "source_raw_sha256",
    "source_event_total_long_charge",
    "source_event_total_short_charge",
    "source_units",
    "source_charge_currency",
)

INPUT_COLUMNS = frozenset(
    {
        "requested_date",
        "effective_time",
        "symbol",
        "days",
        "long_charge",
        "short_charge",
        "charge_currency",
        "units",
        "retrieved_at",
        "raw_sha256",
    }
)


class OandaCostConversionError(ValueError):
    """Raised when the public archive cannot be converted without guessing."""


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(payload)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _parse_utc(value: object, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise OandaCostConversionError(f"invalid {label}: {value!r}") from error
    if parsed.tzinfo is None:
        raise OandaCostConversionError(f"{label} must include a timezone")
    return parsed.astimezone(UTC)


def _parse_decimal(value: object, label: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as error:
        raise OandaCostConversionError(f"invalid {label}: {value!r}") from error
    if not parsed.is_finite():
        raise OandaCostConversionError(f"non-finite {label}: {value!r}")
    return parsed


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _load_source_manifest(path: Path, input_csv: Path) -> tuple[dict[str, Any], str]:
    try:
        manifest_bytes = path.read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OandaCostConversionError(f"invalid OANDA source manifest: {path}") from error
    if not isinstance(manifest, dict):
        raise OandaCostConversionError("OANDA source manifest must be an object")
    expected = {
        "source_page": SOURCE_PAGE,
        "api_endpoint": SOURCE_ENDPOINT,
        "division_id": 1,
        "trading_group_id": 1,
        "failed_dates": 0,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise OandaCostConversionError(
                f"OANDA source manifest {key} must equal {value!r}"
            )
    declared_csv = manifest.get("normalized_csv")
    if not isinstance(declared_csv, str) or not declared_csv:
        raise OandaCostConversionError("OANDA source manifest normalized_csv is missing")
    if (path.parent / declared_csv).resolve() != input_csv.resolve():
        raise OandaCostConversionError("input CSV does not match source manifest normalized_csv")
    actual_csv_sha = _sha256_path(input_csv)
    if manifest.get("normalized_csv_sha256") != actual_csv_sha:
        raise OandaCostConversionError("input CSV hash does not match OANDA source manifest")
    declared_symbols = {str(item).upper() for item in manifest.get("symbols", [])}
    if not set(TARGET_SYMBOLS) <= declared_symbols:
        raise OandaCostConversionError("OANDA source manifest lacks EURUSD or GBPUSD")
    return manifest, _sha256_bytes(manifest_bytes)


def _manifest_raw_hashes(
    manifest: dict[str, Any], *, catalog_root: Path
) -> tuple[dict[str, str], int]:
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise OandaCostConversionError("OANDA source manifest has no raw file catalog")
    result: dict[str, str] = {}
    resolved_root = catalog_root.resolve()
    for entry in files:
        if not isinstance(entry, dict):
            raise OandaCostConversionError("invalid OANDA raw file catalog entry")
        requested_date = str(entry.get("requested_date", ""))
        digest = str(entry.get("sha256", "")).lower()
        if not requested_date or not RAW_SHA_PATTERN.fullmatch(digest):
            raise OandaCostConversionError("invalid date/hash in OANDA raw file catalog")
        if requested_date in result:
            raise OandaCostConversionError(f"duplicate raw catalog date {requested_date}")
        relative_path = entry.get("path")
        if not isinstance(relative_path, str) or not relative_path:
            raise OandaCostConversionError("OANDA raw file catalog entry has no path")
        raw_path = (resolved_root / relative_path).resolve()
        try:
            raw_path.relative_to(resolved_root)
        except ValueError as error:
            raise OandaCostConversionError("OANDA raw file path escapes catalog root") from error
        if not raw_path.is_file():
            raise OandaCostConversionError(f"OANDA raw file is missing: {relative_path}")
        try:
            declared_bytes = int(entry.get("bytes"))
        except (TypeError, ValueError) as error:
            raise OandaCostConversionError(
                f"invalid byte count for OANDA raw file {relative_path}"
            ) from error
        if raw_path.stat().st_size != declared_bytes:
            raise OandaCostConversionError(
                f"OANDA raw file byte count mismatch: {relative_path}"
            )
        if _sha256_path(raw_path) != digest:
            raise OandaCostConversionError(f"OANDA raw file SHA-256 mismatch: {relative_path}")
        result[requested_date] = digest
    return result, len(files)


def _read_input_rows(path: Path, expected_count: object) -> list[dict[str, str]]:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            columns = set(reader.fieldnames or [])
            missing = sorted(INPUT_COLUMNS - columns)
            if missing:
                raise OandaCostConversionError(f"OANDA input CSV missing columns: {missing}")
            rows = [dict(row) for row in reader]
    except OSError as error:
        raise OandaCostConversionError(f"cannot read OANDA input CSV: {path}") from error
    if not rows:
        raise OandaCostConversionError("OANDA input CSV is empty")
    try:
        declared_count = int(expected_count)
    except (TypeError, ValueError) as error:
        raise OandaCostConversionError("OANDA source manifest rows is invalid") from error
    if len(rows) != declared_count:
        raise OandaCostConversionError("OANDA input row count does not match source manifest")
    return rows


def _normalize_rows(
    input_rows: list[dict[str, str]],
    *,
    raw_hashes: dict[str, str],
    provenance: str,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    observed_symbols: set[str] = set()
    for number, source_row in enumerate(input_rows, start=2):
        symbol = str(source_row["symbol"]).upper().replace("/", "")
        if symbol not in TARGET_SYMBOLS:
            continue
        observed_symbols.add(symbol)
        try:
            requested_date = date.fromisoformat(source_row["requested_date"])
            days = int(source_row["days"])
            units = int(source_row["units"])
        except (TypeError, ValueError) as error:
            raise OandaCostConversionError(
                f"invalid date/days/units on input row {number}"
            ) from error
        if days < 0 or units <= 0:
            raise OandaCostConversionError(f"negative days or non-positive units on row {number}")
        effective = _parse_utc(source_row["effective_time"], f"effective_time row {number}")
        retrieved = _parse_utc(source_row["retrieved_at"], f"retrieved_at row {number}")
        if effective.date() != requested_date:
            raise OandaCostConversionError(f"effective date mismatch on input row {number}")
        if retrieved < effective:
            raise OandaCostConversionError(f"retrieved_at precedes effective_time on row {number}")
        charge_currency = str(source_row["charge_currency"]).upper()
        if charge_currency != ACCOUNT_CURRENCY:
            raise OandaCostConversionError(f"non-USD OANDA charge on input row {number}")
        raw_sha = str(source_row["raw_sha256"]).lower()
        if not RAW_SHA_PATTERN.fullmatch(raw_sha):
            raise OandaCostConversionError(f"invalid raw SHA-256 on input row {number}")
        if raw_hashes.get(requested_date.isoformat()) != raw_sha:
            raise OandaCostConversionError(f"raw SHA-256/catalog mismatch on input row {number}")
        long_total = _parse_decimal(source_row["long_charge"], f"long_charge row {number}")
        short_total = _parse_decimal(source_row["short_charge"], f"short_charge row {number}")
        if days == 0:
            if long_total != 0 or short_total != 0:
                raise OandaCostConversionError(
                    f"days=0 requires zero long/short event totals on input row {number}"
                )
            long_per_unit_day = Decimal(0)
            short_per_unit_day = Decimal(0)
        else:
            divisor = Decimal(units) * Decimal(days)
            long_per_unit_day = long_total / divisor
            short_per_unit_day = short_total / divisor
        effective_text = effective.isoformat()
        available_text = retrieved.isoformat()
        duplicate_key = (symbol, effective_text, available_text)
        if duplicate_key in seen:
            raise OandaCostConversionError(f"duplicate selected OANDA row {duplicate_key}")
        seen.add(duplicate_key)
        output.append(
            {
                "symbol": symbol,
                "effective_time": effective_text,
                # Strictly conservative: this archive proves retrieval time, not
                # the original shortly-after-close publication timestamp.
                "available_time": available_text,
                "long_financing": _decimal_text(long_per_unit_day),
                "short_financing": _decimal_text(short_per_unit_day),
                "unit": "account_currency_per_unit",
                "day_count": "broker_schedule",
                "source": SOURCE_NAME,
                "provenance": provenance,
                "quote_quality": QUOTE_QUALITY,
                "version": CONVERTER_VERSION,
                "broker_entity": BROKER_ENTITY,
                "account_currency": ACCOUNT_CURRENCY,
                "triple_swap_weekday": "wednesday",
                "rollover_multiplier": days,
                "source_requested_date": requested_date.isoformat(),
                "source_raw_sha256": raw_sha,
                "source_event_total_long_charge": _decimal_text(long_total),
                "source_event_total_short_charge": _decimal_text(short_total),
                "source_units": units,
                "source_charge_currency": charge_currency,
            }
        )
    missing_symbols = set(TARGET_SYMBOLS) - observed_symbols
    if missing_symbols:
        raise OandaCostConversionError(
            f"OANDA input CSV lacks selected symbols: {sorted(missing_symbols)}"
        )
    return sorted(output, key=lambda row: (str(row["effective_time"]), str(row["symbol"])))


def _csv_bytes(rows: list[dict[str, object]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def convert_oanda_financing(
    input_csv: str | Path,
    input_manifest: str | Path,
    output_csv: str | Path,
) -> dict[str, Any]:
    """Write canonical research-only financing CSV and two auditable manifests."""
    source_csv_path = Path(input_csv).expanduser().resolve()
    source_manifest_path = Path(input_manifest).expanduser().resolve()
    destination = Path(output_csv).expanduser().resolve()
    if not source_csv_path.is_file():
        raise FileNotFoundError(source_csv_path)
    if destination == source_csv_path:
        raise OandaCostConversionError("output CSV must differ from the OANDA source CSV")

    source_manifest, source_manifest_sha = _load_source_manifest(
        source_manifest_path, source_csv_path
    )
    input_csv_sha = _sha256_path(source_csv_path)
    provenance = (
        f"oanda_normalized_sha256:{input_csv_sha};"
        f"oanda_manifest_sha256:{source_manifest_sha}"
    )
    input_rows = _read_input_rows(source_csv_path, source_manifest.get("rows"))
    raw_hashes, raw_file_count = _manifest_raw_hashes(
        source_manifest, catalog_root=source_manifest_path.parent
    )
    rows = _normalize_rows(
        input_rows,
        raw_hashes=raw_hashes,
        provenance=provenance,
    )
    csv_payload = _csv_bytes(rows)
    csv_sha = _sha256_bytes(csv_payload)
    _atomic_write(destination, csv_payload)

    contract_manifest_path = destination.with_suffix(".manifest.json")
    blockers = {
        "license": (
            "unresolved and no permission confirmed: the archived US page says all rights "
            "reserved; Singapore website/tools terms and any separate v20 API agreement must "
            "be reviewed independently; this local-byte conversion grants no collection, reuse, "
            "or redistribution right"
        ),
        "point_in_time": (
            "not strict PIT: available_time is later retrieval time, not original publication time"
        ),
        "account_specific": (
            "public division/trading-group table may differ from finalized live-account charges"
        ),
        "history": "public endpoint exposes roughly one year, not the 2016-2025 target history",
    }
    contract_manifest = {
        "schema_version": 1,
        "dataset_kind": "broker_financing_schedule",
        "csv_sha256": csv_sha,
        "source_catalog": [
            {
                "source": SOURCE_NAME,
                "provenance": provenance,
                "quote_quality": QUOTE_QUALITY,
                "version": CONVERTER_VERSION,
                "broker_entity": BROKER_ENTITY,
                "account_currency": ACCOUNT_CURRENCY,
            }
        ],
        "research_only": True,
        "formal_cost_eligible": False,
        "license_confirmed": False,
        "redistribution_allowed": False,
        "conversion_scope": "offline transformation of already-archived local bytes only",
        "raw_source_verification": {
            "files_verified": raw_file_count,
            "existence_bytes_and_sha256_verified": True,
        },
        "rollover_semantics": (
            "wednesday is the usual triple-swap weekday only; each event's source days and "
            "rollover_multiplier are authoritative, including holiday shifts to other weekdays"
        ),
        "blockers": blockers,
    }
    contract_manifest_payload = _json_bytes(contract_manifest)
    _atomic_write(contract_manifest_path, contract_manifest_payload)

    conversion_manifest_path = destination.with_suffix(".conversion.json")
    effective_times = [str(row["effective_time"]) for row in rows]
    conversion_manifest = {
        "schema_version": 1,
        "converter_version": CONVERTER_VERSION,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source": {
            "csv": str(source_csv_path),
            "csv_sha256": input_csv_sha,
            "manifest": str(source_manifest_path),
            "manifest_sha256": source_manifest_sha,
            "source_page": SOURCE_PAGE,
            "api_endpoint": SOURCE_ENDPOINT,
            "division_id": 1,
            "trading_group_id": 1,
            "raw_files_verified": raw_file_count,
            "raw_existence_bytes_and_sha256_verified": True,
        },
        "output": {
            "csv": str(destination),
            "csv_sha256": csv_sha,
            "source_manifest": str(contract_manifest_path),
            "source_manifest_sha256": _sha256_bytes(contract_manifest_payload),
            "rows": len(rows),
            "symbols": list(TARGET_SYMBOLS),
            "effective_start": min(effective_times),
            "effective_end_inclusive": max(effective_times),
            "quote_quality": QUOTE_QUALITY,
        },
        "amount_semantics": {
            "source": "event total charge in USD per source units, already including days",
            "long_financing": "source longCharge / units / days when days > 0, else zero",
            "short_financing": "source shortCharge / units / days when days > 0, else zero",
            "rollover_multiplier": "source days, including zero and holiday/weekend multiples",
            "rollover_multiplier_is_authoritative": True,
            "triple_swap_weekday": (
                "wednesday is the usual rule only; never override source days by weekday, because "
                "holiday multiples can occur on Monday, Tuesday, or Thursday"
            ),
            "reconstruction": "financing_per_unit_per_day * units * rollover_multiplier",
            "double_count_prevented": True,
        },
        "blockers": blockers,
        "research_only": True,
        "network_accessed": False,
        "license_confirmed": False,
        "redistribution_allowed": False,
        "operation_scope": "offline transformation of already-archived local bytes only",
        "formal_net_returns_ready": False,
        "trading_approval": False,
        "return_labels_opened": False,
        "factor_outcome_evaluations_added": 0,
    }
    _atomic_write(conversion_manifest_path, _json_bytes(conversion_manifest))
    return conversion_manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-csv",
        type=Path,
        default=Path("data/oanda_financing_us/normalized/financing_history.csv"),
    )
    parser.add_argument(
        "--input-manifest",
        type=Path,
        default=Path("data/oanda_financing_us/manifest.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "data/oanda_financing_us/cost_contract/"
            "EURUSD_GBPUSD_public_financing_research_only.csv"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        manifest = convert_oanda_financing(args.input_csv, args.input_manifest, args.output)
    except (OandaCostConversionError, FileNotFoundError) as error:
        print(f"conversion failed: {error}", file=sys.stderr)
        return 1
    output = manifest["output"]
    print(
        f"Converted {output['rows']} research-only rows; csv={output['csv']}; "
        "formal_net_returns_ready=False; trading_approval=False",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
