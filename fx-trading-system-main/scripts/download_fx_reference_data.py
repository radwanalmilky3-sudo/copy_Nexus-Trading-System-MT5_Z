#!/usr/bin/env python3
"""Download small public reference datasets used in FX factor research.

The downloader deliberately stores provider-native files. It does not relabel
money-market rates as OIS, infer forward points, or turn current-vintage data
into point-in-time data. Every file receives a sidecar metadata document with
its source URL and SHA-256 digest, and the run receives a combined manifest.

Only Python's standard library is required, so the script can run on a small
VPS independently of the main project environment.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DOWNLOADER_VERSION = "fx-reference-downloader-v1"
MAX_FILE_BYTES = 128 * 1024 * 1024
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
CFTC_URL = "https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip"
CFTC_HISTORY_URL = "https://www.cftc.gov/files/dea/history/fin_fut_txt_2006_2016.zip"

# Both public endpoints throttle bursts. Downloads from the two independent
# providers can overlap, but requests to the same provider remain serialized.
_PROVIDER_LIMITERS = {
    "fred": threading.BoundedSemaphore(1),
    "cftc": threading.BoundedSemaphore(1),
}


@dataclass(frozen=True)
class DownloadTask:
    key: str
    group: str
    provider: str
    title: str
    url: str
    relative_path: str
    validator: str
    research_eligibility: str
    mutable: bool = True
    series_id: str | None = None
    year: int | None = None


FRED_SERIES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "value": (
        ("RBUSBIS", "BIS real broad effective exchange rate: United States", "USD"),
        ("RBXMBIS", "BIS real broad effective exchange rate: Euro area", "EUR"),
        ("RBGBBIS", "BIS real broad effective exchange rate: United Kingdom", "GBP"),
        ("RBJPBIS", "BIS real broad effective exchange rate: Japan", "JPY"),
        ("RBCHBIS", "BIS real broad effective exchange rate: Switzerland", "CHF"),
        ("RBCABIS", "BIS real broad effective exchange rate: Canada", "CAD"),
        ("RBAUBIS", "BIS real broad effective exchange rate: Australia", "AUD"),
        ("RBNZBIS", "BIS real broad effective exchange rate: New Zealand", "NZD"),
    ),
    "risk": (
        ("VIXCLS", "CBOE VIX close", "global_risk"),
        ("DTWEXBGS", "Federal Reserve nominal broad US dollar index", "usd_regime"),
        ("NFCI", "Chicago Fed national financial conditions index", "financial_conditions"),
        ("STLFSI4", "St. Louis Fed financial stress index", "financial_stress"),
        ("BAMLH0A0HYM2", "US high-yield option-adjusted spread", "credit_risk"),
    ),
    "rates_reference": (
        ("DFF", "Effective federal funds rate", "USD"),
        ("ECBDFR", "ECB deposit facility rate", "EUR"),
        ("IRSTCI01GBM156N", "OECD immediate rate: United Kingdom", "GBP"),
        ("IRSTCI01JPM156N", "OECD immediate rate: Japan", "JPY"),
        ("IRSTCI01CHM156N", "OECD immediate rate: Switzerland", "CHF"),
        ("IRSTCI01CAM156N", "OECD immediate rate: Canada", "CAD"),
        ("IRSTCI01AUM156N", "OECD immediate rate: Australia", "AUD"),
        ("IRSTCI01NZM156N", "OECD immediate rate: New Zealand", "NZD"),
    ),
}

GROUP_DESCRIPTIONS = {
    "value": "BIS real effective exchange-rate levels delivered by FRED",
    "risk": "public risk-regime and financial-condition series",
    "rates_reference": "heterogeneous policy/money-market references; not OIS or tradable carry",
    "cftc": "raw CFTC Traders in Financial Futures annual archives",
}


def build_tasks(start_year: int, end_year: int) -> list[DownloadTask]:
    tasks: list[DownloadTask] = []
    for group, series in FRED_SERIES.items():
        eligibility = {
            "value": "exploratory_current_vintage_not_point_in_time",
            "risk": "exploratory_current_vintage_not_release_surprise",
            "rates_reference": "proxy_only_not_ois_forward_or_broker_swap",
        }[group]
        for series_id, title, _entity in series:
            tasks.append(
                DownloadTask(
                    key=f"fred:{series_id}",
                    group=group,
                    provider="fred",
                    title=title,
                    url=FRED_URL.format(series_id=series_id),
                    relative_path=f"fred/{group}/{series_id}.csv",
                    validator="fred_csv",
                    research_eligibility=eligibility,
                    series_id=series_id,
                )
            )
    current_year = datetime.now(UTC).year
    if start_year < 2010:
        tasks.append(
            DownloadTask(
                key="cftc:tff:2006_2016",
                group="cftc",
                provider="cftc",
                title="CFTC TFF combined history 2006-2016",
                url=CFTC_HISTORY_URL,
                relative_path="cftc/tff/fin_fut_txt_2006_2016.zip",
                validator="cftc_zip",
                research_eligibility="raw_requires_point_in_time_release_lag_handling",
                mutable=False,
            )
        )
    for year in range(max(2010, start_year), end_year + 1):
        tasks.append(
            DownloadTask(
                key=f"cftc:tff:{year}",
                group="cftc",
                provider="cftc",
                title=f"CFTC TFF futures-only archive {year}",
                url=CFTC_URL.format(year=year),
                relative_path=f"cftc/tff/fut_fin_txt_{year}.zip",
                validator="cftc_zip",
                research_eligibility="raw_requires_point_in_time_release_lag_handling",
                mutable=year == current_year,
                year=year,
            )
        )
    return tasks


def _validate_fred_csv(payload: bytes, task: DownloadTask) -> dict[str, Any]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError(f"{task.key}: response is not UTF-8 CSV") from error
    if text.lstrip().lower().startswith(("<!doctype html", "<html")):
        raise ValueError(f"{task.key}: provider returned HTML instead of CSV")
    rows = list(csv.reader(io.StringIO(text)))
    expected_header = ["observation_date", str(task.series_id)]
    if not rows or rows[0] != expected_header:
        raise ValueError(f"{task.key}: unexpected CSV header {rows[0] if rows else None!r}")
    if len(rows) < 3:
        raise ValueError(f"{task.key}: expected at least two observations")
    observation_dates: list[date] = []
    non_missing = 0
    for line_number, row in enumerate(rows[1:], start=2):
        if len(row) != 2:
            raise ValueError(f"{task.key}: line {line_number} does not have two fields")
        try:
            observation_dates.append(date.fromisoformat(row[0]))
        except ValueError as error:
            raise ValueError(f"{task.key}: invalid date on line {line_number}") from error
        value = row[1].strip()
        if value not in {"", "."}:
            try:
                number = float(value)
            except ValueError as error:
                raise ValueError(f"{task.key}: invalid value on line {line_number}") from error
            if not (-1e100 < number < 1e100):
                raise ValueError(f"{task.key}: non-finite value on line {line_number}")
            non_missing += 1
    if observation_dates != sorted(observation_dates):
        raise ValueError(f"{task.key}: observation dates are not sorted")
    if len(set(observation_dates)) != len(observation_dates):
        raise ValueError(f"{task.key}: duplicate observation dates")
    if non_missing == 0:
        raise ValueError(f"{task.key}: all observations are missing")
    return {
        "rows": len(rows) - 1,
        "non_missing_rows": non_missing,
        "first_observation": observation_dates[0].isoformat(),
        "last_observation": observation_dates[-1].isoformat(),
    }


def _validate_cftc_zip(payload: bytes, task: DownloadTask) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise ValueError(f"{task.key}: corrupt ZIP member {bad_member}")
            text_members = [name for name in archive.namelist() if name.lower().endswith(".txt")]
            if len(text_members) != 1:
                raise ValueError(f"{task.key}: expected one TXT member, found {text_members}")
            info = archive.getinfo(text_members[0])
            if info.file_size <= 0:
                raise ValueError(f"{task.key}: empty TXT member")
            with archive.open(info) as handle:
                header = handle.readline(64 * 1024).decode("utf-8-sig", errors="strict")
            has_contract = "CFTC_Contract_Market_Code" in header
            has_report_date = any(
                marker in header
                for marker in ("Report_Date_as_YYYY-MM-DD", "Report_Date_as_MM_DD_YYYY")
            )
            if not has_contract or not has_report_date:
                raise ValueError(f"{task.key}: TFF header does not match the expected schema")
            return {
                "archive_members": archive.namelist(),
                "uncompressed_bytes": info.file_size,
            }
    except zipfile.BadZipFile as error:
        raise ValueError(f"{task.key}: response is not a valid ZIP") from error


def validate_payload(payload: bytes, task: DownloadTask) -> dict[str, Any]:
    if len(payload) == 0:
        raise ValueError(f"{task.key}: empty response")
    if len(payload) > MAX_FILE_BYTES:
        raise ValueError(f"{task.key}: response exceeds {MAX_FILE_BYTES} bytes")
    if task.validator == "fred_csv":
        return _validate_fred_csv(payload, task)
    if task.validator == "cftc_zip":
        return _validate_cftc_zip(payload, task)
    raise ValueError(f"{task.key}: unknown validator {task.validator!r}")


def _fetch(task: DownloadTask, timeout: float, retries: int) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(
        task.url,
        headers={
            "User-Agent": f"{DOWNLOADER_VERSION} (+public research archive)",
        },
    )
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with _PROVIDER_LIMITERS[task.provider]:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    declared_length = response.headers.get("Content-Length")
                    if declared_length and int(declared_length) > MAX_FILE_BYTES:
                        raise ValueError(f"{task.key}: declared response is too large")
                    payload = response.read(MAX_FILE_BYTES + 1)
                    if len(payload) > MAX_FILE_BYTES:
                        raise ValueError(f"{task.key}: response exceeds maximum size")
                    headers = {
                        "content_type": response.headers.get("Content-Type", ""),
                        "etag": response.headers.get("ETag", ""),
                        "last_modified": response.headers.get("Last-Modified", ""),
                    }
                    return payload, headers
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


def _write_json(path: Path, value: dict[str, Any]) -> None:
    encoded = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    _atomic_write(path, encoded)


def download_task(
    task: DownloadTask,
    output_root: Path,
    *,
    timeout: float,
    retries: int,
    refresh: bool,
    skip_existing: bool,
) -> dict[str, Any]:
    destination = output_root / task.relative_path
    metadata_path = destination.with_suffix(destination.suffix + ".meta.json")
    may_reuse = destination.exists() and not refresh and (skip_existing or not task.mutable)
    if may_reuse:
        payload = destination.read_bytes()
        validation = validate_payload(payload, task)
        result = {
            **asdict(task),
            "status": "cached",
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "path": destination.relative_to(output_root).as_posix(),
            "validated_at": datetime.now(UTC).isoformat(),
            "validation": validation,
        }
        if metadata_path.exists():
            previous = json.loads(metadata_path.read_text(encoding="utf-8"))
            result["retrieved_at"] = previous.get("retrieved_at")
            if previous.get("sha256") != result["sha256"]:
                raise ValueError(f"{task.key}: cached file does not match its metadata digest")
        return result

    payload, response_headers = _fetch(task, timeout, retries)
    validation = validate_payload(payload, task)
    retrieved_at = datetime.now(UTC).isoformat()
    digest = hashlib.sha256(payload).hexdigest()
    _atomic_write(destination, payload)
    result = {
        **asdict(task),
        "status": "downloaded",
        "bytes": len(payload),
        "sha256": digest,
        "path": destination.relative_to(output_root).as_posix(),
        "retrieved_at": retrieved_at,
        "validated_at": retrieved_at,
        "response_headers": response_headers,
        "validation": validation,
    }
    _write_json(metadata_path, result)
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/external_raw"))
    parser.add_argument(
        "--group",
        action="append",
        choices=[*GROUP_DESCRIPTIONS, "all"],
        help="Download one group; repeat the option for several groups (default: all)",
    )
    parser.add_argument("--start-year", type=int, default=2006, help="First CFTC TFF year")
    parser.add_argument(
        "--end-year", type=int, default=datetime.now(UTC).year, help="Last CFTC TFF year"
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--refresh", action="store_true", help="Redownload every selected file")
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Reuse every valid existing file, including normally mutable series",
    )
    parser.add_argument("--list", action="store_true", help="List tasks without downloading")
    return parser.parse_args(argv)


def _interleave_providers(tasks: list[DownloadTask]) -> list[DownloadTask]:
    """Keep both provider lanes busy without bursting either public endpoint."""
    buckets = {
        provider: [task for task in tasks if task.provider == provider]
        for provider in sorted({task.provider for task in tasks})
    }
    ordered: list[DownloadTask] = []
    while any(buckets.values()):
        for provider in buckets:
            if buckets[provider]:
                ordered.append(buckets[provider].pop(0))
    return ordered


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    current_year = datetime.now(UTC).year
    if not 2006 <= args.start_year <= args.end_year <= current_year:
        print(f"CFTC years must satisfy 2006 <= start <= end <= {current_year}", file=sys.stderr)
        return 2
    if not 1 <= args.workers <= 32:
        print("--workers must be between 1 and 32", file=sys.stderr)
        return 2
    if args.timeout <= 0 or not 0 <= args.retries <= 10:
        print("--timeout must be positive and --retries must be between 0 and 10", file=sys.stderr)
        return 2

    selected_groups = set(args.group or ["all"])
    if "all" in selected_groups:
        selected_groups = set(GROUP_DESCRIPTIONS)
    tasks = _interleave_providers(
        [
            task
            for task in build_tasks(args.start_year, args.end_year)
            if task.group in selected_groups
        ]
    )
    if args.list:
        for task in tasks:
            print(f"{task.group:15} {task.key:28} {task.url}")
        return 0

    output_root = args.output.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(UTC).isoformat()
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                download_task,
                task,
                output_root,
                timeout=args.timeout,
                retries=args.retries,
                refresh=args.refresh,
                skip_existing=args.skip_existing,
            ): task
            for task in tasks
        }
        for future in as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
                results.append(result)
                print(
                    f"[{result['status']:10}] {task.key:28} "
                    f"{result['bytes'] / 1024:10.1f} KiB",
                    flush=True,
                )
            except Exception as error:  # keep independent tasks running and report all failures
                errors.append({"key": task.key, "url": task.url, "error": str(error)})
                print(f"[failed    ] {task.key:28} {error}", file=sys.stderr, flush=True)

    results.sort(key=lambda item: item["key"])
    errors.sort(key=lambda item: item["key"])
    total_bytes = sum(int(item["bytes"]) for item in results)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "downloader_version": DOWNLOADER_VERSION,
        "started_at": started_at,
        "completed_at": datetime.now(UTC).isoformat(),
        "output_root": str(output_root),
        "selected_groups": sorted(selected_groups),
        "group_descriptions": GROUP_DESCRIPTIONS,
        "summary": {
            "selected_tasks": len(tasks),
            "successful_tasks": len(results),
            "failed_tasks": len(errors),
            "downloaded_tasks": sum(item["status"] == "downloaded" for item in results),
            "cached_tasks": sum(item["status"] == "cached" for item in results),
            "total_bytes": total_bytes,
        },
        "tasks": results,
        "errors": errors,
        "limitations": [
            "FRED files are current-vintage downloads, not revision-aware point-in-time data.",
            "Rate references are heterogeneous and must not be called OIS or tradable carry.",
            "CFTC report dates are not actual publication timestamps.",
            "No forward points, option-implied data, or broker financing history is synthesized.",
        ],
    }
    manifest_name = f"download_manifest_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    _write_json(output_root / manifest_name, manifest)
    _write_json(output_root / "latest_manifest.json", manifest)
    print(
        f"Completed {len(results)}/{len(tasks)} tasks, {total_bytes / (1024**2):.2f} MiB; "
        f"manifest={output_root / 'latest_manifest.json'}"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
