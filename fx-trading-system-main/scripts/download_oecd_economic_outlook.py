#!/usr/bin/env python3
"""Download a small, audited panel of official OECD Economic Outlook editions.

The program deliberately requests an explicit server-side subset: eight currency
economies (with the original OECD euro-area aggregate codes), five verified
annual forecast measures, and only the publication year through publication year
+ 2.  It will not fall back to downloading a complete Economic Outlook dataflow.

OECD publication dates are date-only.  Rows therefore become usable on the next
weekday, at 00:00 UTC, and are labelled as official forecast-edition observations.
They are not actual-data release vintages and are not consensus surprises.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import os
import re
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final
from urllib.parse import parse_qs, quote, unquote, urlparse

import httpx

PROGRAM_VERSION: Final = "oecd-economic-outlook-v1"
PROVIDER: Final = "OECD Economic Outlook"
ALLOWED_HOST: Final = "sdmx.oecd.org"
MAX_RESPONSE_BYTES: Final = 2 * 1024 * 1024
DEFAULT_REQUEST_DELAY_SECONDS: Final = 0.75
MAX_RETRY_AFTER_SECONDS: Final = 60.0

MEASURES: Final[dict[str, str]] = {
    "GDPV_ANNPCT": "real_gdp_volume_growth",
    "CPI_YTYPCT": "headline_inflation",
    "UNR": "unemployment_rate",
    "CBGDPR": "current_account_balance_pct_gdp",
    "NLGQ": "general_government_net_lending_pct_gdp",
}

NON_EURO_ECONOMIES: Final[tuple[str, ...]] = (
    "USA",
    "GBR",
    "JPN",
    "CHE",
    "CAN",
    "AUS",
    "NZL",
)
ECONOMY_CURRENCY: Final[dict[str, str]] = {
    "USA": "USD",
    "GBR": "GBP",
    "JPN": "JPY",
    "CHE": "CHF",
    "CAN": "CAD",
    "AUS": "AUD",
    "NZL": "NZD",
    "EA15": "EUR",
    "EA16": "EUR",
    "EA17": "EUR",
}

RELEASE_DATES: Final[dict[int, date]] = {
    99: date(2016, 6, 1),
    100: date(2016, 12, 17),
    101: date(2017, 6, 30),
    102: date(2017, 12, 19),
    103: date(2018, 6, 21),
    104: date(2018, 12, 7),
    105: date(2019, 5, 21),
    106: date(2019, 12, 10),
    107: date(2020, 6, 10),
    108: date(2020, 12, 1),
    109: date(2021, 5, 31),
    110: date(2021, 12, 1),
    111: date(2022, 6, 8),
    112: date(2022, 11, 22),
    113: date(2023, 6, 7),
    114: date(2023, 11, 29),
    115: date(2024, 5, 2),
    116: date(2024, 12, 4),
    117: date(2025, 6, 3),
    118: date(2025, 12, 2),
}
MODERN_VERSIONS: Final[dict[int, str]] = {
    115: "1.1",
    116: "1.2",
    117: "1.3",
    118: "1.4",
}

OUTPUT_COLUMNS: Final[tuple[str, ...]] = (
    "edition",
    "scenario",
    "release_date",
    "available_time",
    "availability_precision",
    "availability_policy",
    "release_kind",
    "value_vintage_quality",
    "pit_eligible_for_periodic_forecast_research",
    "strict_intraday_eligible",
    "is_actual_release_vintage",
    "is_consensus_surprise",
    "economy_code",
    "economy_name",
    "currency",
    "aggregate_variant",
    "currency_mapping_quality",
    "composition_break",
    "cross_edition_comparability",
    "measure_code",
    "measure_name",
    "measure_family",
    "frequency_code",
    "frequency_name",
    "target_period",
    "forecast_horizon_years",
    "is_future_target",
    "value",
    "observation_status_code",
    "observation_status_name",
    "unit_code",
    "unit_name",
    "unit_multiplier_code",
    "unit_multiplier_name",
    "base_period",
    "structure_id",
    "structure_name",
    "provider",
    "source_url",
    "raw_sha256",
)


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    edition: int
    scenario: str
    release_date: date
    api_generation: str
    flow_id: str
    url: str
    economy_codes: tuple[str, ...]
    start_period: int
    end_period: int


def _euro_codes(edition: int) -> tuple[str, ...]:
    # These are OECD-member aggregates, not the number of all euro users.
    # EO100 publishes both the old and new composition, so both are retained.
    if edition == 99:
        return ("EA15",)
    if edition == 100:
        return ("EA15", "EA16")
    if 101 <= edition <= 103:
        return ("EA16",)
    return ("EA17",)


def _encoded_key(economies: tuple[str, ...]) -> str:
    areas = quote("+".join(economies), safe="")
    measures = quote("+".join(MEASURES), safe="")
    return f"{areas}.{measures}.A"


def _source(
    edition: int,
    *,
    scenario: str = "baseline",
    flow_suffix: str = "",
) -> SourceSpec:
    release = RELEASE_DATES[edition]
    economies = (*NON_EURO_ECONOMIES, *_euro_codes(edition))
    key = _encoded_key(economies)
    start_period = release.year
    end_period = release.year + 2
    if edition <= 114:
        flow_id = f"DF_EO{edition}_INTERNET{flow_suffix}"
        url = (
            f"https://{ALLOWED_HOST}/archive/rest/data/OECD,{flow_id}/{key}"
            f"?startPeriod={start_period}&endPeriod={end_period}"
            "&format=csvfilewithlabels"
        )
        generation = "legacy_archive"
    else:
        version = MODERN_VERSIONS[edition]
        flow_id = "DSD_EO@DF_EO"
        url = (
            f"https://{ALLOWED_HOST}/public/rest/v1/data/"
            f"OECD.ECO.MAD,{flow_id},{version}/{key}"
            f"?startPeriod={start_period}&endPeriod={end_period}"
            "&format=csvfilewithlabels"
        )
        generation = "versioned_modern"
    return SourceSpec(
        source_id=f"eo{edition}_{scenario}",
        edition=edition,
        scenario=scenario,
        release_date=release,
        api_generation=generation,
        flow_id=flow_id,
        url=url,
        economy_codes=economies,
        start_period=start_period,
        end_period=end_period,
    )


SOURCES: Final[tuple[SourceSpec, ...]] = (
    *(_source(edition) for edition in range(99, 107)),
    _source(107, scenario="single_hit", flow_suffix="_1"),
    _source(107, scenario="double_hit", flow_suffix="_2"),
    *(_source(edition) for edition in range(108, 119)),
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _next_weekday(day: date) -> date:
    result = day + timedelta(days=1)
    while result.weekday() >= 5:
        result += timedelta(days=1)
    return result


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(payload)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_source_spec(spec: SourceSpec) -> None:
    parsed = urlparse(spec.url)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
        raise ValueError(f"{spec.source_id}: only the official OECD HTTPS API is allowed")
    query = parse_qs(parsed.query, strict_parsing=True)
    expected_query = {
        "startPeriod": [str(spec.start_period)],
        "endPeriod": [str(spec.end_period)],
        "format": ["csvfilewithlabels"],
    }
    if query != expected_query:
        raise ValueError(f"{spec.source_id}: query must contain the frozen size filters")
    key = unquote(parsed.path.rsplit("/", 1)[-1])
    parts = key.split(".")
    if len(parts) != 3:
        raise ValueError(f"{spec.source_id}: missing explicit SDMX dimension key")
    areas, measures, frequency = parts
    if tuple(areas.split("+")) != spec.economy_codes:
        raise ValueError(f"{spec.source_id}: economy filter differs from the frozen subset")
    if tuple(measures.split("+")) != tuple(MEASURES):
        raise ValueError(f"{spec.source_id}: measure filter differs from the frozen subset")
    if frequency != "A":
        raise ValueError(f"{spec.source_id}: only the verified annual frequency is allowed")


def _fetch(
    spec: SourceSpec,
    *,
    timeout: float,
    retries: int,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    max_response_bytes: int = MAX_RESPONSE_BYTES,
) -> tuple[bytes, dict[str, str]]:
    _validate_source_spec(spec)
    last_error: Exception | None = None
    headers = {
        "User-Agent": f"{PROGRAM_VERSION} (+small public-research subset)",
        "Accept": "text/csv",
    }
    for attempt in range(retries + 1):
        try:
            with httpx.Client(
                transport=transport,
                follow_redirects=True,
                timeout=timeout,
                headers=headers,
            ) as client:
                with client.stream("GET", spec.url) as response:
                    response.raise_for_status()
                    declared = response.headers.get("Content-Length")
                    if declared is not None and int(declared) > max_response_bytes:
                        raise ValueError(
                            f"{spec.source_id}: declared response exceeds the size gate"
                        )
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > max_response_bytes:
                            raise ValueError(
                                f"{spec.source_id}: streamed response exceeds the size gate"
                            )
                        chunks.append(chunk)
                    payload = b"".join(chunks)
                    if not payload:
                        raise ValueError(f"{spec.source_id}: OECD response is empty")
                    metadata = {
                        "content_type": response.headers.get("Content-Type", ""),
                        "etag": response.headers.get("ETag", ""),
                        "last_modified": response.headers.get("Last-Modified", ""),
                    }
                    return payload, metadata
        except ValueError:
            # Schema and size-gate failures are deterministic; repeating them
            # would only burden the provider.
            raise
        except httpx.HTTPStatusError as error:
            last_error = error
            status = error.response.status_code
            if status != 429 and status < 500:
                raise
            retry_after = error.response.headers.get("Retry-After", "").strip()
            retry_seconds = float(retry_after) if retry_after.isdigit() else None
            server = error.response.headers.get("Server", "").lower()
            cloudflare_marker = bool(error.response.headers.get("CF-Ray")) or "__cf_bm" in (
                error.response.headers.get("Set-Cookie", "")
            )
            if (
                status == 429
                and spec.api_generation == "legacy_archive"
                and server == "cloudflare"
                and cloudflare_marker
                and retry_seconds is not None
                and retry_seconds <= 0
            ):
                raise ValueError(
                    f"{spec.source_id}: official archive access blocked by Cloudflare; "
                    "retry from permitted network/manual official export"
                ) from error
            if attempt < retries:
                delay = (
                    retry_seconds
                    if retry_seconds is not None and retry_seconds > 0
                    else 0.75 * (2**attempt)
                )
                sleep(min(MAX_RETRY_AFTER_SECONDS, delay))
        except (httpx.HTTPError, OSError) as error:
            last_error = error
            if attempt < retries:
                sleep(min(8.0, 0.75 * (2**attempt)))
    assert last_error is not None
    raise last_error


def _column_contract(fieldnames: list[str] | None) -> dict[str, str]:
    if fieldnames is None:
        raise ValueError("OECD CSV has no header")
    fields = set(fieldnames)
    common = {
        "STRUCTURE_ID",
        "STRUCTURE_NAME",
        "TIME_PERIOD",
        "OBS_VALUE",
        "OBS_STATUS",
        "UNIT_MEASURE",
        "UNIT_MULT",
        "BASE_PER",
    }
    if not common.issubset(fields):
        missing = sorted(common - fields)
        raise ValueError(f"OECD CSV is missing columns: {missing}")
    if {"LOCATION", "Country", "VARIABLE", "Variable", "FREQUENCY"}.issubset(fields):
        return {
            "economy": "LOCATION",
            "economy_name": "Country",
            "measure": "VARIABLE",
            "measure_name": "Variable",
            "frequency": "FREQUENCY",
            "frequency_name": "Frequency",
            "status_name": "Observation Status",
            "unit_name": "Unit of Measures",
            "multiplier_name": "Multiplier",
        }
    modern = {"REF_AREA", "Reference area", "MEASURE", "Measure", "FREQ"}
    if modern.issubset(fields):
        return {
            "economy": "REF_AREA",
            "economy_name": "Reference area",
            "measure": "MEASURE",
            "measure_name": "Measure",
            "frequency": "FREQ",
            "frequency_name": "Frequency of observation",
            "status_name": "Observation status",
            "unit_name": "Unit of measure",
            "multiplier_name": "Unit multiplier",
        }
    raise ValueError("OECD CSV does not match the verified legacy or modern schema")


def _text(row: dict[str, str | None], name: str) -> str:
    value = row.get(name)
    return "" if value is None else str(value).strip()


def normalize_payload(spec: SourceSpec, payload: bytes) -> list[dict[str, object]]:
    """Validate one filtered response and retain its original OECD dimensions."""

    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError(f"{spec.source_id}: response is not UTF-8 CSV") from error
    reader = csv.DictReader(io.StringIO(text))
    columns = _column_contract(reader.fieldnames)
    available_date = _next_weekday(spec.release_date)
    available_time = datetime.combine(available_date, datetime.min.time(), tzinfo=UTC)
    raw_hash = _sha256(payload)
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str]] = set()
    observed_economies: set[str] = set()
    observed_measures: set[str] = set()

    for line_number, raw in enumerate(reader, start=2):
        economy = _text(raw, columns["economy"])
        measure = _text(raw, columns["measure"])
        frequency = _text(raw, columns["frequency"])
        target_period = _text(raw, "TIME_PERIOD")
        if economy not in spec.economy_codes:
            raise ValueError(f"{spec.source_id}:{line_number}: unexpected economy {economy!r}")
        if measure not in MEASURES:
            raise ValueError(f"{spec.source_id}:{line_number}: unexpected measure {measure!r}")
        if frequency != "A":
            raise ValueError(
                f"{spec.source_id}:{line_number}: unexpected frequency {frequency!r}"
            )
        if not re.fullmatch(r"\d{4}", target_period):
            raise ValueError(
                f"{spec.source_id}:{line_number}: unexpected target period {target_period!r}"
            )
        target_year = int(target_period)
        if not spec.start_period <= target_year <= spec.end_period:
            raise ValueError(
                f"{spec.source_id}:{line_number}: target period escaped the query gate"
            )
        raw_value = _text(raw, "OBS_VALUE")
        try:
            value = float(raw_value)
        except ValueError as error:
            raise ValueError(
                f"{spec.source_id}:{line_number}: invalid observation {raw_value!r}"
            ) from error
        if not math.isfinite(value):
            raise ValueError(f"{spec.source_id}:{line_number}: non-finite observation")
        key = (economy, measure, frequency, target_period)
        if key in seen:
            raise ValueError(f"{spec.source_id}:{line_number}: duplicate observation key {key}")
        seen.add(key)
        observed_economies.add(economy)
        observed_measures.add(measure)

        is_euro = economy.startswith("EA")
        if is_euro and spec.edition == 100:
            mapping_quality = "ambiguous_composition_requires_explicit_selection"
        elif is_euro:
            mapping_quality = "composition_specific_explicit_selection_required"
        else:
            mapping_quality = "direct_country_currency_mapping"
        rows.append(
            {
                "edition": spec.edition,
                "scenario": spec.scenario,
                "release_date": spec.release_date.isoformat(),
                "available_time": _iso_utc(available_time),
                "availability_precision": "date_only_conservative_next_weekday",
                "availability_policy": "after_official_oecd_forecast_edition_date",
                "release_kind": "official_date_only_forecast_edition",
                "value_vintage_quality": "official_as_published_forecast_edition",
                "pit_eligible_for_periodic_forecast_research": True,
                "strict_intraday_eligible": False,
                "is_actual_release_vintage": False,
                "is_consensus_surprise": False,
                "economy_code": economy,
                "economy_name": _text(raw, columns["economy_name"]),
                "currency": ECONOMY_CURRENCY[economy],
                "aggregate_variant": economy if is_euro else "",
                "currency_mapping_quality": mapping_quality,
                "composition_break": is_euro,
                "cross_edition_comparability": (
                    "composition_specific_no_automatic_splice" if is_euro else "country_stable"
                ),
                "measure_code": measure,
                "measure_name": _text(raw, columns["measure_name"]),
                "measure_family": MEASURES[measure],
                "frequency_code": frequency,
                "frequency_name": _text(raw, columns["frequency_name"]),
                "target_period": target_period,
                "forecast_horizon_years": target_year - spec.release_date.year,
                "is_future_target": target_year > spec.release_date.year,
                "value": value,
                "observation_status_code": _text(raw, "OBS_STATUS"),
                "observation_status_name": _text(raw, columns["status_name"]),
                "unit_code": _text(raw, "UNIT_MEASURE"),
                "unit_name": _text(raw, columns["unit_name"]),
                "unit_multiplier_code": _text(raw, "UNIT_MULT"),
                "unit_multiplier_name": _text(raw, columns["multiplier_name"]),
                "base_period": _text(raw, "BASE_PER"),
                "structure_id": _text(raw, "STRUCTURE_ID"),
                "structure_name": _text(raw, "STRUCTURE_NAME"),
                "provider": PROVIDER,
                "source_url": spec.url,
                "raw_sha256": raw_hash,
            }
        )

    if not rows:
        raise ValueError(f"{spec.source_id}: filtered response contains no observations")
    missing_economies = set(spec.economy_codes) - observed_economies
    missing_measures = set(MEASURES) - observed_measures
    if missing_economies or missing_measures:
        raise ValueError(
            f"{spec.source_id}: incomplete filtered response; "
            f"missing economies={sorted(missing_economies)}, "
            f"missing measures={sorted(missing_measures)}"
        )
    return rows


def _archive_snapshot(
    root: Path,
    *,
    spec: SourceSpec,
    payload: bytes,
    retrieved_at: datetime,
) -> Path:
    digest = _sha256(payload)
    timestamp = retrieved_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    destination = root / "raw" / "archive" / spec.source_id / f"{timestamp}_{digest[:16]}.csv"
    if destination.exists():
        if _sha256(destination.read_bytes()) != digest:
            raise ValueError(f"archived OECD snapshot digest mismatch: {destination}")
    else:
        _atomic_write(destination, payload)
    return destination


def _write_normalized(rows: list[dict[str, object]], path: Path) -> str:
    key_fields = (
        "edition",
        "scenario",
        "economy_code",
        "aggregate_variant",
        "measure_code",
        "frequency_code",
        "target_period",
    )
    keys = {tuple(row[field] for field in key_fields) for row in rows}
    if not rows or len(keys) != len(rows):
        raise ValueError("normalized OECD output is empty or contains duplicate keys")
    ordered = sorted(
        rows,
        key=lambda row: (
            int(row["edition"]),
            str(row["scenario"]),
            str(row["economy_code"]),
            str(row["measure_code"]),
            str(row["frequency_code"]),
            str(row["target_period"]),
        ),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as binary:
            with gzip.GzipFile(filename="", mode="wb", fileobj=binary, mtime=0) as compressed:
                with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text:
                    writer = csv.DictWriter(text, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
                    writer.writeheader()
                    writer.writerows(ordered)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return _sha256(path.read_bytes())


def _previous_sources(manifest_path: Path) -> dict[str, dict[str, object]]:
    if not manifest_path.exists():
        return {}
    sidecar_path = manifest_path.with_suffix(".sha256")
    if not sidecar_path.is_file():
        raise ValueError("existing OECD manifest has no SHA-256 sidecar")
    try:
        manifest_payload = manifest_path.read_bytes()
        expected_hash = sidecar_path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError("existing OECD manifest or SHA-256 sidecar is unreadable") from error
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise ValueError("existing OECD manifest SHA-256 sidecar is invalid")
    if _sha256(manifest_payload) != expected_hash:
        raise ValueError("existing OECD manifest SHA-256 verification failed")
    try:
        manifest = json.loads(manifest_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("existing OECD manifest is unreadable") from error
    sources = manifest.get("sources")
    if not isinstance(sources, list):
        raise ValueError("existing OECD manifest has no source list")
    indexed: dict[str, dict[str, object]] = {}
    for item in sources:
        if not isinstance(item, dict):
            raise ValueError("existing OECD manifest contains an invalid source record")
        source_id = str(item.get("source_id", ""))
        digest = str(item.get("sha256", ""))
        if not source_id or source_id in indexed:
            raise ValueError("existing OECD manifest contains a missing or duplicate source id")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"existing OECD source {source_id!r} has an invalid SHA-256")
        indexed[source_id] = item
    return indexed


def download_dataset(
    output_directory: str | Path,
    *,
    refresh: bool = False,
    timeout: float = 60.0,
    retries: int = 3,
    request_delay: float = DEFAULT_REQUEST_DELAY_SECONDS,
    transport: httpx.BaseTransport | None = None,
    now: datetime | None = None,
    sources: Iterable[SourceSpec] = SOURCES,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[Path, Path]:
    if timeout <= 0 or not 0 <= retries <= 10 or request_delay < 0:
        raise ValueError("invalid timeout, retry count, or request delay")
    root = Path(output_directory).expanduser().resolve()
    manifest_path = root / "oecd_economic_outlook_manifest.json"
    # An explicit refresh never trusts an old cache or its manifest.
    prior = {} if refresh else _previous_sources(manifest_path)
    run_time = (now or datetime.now(UTC)).astimezone(UTC)
    rows: list[dict[str, object]] = []
    source_records: list[dict[str, object]] = []
    specs = tuple(sources)
    if not specs:
        raise ValueError("no OECD source editions were declared")

    downloaded = 0
    for spec in specs:
        _validate_source_spec(spec)
        cache_path = root / "raw" / "cache" / f"{spec.source_id}.csv"
        prior_record = prior.get(spec.source_id)
        if cache_path.exists() and not refresh:
            if prior_record is None:
                raise ValueError(
                    f"{spec.source_id}: orphan cache has no verified manifest source record; "
                    "run with --refresh to replace it"
                )
            payload = cache_path.read_bytes()
            expected_hash = str(prior_record["sha256"])
            if _sha256(payload) != expected_hash:
                raise ValueError(f"{spec.source_id}: cached response hash differs from manifest")
            retrieved_raw = prior_record.get("retrieved_at")
            retrieved_at = (
                datetime.fromisoformat(str(retrieved_raw).replace("Z", "+00:00"))
                if retrieved_raw
                else datetime.fromtimestamp(cache_path.stat().st_mtime, tz=UTC)
            )
            response_metadata = {
                "content_type": str(prior_record.get("content_type", "")),
                "etag": str(prior_record.get("etag", "")),
                "last_modified": str(prior_record.get("last_modified", "")),
            }
            status = "cached"
        else:
            if downloaded and request_delay:
                sleep(request_delay)
            payload, response_metadata = _fetch(
                spec,
                timeout=timeout,
                retries=retries,
                transport=transport,
                sleep=sleep,
            )
            # Validate before replacing a known-good cache.
            normalized = normalize_payload(spec, payload)
            _atomic_write(cache_path, payload)
            retrieved_at = run_time
            status = "downloaded"
            downloaded += 1

        normalized = normalize_payload(spec, payload)
        rows.extend(normalized)
        archive_path = _archive_snapshot(
            root,
            spec=spec,
            payload=payload,
            retrieved_at=retrieved_at,
        )
        source_records.append(
            {
                "source_id": spec.source_id,
                "edition": spec.edition,
                "scenario": spec.scenario,
                "api_generation": spec.api_generation,
                "flow_id": spec.flow_id,
                "url": spec.url,
                "status": status,
                "retrieved_at": _iso_utc(retrieved_at),
                "bytes": len(payload),
                "sha256": _sha256(payload),
                "rows": len(normalized),
                "cache_path": cache_path.relative_to(root).as_posix(),
                "archive_path": archive_path.relative_to(root).as_posix(),
                **response_metadata,
            }
        )

    normalized_path = root / "normalized" / "oecd_economic_outlook_forecasts.csv.gz"
    normalized_hash = _write_normalized(rows, normalized_path)
    euro_variants = sorted(
        {str(row["aggregate_variant"]) for row in rows if row["aggregate_variant"]}
    )
    manifest = {
        "schema_version": 1,
        "program_version": PROGRAM_VERSION,
        "retrieved_at": _iso_utc(run_time),
        "official_api_only": True,
        "rows": len(rows),
        "editions": sorted({int(row["edition"]) for row in rows}),
        "measures": list(MEASURES),
        "euro_area_aggregate_variants": euro_variants,
        "normalized_path": normalized_path.relative_to(root).as_posix(),
        "normalized_format": "deterministic gzip-compressed CSV",
        "normalized_sha256": normalized_hash,
        "availability_contract": {
            "release_kind": "official_date_only_forecast_edition",
            "policy": "next weekday after official OECD publication date at 00:00 UTC",
            "actual_release_vintage": False,
            "consensus_surprise": False,
            "strict_intraday_eligible": False,
        },
        "query_gate": {
            "server_side_dimensions": ["economy", "measure", "annual frequency"],
            "target_period_window": "publication year through publication year + 2",
            "max_response_bytes_per_source": MAX_RESPONSE_BYTES,
            "full_dataflow_fallback": False,
        },
        "sources": source_records,
        "limitations": [
            "Forecast editions are not actual-data release vintages or consensus surprises.",
            "Publication evidence has date precision only; rows are not eligible for intraday use.",
            "EA15, EA16, and EA17 are OECD-member aggregates, not counts of all euro users.",
            "EO100 contains both EA15 and EA16 and requires explicit downstream selection.",
            "Euro-area composition changes are structural breaks and are never auto-spliced.",
            "The downloader fails closed instead of requesting an unfiltered OECD dataflow.",
        ],
    }
    manifest_payload = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode()
    manifest_hash = _sha256(manifest_payload)
    _atomic_write(manifest_path, manifest_payload)
    _atomic_write(manifest_path.with_suffix(".sha256"), f"{manifest_hash}\n".encode())
    _atomic_write(
        root / "manifests" / f"oecd_eo_{run_time.strftime('%Y%m%dT%H%M%S%fZ')}.json",
        manifest_payload,
    )
    return normalized_path, manifest_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/oecd_economic_outlook"))
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument(
        "--request-delay",
        type=float,
        default=DEFAULT_REQUEST_DELAY_SECONDS,
        help="Delay between OECD network requests; cached files do not incur a delay.",
    )
    parser.add_argument("--refresh", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        normalized_path, manifest_path = download_dataset(
            args.output,
            refresh=args.refresh,
            timeout=args.timeout,
            retries=args.retries,
            request_delay=args.request_delay,
        )
    except Exception as error:
        print(f"OECD Economic Outlook download failed: {error}", file=sys.stderr)
        return 1
    print(f"Wrote {normalized_path}")
    print(f"Wrote {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
