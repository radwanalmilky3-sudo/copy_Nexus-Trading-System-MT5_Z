#!/usr/bin/env python3
"""Download and normalize Philadelphia Fed RTDSM CPI and IP vintages.

Unlike ordinary historical macro downloads, every value in the output remains
attached to the vintage in which it appeared.  Availability is conservative:
date-only releases become usable at the start of the following New York day.
When an exact historical G.17 release date cannot be verified, an IP vintage is
not made usable until the start of the month after its labelled vintage month.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

PROGRAM_VERSION = "phillyfed-rtdsm-v3"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
NEW_YORK = ZoneInfo("America/New_York")

CPI_URL = (
    "https://www.philadelphiafed.org/-/media/FRBP/Assets/Surveys-And-Data/"
    "real-time-data/data-files/xlsx/cpiQvMd.xlsx"
)
IP_URL = (
    "https://www.philadelphiafed.org/-/media/FRBP/Assets/Surveys-And-Data/"
    "real-time-data/data-files/xlsx/iptMvMd.xlsx"
)
G17_ARCHIVE_URL = "https://www.federalreserve.gov/releases/g17/"

OUTPUT_COLUMNS = [
    "observation_time",
    "vintage_label",
    "vintage_period",
    "vintage_date",
    "available_time",
    "availability_precision",
    "availability_policy",
    "series_id",
    "series_name",
    "value",
    "unit",
    "frequency",
    "provider",
    "quality",
    "pit_eligible",
    "source_url",
    "availability_source_url",
]

OBSERVATION_PATTERN = re.compile(r"(\d{4}):(\d{2})")
CPI_VINTAGE_PATTERN = re.compile(r"CPI(\d{2})Q([1-4])", re.IGNORECASE)
IP_VINTAGE_PATTERN = re.compile(r"IPT(\d{2})M(1[0-2]|[1-9])", re.IGNORECASE)
G17_LINK_PATTERN = re.compile(
    r"href=[\"'](?![^\"']*[Rr]evisions/)"
    r"(?:https://www\.federalreserve\.gov/releases/g17/)?"
    r"(\d{8})(?:/|[\"'])",
    re.IGNORECASE,
)


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(payload)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sidecar_payload(digest: str, filename: str) -> bytes:
    return f"{digest}  {filename}\n".encode("ascii")


def _sidecar_digest(path: Path, filename: str) -> str:
    try:
        line = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError(f"invalid RTDSM SHA-256 sidecar: {path}") from error
    match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
    if match is None or match.group(2) != filename:
        raise ValueError(f"invalid RTDSM SHA-256 sidecar: {path}")
    return match.group(1)


def _safe_child(root: Path, relative: object, label: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError(f"RTDSM {label} path is missing")
    path = (root / relative).resolve()
    if root not in path.parents:
        raise ValueError(f"RTDSM {label} path escaped the output root")
    return path


def _archive_snapshot(
    root: Path,
    *,
    key: str,
    relative_path: str,
    payload: bytes,
    retrieved_at: datetime,
) -> Path:
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise ValueError("snapshot retrieved_at must be timezone-aware")
    timestamp = retrieved_at.astimezone(UTC)
    digest = hashlib.sha256(payload).hexdigest()
    suffixes = "".join(Path(relative_path).suffixes) or ".bin"
    filename = f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}_{digest[:16]}{suffixes}"
    destination = root / "archive" / key / f"{timestamp.year:04d}" / filename
    if destination.exists():
        if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            raise ValueError(f"archived RTDSM snapshot digest mismatch: {destination}")
    else:
        _atomic_write(destination, payload)
    return destination


def _fetch(url: str, timeout: float, retries: int) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": f"{PROGRAM_VERSION} (+public research archive)"}
    )
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                declared = response.headers.get("Content-Length")
                if declared and int(declared) > MAX_RESPONSE_BYTES:
                    raise ValueError("RTDSM response exceeds declared size limit")
                payload = response.read(MAX_RESPONSE_BYTES + 1)
                if not payload or len(payload) > MAX_RESPONSE_BYTES:
                    raise ValueError("RTDSM response is empty or oversized")
                return payload
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, ValueError) as error:
            last_error = error
            if attempt < retries:
                time.sleep(0.5 * (2**attempt))
    assert last_error is not None
    raise last_error


def _read_excel(payload: bytes, sheet_name: str) -> pd.DataFrame:
    if not payload.startswith(b"PK"):
        raise ValueError("RTDSM workbook is not an XLSX file")
    try:
        return pd.read_excel(io.BytesIO(payload), sheet_name=sheet_name, engine="openpyxl")
    except (ValueError, KeyError) as error:
        raise ValueError(f"RTDSM workbook is missing sheet {sheet_name!r}") from error


def _four_digit_year(two_digit_year: int) -> int:
    # Both official files start in the 1960s and continue through the 2000s.
    return 1900 + two_digit_year if two_digit_year >= 60 else 2000 + two_digit_year


def _month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def _next_local_day_start(day: date) -> datetime:
    local = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=NEW_YORK)
    return local.astimezone(UTC)


def _next_local_month_start(year: int, month: int) -> datetime:
    if month == 12:
        year, month = year + 1, 1
    else:
        month += 1
    return datetime(year, month, 1, tzinfo=NEW_YORK).astimezone(UTC)


def _finite(value: object, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid {label}: {value!r}") from error
    if not math.isfinite(number):
        raise ValueError(f"non-finite {label}: {value!r}")
    return number


def _observation_dates(frame: pd.DataFrame) -> pd.Series:
    if "DATE" not in frame.columns:
        raise ValueError("RTDSM workbook is missing the DATE column")
    parsed: list[date | None] = []
    seen: set[date] = set()
    for raw in frame["DATE"]:
        if pd.isna(raw) or not str(raw).strip():
            parsed.append(None)
            continue
        match = OBSERVATION_PATTERN.fullmatch(str(raw).strip())
        if not match:
            raise ValueError(f"invalid RTDSM observation label: {raw!r}")
        year, month = int(match.group(1)), int(match.group(2))
        if not 1 <= month <= 12:
            raise ValueError(f"invalid RTDSM observation month: {raw!r}")
        observation = _month_end(year, month)
        if observation in seen:
            raise ValueError(f"duplicate RTDSM observation label: {raw!r}")
        seen.add(observation)
        parsed.append(observation)
    if len(seen) < 2:
        raise ValueError("RTDSM workbook contains too few observation periods")
    return pd.Series(parsed, index=frame.index, dtype="object")


def parse_g17_release_dates(payload: bytes) -> dict[tuple[int, int], date]:
    """Return the latest ordinary G.17 release date in each calendar month."""

    try:
        html = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("Federal Reserve G.17 archive is not valid UTF-8") from error
    releases: dict[tuple[int, int], date] = {}
    for raw in G17_LINK_PATTERN.findall(html):
        try:
            release = datetime.strptime(raw, "%Y%m%d").date()
        except ValueError as error:
            raise ValueError(f"invalid G.17 archive release date: {raw}") from error
        key = (release.year, release.month)
        releases[key] = max(release, releases.get(key, release))
    if len(releases) < 12:
        raise ValueError("Federal Reserve G.17 archive contains too few release months")
    return releases


def _record(
    *,
    observation: date,
    vintage_label: str,
    vintage_period: str,
    vintage_date: date | None,
    available: datetime,
    availability_policy: str,
    series_id: str,
    series_name: str,
    value: object,
    unit: str,
    quality: str,
    source_url: str,
    availability_source_url: str,
) -> dict[str, object]:
    observation_time = datetime.combine(observation, datetime.min.time(), tzinfo=UTC)
    if observation_time >= available:
        raise ValueError(
            f"{vintage_label} includes observation {observation} at/after availability"
        )
    return {
        "observation_time": observation_time.isoformat(),
        "vintage_label": vintage_label,
        "vintage_period": vintage_period,
        "vintage_date": vintage_date.isoformat() if vintage_date else "",
        "available_time": available.isoformat(),
        "availability_precision": "date_only_conservative_next_day",
        "availability_policy": availability_policy,
        "series_id": series_id,
        "series_name": series_name,
        "value": _finite(value, f"{series_id} {vintage_label}"),
        "unit": unit,
        "frequency": "monthly",
        "provider": "philadelphia_fed_rtdsm",
        "quality": quality,
        "pit_eligible": True,
        "source_url": source_url,
        "availability_source_url": availability_source_url,
    }


def parse_cpi_vintages(payload: bytes, source_url: str = CPI_URL) -> list[dict[str, object]]:
    frame = _read_excel(payload, "cpi")
    observations = _observation_dates(frame)
    output: list[dict[str, object]] = []
    populated_vintages = 0
    for column in frame.columns[1:]:
        match = CPI_VINTAGE_PATTERN.fullmatch(str(column).strip())
        if not match:
            raise ValueError(f"invalid CPI vintage label: {column!r}")
        values = frame[column]
        valid = observations.notna() & values.notna()
        if not valid.any():
            continue
        year = _four_digit_year(int(match.group(1)))
        quarter = int(match.group(2))
        vintage_day = date(year, {1: 2, 2: 5, 3: 8, 4: 11}[quarter], 15)
        available = _next_local_day_start(vintage_day)
        vintage_label = str(column).strip()
        for row_number in frame.index[valid]:
            output.append(
                _record(
                    observation=observations.at[row_number],
                    vintage_label=vintage_label,
                    vintage_period=f"{year:04d}-Q{quarter}",
                    vintage_date=vintage_day,
                    available=available,
                    availability_policy="after_rtdsm_mid_quarter_vintage_date",
                    series_id="US_CPI_SA_RTDSM",
                    series_name="US Consumer Price Index, seasonally adjusted",
                    value=values.at[row_number],
                    unit="index_level_vintage_specific_base",
                    quality="official_quarterly_vintage_date_level",
                    source_url=source_url,
                    availability_source_url=source_url,
                )
            )
        populated_vintages += 1
    if populated_vintages < 2 or not output:
        raise ValueError("CPI workbook contains too few populated vintages")
    return output


def parse_ip_vintages(
    payload: bytes,
    release_dates: dict[tuple[int, int], date],
    source_url: str = IP_URL,
    release_source_url: str = G17_ARCHIVE_URL,
) -> list[dict[str, object]]:
    frame = _read_excel(payload, "ipt")
    observations = _observation_dates(frame)
    output: list[dict[str, object]] = []
    populated_vintages = 0
    for column in frame.columns[1:]:
        match = IP_VINTAGE_PATTERN.fullmatch(str(column).strip())
        if not match:
            raise ValueError(f"invalid IP vintage label: {column!r}")
        values = frame[column]
        valid = observations.notna() & values.notna()
        if not valid.any():
            continue
        year = _four_digit_year(int(match.group(1)))
        month = int(match.group(2))
        release = release_dates.get((year, month))
        if release is None:
            available = _next_local_month_start(year, month)
            availability_policy = "after_unresolved_ip_vintage_month"
            quality = "official_monthly_vintage_conservative_month_end"
            availability_url = source_url
        else:
            available = _next_local_day_start(release)
            availability_policy = "after_verified_g17_release_date"
            quality = "official_monthly_vintage_release_day_verified"
            availability_url = release_source_url
        vintage_label = str(column).strip()
        for row_number in frame.index[valid]:
            output.append(
                _record(
                    observation=observations.at[row_number],
                    vintage_label=vintage_label,
                    vintage_period=f"{year:04d}-{month:02d}",
                    vintage_date=release,
                    available=available,
                    availability_policy=availability_policy,
                    series_id="US_IP_TOTAL_SA_RTDSM",
                    series_name="US Total Industrial Production Index, seasonally adjusted",
                    value=values.at[row_number],
                    unit="index_level_vintage_specific_base",
                    quality=quality,
                    source_url=source_url,
                    availability_source_url=availability_url,
                )
            )
        populated_vintages += 1
    if populated_vintages < 2 or not output:
        raise ValueError("IP workbook contains too few populated vintages")
    return output


def _write_vintages(rows: list[dict[str, object]], path: Path) -> str:
    frame = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    key = ["observation_time", "vintage_label", "series_id"]
    if frame.empty or frame.duplicated(key).any():
        raise ValueError("normalized RTDSM data is empty or contains duplicate keys")
    if not frame["pit_eligible"].all():
        raise ValueError("normalized RTDSM output contains a non-PIT row")
    frame = frame.sort_values(["available_time", "series_id", "observation_time"]).reset_index(
        drop=True
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as binary:
            with gzip.GzipFile(filename="", mode="wb", fileobj=binary, mtime=0) as compressed:
                with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text:
                    frame.to_csv(text, index=False)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/supplemental_fx"))
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--refresh", action="store_true")
    return parser.parse_args(argv)


SOURCE_CONTRACT = {
    "phillyfed_rtdsm_cpi": (CPI_URL, "raw/phillyfed/cpiQvMd.xlsx"),
    "phillyfed_rtdsm_ip": (IP_URL, "raw/phillyfed/iptMvMd.xlsx"),
    "federal_reserve_g17_archive": (
        G17_ARCHIVE_URL,
        "raw/federal_reserve/g17_release_archive.html",
    ),
}


def _load_previous_manifest(
    root: Path,
    metadata_path: Path,
    *,
    allow_legacy_migration: bool,
) -> dict[str, object]:
    expected_paths = {key: root / relative for key, (_, relative) in SOURCE_CONTRACT.items()}
    present = {key for key, path in expected_paths.items() if path.is_file()}
    if not present:
        if metadata_path.exists():
            raise ValueError("orphan RTDSM manifest exists without the frozen raw cache")
        return {}
    if present != set(expected_paths):
        missing = sorted(set(expected_paths) - present)
        raise ValueError(f"partial RTDSM cache is not reusable; missing {missing}")
    if not metadata_path.is_file():
        raise ValueError("orphan RTDSM raw cache has no manifest")

    payload = metadata_path.read_bytes()
    try:
        manifest = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ValueError("RTDSM manifest is invalid JSON") from error
    if not isinstance(manifest, dict):
        raise ValueError("RTDSM manifest must be a JSON object")
    schema_version = manifest.get("schema_version")
    if schema_version == 2:
        sidecar = metadata_path.with_suffix(".sha256")
        digest = _sha256(payload)
        if not sidecar.is_file() or _sidecar_digest(sidecar, metadata_path.name) != digest:
            raise ValueError("RTDSM manifest SHA-256 sidecar mismatch")
        archive_manifest = _safe_child(
            root, manifest.get("manifest_archive_path"), "archived manifest"
        )
        if not archive_manifest.is_file() or archive_manifest.read_bytes() != payload:
            raise ValueError("RTDSM latest and archived manifests disagree")
        archive_sidecar = archive_manifest.with_suffix(archive_manifest.suffix + ".sha256")
        if (
            not archive_sidecar.is_file()
            or _sidecar_digest(archive_sidecar, archive_manifest.name) != digest
        ):
            raise ValueError("RTDSM archived manifest SHA-256 mismatch")
    elif schema_version == 1 and allow_legacy_migration:
        if manifest.get("program_version") != "phillyfed-rtdsm-v2":
            raise ValueError("only the locally audited RTDSM v2 manifest can be migrated")
    else:
        raise ValueError("RTDSM manifest schema is unsupported or requires --refresh migration")

    records = manifest.get("sources")
    if not isinstance(records, list) or len(records) != len(SOURCE_CONTRACT):
        raise ValueError("RTDSM manifest source set is incomplete")
    by_key: dict[str, dict[str, object]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("key"), str):
            raise ValueError("RTDSM manifest contains an invalid source record")
        key = str(record["key"])
        if key in by_key:
            raise ValueError(f"RTDSM manifest contains duplicate source {key}")
        by_key[key] = record
    if set(by_key) != set(SOURCE_CONTRACT):
        raise ValueError("RTDSM manifest source keys differ from the frozen source contract")

    for key, (url, relative) in SOURCE_CONTRACT.items():
        record = by_key[key]
        if record.get("url") != url or record.get("path") != relative:
            raise ValueError(f"{key}: cached provenance differs from the frozen source")
        raw_path = expected_paths[key]
        raw_payload = raw_path.read_bytes()
        if record.get("bytes") != len(raw_payload) or record.get("sha256") != _sha256(
            raw_payload
        ):
            raise ValueError(f"{key}: cached raw SHA-256 mismatch")
        archive_path = _safe_child(root, record.get("archive_path"), f"{key} archive")
        if not archive_path.is_file() or _file_sha256(archive_path) != record["sha256"]:
            raise ValueError(f"{key}: archived source SHA-256 mismatch")

    normalized_path = _safe_child(
        root, manifest.get("normalized_path"), "normalized artifact"
    )
    expected_normalized = (root / "normalized/phillyfed_rtdsm_vintages.csv.gz").resolve()
    if normalized_path != expected_normalized or not normalized_path.is_file():
        raise ValueError("RTDSM normalized artifact is missing or has an unexpected path")
    if _file_sha256(normalized_path) != manifest.get("normalized_sha256"):
        raise ValueError("RTDSM normalized artifact SHA-256 mismatch")
    return manifest


def _load_source(
    *,
    root: Path,
    key: str,
    relative_path: str,
    url: str,
    refresh: bool,
    timeout: float,
    retries: int,
    run_retrieved_at: datetime,
    previous_source: dict[str, object] | None,
) -> tuple[bytes, str, dict[str, object]]:
    path = root / relative_path
    if path.exists() and not refresh:
        if previous_source is None:
            raise ValueError(f"{key}: cached source has no manifest record")
        payload = path.read_bytes()
        if (
            previous_source.get("url") != url
            or previous_source.get("path") != relative_path
            or previous_source.get("bytes") != len(payload)
            or previous_source.get("sha256") != _sha256(payload)
        ):
            raise ValueError(f"{key}: cached source disagrees with its manifest")
        prior_archive = _safe_child(
            root, previous_source.get("archive_path"), f"{key} archive"
        )
        if not prior_archive.is_file() or _file_sha256(prior_archive) != _sha256(payload):
            raise ValueError(f"{key}: cached archive disagrees with its manifest")
        status = "cached"
        stored_retrieval = previous_source.get("retrieved_at")
        if not stored_retrieval:
            raise ValueError(f"{key}: cached source has no retrieval timestamp")
        retrieved_at = pd.Timestamp(stored_retrieval).to_pydatetime()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError(f"{key}: cached retrieval timestamp is timezone-naive")
    else:
        payload = _fetch(url, timeout, retries)
        _atomic_write(path, payload)
        status = "downloaded"
        retrieved_at = run_retrieved_at
    archive_path = _archive_snapshot(
        root,
        key=key,
        relative_path=relative_path,
        payload=payload,
        retrieved_at=retrieved_at,
    )
    return (
        payload,
        status,
        {
            "url": url,
            "path": relative_path,
            "archive_path": archive_path.relative_to(root).as_posix(),
            "status": status,
            "retrieved_at": retrieved_at.astimezone(UTC).isoformat(),
            "bytes": len(payload),
            "sha256": _sha256(payload),
        },
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.timeout <= 0 or not 0 <= args.retries <= 10:
        print("invalid timeout or retry count", file=sys.stderr)
        return 2
    root = args.output.expanduser().resolve()
    metadata_path = root / "phillyfed_rtdsm_manifest.json"
    run_retrieved_at = datetime.now(UTC)
    sources: list[dict[str, object]] = []
    try:
        previous = _load_previous_manifest(
            root,
            metadata_path,
            allow_legacy_migration=args.refresh,
        )
        previous_sources = {
            item["key"]: item for item in previous.get("sources", []) if "key" in item
        }
        cpi_payload, cpi_status, cpi_manifest = _load_source(
            root=root,
            key="phillyfed_rtdsm_cpi",
            relative_path="raw/phillyfed/cpiQvMd.xlsx",
            url=CPI_URL,
            refresh=args.refresh,
            timeout=args.timeout,
            retries=args.retries,
            run_retrieved_at=run_retrieved_at,
            previous_source=previous_sources.get("phillyfed_rtdsm_cpi"),
        )
        sources.append({"key": "phillyfed_rtdsm_cpi", **cpi_manifest})
        print(f"[{cpi_status:10}] phillyfed_rtdsm_cpi", flush=True)
        ip_payload, ip_status, ip_manifest = _load_source(
            root=root,
            key="phillyfed_rtdsm_ip",
            relative_path="raw/phillyfed/iptMvMd.xlsx",
            url=IP_URL,
            refresh=args.refresh,
            timeout=args.timeout,
            retries=args.retries,
            run_retrieved_at=run_retrieved_at,
            previous_source=previous_sources.get("phillyfed_rtdsm_ip"),
        )
        sources.append({"key": "phillyfed_rtdsm_ip", **ip_manifest})
        print(f"[{ip_status:10}] phillyfed_rtdsm_ip", flush=True)
        archive_payload, archive_status, archive_manifest = _load_source(
            root=root,
            key="federal_reserve_g17_archive",
            relative_path="raw/federal_reserve/g17_release_archive.html",
            url=G17_ARCHIVE_URL,
            refresh=args.refresh,
            timeout=args.timeout,
            retries=args.retries,
            run_retrieved_at=run_retrieved_at,
            previous_source=previous_sources.get("federal_reserve_g17_archive"),
        )
        sources.append({"key": "federal_reserve_g17_archive", **archive_manifest})
        print(f"[{archive_status:10}] federal_reserve_g17_archive", flush=True)

        release_dates = parse_g17_release_dates(archive_payload)
        cpi_rows = parse_cpi_vintages(cpi_payload)
        ip_rows = parse_ip_vintages(ip_payload, release_dates)
        rows = [*cpi_rows, *ip_rows]
        normalized_path = root / "normalized" / "phillyfed_rtdsm_vintages.csv.gz"
        normalized_hash = _write_vintages(rows, normalized_path)
        for source, count in zip(sources[:2], (len(cpi_rows), len(ip_rows)), strict=True):
            source["rows"] = count
    except Exception as error:
        print(f"RTDSM download failed: {error}", file=sys.stderr)
        return 1

    policies = pd.Series(row["availability_policy"] for row in rows).value_counts()
    archive_manifest_path = (
        root
        / "manifests"
        / f"rtdsm_{run_retrieved_at.strftime('%Y%m%dT%H%M%S%fZ')}.json"
    )
    manifest = {
        "schema_version": 2,
        "program_version": PROGRAM_VERSION,
        "retrieved_at": run_retrieved_at.isoformat(),
        "complete": True,
        "rows": len(rows),
        "series": {
            "US_CPI_SA_RTDSM": len(cpi_rows),
            "US_IP_TOTAL_SA_RTDSM": len(ip_rows),
        },
        "availability_policy_rows": {str(key): int(value) for key, value in policies.items()},
        "normalized_path": normalized_path.relative_to(root).as_posix(),
        "normalized_format": "gzip-compressed CSV",
        "normalized_sha256": normalized_hash,
        "manifest_archive_path": archive_manifest_path.relative_to(root).as_posix(),
        "sources": sources,
        "limitations": [
            "Values are preserved by vintage; no latest-vintage history is substituted.",
            "Published dates have no intraday timestamp, so rows become usable only at "
            "the start of the following New York calendar day.",
            "CPI quarterly vintage dates are February 15, May 15, August 15, and "
            "November 15, as documented by the Philadelphia Fed.",
            "IP exact release days use the official Federal Reserve G.17 archive. "
            "Unresolved IP months have blank vintage_date and become usable only in "
            "the next month.",
            "When multiple ordinary G.17 releases occur in one month, the latest is "
            "matched to that month-end RTDSM snapshot.",
            "Index bases may differ across vintages; compute changes within a vintage.",
            "Raw workbooks, the G.17 archive page, and run manifests are time-versioned "
            "instead of being silently overwritten on refresh.",
            "Cached raw files are reusable only when latest and archived manifests, SHA-256 "
            "sidecars, raw snapshots, archived snapshots, and normalized output agree.",
        ],
    }
    manifest_payload = (
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    manifest_digest = _sha256(manifest_payload)
    _atomic_write(
        archive_manifest_path,
        manifest_payload,
    )
    _atomic_write(
        archive_manifest_path.with_suffix(archive_manifest_path.suffix + ".sha256"),
        _sidecar_payload(manifest_digest, archive_manifest_path.name),
    )
    _atomic_write(metadata_path, manifest_payload)
    _atomic_write(
        metadata_path.with_suffix(".sha256"),
        _sidecar_payload(manifest_digest, metadata_path.name),
    )
    _load_previous_manifest(root, metadata_path, allow_legacy_migration=False)
    print(f"Wrote {len(rows):,} true-vintage rows to {normalized_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
