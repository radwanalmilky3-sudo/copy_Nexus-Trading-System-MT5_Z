#!/usr/bin/env python3
"""Download free official policy, overnight and explicitly identified OIS rates.

Every provider-native response is archived. The normalized output preserves the
rate role and tenor; overnight reference rates are never relabelled as OIS, and
only source columns explicitly titled OIS receive ``is_ois=true``.
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
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

PROGRAM_VERSION = "official-fx-rates-v1"
MAX_RESPONSE_BYTES = 16 * 1024 * 1024


def _finite(value: object, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid {label}: {value!r}") from error
    if not math.isfinite(number):
        raise ValueError(f"non-finite {label}: {value!r}")
    return number


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(payload)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _fetch(url: str, timeout: float, retries: int) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": f"{PROGRAM_VERSION} (+public research archive)"}
    )
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
                if not payload or len(payload) > MAX_RESPONSE_BYTES:
                    raise ValueError("empty or oversized official-rate response")
                return payload
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, ValueError) as error:
            last_error = error
            if attempt < retries:
                time.sleep(0.5 * (2**attempt))
    assert last_error is not None
    raise last_error


def _row(
    *,
    observation_date: date,
    currency: str,
    series_id: str,
    series_name: str,
    value: object,
    provider: str,
    role: str,
    tenor: str,
    source_url: str,
    availability_lag_days: int,
    is_ois: bool = False,
    quality: str = "official_current_vintage",
) -> dict[str, object]:
    return {
        "observation_time": datetime.combine(
            observation_date, datetime.min.time(), tzinfo=UTC
        ).isoformat(),
        "available_time": datetime.combine(
            observation_date + timedelta(days=availability_lag_days),
            datetime.min.time(),
            tzinfo=UTC,
        ).isoformat(),
        "currency": currency,
        "series_id": series_id,
        "series_name": series_name,
        "rate_percent": _finite(value, f"{provider} {series_id}"),
        "provider": provider,
        "series_role": role,
        "tenor": tenor,
        "is_ois": is_ois,
        "frequency": "daily",
        "quality": quality,
        "source_url": source_url,
    }


def parse_nyfed(payload: bytes, source_url: str) -> list[dict[str, object]]:
    document = json.loads(payload)
    rates = document.get("refRates") if isinstance(document, dict) else None
    if not isinstance(rates, list) or not rates:
        raise ValueError("NY Fed response contains no refRates")
    rows = []
    for item in rates:
        if item.get("type") != "SOFR":
            continue
        rows.append(
            _row(
                observation_date=date.fromisoformat(item["effectiveDate"]),
                currency="USD",
                series_id="SOFR",
                series_name="Secured Overnight Financing Rate",
                value=item["percentRate"],
                provider="new_york_fed",
                role="overnight_reference",
                tenor="ON",
                source_url=source_url,
                availability_lag_days=1,
            )
        )
    return rows


def parse_ecb(
    payload: bytes,
    source_url: str,
    *,
    currency: str,
    series_id: str,
    series_name: str,
    role: str,
    tenor: str,
) -> list[dict[str, object]]:
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    required = {"TIME_PERIOD", "OBS_VALUE"}
    if reader.fieldnames is None or not required <= set(reader.fieldnames):
        raise ValueError("ECB response has an unexpected CSV schema")
    rows = []
    for item in reader:
        if not item["OBS_VALUE"].strip():
            continue
        rows.append(
            _row(
                observation_date=date.fromisoformat(item["TIME_PERIOD"]),
                currency=currency,
                series_id=series_id,
                series_name=series_name,
                value=item["OBS_VALUE"],
                provider="ecb",
                role=role,
                tenor=tenor,
                source_url=source_url,
                availability_lag_days=1,
            )
        )
    if not rows:
        raise ValueError(f"ECB {series_id} response has no observations")
    return rows


def parse_boe(payload: bytes, source_url: str) -> list[dict[str, object]]:
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    expected = {"DATE", "IUDSOIA", "IUDBEDR"}
    if reader.fieldnames is None or not expected <= set(reader.fieldnames):
        raise ValueError("Bank of England response has an unexpected CSV schema")
    definitions = {
        "IUDSOIA": ("SONIA", "Sterling Overnight Index Average", "overnight_reference", "ON"),
        "IUDBEDR": ("BANK_RATE", "Official Bank Rate", "policy_rate", "POLICY"),
    }
    rows = []
    for item in reader:
        observation_date = datetime.strptime(item["DATE"], "%d %b %Y").date()
        for column, (series_id, name, role, tenor) in definitions.items():
            if item[column].strip():
                rows.append(
                    _row(
                        observation_date=observation_date,
                        currency="GBP",
                        series_id=series_id,
                        series_name=name,
                        value=item[column],
                        provider="bank_of_england",
                        role=role,
                        tenor=tenor,
                        source_url=source_url,
                        availability_lag_days=1,
                    )
                )
    if not rows:
        raise ValueError("Bank of England response has no observations")
    return rows


def parse_boc(
    payload: bytes,
    source_url: str,
    *,
    source_series: str,
    series_id: str,
    series_name: str,
    role: str,
    tenor: str,
) -> list[dict[str, object]]:
    document = json.loads(payload)
    observations = document.get("observations") if isinstance(document, dict) else None
    if not isinstance(observations, list) or not observations:
        raise ValueError(f"Bank of Canada {source_series} response has no observations")
    rows = []
    for item in observations:
        value = item.get(source_series, {}).get("v")
        if value in {None, ""}:
            continue
        rows.append(
            _row(
                observation_date=date.fromisoformat(item["d"]),
                currency="CAD",
                series_id=series_id,
                series_name=series_name,
                value=value,
                provider="bank_of_canada",
                role=role,
                tenor=tenor,
                source_url=source_url,
                availability_lag_days=1,
            )
        )
    return rows


def parse_rba(payload: bytes, source_url: str) -> list[dict[str, object]]:
    records = list(csv.reader(io.StringIO(payload.decode("utf-8-sig"))))
    series_row = next(
        (number for number, row in enumerate(records) if row and row[0] == "Series ID"),
        None,
    )
    if series_row is None or series_row + 1 >= len(records):
        raise ValueError("RBA F1 response is missing its Series ID row")
    series_ids = records[series_row]
    desired = {
        "FIRMMCRTD": ("CASH_RATE_TARGET", "Cash Rate Target", "policy_rate", "POLICY", False),
        "FIRMMCRID": (
            "AONIA",
            "Interbank Overnight Cash Rate",
            "overnight_reference",
            "ON",
            False,
        ),
        "FIRMMOIS1D": ("AUD_OIS_1M", "AUD Overnight Indexed Swap 1 month", "ois", "1M", True),
        "FIRMMOIS3D": ("AUD_OIS_3M", "AUD Overnight Indexed Swap 3 months", "ois", "3M", True),
    }
    locations = {
        source_id: series_ids.index(source_id)
        for source_id in desired
        if source_id in series_ids
    }
    if set(locations) != set(desired):
        missing = sorted(set(desired) - set(locations))
        raise ValueError(f"RBA F1 response is missing series {missing}")
    rows = []
    for record in records[series_row + 1 :]:
        if not record or not record[0].strip():
            continue
        try:
            observation_date = datetime.strptime(record[0], "%d-%b-%Y").date()
        except ValueError:
            continue
        for source_id, location in locations.items():
            if location >= len(record) or not record[location].strip():
                continue
            series_id, name, role, tenor, is_ois = desired[source_id]
            rows.append(
                _row(
                    observation_date=observation_date,
                    currency="AUD",
                    series_id=series_id,
                    series_name=name,
                    value=record[location],
                    provider="reserve_bank_of_australia",
                    role=role,
                    tenor=tenor,
                    source_url=source_url,
                    availability_lag_days=1,
                    is_ois=is_ois,
                    quality="official_original_series",
                )
            )
    if not rows:
        raise ValueError("RBA F1 response has no observations")
    return rows


def parse_snb(payload: bytes, source_url: str) -> list[dict[str, object]]:
    records = list(
        csv.reader(io.StringIO(payload.decode("utf-8-sig")), delimiter=";")
    )
    header = next(
        (number for number, row in enumerate(records) if row == ["Date", "D0", "Value"]),
        None,
    )
    if header is None:
        raise ValueError("SNB zimoma response has an unexpected schema")
    desired = {
        "SARON": ("CHF", "SARON", "Swiss Average Rate Overnight", "overnight_reference"),
        "1TGT": ("CHF", "SNB_POLICY", "SNB policy rate", "policy_rate"),
        "TONA": ("JPY", "TONA_MONTHLY", "Tokyo Overnight Average rate", "overnight_reference"),
    }
    rows = []
    for record in records[header + 1 :]:
        if len(record) != 3:
            continue
        date_text, code, value = record
        if code not in desired or not value.strip():
            continue
        year, month = (int(item) for item in date_text.split("-"))
        observation_date = date(year, month, monthrange(year, month)[1])
        currency, series_id, name, role = desired[code]
        normalized = _row(
            observation_date=observation_date,
            currency=currency,
            series_id=series_id,
            series_name=name,
            value=value,
            provider="swiss_national_bank",
            role=role,
            tenor="ON" if role == "overnight_reference" else "POLICY",
            source_url=source_url,
            availability_lag_days=32,
            quality=(
                "official_primary_monthly"
                if currency == "CHF"
                else "official_secondary_monthly_republication"
            ),
        )
        normalized["frequency"] = "monthly"
        rows.append(normalized)
    if not rows:
        raise ValueError("SNB zimoma response has no selected observations")
    return rows


def _write_normalized(rows: list[dict[str, object]], path: Path) -> str:
    columns = [
        "observation_time",
        "available_time",
        "currency",
        "series_id",
        "series_name",
        "rate_percent",
        "provider",
        "series_role",
        "tenor",
        "is_ois",
        "frequency",
        "quality",
        "source_url",
    ]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    payload = buffer.getvalue().encode("utf-8")
    _atomic_write(path, payload)
    return hashlib.sha256(payload).hexdigest()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/official_rates"))
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(1997, 1, 1))
    parser.add_argument("--end-date", type=date.fromisoformat, default=datetime.now(UTC).date())
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--refresh", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.end_date < args.start_date or args.timeout <= 0 or not 0 <= args.retries <= 10:
        print("invalid date range, timeout, or retries", file=sys.stderr)
        return 2
    end_boe = args.end_date.strftime("%d/%b/%Y")
    start_boe = args.start_date.strftime("%d/%b/%Y")
    sources = [
        (
            "nyfed_sofr",
            "https://markets.newyorkfed.org/api/rates/secured/sofr/search.json?"
            + urllib.parse.urlencode(
                {
                    "startDate": max(args.start_date, date(2018, 4, 3)).isoformat(),
                    "endDate": args.end_date.isoformat(),
                    "type": "rate",
                }
            ),
            "nyfed/sofr.json",
            parse_nyfed,
            {},
        ),
        (
            "ecb_estr",
            "https://data-api.ecb.europa.eu/service/data/EST/B.EU000A2X2A25.WT?"
            + urllib.parse.urlencode(
                {"startPeriod": "2019-10-01", "endPeriod": args.end_date, "format": "csvdata"}
            ),
            "ecb/estr.csv",
            parse_ecb,
            {
                "currency": "EUR",
                "series_id": "ESTR",
                "series_name": "Euro short-term rate",
                "role": "overnight_reference",
                "tenor": "ON",
            },
        ),
        (
            "ecb_deposit",
            "https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.DFR.LEV?"
            + urllib.parse.urlencode(
                {"startPeriod": "1999-01-01", "endPeriod": args.end_date, "format": "csvdata"}
            ),
            "ecb/deposit_facility.csv",
            parse_ecb,
            {
                "currency": "EUR",
                "series_id": "ECB_DFR",
                "series_name": "ECB deposit facility rate",
                "role": "policy_rate",
                "tenor": "POLICY",
            },
        ),
        (
            "boe",
            "https://www.bankofengland.co.uk/boeapps/database/"
            "_iadb-fromshowcolumns.asp?"
            + urllib.parse.urlencode(
                {
                    "csv.x": "yes",
                    "Datefrom": start_boe,
                    "Dateto": end_boe,
                    "SeriesCodes": "IUDSOIA,IUDBEDR",
                    "CSVF": "TN",
                    "UsingCodes": "Y",
                    "VPD": "Y",
                    "VFD": "N",
                }
            ),
            "boe/sonia_bank_rate.csv",
            parse_boe,
            {},
        ),
        (
            "boc_corra",
            "https://www.bankofcanada.ca/valet/observations/AVG.INTWO/json?"
            + urllib.parse.urlencode({"start_date": args.start_date, "end_date": args.end_date}),
            "boc/corra.json",
            parse_boc,
            {
                "source_series": "AVG.INTWO",
                "series_id": "CORRA",
                "series_name": "Canadian Overnight Repo Rate Average",
                "role": "overnight_reference",
                "tenor": "ON",
            },
        ),
        (
            "boc_target",
            "https://www.bankofcanada.ca/valet/observations/V39079/json?"
            + urllib.parse.urlencode({"start_date": args.start_date, "end_date": args.end_date}),
            "boc/overnight_target.json",
            parse_boc,
            {
                "source_series": "V39079",
                "series_id": "BOC_TARGET",
                "series_name": "Target for the overnight rate",
                "role": "policy_rate",
                "tenor": "POLICY",
            },
        ),
        (
            "rba_f1",
            "https://www.rba.gov.au/statistics/tables/csv/f1-data.csv",
            "rba/f1-data.csv",
            parse_rba,
            {},
        ),
        (
            "snb_zimoma",
            "https://data.snb.ch/api/cube/zimoma/data/csv/en",
            "snb/zimoma.csv",
            parse_snb,
            {},
        ),
    ]
    root = args.output.expanduser().resolve()
    retrieved_at = datetime.now(UTC).isoformat()
    normalized: list[dict[str, object]] = []
    source_manifest: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    for key, url, relative_path, parser, parser_kwargs in sources:
        path = root / "raw" / relative_path
        try:
            if path.exists() and not args.refresh:
                payload = path.read_bytes()
                status = "cached"
            else:
                payload = _fetch(url, args.timeout, args.retries)
                _atomic_write(path, payload)
                status = "downloaded"
            rows = parser(payload, url, **parser_kwargs)
            normalized.extend(rows)
            source_manifest.append(
                {
                    "key": key,
                    "url": url,
                    "path": path.relative_to(root).as_posix(),
                    "status": status,
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "rows": len(rows),
                }
            )
            print(f"[{status:10}] {key:16} {len(rows):>7} rows", flush=True)
        except Exception as error:
            errors.append({"key": key, "url": url, "error": str(error)})
            print(f"[failed    ] {key}: {error}", file=sys.stderr, flush=True)
    normalized.sort(
        key=lambda item: (
            str(item["observation_time"]),
            str(item["currency"]),
            str(item["series_id"]),
        )
    )
    normalized_path = root / "normalized" / "official_rate_observations.csv"
    normalized_sha256 = _write_normalized(normalized, normalized_path)
    currencies = sorted({str(item["currency"]) for item in normalized})
    manifest = {
        "schema_version": 1,
        "program_version": PROGRAM_VERSION,
        "retrieved_at": retrieved_at,
        "start_date": args.start_date.isoformat(),
        "end_date": args.end_date.isoformat(),
        "successful_sources": len(source_manifest),
        "failed_sources": len(errors),
        "rows": len(normalized),
        "currencies": currencies,
        "missing_primary_currency": ["NZD"],
        "normalized_path": normalized_path.relative_to(root).as_posix(),
        "normalized_sha256": normalized_sha256,
        "sources": source_manifest,
        "errors": errors,
        "limitations": [
            "The archive is current-vintage and not a complete revision history.",
            "Overnight and policy rates are not 1M/3M OIS.",
            "Only RBA columns explicitly titled OIS are marked is_ois=true.",
            "JPY TONA is a monthly secondary republication by SNB, not a primary BOJ feed.",
            "No accessible primary NZD series is normalized in this version.",
        ],
    }
    _atomic_write(
        root / "manifest.json",
        (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode(),
    )
    print(
        f"Completed {len(source_manifest)}/{len(sources)} sources, {len(normalized)} rows, "
        f"currencies={','.join(currencies)}",
        flush=True,
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
