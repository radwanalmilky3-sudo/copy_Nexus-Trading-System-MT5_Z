#!/usr/bin/env python3
"""Archive official Philadelphia Fed SPF evidence and build a release calendar.

The official mean and median workbooks are consolidated historical files that
may change when the Philadelphia Fed publishes errata.  They are archived for
research, but this program deliberately does not normalize their values or mark
them as as-published vintages.  Only the official, date-only 2016--2025 news
release calendar is normalized.  It becomes usable at the start of the next New
York calendar day and is not suitable for intraday release trading.
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
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

PROGRAM_VERSION: Final = "phillyfed-spf-v1"
ALLOWED_HOST: Final = "www.philadelphiafed.org"
START_YEAR: Final = 2016
END_YEAR: Final = 2025
MAX_RESPONSE_BYTES: Final = 4 * 1024 * 1024
NEW_YORK: Final = ZoneInfo("America/New_York")

SPF_ROOT = (
    "https://www.philadelphiafed.org/-/media/FRBP/Assets/Surveys-And-Data/"
    "survey-of-professional-forecasters"
)
SPF_PAGE_URL = (
    "https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/"
    "survey-of-professional-forecasters"
)
MEAN_PAGE_URL = (
    "https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/"
    "mean-forecasts"
)
MEDIAN_PAGE_URL = (
    "https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/"
    "median-forecasts"
)
RELEASE_DATES_URL = f"{SPF_ROOT}/spf-release-dates.txt"
TERMS_URL = "https://www.philadelphiafed.org/about-us/privacy-notice"
ROBOTS_URL = "https://www.philadelphiafed.org/robots.txt"


@dataclass(frozen=True)
class SourceSpec:
    key: str
    url: str
    relative_path: str
    kind: str
    expected_marker: str = ""


SOURCES: Final[tuple[SourceSpec, ...]] = (
    SourceSpec(
        "spf_main_page",
        SPF_PAGE_URL,
        "raw/phillyfed/spf/pages/main.html",
        "html",
        "Survey of Professional Forecasters",
    ),
    SourceSpec(
        "spf_mean_page",
        MEAN_PAGE_URL,
        "raw/phillyfed/spf/pages/mean_forecasts.html",
        "html",
        "Mean Forecasts",
    ),
    SourceSpec(
        "spf_median_page",
        MEDIAN_PAGE_URL,
        "raw/phillyfed/spf/pages/median_forecasts.html",
        "html",
        "Median Forecasts",
    ),
    SourceSpec(
        "spf_mean_level",
        f"{SPF_ROOT}/historical-data/meanLevel.xlsx",
        "raw/phillyfed/spf/data/meanLevel.xlsx",
        "xlsx",
    ),
    SourceSpec(
        "spf_mean_growth",
        f"{SPF_ROOT}/historical-data/meanGrowth.xlsx",
        "raw/phillyfed/spf/data/meanGrowth.xlsx",
        "xlsx",
    ),
    SourceSpec(
        "spf_median_level",
        f"{SPF_ROOT}/historical-data/medianLevel.xlsx",
        "raw/phillyfed/spf/data/medianLevel.xlsx",
        "xlsx",
    ),
    SourceSpec(
        "spf_median_growth",
        f"{SPF_ROOT}/historical-data/medianGrowth.xlsx",
        "raw/phillyfed/spf/data/medianGrowth.xlsx",
        "xlsx",
    ),
    SourceSpec(
        "spf_release_dates",
        RELEASE_DATES_URL,
        "raw/phillyfed/spf/evidence/spf-release-dates.txt",
        "text",
        "News Release Date",
    ),
    SourceSpec(
        "spf_documentation",
        f"{SPF_ROOT}/spf-documentation.pdf",
        "raw/phillyfed/spf/evidence/spf-documentation.pdf",
        "pdf",
    ),
    SourceSpec(
        "spf_errata",
        f"{SPF_ROOT}/spf-errata.pdf",
        "raw/phillyfed/spf/evidence/spf-errata.pdf",
        "pdf",
    ),
    SourceSpec(
        "philadelphia_fed_terms",
        TERMS_URL,
        "raw/phillyfed/spf/evidence/terms.html",
        "terms",
        "informational, educational, and research purposes only",
    ),
    SourceSpec(
        "philadelphia_fed_robots",
        ROBOTS_URL,
        "raw/phillyfed/spf/evidence/robots.txt",
        "robots",
        "User-agent:",
    ),
)

RELEASE_LINE = re.compile(
    r"^\s*(?:(?P<year>(?:19|20)\d{2})\s+)?Q(?P<quarter>[1-4])\s+"
    r"(?P<deadline>\d{1,2}/\d{1,2}/\d{2})(?:\*+)?\s+"
    r"(?P<release>\d{1,2}/\d{1,2}/\d{2})(?:\*+)?\s*$",
    re.IGNORECASE,
)

OUTPUT_COLUMNS: Final[tuple[str, ...]] = (
    "survey_period",
    "survey_year",
    "survey_quarter",
    "response_deadline_date",
    "news_release_date",
    "available_time",
    "availability_precision",
    "availability_policy",
    "provider",
    "date_evidence_quality",
    "values_vintage_quality",
    "value_strict_pit_eligible",
    "strict_intraday_eligible",
    "research_use_scope",
    "source_url",
    "raw_sha256",
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
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


def _validate_url(spec: SourceSpec) -> None:
    parsed = urlparse(spec.url)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
        raise ValueError(f"{spec.key}: only official Philadelphia Fed HTTPS is allowed")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{spec.key}: source URL must be stable and unparameterized")
    allowed_prefixes = (
        "/-/media/FRBP/",
        "/surveys-and-data/",
        "/about-us/",
        "/robots.txt",
    )
    if not parsed.path.startswith(allowed_prefixes):
        raise ValueError(f"{spec.key}: source path escaped the official allowlist")


def _validate_payload(spec: SourceSpec, payload: bytes) -> None:
    if not payload or len(payload) > MAX_RESPONSE_BYTES:
        raise ValueError(f"{spec.key}: empty or oversized response")
    if spec.kind == "xlsx":
        if not payload.startswith(b"PK"):
            raise ValueError(f"{spec.key}: response is not XLSX")
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as workbook:
                names = set(workbook.namelist())
                if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                    raise ValueError(f"{spec.key}: XLSX structure is incomplete")
                if not any(name.startswith("xl/worksheets/") for name in names):
                    raise ValueError(f"{spec.key}: XLSX has no worksheets")
                bad_member = workbook.testzip()
                if bad_member is not None:
                    raise ValueError(f"{spec.key}: corrupt XLSX member {bad_member}")
        except zipfile.BadZipFile as error:
            raise ValueError(f"{spec.key}: corrupt XLSX archive") from error
        return
    if spec.kind == "pdf":
        if not payload.startswith(b"%PDF-") or b"%%EOF" not in payload[-4096:]:
            raise ValueError(f"{spec.key}: response is not a complete PDF")
        return
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{spec.key}: text response is not UTF-8") from error
    if spec.expected_marker and spec.expected_marker.casefold() not in text.casefold():
        raise ValueError(f"{spec.key}: expected official marker is missing")
    if spec.kind in {"html", "terms"}:
        if "<html" not in text.casefold() or "<title>Error - 404</title>" in text:
            raise ValueError(f"{spec.key}: response is a soft error page")
    if spec.kind == "terms" and "excessive access" not in text.casefold():
        raise ValueError(f"{spec.key}: excessive-access restriction is missing")
    if spec.kind == "robots":
        blocked = {
            line.split(":", 1)[1].strip()
            for line in text.splitlines()
            if line.casefold().startswith("disallow:") and ":" in line
        }
        if any(path in blocked for path in ("/surveys-and-data", "/-/media")):
            raise ValueError("official robots policy disallows an SPF source path")


def _fetch(spec: SourceSpec, timeout: float, retries: int) -> bytes:
    _validate_url(spec)
    request = urllib.request.Request(
        spec.url,
        headers={"User-Agent": f"{PROGRAM_VERSION} (+research archive; low rate)"},
    )
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                final = urlparse(response.geturl())
                if final.scheme != "https" or final.hostname != ALLOWED_HOST:
                    raise ValueError(f"{spec.key}: redirect escaped the official host")
                declared = response.headers.get("Content-Length")
                if declared and int(declared) > MAX_RESPONSE_BYTES:
                    raise ValueError(f"{spec.key}: declared response exceeds size gate")
                payload = response.read(MAX_RESPONSE_BYTES + 1)
            _validate_payload(spec, payload)
            return payload
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, ValueError) as error:
            last_error = error
            if attempt < retries:
                time.sleep(0.5 * (2**attempt))
    assert last_error is not None
    raise last_error


def _parse_date(raw: str) -> date:
    parsed = datetime.strptime(raw, "%m/%d/%y").date()
    if not 1990 <= parsed.year <= 2099:
        raise ValueError(f"SPF date escaped the documented range: {raw}")
    return parsed


def parse_release_dates(payload: bytes) -> list[dict[str, object]]:
    """Parse the official date-only 2016--2025 SPF calendar."""

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("SPF release-date file is not UTF-8") from error
    current_year: int | None = None
    selected: dict[tuple[int, int], tuple[date, date]] = {}
    for line in text.splitlines():
        match = RELEASE_LINE.fullmatch(line)
        if match is None:
            continue
        if match.group("year"):
            current_year = int(match.group("year"))
        if current_year is None:
            raise ValueError("SPF release-date row has no year context")
        quarter = int(match.group("quarter"))
        deadline = _parse_date(match.group("deadline"))
        release = _parse_date(match.group("release"))
        if deadline.year != current_year or release.year != current_year:
            raise ValueError(f"SPF {current_year} Q{quarter}: year mismatch")
        if release < deadline or (release - deadline).days > 31:
            raise ValueError(f"SPF {current_year} Q{quarter}: implausible release lag")
        key = (current_year, quarter)
        if key in selected:
            raise ValueError(f"duplicate SPF release row: {current_year} Q{quarter}")
        selected[key] = (deadline, release)

    expected = {
        (year, quarter)
        for year in range(START_YEAR, END_YEAR + 1)
        for quarter in range(1, 5)
    }
    missing = sorted(expected - set(selected))
    if missing:
        raise ValueError(f"SPF release calendar is incomplete: {missing}")
    extra = sorted(
        key for key in selected if START_YEAR <= key[0] <= END_YEAR and key not in expected
    )
    if extra:
        raise ValueError(f"SPF release calendar has unexpected rows: {extra}")

    raw_digest = _sha256(payload)
    rows: list[dict[str, object]] = []
    for year, quarter in sorted(expected):
        deadline, release = selected[(year, quarter)]
        next_day = datetime.combine(
            release + timedelta(days=1), datetime.min.time(), tzinfo=NEW_YORK
        ).astimezone(UTC)
        rows.append(
            {
                "survey_period": f"{year:04d}-Q{quarter}",
                "survey_year": year,
                "survey_quarter": quarter,
                "response_deadline_date": deadline.isoformat(),
                "news_release_date": release.isoformat(),
                "available_time": next_day.isoformat(),
                "availability_precision": "official_date_only_conservative_next_day",
                "availability_policy": "after_official_spf_news_release_date",
                "provider": "Federal Reserve Bank of Philadelphia",
                "date_evidence_quality": "verified_official_historical_release_date",
                "values_vintage_quality": (
                    "current_consolidated_archive_with_errata_not_verified_as_published"
                ),
                "value_strict_pit_eligible": False,
                "strict_intraday_eligible": False,
                "research_use_scope": (
                    "release_event_calendar_or_exploratory_quarterly_us_macro_regime"
                ),
                "source_url": RELEASE_DATES_URL,
                "raw_sha256": raw_digest,
            }
        )
    return rows


def _release_csv(rows: list[dict[str, object]]) -> bytes:
    if len(rows) != 40:
        raise ValueError("normalized SPF release calendar must contain exactly 40 rows")
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _sidecar_payload(digest: str, filename: str) -> bytes:
    return f"{digest}  {filename}\n".encode("ascii")


def _sidecar_digest(path: Path, filename: str) -> str:
    try:
        line = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError(f"invalid SHA-256 sidecar: {path}") from error
    match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
    if match is None or match.group(2) != filename:
        raise ValueError(f"invalid SHA-256 sidecar: {path}")
    return match.group(1)


def _expected_raw_paths(root: Path) -> set[Path]:
    return {(root / spec.relative_path).resolve() for spec in SOURCES}


def _validate_existing_dataset(root: Path) -> dict[str, object] | None:
    raw_root = root / "raw" / "phillyfed" / "spf"
    actual_raw = (
        {path.resolve() for path in raw_root.rglob("*") if path.is_file()}
        if raw_root.exists()
        else set()
    )
    expected_raw = _expected_raw_paths(root)
    if actual_raw - expected_raw:
        unexpected = sorted(str(path) for path in actual_raw - expected_raw)
        raise ValueError(f"orphan or unexpected SPF cache files: {unexpected}")
    if not actual_raw:
        return None
    if actual_raw != expected_raw:
        missing = sorted(str(path) for path in expected_raw - actual_raw)
        raise ValueError(f"partial SPF cache is not reusable: {missing}")

    manifest_path = root / "phillyfed_spf_manifest.json"
    manifest_sidecar = root / "phillyfed_spf_manifest.sha256"
    if not manifest_path.is_file() or not manifest_sidecar.is_file():
        raise ValueError("orphan SPF cache has no manifest and SHA-256 sidecar")
    manifest_payload = manifest_path.read_bytes()
    digest = _sha256(manifest_payload)
    if _sidecar_digest(manifest_sidecar, manifest_path.name) != digest:
        raise ValueError("SPF manifest SHA-256 sidecar mismatch")
    try:
        manifest = json.loads(manifest_payload)
    except json.JSONDecodeError as error:
        raise ValueError("SPF manifest is invalid JSON") from error
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("SPF manifest schema is unsupported")
    archive_relative = manifest.get("manifest_archive_path")
    if not isinstance(archive_relative, str):
        raise ValueError("SPF manifest has no immutable archive path")
    archive_manifest = (root / archive_relative).resolve()
    if root not in archive_manifest.parents or not archive_manifest.is_file():
        raise ValueError("SPF archived manifest is missing or escaped the output root")
    if archive_manifest.read_bytes() != manifest_payload:
        raise ValueError("SPF latest and archived manifests disagree")
    archive_sidecar = archive_manifest.with_suffix(archive_manifest.suffix + ".sha256")
    if _sidecar_digest(archive_sidecar, archive_manifest.name) != digest:
        raise ValueError("SPF archived manifest SHA-256 mismatch")

    records = manifest.get("sources")
    if not isinstance(records, list) or len(records) != len(SOURCES):
        raise ValueError("SPF manifest source set is incomplete")
    by_key: dict[str, dict[str, object]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("key"), str):
            raise ValueError("SPF manifest contains an invalid source record")
        key = str(record["key"])
        if key in by_key:
            raise ValueError(f"SPF manifest contains duplicate source {key}")
        by_key[key] = record
    if set(by_key) != {spec.key for spec in SOURCES}:
        raise ValueError("SPF manifest source keys differ from the frozen catalog")
    for spec in SOURCES:
        record = by_key[spec.key]
        if record.get("url") != spec.url or record.get("path") != spec.relative_path:
            raise ValueError(f"{spec.key}: cached provenance differs from the frozen source")
        raw_path = root / spec.relative_path
        raw_payload = raw_path.read_bytes()
        if record.get("bytes") != len(raw_payload) or record.get("sha256") != _sha256(raw_payload):
            raise ValueError(f"{spec.key}: cached raw SHA-256 mismatch")
        _validate_payload(spec, raw_payload)
        archive_path_value = record.get("archive_path")
        if not isinstance(archive_path_value, str):
            raise ValueError(f"{spec.key}: archive path is missing")
        archive_path = (root / archive_path_value).resolve()
        if root not in archive_path.parents or not archive_path.is_file():
            raise ValueError(f"{spec.key}: archived source is missing or unsafe")
        if _file_sha256(archive_path) != record["sha256"]:
            raise ValueError(f"{spec.key}: archived source SHA-256 mismatch")

    normalized_value = manifest.get("normalized_path")
    normalized_digest = manifest.get("normalized_sha256")
    if not isinstance(normalized_value, str) or not isinstance(normalized_digest, str):
        raise ValueError("SPF normalized artifact is absent from the manifest")
    normalized_path = (root / normalized_value).resolve()
    if root not in normalized_path.parents or not normalized_path.is_file():
        raise ValueError("SPF normalized release calendar is missing or unsafe")
    if _file_sha256(normalized_path) != normalized_digest:
        raise ValueError("SPF normalized release calendar SHA-256 mismatch")
    return manifest


def _archive_source(
    root: Path, spec: SourceSpec, payload: bytes, retrieved_at: datetime
) -> str:
    digest = _sha256(payload)
    suffixes = "".join(Path(spec.relative_path).suffixes) or ".bin"
    filename = f"{retrieved_at.strftime('%Y%m%dT%H%M%S%fZ')}_{digest[:16]}{suffixes}"
    destination = root / "archive" / spec.key / str(retrieved_at.year) / filename
    if destination.exists() and _file_sha256(destination) != digest:
        raise ValueError(f"{spec.key}: existing archive snapshot was tampered")
    if not destination.exists():
        _atomic_write(destination, payload)
    return destination.relative_to(root).as_posix()


Fetch = Callable[[SourceSpec, float, int], bytes]


def download_dataset(
    root: Path,
    *,
    refresh: bool,
    timeout: float,
    retries: int,
    delay: float,
    fetcher: Fetch = _fetch,
    retrieved_at: datetime | None = None,
) -> tuple[Path, Path]:
    root = root.expanduser().resolve()
    prior = _validate_existing_dataset(root)
    if prior is not None and not refresh:
        return root / str(prior["normalized_path"]), root / "phillyfed_spf_manifest.json"
    if timeout <= 0 or not 0 <= retries <= 10 or delay < 0:
        raise ValueError("invalid timeout, retry count, or request delay")
    now = (retrieved_at or datetime.now(UTC)).astimezone(UTC)

    payloads: dict[str, bytes] = {}
    for index, spec in enumerate(SOURCES):
        _validate_url(spec)
        payload = fetcher(spec, timeout, retries)
        _validate_payload(spec, payload)
        payloads[spec.key] = payload
        if delay and index + 1 < len(SOURCES):
            time.sleep(delay)

    release_payload = payloads["spf_release_dates"]
    rows = parse_release_dates(release_payload)
    csv_payload = _release_csv(rows)

    records: list[dict[str, object]] = []
    for spec in SOURCES:
        payload = payloads[spec.key]
        archive_path = _archive_source(root, spec, payload, now)
        _atomic_write(root / spec.relative_path, payload)
        records.append(
            {
                "key": spec.key,
                "url": spec.url,
                "path": spec.relative_path,
                "archive_path": archive_path,
                "retrieved_at": now.isoformat(),
                "bytes": len(payload),
                "sha256": _sha256(payload),
                "source_kind": spec.kind,
            }
        )

    normalized_path = root / "normalized" / "phillyfed_spf_release_calendar_2016_2025.csv"
    _atomic_write(normalized_path, csv_payload)
    timestamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    archive_manifest = root / "manifests" / f"spf_{timestamp}.json"
    manifest = {
        "schema_version": 1,
        "program_version": PROGRAM_VERSION,
        "retrieved_at": now.isoformat(),
        "complete": True,
        "coverage": {"start_year": START_YEAR, "end_year": END_YEAR, "release_rows": 40},
        "normalized_path": normalized_path.relative_to(root).as_posix(),
        "normalized_sha256": _sha256(csv_payload),
        "manifest_archive_path": archive_manifest.relative_to(root).as_posix(),
        "research_status": "release_calendar_eligible_values_fail_closed",
        "strict_pit": {
            "release_dates": True,
            "forecast_values": False,
            "strict_intraday": False,
        },
        "forecast_value_quality": (
            "current_consolidated_archive_with_errata_not_verified_as_published"
        ),
        "automation_policy_evidence": {
            "assessment": (
                "official direct downloads for research; relevant paths are not disallowed "
                "by robots.txt; terms forbid excessive access"
            ),
            "terms_url": TERMS_URL,
            "robots_url": ROBOTS_URL,
            "recommended_refresh": "quarterly, after an SPF release",
            "default_delay_seconds": delay,
        },
        "sources": records,
        "limitations": [
            "The normalized artifact is a release calendar, not a forecast-value panel.",
            "Mean and median workbooks are current consolidated histories and the official "
            "site publishes errata; they are not verified as-published file vintages.",
            "Official release evidence is date-only. Values become usable on the next New "
            "York calendar day and are ineligible for intraday release trading.",
            "The SPF is a quarterly United States forecast survey, not a cross-country FX "
            "expectations panel or a consensus-surprise feed.",
            "Any directional factor formula must be frozen before opening forecast values.",
        ],
    }
    manifest_payload = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )
    manifest_digest = _sha256(manifest_payload)
    latest_manifest = root / "phillyfed_spf_manifest.json"
    _atomic_write(archive_manifest, manifest_payload)
    _atomic_write(
        archive_manifest.with_suffix(archive_manifest.suffix + ".sha256"),
        _sidecar_payload(manifest_digest, archive_manifest.name),
    )
    _atomic_write(latest_manifest, manifest_payload)
    _atomic_write(
        root / "phillyfed_spf_manifest.sha256",
        _sidecar_payload(manifest_digest, latest_manifest.name),
    )
    _validate_existing_dataset(root)
    return normalized_path, latest_manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/supplemental_fx"))
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--delay", type=float, default=0.75)
    parser.add_argument("--refresh", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        normalized, manifest = download_dataset(
            args.output,
            refresh=args.refresh,
            timeout=args.timeout,
            retries=args.retries,
            delay=args.delay,
        )
    except Exception as error:
        print(f"SPF archive failed closed: {error}", file=sys.stderr)
        return 1
    print(f"Release calendar: {normalized}")
    print(f"Manifest: {manifest}")
    print("Forecast values remain non-strict current consolidated archives.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
