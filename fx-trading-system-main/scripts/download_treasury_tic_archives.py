#!/usr/bin/env python3
"""Archive official monthly Treasury International Capital release ZIP files.

The Treasury archive page says each ZIP contains the TIC data released on the
displayed date.  This downloader preserves the release page, each ZIP, hashes,
member names and conservative availability evidence.  It does not yet parse a
directional FX factor: release archives remain candidate PIT inputs until a
series-specific parser and cross-release revision audit are completed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import re
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Final
from urllib.parse import urlparse

import httpx

PROGRAM_VERSION: Final = "treasury-tic-release-archives-v1.1"
PROVIDER: Final = "U.S. Department of the Treasury, Treasury International Capital"
ARCHIVE_PAGE: Final = "https://home.treasury.gov/archives-of-tic-monthly-data-releases"
DESCRIPTION_URL: Final = (
    "https://www.treasury.gov/resource-center/data-chart-center/tic/Documents/"
    "arcdatadesc.txt"
)
ALLOWED_HOSTS: Final[frozenset[str]] = frozenset(
    {"home.treasury.gov", "www.treasury.gov", "treasury.gov", "ticdata.treasury.gov"}
)
MAX_PAGE_BYTES: Final = 4 * 1024 * 1024
MAX_ZIP_BYTES: Final = 12 * 1024 * 1024
MAX_MEMBER_BYTES: Final = 12 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES: Final = 64 * 1024 * 1024
MAX_MEMBERS: Final = 250
DEFAULT_DELAY_SECONDS: Final = 0.5

LINK_PATTERN: Final = re.compile(
    r'<a\s+[^>]*href="(?P<url>[^"]*ticrel_(?P<file_date>\d{8})\.zip)"[^>]*>'
    r"(?P<label>[^<]+)</a>\s*(?P<description>[^<]*)<br\s*/?>",
    flags=re.IGNORECASE,
)
REFERENCE_PATTERN: Final = re.compile(
    r"TIC\s+Data\s+for\s+(?P<month>[A-Za-z]+)\s+(?P<year>\d{4})",
    flags=re.IGNORECASE,
)
ACTUAL_RELEASE_PATTERN: Final = re.compile(
    r"released\s+(?P<month>\d{1,2})-(?P<day>\d{1,2})-(?P<year>\d{4})",
    flags=re.IGNORECASE,
)
INTEREST_MEMBER_PATTERNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern, flags=re.IGNORECASE)
    for pattern in (
        r"^npr_history\.(csv|html|txt)$",
        r"^mfh\.txt$",
        r"^mfhhis01\.(txt|html)$",
        r"^tressect\.txt$",
        r"^slt[_-]table[125]\.html$",
        r"^bctype_history\.txt$",
        r"^bltype_history\.txt$",
        r"^totalticliabs_hist\.txt$",
    )
)

CATALOG_COLUMNS: Final[tuple[str, ...]] = (
    "archive_id",
    "anchor_date",
    "actual_release_date",
    "availability_basis_date",
    "availability_basis_evidence",
    "available_time",
    "release_date_evidence",
    "reference_month",
    "description",
    "file_date",
    "file_date_matches_anchor",
    "source_url",
    "downloaded",
    "bytes",
    "sha256",
    "member_count",
    "uncompressed_bytes",
    "members_of_interest",
    "official_release_archive",
    "strict_pit_eligible",
    "pit_blocker",
    "allowed_research_role",
)


@dataclass(frozen=True)
class ReleaseSpec:
    archive_id: str
    anchor_date: date
    actual_release_date: date
    release_date_evidence: str
    reference_month: str
    description: str
    file_date: str
    source_url: str

    @property
    def file_date_value(self) -> date:
        try:
            return datetime.strptime(self.file_date, "%Y%m%d").date()
        except ValueError as error:
            raise ValueError(f"invalid TIC ZIP file date: {self.file_date!r}") from error

    @property
    def availability_basis_date(self) -> date:
        return max(self.actual_release_date, self.file_date_value)

    @property
    def availability_basis_evidence(self) -> str:
        if self.file_date_value > self.actual_release_date:
            return "later_official_zip_file_date"
        return self.release_date_evidence

    @property
    def available_time(self) -> str:
        value = datetime.combine(
            self.availability_basis_date + timedelta(days=1),
            datetime.min.time(),
            tzinfo=UTC,
        )
        return value.isoformat().replace("+00:00", "Z")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"refusing non-Treasury URL: {url}")


def _parse_date_label(value: str) -> date:
    try:
        return datetime.strptime(html.unescape(value).strip(), "%m/%d/%Y").date()
    except ValueError as error:
        raise ValueError(f"invalid TIC release date label: {value!r}") from error


def _reference_month(description: str) -> str:
    match = REFERENCE_PATTERN.search(description)
    if match is None:
        raise ValueError(f"TIC release description lacks reference month: {description!r}")
    try:
        parsed = datetime.strptime(
            f"{match.group('month')} {match.group('year')}", "%B %Y"
        ).date()
    except ValueError as error:
        raise ValueError(f"invalid TIC reference month: {description!r}") from error
    return parsed.replace(day=1).isoformat()


def parse_release_page(payload: bytes, *, start_year: int, end_year: int) -> list[ReleaseSpec]:
    try:
        document = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("TIC release page is not UTF-8") from error
    releases: list[ReleaseSpec] = []
    for match in LINK_PATTERN.finditer(document):
        anchor = _parse_date_label(match.group("label"))
        if not start_year <= anchor.year <= end_year:
            continue
        source_url = html.unescape(match.group("url"))
        _validate_url(source_url)
        description = " ".join(html.unescape(match.group("description")).split())
        actual_match = ACTUAL_RELEASE_PATTERN.search(description)
        if actual_match is None:
            actual = anchor
            evidence = "official_archive_anchor_date"
        else:
            actual = date(
                int(actual_match.group("year")),
                int(actual_match.group("month")),
                int(actual_match.group("day")),
            )
            evidence = "official_archive_explicit_actual_release_exception"
        file_date = match.group("file_date")
        releases.append(
            ReleaseSpec(
                archive_id=f"tic_release_{anchor.isoformat()}",
                anchor_date=anchor,
                actual_release_date=actual,
                release_date_evidence=evidence,
                reference_month=_reference_month(description),
                description=description,
                file_date=file_date,
                source_url=source_url,
            )
        )
    releases.sort(key=lambda item: item.anchor_date)
    if not releases:
        raise ValueError("no TIC release archives found in requested years")
    ids = [item.archive_id for item in releases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate TIC release dates found")
    return releases


def _safe_members(payload: bytes) -> tuple[list[str], int]:
    if not zipfile.is_zipfile(io.BytesIO(payload)):
        raise ValueError("TIC payload is not a ZIP file")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        infos = archive.infolist()
        if not 1 <= len(infos) <= MAX_MEMBERS:
            raise ValueError(f"TIC ZIP member count outside contract: {len(infos)}")
        total = 0
        names: list[str] = []
        for info in infos:
            path = PurePosixPath(info.filename)
            if path.is_absolute() or ".." in path.parts or info.flag_bits & 0x1:
                raise ValueError(f"unsafe TIC ZIP member: {info.filename!r}")
            if info.file_size > MAX_MEMBER_BYTES:
                raise ValueError(f"oversized TIC ZIP member: {info.filename!r}")
            total += info.file_size
            names.append(info.filename)
        if total > MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise ValueError("TIC ZIP exceeds uncompressed size contract")
    return sorted(names), total


def _members_of_interest(names: list[str]) -> list[str]:
    return [
        name
        for name in names
        if any(pattern.fullmatch(PurePosixPath(name).name) for pattern in INTEREST_MEMBER_PATTERNS)
    ]


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    _atomic_bytes(path, (json.dumps(payload, indent=2) + "\n").encode())


def _write_catalog(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CATALOG_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _get_limited(client: httpx.Client, url: str, maximum_bytes: int) -> bytes:
    _validate_url(url)
    response = client.get(url)
    response.raise_for_status()
    if response.url.host not in ALLOWED_HOSTS:
        raise ValueError(f"TIC redirect left allowed hosts: {response.url}")
    payload = response.content
    if len(payload) > maximum_bytes:
        raise ValueError(f"TIC response exceeds {maximum_bytes} bytes: {url}")
    return payload


def run_download(
    output_dir: Path,
    *,
    start_year: int,
    end_year: int,
    download_zips: bool,
    refresh: bool,
    delay_seconds: float,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, object]:
    if start_year < 1970 or end_year < start_year:
        raise ValueError("invalid TIC year range")
    if delay_seconds < 0:
        raise ValueError("delay_seconds must be non-negative")
    retrieved_at = _utc_now()
    raw_root = output_dir / "raw"
    archive_root = output_dir / "archive"
    headers = {"User-Agent": f"fx-portfolio-system/{PROGRAM_VERSION}"}
    with httpx.Client(
        timeout=90,
        follow_redirects=True,
        trust_env=False,
        headers=headers,
        transport=transport,
    ) as client:
        page = _get_limited(client, ARCHIVE_PAGE, MAX_PAGE_BYTES)
        description = _get_limited(client, DESCRIPTION_URL, MAX_PAGE_BYTES)
        releases = parse_release_page(page, start_year=start_year, end_year=end_year)
        _atomic_bytes(raw_root / "tic_release_archive_page.html", page)
        _atomic_bytes(raw_root / "archive_file_descriptions.txt", description)
        rows: list[dict[str, object]] = []
        downloads: list[dict[str, object]] = []
        for index, spec in enumerate(releases):
            if download_zips and index and delay_seconds:
                time.sleep(delay_seconds)
            raw_path = raw_root / f"ticrel_{spec.file_date}.zip"
            payload: bytes | None = None
            if download_zips:
                if raw_path.is_file() and not refresh:
                    payload = raw_path.read_bytes()
                else:
                    payload = _get_limited(client, spec.source_url, MAX_ZIP_BYTES)
                    _atomic_bytes(raw_path, payload)
                digest = _sha256(payload)
                archive_path = archive_root / f"{digest}.zip"
                if not archive_path.exists():
                    _atomic_bytes(archive_path, payload)
                members, uncompressed = _safe_members(payload)
                interest = _members_of_interest(members)
                if not any(name.lower().startswith("npr_history.") for name in interest):
                    raise ValueError(f"{spec.archive_id}: npr_history member absent")
                downloads.append(
                    {
                        "archive_id": spec.archive_id,
                        "raw_path": str(raw_path),
                        "archive_path": str(archive_path),
                        "bytes": len(payload),
                        "sha256": digest,
                        "member_count": len(members),
                        "uncompressed_bytes": uncompressed,
                        "members_sha256": _sha256("\n".join(members).encode()),
                        "members_of_interest": interest,
                    }
                )
            else:
                digest = ""
                members = []
                uncompressed = 0
                interest = []
            rows.append(
                {
                    "archive_id": spec.archive_id,
                    "anchor_date": spec.anchor_date.isoformat(),
                    "actual_release_date": spec.actual_release_date.isoformat(),
                    "availability_basis_date": spec.availability_basis_date.isoformat(),
                    "availability_basis_evidence": spec.availability_basis_evidence,
                    "available_time": spec.available_time,
                    "release_date_evidence": spec.release_date_evidence,
                    "reference_month": spec.reference_month,
                    "description": spec.description,
                    "file_date": spec.file_date,
                    "file_date_matches_anchor": (
                        spec.file_date == spec.anchor_date.strftime("%Y%m%d")
                    ),
                    "source_url": spec.source_url,
                    "downloaded": payload is not None,
                    "bytes": len(payload) if payload is not None else "",
                    "sha256": digest,
                    "member_count": len(members) if payload is not None else "",
                    "uncompressed_bytes": uncompressed if payload is not None else "",
                    "members_of_interest": " | ".join(interest),
                    "official_release_archive": True,
                    "strict_pit_eligible": False,
                    "pit_blocker": "series_parser_and_cross_release_revision_audit_pending",
                    "allowed_research_role": "low_frequency_state_candidate_not_directional_alpha",
                }
            )
    catalog_path = output_dir / "release_catalog.csv"
    _write_catalog(catalog_path, rows)
    manifest: dict[str, object] = {
        "schema_version": 2,
        "program_version": PROGRAM_VERSION,
        "generated_at_utc": retrieved_at,
        "provider": PROVIDER,
        "archive_page": ARCHIVE_PAGE,
        "archive_page_sha256": _sha256(page),
        "description_url": DESCRIPTION_URL,
        "description_sha256": _sha256(description),
        "start_year": start_year,
        "end_year": end_year,
        "release_count": len(releases),
        "download_zips": download_zips,
        "downloaded_count": len(downloads),
        "downloaded_bytes": sum(int(item["bytes"]) for item in downloads),
        "catalog_path": str(catalog_path),
        "catalog_sha256": _sha256(catalog_path.read_bytes()),
        "official_page_claim": "each ZIP contains TIC data released on the date shown",
        "strict_pit_eligible": False,
        "pit_blocker": "series_parser_and_cross_release_revision_audit_pending",
        "is_treasury_basis": False,
        "is_fx_order_flow": False,
        "factor_registry_modified": False,
        "outcome_evaluations_added": 0,
        "downloads": downloads,
    }
    _atomic_json(output_dir / "manifest.json", manifest)
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data/treasury_tic"))
    parser.add_argument("--start-year", type=int, default=2016)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--download-zips", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--delay-seconds", type=float, default=DEFAULT_DELAY_SECONDS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        manifest = run_download(
            args.output_dir,
            start_year=args.start_year,
            end_year=args.end_year,
            download_zips=args.download_zips,
            refresh=args.refresh,
            delay_seconds=args.delay_seconds,
        )
    except (httpx.HTTPError, OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"TIC archive download failed: {error}", file=sys.stderr)
        return 1
    print(
        f"releases={manifest['release_count']} downloaded={manifest['downloaded_count']} "
        f"bytes={manifest['downloaded_bytes']} output={args.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
