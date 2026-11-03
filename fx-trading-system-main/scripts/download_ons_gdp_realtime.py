#!/usr/bin/env python3
"""Catalog and download official ONS ABMI/YBHA GDP real-time editions.

The legacy ONS dataset pages provide stable, edition-specific workbook links,
but their edition subpages currently repeat the latest dataset release date.
This program never treats that repeated page date as a historical release date.
An edition is normalized only when its own workbook contains an explicit
"originally published" date. Older workbooks remain archived catalog evidence
and fail closed for point-in-time use.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Final
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx
import pandas as pd

PROGRAM_VERSION: Final = "ons-gdp-realtime-v2"
MANIFEST_SCHEMA_VERSION: Final = 2
PROVIDER: Final = "UK Office for National Statistics"
ALLOWED_HOST: Final = "www.ons.gov.uk"
LICENSE_URL: Final = (
    "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"
)
MAX_PAGE_BYTES: Final = 4 * 1024 * 1024
MAX_WORKBOOK_BYTES: Final = 4 * 1024 * 1024
DEFAULT_REQUEST_DELAY_SECONDS: Final = 1.0
MAX_RETRY_AFTER_SECONDS: Final = 60.0

QUARTER_PATTERN: Final = re.compile(r"Q([1-4])\s+(\d{4})", re.IGNORECASE)
EDITION_YEAR_PATTERN: Final = re.compile(r"\b(20\d{2})\b")
PUBLICATION_PATTERN: Final = re.compile(
    r"originally published at\s+"
    r"(?:(\d{1,2}:\d{2})\s+)?"
    r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})",
    re.IGNORECASE,
)
SIZE_PATTERN: Final = re.compile(r"([0-9.]+)\s*(kB|KB|MB)", re.IGNORECASE)
EDITION_SLUG_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

OUTPUT_COLUMNS: Final[tuple[str, ...]] = (
    "observation_period",
    "observation_end_date",
    "edition",
    "edition_title",
    "release_date",
    "available_time",
    "availability_quality",
    "availability_policy",
    "series_code",
    "series_name",
    "price_basis",
    "seasonal_adjustment",
    "frequency",
    "unit",
    "value",
    "publication_vintage_header",
    "source_url",
    "source_sha256",
    "catalog_page_url",
    "catalog_page_sha256",
    "edition_quality",
    "growth_rate_policy",
    "strict_intraday_eligible",
    "use_scope",
)


@dataclass(frozen=True)
class DatasetSpec:
    dataset_id: str
    series_code: str
    series_name: str
    price_basis: str
    page_url: str


DATASETS: Final[tuple[DatasetSpec, ...]] = (
    DatasetSpec(
        dataset_id="abmi",
        series_code="ABMI",
        series_name="UK GDP at market prices, chained volume measure",
        price_basis="chained_volume_measure",
        page_url=(
            "https://www.ons.gov.uk/economy/grossdomesticproductgdp/datasets/"
            "realtimedatabaseforukgdpabmi"
        ),
    ),
    DatasetSpec(
        dataset_id="ybha",
        series_code="YBHA",
        series_name="UK GDP at market prices, current prices",
        price_basis="current_prices",
        page_url=(
            "https://www.ons.gov.uk/economy/grossdomesticproductgdp/datasets/"
            "realtimedatabaseforukgdpybha"
        ),
    ),
)

EXPECTED_EDITION_COUNTS_2016_2025: Final[dict[int, int]] = {
    2016: 6,
    **{year: 8 for year in range(2017, 2026)},
}
CATALOG_DATASET_KIND: Final = "ons_gdp_realtime_edition_catalog"
WORKBOOK_DATASET_KIND: Final = "ons_gdp_realtime_edition_workbooks"


@dataclass(frozen=True)
class EditionSpec:
    dataset_id: str
    series_code: str
    series_name: str
    price_basis: str
    edition: str
    edition_title: str
    edition_year: int
    workbook_url: str
    workbook_format: str
    listed_size_bytes: int | None
    catalog_page_url: str
    catalog_page_sha256: str


class ReleaseDateUnavailable(ValueError):
    """Raised when an edition workbook has no verifiable publication date."""


class _EditionLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._capture_heading = False
        self._capture_link = False
        self._parts: list[str] = []
        self._link_parts: list[str] = []
        self._pending_heading = ""
        self._pending_href = ""
        self.links: list[tuple[str, str, str]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = dict(attrs)
        if tag == "h3":
            self._capture_heading = True
            self._parts = []
        elif tag == "a":
            href = attributes.get("href") or ""
            if (
                self._pending_heading
                and "edition of this dataset" in self._pending_heading.lower()
                and href.startswith("/file?uri=")
            ):
                self._capture_link = True
                self._pending_href = href
                self._link_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "h3" and self._capture_heading:
            self._capture_heading = False
            self._pending_heading = " ".join("".join(self._parts).split())
        elif tag == "a" and self._capture_link:
            self._capture_link = False
            link_text = " ".join("".join(self._link_parts).split())
            self.links.append(
                (self._pending_heading, self._pending_href, link_text)
            )
            self._pending_heading = ""
            self._pending_href = ""

    def handle_data(self, data: str) -> None:
        if self._capture_heading:
            self._parts.append(data)
        if self._capture_link:
            self._link_parts.append(data)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(payload)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _cache_sidecar(path: Path) -> Path:
    return path.with_name(f"{path.name}.sha256")


def _manifest_sidecar(path: Path) -> Path:
    return path.with_suffix(".sha256")


def _digest_sidecar_payload(payload: bytes) -> bytes:
    return (_sha256(payload) + "\n").encode("ascii")


def _read_digest_sidecar(path: Path, *, label: str) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} SHA-256 sidecar must be a regular file")
    try:
        digest = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as error:
        raise ValueError(f"{label} SHA-256 sidecar is unreadable") from error
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError(f"{label} SHA-256 sidecar is invalid")
    return digest


def _prepare_root(output_directory: str | Path) -> Path:
    raw_root = Path(output_directory).expanduser()
    if raw_root.is_symlink():
        raise ValueError("ONS output directory cannot be a symlink")
    return raw_root.resolve()


def _reject_symlink_components(root: Path, path: Path, *, field: str) -> None:
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError(f"{field} cannot contain symlinks")
        if root not in current.parents:
            raise ValueError(f"{field} escapes the output directory")
        current = current.parent


def _manifest_file(root: Path, value: object, *, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} is not a safe relative path")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{field} is not a safe relative path")
    path = root / relative
    _reject_symlink_components(root, path, field=field)
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"{field} escapes the output directory")
    return path


def _tree_files(path: Path, *, label: str) -> set[Path]:
    if path.is_symlink():
        raise ValueError(f"{label} directory cannot be a symlink")
    if not path.exists():
        return set()
    files: set[Path] = set()
    for candidate in path.rglob("*"):
        if candidate.is_symlink():
            raise ValueError(f"{label} cannot contain symlinks")
        if candidate.is_file():
            files.add(candidate.resolve())
    return files


def _write_manifest_pair(
    root: Path,
    *,
    latest_path: Path,
    archive_prefix: str,
    manifest: dict[str, object],
    retrieved_at: datetime,
) -> Path:
    timestamp = retrieved_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    archive_path = (
        root / "manifests" / "archive" / f"{archive_prefix}_{timestamp}.json"
    )
    manifest["manifest_archive_path"] = archive_path.relative_to(root).as_posix()
    payload = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode()
    archive_sidecar = _manifest_sidecar(archive_path)
    if archive_path.exists() and archive_path.read_bytes() != payload:
        raise ValueError("ONS archived manifest timestamp collision")
    if archive_sidecar.exists() and (
        _read_digest_sidecar(archive_sidecar, label="archived manifest")
        != _sha256(payload)
    ):
        raise ValueError("ONS archived manifest sidecar collision")
    if not archive_path.exists():
        _atomic_write(archive_path, payload)
    if not archive_sidecar.exists():
        _atomic_write(archive_sidecar, _digest_sidecar_payload(payload))
    _atomic_write(latest_path, payload)
    _atomic_write(_manifest_sidecar(latest_path), _digest_sidecar_payload(payload))
    return latest_path


def _load_manifest_pair(
    root: Path,
    *,
    latest_path: Path,
    dataset_kind: str,
) -> tuple[dict[str, object], bytes]:
    latest_sidecar = _manifest_sidecar(latest_path)
    if (
        latest_path.is_symlink()
        or not latest_path.is_file()
        or latest_sidecar.is_symlink()
        or not latest_sidecar.is_file()
    ):
        raise ValueError("ONS latest manifest and sidecar must both be regular files")
    payload = latest_path.read_bytes()
    digest = _sha256(payload)
    if _read_digest_sidecar(latest_sidecar, label="latest manifest") != digest:
        raise ValueError("ONS latest manifest SHA-256 verification failed")
    try:
        manifest = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("ONS latest manifest is unreadable") from error
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION
        or manifest.get("program_version") != PROGRAM_VERSION
        or manifest.get("dataset_kind") != dataset_kind
    ):
        raise ValueError("ONS manifest schema is unsupported; use --refresh")
    archive_path = _manifest_file(
        root,
        manifest.get("manifest_archive_path"),
        field="manifest_archive_path",
    )
    archive_root = root / "manifests" / "archive"
    if not archive_path.is_relative_to(archive_root):
        raise ValueError("ONS archived manifest path is outside the archive directory")
    archive_sidecar = _manifest_sidecar(archive_path)
    if archive_path.is_symlink() or not archive_path.is_file():
        raise ValueError("ONS archived manifest is missing or unsafe")
    if archive_path.read_bytes() != payload:
        raise ValueError("ONS latest and archived manifests disagree")
    if _read_digest_sidecar(archive_sidecar, label="archived manifest") != digest:
        raise ValueError("ONS archived manifest SHA-256 verification failed")
    return manifest, payload


def _write_hashed_cache(path: Path, payload: bytes) -> None:
    _atomic_write(path, payload)
    _atomic_write(
        _cache_sidecar(path),
        _digest_sidecar_payload(payload),
    )


def _read_hashed_cache(path: Path) -> bytes:
    sidecar = _cache_sidecar(path)
    if path.is_symlink() or sidecar.is_symlink() or not path.is_file() or not sidecar.is_file():
        raise ValueError(f"orphan ONS cache lacks SHA-256 sidecar: {path}")
    expected = _read_digest_sidecar(sidecar, label=f"ONS cache {path}")
    payload = path.read_bytes()
    if _sha256(payload) != expected:
        raise ValueError(f"ONS cached response hash differs from sidecar: {path}")
    return payload


def _catalog_prior_sources(
    root: Path,
    *,
    dataset_specs: Sequence[DatasetSpec],
) -> dict[str, dict[str, object]]:
    """Return only a complete, manifest-anchored catalog cache.

    A raw file plus a rewritten sidecar is not enough to trust a cached
    response.  The previous latest manifest, its immutable archive copy, the
    normalized catalog, each raw page and each raw archive must agree.
    """

    latest_path = root / "manifests" / "ons_gdp_realtime_catalog_manifest.json"
    latest_sidecar = _manifest_sidecar(latest_path)
    cache_root = root / "raw" / "catalog_pages"
    cache_files = _tree_files(cache_root, label="ONS catalog cache")
    has_manifest = latest_path.exists() or latest_sidecar.exists()
    if not cache_files and not has_manifest:
        return {}
    if not cache_files or not has_manifest:
        raise ValueError("ONS catalog cache and manifest must either both exist or both be absent")

    manifest, _ = _load_manifest_pair(
        root,
        latest_path=latest_path,
        dataset_kind=CATALOG_DATASET_KIND,
    )
    catalog_path = _manifest_file(root, manifest.get("catalog_path"), field="catalog_path")
    catalog_hash = manifest.get("catalog_sha256")
    if (
        catalog_path.is_symlink()
        or not catalog_path.is_file()
        or not isinstance(catalog_hash, str)
        or _sha256(catalog_path.read_bytes()) != catalog_hash
    ):
        raise ValueError("ONS prior normalized catalog hash verification failed")

    records = manifest.get("catalog_pages")
    if not isinstance(records, list) or len(records) != len(dataset_specs):
        raise ValueError("ONS prior catalog source set is incomplete")
    expected_ids = {f"catalog_{spec.dataset_id}" for spec in dataset_specs}
    by_id: dict[str, dict[str, object]] = {}
    expected_cache_files: set[Path] = set()
    expected_urls = {f"catalog_{spec.dataset_id}": spec.page_url for spec in dataset_specs}
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"ONS prior catalog source record {index} is invalid")
        source_id = record.get("source_id")
        if not isinstance(source_id, str) or source_id in by_id or source_id not in expected_ids:
            raise ValueError(f"ONS prior catalog source identifier {index} is invalid")
        if record.get("url") != expected_urls[source_id]:
            raise ValueError(f"{source_id}: prior catalog URL does not match the frozen source")
        cache_path = _manifest_file(root, record.get("cache_path"), field=f"{source_id} cache_path")
        sidecar_path = _manifest_file(
            root,
            record.get("cache_sidecar_path"),
            field=f"{source_id} cache_sidecar_path",
        )
        expected_path = (
            root
            / "raw"
            / "catalog_pages"
            / f"{source_id.removeprefix('catalog_')}.html"
        )
        if cache_path != expected_path or sidecar_path != _cache_sidecar(expected_path):
            raise ValueError(f"{source_id}: prior catalog cache path is unexpected")
        payload = _read_hashed_cache(cache_path)
        digest = _sha256(payload)
        if record.get("bytes") != len(payload) or record.get("sha256") != digest:
            raise ValueError(f"{source_id}: prior catalog cache disagrees with manifest")
        archive_path = _manifest_file(
            root,
            record.get("archive_path"),
            field=f"{source_id} archive_path",
        )
        if (
            archive_path.is_symlink()
            or not archive_path.is_file()
            or _sha256(archive_path.read_bytes()) != digest
        ):
            raise ValueError(f"{source_id}: prior catalog archive hash verification failed")
        expected_cache_files.update({cache_path.resolve(), sidecar_path.resolve()})
        by_id[source_id] = record
    if set(by_id) != expected_ids or cache_files != expected_cache_files:
        raise ValueError("ONS prior catalog cache has orphan or missing files")
    return by_id


def _remove_refresh_catalog_orphans(root: Path, records: Sequence[Mapping[str, object]]) -> None:
    cache_root = root / "raw" / "catalog_pages"
    expected = {
        _manifest_file(root, record.get(field), field=f"refresh {field}").resolve()
        for record in records
        for field in ("cache_path", "cache_sidecar_path")
    }
    for path in _tree_files(cache_root, label="ONS catalog refresh cache"):
        if path not in expected:
            path.unlink()


def _workbook_prior_sources(
    root: Path,
    *,
    editions: Sequence[EditionSpec],
) -> dict[str, dict[str, object]]:
    latest_path = root / "manifests" / "ons_gdp_realtime_workbook_manifest.json"
    latest_sidecar = _manifest_sidecar(latest_path)
    cache_root = root / "raw" / "cache"
    cache_files = _tree_files(cache_root, label="ONS workbook cache")
    has_manifest = latest_path.exists() or latest_sidecar.exists()
    if not cache_files and not has_manifest:
        return {}
    if not cache_files or not has_manifest:
        raise ValueError("ONS workbook cache and manifest must either both exist or both be absent")
    manifest, _ = _load_manifest_pair(
        root,
        latest_path=latest_path,
        dataset_kind=WORKBOOK_DATASET_KIND,
    )
    audit_path = _manifest_file(
        root,
        manifest.get("workbook_audit_path"),
        field="workbook_audit_path",
    )
    audit_hash = manifest.get("workbook_audit_sha256")
    if (
        audit_path.is_symlink()
        or not audit_path.is_file()
        or not isinstance(audit_hash, str)
        or _sha256(audit_path.read_bytes()) != audit_hash
    ):
        raise ValueError("ONS prior workbook audit hash verification failed")
    complete = manifest.get("normalization_complete")
    normalized_path_value = manifest.get("normalized_path")
    normalized_hash = manifest.get("normalized_sha256")
    if complete is True:
        normalized_path = _manifest_file(
            root, normalized_path_value, field="normalized_path"
        )
        if (
            normalized_path.is_symlink()
            or not normalized_path.is_file()
            or not isinstance(normalized_hash, str)
            or _sha256(normalized_path.read_bytes()) != normalized_hash
        ):
            raise ValueError("ONS prior normalized workbook output hash verification failed")
    elif complete is False:
        if normalized_path_value not in {"", None} or normalized_hash not in {"", None}:
            raise ValueError("ONS incomplete workbook manifest cannot claim normalized output")
    else:
        raise ValueError("ONS prior workbook normalization status is invalid")

    records = manifest.get("sources")
    if not isinstance(records, list) or len(records) != len(editions):
        raise ValueError("ONS prior workbook source set is incomplete")
    expected_specs = {f"{item.dataset_id}/{item.edition}": item for item in editions}
    by_id: dict[str, dict[str, object]] = {}
    expected_cache_files: set[Path] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"ONS prior workbook source record {index} is invalid")
        source_id = record.get("source_id")
        if not isinstance(source_id, str) or source_id in by_id or source_id not in expected_specs:
            raise ValueError(f"ONS prior workbook source identifier {index} is invalid")
        spec = expected_specs[source_id]
        suffix = f".{spec.workbook_format}"
        expected_path = root / "raw" / "cache" / spec.dataset_id / f"{spec.edition}{suffix}"
        cache_path = _manifest_file(root, record.get("cache_path"), field=f"{source_id} cache_path")
        sidecar_path = _manifest_file(
            root,
            record.get("cache_sidecar_path"),
            field=f"{source_id} cache_sidecar_path",
        )
        if cache_path != expected_path or sidecar_path != _cache_sidecar(expected_path):
            raise ValueError(f"{source_id}: prior workbook cache path is unexpected")
        if record.get("workbook_url") != spec.workbook_url:
            raise ValueError(f"{source_id}: prior workbook URL does not match the frozen source")
        payload = _read_hashed_cache(cache_path)
        digest = _sha256(payload)
        if record.get("bytes") != len(payload) or record.get("sha256") != digest:
            raise ValueError(f"{source_id}: prior workbook cache disagrees with manifest")
        archive_path = _manifest_file(
            root,
            record.get("archive_path"),
            field=f"{source_id} archive_path",
        )
        if (
            archive_path.is_symlink()
            or not archive_path.is_file()
            or _sha256(archive_path.read_bytes()) != digest
        ):
            raise ValueError(f"{source_id}: prior workbook archive hash verification failed")
        expected_cache_files.update({cache_path.resolve(), sidecar_path.resolve()})
        by_id[source_id] = record
    if set(by_id) != set(expected_specs) or cache_files != expected_cache_files:
        raise ValueError("ONS prior workbook cache has orphan or missing files")
    return by_id


def _remove_refresh_workbook_orphans(root: Path, records: Sequence[Mapping[str, object]]) -> None:
    cache_root = root / "raw" / "cache"
    expected = {
        _manifest_file(root, record.get(field), field=f"refresh {field}").resolve()
        for record in records
        for field in ("cache_path", "cache_sidecar_path")
    }
    for path in _tree_files(cache_root, label="ONS workbook refresh cache"):
        if path not in expected:
            path.unlink()


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _listed_size_bytes(text: str) -> int | None:
    match = SIZE_PATTERN.search(text)
    if not match:
        return None
    value = float(match.group(1))
    multiplier = 1024 if match.group(2).lower() == "kb" else 1024 * 1024
    return int(round(value * multiplier))


def _validate_official_url(url: str, *, workbook: bool) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != ALLOWED_HOST:
        raise ValueError("only official www.ons.gov.uk HTTPS URLs are allowed")
    if parsed.fragment:
        raise ValueError("ONS URLs cannot contain fragments")
    if workbook:
        if parsed.path != "/file":
            raise ValueError("ONS workbook URL must use the official /file endpoint")
        query = parse_qs(parsed.query, strict_parsing=True)
        if set(query) != {"uri"} or len(query["uri"]) != 1:
            raise ValueError("ONS workbook URL must contain exactly one uri parameter")
        uri = unquote(query["uri"][0])
        if not uri.startswith("/economy/grossdomesticproductgdp/datasets/"):
            raise ValueError("ONS workbook uri escaped the GDP dataset namespace")
        if Path(uri).suffix.lower() not in {".xls", ".xlsx"}:
            raise ValueError("ONS workbook must be an XLS or XLSX file")
    elif parsed.query:
        raise ValueError("ONS catalog page URL cannot contain a query")


def parse_dataset_page(
    spec: DatasetSpec,
    payload: bytes,
    *,
    start_year: int = 2016,
    end_year: int = 2025,
) -> list[EditionSpec]:
    """Parse only links actually published on one official dataset page."""
    _validate_official_url(spec.page_url, workbook=False)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{spec.dataset_id}: catalog page is not UTF-8") from error
    if spec.series_code not in text or LICENSE_URL not in text:
        raise ValueError(
            f"{spec.dataset_id}: page lacks the expected series code or OGL licence"
        )
    parser = _EditionLinkParser()
    parser.feed(text)
    page_hash = _sha256(payload)
    editions: list[EditionSpec] = []
    seen: set[str] = set()
    expected_uri_prefix = urlparse(spec.page_url).path + "/"
    for raw_title, raw_href, link_text in parser.links:
        year_match = EDITION_YEAR_PATTERN.search(raw_title)
        if not year_match:
            raise ValueError(f"{spec.dataset_id}: edition title has no year: {raw_title!r}")
        edition_year = int(year_match.group(1))
        if not start_year <= edition_year <= end_year:
            continue
        workbook_url = urljoin(spec.page_url, raw_href)
        _validate_official_url(workbook_url, workbook=True)
        query = parse_qs(urlparse(workbook_url).query, strict_parsing=True)
        uri = unquote(query["uri"][0])
        if not uri.startswith(expected_uri_prefix):
            raise ValueError(f"{spec.dataset_id}: workbook does not belong to dataset")
        relative = uri[len(expected_uri_prefix) :]
        parts = relative.split("/")
        if len(parts) != 2 or not all(parts):
            raise ValueError(f"{spec.dataset_id}: workbook path lacks edition/version")
        edition, filename = parts
        if not EDITION_SLUG_PATTERN.fullmatch(edition):
            raise ValueError(f"{spec.dataset_id}: unsafe edition slug {edition!r}")
        if edition in seen:
            raise ValueError(f"{spec.dataset_id}: duplicate edition slug {edition!r}")
        seen.add(edition)
        workbook_format = Path(filename).suffix.lower().lstrip(".")
        title = re.sub(
            r"\s+edition of this dataset\s*$", "", raw_title, flags=re.IGNORECASE
        ).strip()
        editions.append(
            EditionSpec(
                dataset_id=spec.dataset_id,
                series_code=spec.series_code,
                series_name=spec.series_name,
                price_basis=spec.price_basis,
                edition=edition,
                edition_title=title,
                edition_year=edition_year,
                workbook_url=workbook_url,
                workbook_format=workbook_format,
                listed_size_bytes=_listed_size_bytes(link_text),
                catalog_page_url=spec.page_url,
                catalog_page_sha256=page_hash,
            )
        )
    if not editions:
        raise ValueError(f"{spec.dataset_id}: page contains no requested editions")
    return editions


def validate_catalog_coverage(
    editions: Sequence[EditionSpec],
    *,
    expected_counts: Mapping[int, int] = EXPECTED_EDITION_COUNTS_2016_2025,
    required_dataset_ids: Sequence[str] = ("abmi", "ybha"),
) -> None:
    by_dataset: dict[str, list[EditionSpec]] = {}
    for edition in editions:
        by_dataset.setdefault(edition.dataset_id, []).append(edition)
    if set(by_dataset) != set(required_dataset_ids):
        raise ValueError(
            "ONS catalog dataset coverage mismatch: "
            f"expected={sorted(required_dataset_ids)}, actual={sorted(by_dataset)}"
        )
    expected_total = sum(expected_counts.values())
    semantic_sets: list[set[tuple[int, str]]] = []
    for dataset_id in required_dataset_ids:
        items = by_dataset[dataset_id]
        if len(items) != expected_total:
            raise ValueError(
                f"{dataset_id}: expected {expected_total} editions, found {len(items)}"
            )
        counts: dict[int, int] = {}
        for item in items:
            counts[item.edition_year] = counts.get(item.edition_year, 0) + 1
        if counts != dict(expected_counts):
            raise ValueError(
                f"{dataset_id}: edition year coverage mismatch; "
                f"expected={dict(expected_counts)}, actual={counts}"
            )
        semantic_keys = [
            (item.edition_year, _semantic_edition_title(item.edition_title)) for item in items
        ]
        if len(semantic_keys) != len(set(semantic_keys)):
            raise ValueError(f"{dataset_id}: duplicate semantic edition identity")
        semantic_sets.append(set(semantic_keys))
    if any(keys != semantic_sets[0] for keys in semantic_sets[1:]):
        raise ValueError("ABMI and YBHA semantic edition coverage does not match")


def _semantic_edition_title(value: str) -> str:
    normalized = value.lower()
    month_aliases = {
        "january": "jan",
        "february": "feb",
        "march": "mar",
        "april": "apr",
        "june": "jun",
        "july": "jul",
        "august": "aug",
        "september": "sept",
        "october": "oct",
        "november": "nov",
        "december": "dec",
    }
    for full, short in month_aliases.items():
        normalized = normalized.replace(full, short)
    normalized = re.sub(r"\bfirst estimates\b", "first estimate", normalized)
    normalized = re.sub(r"\bedition\b", "", normalized)
    return re.sub(r"[^a-z0-9]+", "", normalized)


def _validate_workbook_payload(spec: EditionSpec, payload: bytes) -> None:
    if not payload or len(payload) > MAX_WORKBOOK_BYTES:
        raise ValueError(f"{spec.dataset_id}/{spec.edition}: empty or oversized workbook")
    is_xlsx = payload.startswith(b"PK\x03\x04")
    is_xls = payload.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    if spec.workbook_format == "xlsx" and not is_xlsx:
        raise ValueError(f"{spec.dataset_id}/{spec.edition}: XLSX magic mismatch")
    if spec.workbook_format == "xls" and not is_xls:
        raise ValueError(f"{spec.dataset_id}/{spec.edition}: XLS magic mismatch")


def _workbook_frames(payload: bytes) -> tuple[pd.ExcelFile, dict[str, pd.DataFrame]]:
    try:
        book = pd.ExcelFile(io.BytesIO(payload))
    except (ValueError, ImportError) as error:
        raise ValueError("ONS workbook cannot be opened") from error
    frames: dict[str, pd.DataFrame] = {}
    for sheet in book.sheet_names:
        try:
            frames[sheet] = pd.read_excel(
                io.BytesIO(payload), sheet_name=sheet, header=None
            )
        except (ValueError, ImportError) as error:
            raise ValueError(f"ONS workbook sheet {sheet!r} cannot be read") from error
    return book, frames


def _release_date_from_cover(frames: Mapping[str, pd.DataFrame]) -> date:
    cover_name = next(
        (name for name in frames if name.lower().replace(" ", "_") == "cover_sheet"),
        None,
    )
    if cover_name is None:
        raise ReleaseDateUnavailable(
            "workbook has no Cover_sheet with an original publication date"
        )
    cover = frames[cover_name]
    text = "\n".join(
        str(value)
        for value in cover.to_numpy().ravel()
        if not pd.isna(value)
    )
    matches = PUBLICATION_PATTERN.findall(text)
    if len(matches) != 1:
        raise ReleaseDateUnavailable(
            "workbook does not contain exactly one original publication date"
        )
    _, day, month, year = matches[0]
    try:
        return datetime.strptime(f"{day} {month} {year}", "%d %B %Y").date()
    except ValueError as error:
        raise ReleaseDateUnavailable(
            "workbook original publication date cannot be parsed"
        ) from error


def _validate_workbook_identity(
    spec: EditionSpec, frames: Mapping[str, pd.DataFrame]
) -> None:
    text = "\n".join(
        str(value)
        for frame in frames.values()
        for value in frame.iloc[:20].to_numpy().ravel()
        if not pd.isna(value)
    )
    if spec.series_code not in text:
        raise ValueError(
            f"{spec.dataset_id}/{spec.edition}: workbook lacks series code "
            f"{spec.series_code}"
        )


def _latest_vintage_column(
    frames: Mapping[str, pd.DataFrame],
) -> tuple[pd.DataFrame, int, int, str]:
    candidates: list[tuple[pd.DataFrame, int, int, str]] = []
    for name, frame in frames.items():
        if name.lower().replace(" ", "_") in {"cover_sheet", "table_of_contents", "index"}:
            continue
        for row_number in range(min(20, len(frame))):
            first = str(frame.iat[row_number, 0]).strip()
            if "publication date and time period" not in first.lower():
                continue
            populated = [
                column
                for column in range(1, frame.shape[1])
                if not pd.isna(frame.iat[row_number, column])
                and str(frame.iat[row_number, column]).strip()
            ]
            if not populated:
                raise ValueError(f"ONS workbook sheet {name!r} has no vintage columns")
            latest = populated[-1]
            candidates.append(
                (frame, row_number, latest, str(frame.iat[row_number, latest]).strip())
            )
    if not candidates:
        raise ValueError("ONS workbook lacks the verified modern table header")
    # Modern workbooks partition publication vintages across ordered sheets;
    # the final matching sheet contains the edition's newest vintage column.
    return candidates[-1]


def normalize_workbook(spec: EditionSpec, payload: bytes) -> list[dict[str, object]]:
    """Extract the latest column from one true edition-specific workbook."""
    _validate_workbook_payload(spec, payload)
    _, frames = _workbook_frames(payload)
    _validate_workbook_identity(spec, frames)
    release_date = _release_date_from_cover(frames)
    frame, header_row, latest_column, vintage_header = _latest_vintage_column(frames)
    release_month_pattern = re.compile(
        rf"\b{release_date.strftime('%b')}(?:{release_date.strftime('%B')[3:]})?"
        rf"\s*-?\s*(?:{release_date.year}|{release_date.year % 100:02d})\b",
        re.IGNORECASE,
    )
    normalized_header = " ".join(vintage_header.replace("\n", " ").split())
    if not release_month_pattern.search(normalized_header):
        raise ValueError(
            f"{spec.dataset_id}/{spec.edition}: latest vintage header "
            "does not match workbook publication month"
        )
    available = datetime.combine(
        release_date + timedelta(days=1), datetime.min.time(), tzinfo=UTC
    )
    raw_hash = _sha256(payload)
    output: list[dict[str, object]] = []
    seen: set[str] = set()
    for row_number in range(header_row + 1, len(frame)):
        raw_period = frame.iat[row_number, 0]
        if pd.isna(raw_period):
            continue
        match = QUARTER_PATTERN.fullmatch(" ".join(str(raw_period).split()))
        if not match:
            continue
        observation_period = f"{int(match.group(2)):04d}-Q{int(match.group(1))}"
        if observation_period in seen:
            raise ValueError(
                f"{spec.dataset_id}/{spec.edition}: duplicate {observation_period}"
            )
        raw_value = frame.iat[row_number, latest_column]
        if pd.isna(raw_value) or not str(raw_value).strip():
            continue
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"{spec.dataset_id}/{spec.edition}: non-numeric value "
                f"for {observation_period}"
            ) from error
        if not math.isfinite(value):
            raise ValueError(
                f"{spec.dataset_id}/{spec.edition}: non-finite value "
                f"for {observation_period}"
            )
        period = pd.Period(observation_period, freq="Q")
        observation_end = period.end_time.date()
        if observation_end >= release_date:
            raise ValueError(
                f"{spec.dataset_id}/{spec.edition}: future observation "
                f"{observation_period} is not before release {release_date}"
            )
        seen.add(observation_period)
        output.append(
            {
                "observation_period": observation_period,
                "observation_end_date": observation_end.isoformat(),
                "edition": spec.edition,
                "edition_title": spec.edition_title,
                "release_date": release_date.isoformat(),
                "available_time": _iso_utc(available),
                "availability_quality": (
                    "official_workbook_release_date_conservative_next_day"
                ),
                "availability_policy": "next_utc_day_after_workbook_publication_date",
                "series_code": spec.series_code,
                "series_name": spec.series_name,
                "price_basis": spec.price_basis,
                "seasonal_adjustment": "seasonally_adjusted",
                "frequency": "quarterly",
                "unit": "GBP_million",
                "value": value,
                "publication_vintage_header": vintage_header,
                "source_url": spec.workbook_url,
                "source_sha256": raw_hash,
                "catalog_page_url": spec.catalog_page_url,
                "catalog_page_sha256": spec.catalog_page_sha256,
                "edition_quality": "official_ons_edition_workbook_as_published",
                "growth_rate_policy": "same_edition_only_not_computed_by_downloader",
                "strict_intraday_eligible": False,
                "use_scope": "GBP_macro_state_reference_only_no_directional_alpha",
            }
        )
    if len(output) < 2:
        raise ValueError(f"{spec.dataset_id}/{spec.edition}: too few observations")
    return output


def combine_edition_rows(
    rows_by_edition: Sequence[Sequence[dict[str, object]]],
) -> list[dict[str, object]]:
    """Combine without replacing an older edition's revised observations."""
    output: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for rows in rows_by_edition:
        for row in rows:
            key = (
                str(row["series_code"]),
                str(row["edition"]),
                str(row["observation_period"]),
            )
            if key in seen:
                raise ValueError(f"duplicate within-edition observation key: {key}")
            seen.add(key)
            output.append(dict(row))
    return output


def _fetch(
    url: str,
    *,
    workbook: bool,
    timeout: float,
    retries: int,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bytes, dict[str, str]]:
    _validate_official_url(url, workbook=workbook)
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if retries < 0:
        raise ValueError("retries cannot be negative")
    maximum = MAX_WORKBOOK_BYTES if workbook else MAX_PAGE_BYTES
    last_error: Exception | None = None
    headers = {
        "User-Agent": f"{PROGRAM_VERSION} (+rate-limited public research archive)",
        "Accept": (
            "application/vnd.ms-excel,"
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            if workbook
            else "text/html"
        ),
    }
    for attempt in range(retries + 1):
        try:
            with httpx.Client(
                transport=transport,
                timeout=timeout,
                follow_redirects=True,
                headers=headers,
            ) as client:
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    try:
                        _validate_official_url(str(response.url), workbook=workbook)
                    except ValueError as error:
                        raise ValueError(
                            "ONS response redirected outside the canonical official URL"
                        ) from error
                    declared = response.headers.get("Content-Length")
                    if declared and int(declared) > maximum:
                        raise ValueError("ONS response exceeds the declared size gate")
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > maximum:
                            raise ValueError("ONS response exceeds the streamed size gate")
                        chunks.append(chunk)
                    payload = b"".join(chunks)
                    if not payload:
                        raise ValueError("ONS response is empty")
                    return payload, {
                        "content_type": response.headers.get("Content-Type", ""),
                        "etag": response.headers.get("ETag", ""),
                        "last_modified": response.headers.get("Last-Modified", ""),
                    }
        except ValueError:
            raise
        except httpx.HTTPStatusError as error:
            last_error = error
            status = error.response.status_code
            if status != 429 and status < 500:
                raise
            if attempt < retries:
                retry_after = error.response.headers.get("Retry-After", "").strip()
                backoff = 0.75 * (2**attempt)
                delay = max(float(retry_after), backoff) if retry_after.isdigit() else backoff
                sleep(min(MAX_RETRY_AFTER_SECONDS, delay))
        except (httpx.HTTPError, OSError) as error:
            last_error = error
            if attempt < retries:
                sleep(min(8.0, 0.75 * (2**attempt)))
    assert last_error is not None
    raise last_error


def _archive_snapshot(
    root: Path,
    *,
    key: str,
    suffix: str,
    payload: bytes,
    retrieved_at: datetime,
) -> Path:
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise ValueError("retrieved_at must be timezone-aware")
    digest = _sha256(payload)
    timestamp = retrieved_at.astimezone(UTC)
    filename = (
        f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}_{digest[:16]}{suffix}"
    )
    path = root / "archive" / key / str(timestamp.year) / filename
    if path.exists():
        if _sha256(path.read_bytes()) != digest:
            raise ValueError(f"archive hash mismatch: {path}")
    else:
        _atomic_write(path, payload)
    return path


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]], columns: Sequence[str]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(columns), extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    _atomic_write(path, buffer.getvalue().encode("utf-8"))


def _catalog_rows(editions: Sequence[EditionSpec]) -> list[dict[str, object]]:
    return [
        {
            **asdict(item),
            "listed_size_bytes": item.listed_size_bytes or "",
            "release_date": "",
            "release_date_quality": "unverified_until_workbook_cover",
            "normalization_eligible": False,
        }
        for item in editions
    ]


CATALOG_COLUMNS: Final[tuple[str, ...]] = (
    "dataset_id",
    "series_code",
    "series_name",
    "price_basis",
    "edition",
    "edition_title",
    "edition_year",
    "workbook_url",
    "workbook_format",
    "listed_size_bytes",
    "catalog_page_url",
    "catalog_page_sha256",
    "release_date",
    "release_date_quality",
    "normalization_eligible",
)


def build_catalog(
    output_directory: str | Path,
    *,
    refresh: bool = False,
    timeout: float = 30.0,
    retries: int = 3,
    request_delay: float = DEFAULT_REQUEST_DELAY_SECONDS,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: datetime | None = None,
    dataset_specs: Sequence[DatasetSpec] = DATASETS,
    expected_counts: Mapping[int, int] = EXPECTED_EDITION_COUNTS_2016_2025,
) -> tuple[list[EditionSpec], Path, Path]:
    """Fetch/cache official pages and write a hash-complete fail-closed catalog."""
    if request_delay < 0:
        raise ValueError("request_delay cannot be negative")
    root = _prepare_root(output_directory)
    retrieved_at = (now or datetime.now(UTC)).astimezone(UTC)
    prior = {} if refresh else _catalog_prior_sources(root, dataset_specs=dataset_specs)
    page_records: list[dict[str, object]] = []
    editions: list[EditionSpec] = []
    for position, spec in enumerate(dataset_specs):
        source_id = f"catalog_{spec.dataset_id}"
        cache_path = root / "raw" / "catalog_pages" / f"{spec.dataset_id}.html"
        sidecar_path = _cache_sidecar(cache_path)
        prior_record = prior.get(source_id)
        if cache_path.exists() and not refresh:
            if prior_record is None:
                raise ValueError(f"{source_id}: cached catalog page has no prior manifest record")
            payload = _read_hashed_cache(cache_path)
            if (
                prior_record.get("bytes") != len(payload)
                or prior_record.get("sha256") != _sha256(payload)
                or prior_record.get("url") != spec.page_url
            ):
                raise ValueError(f"{source_id}: cached catalog page disagrees with prior manifest")
            archive_path = _manifest_file(
                root,
                prior_record.get("archive_path"),
                field=f"{source_id} archive_path",
            )
            source_retrieved = prior_record.get("retrieved_at")
            if not isinstance(source_retrieved, str) or not source_retrieved:
                raise ValueError(f"{source_id}: prior catalog retrieval timestamp is invalid")
            metadata = {
                key: str(prior_record.get(key, ""))
                for key in ("content_type", "etag", "last_modified")
            }
        else:
            if not refresh and (prior_record is not None or sidecar_path.exists()):
                raise ValueError(f"{source_id}: prior catalog cache is incomplete; use --refresh")
            if position and request_delay:
                sleep(request_delay)
            payload, metadata = _fetch(
                spec.page_url,
                workbook=False,
                timeout=timeout,
                retries=retries,
                transport=transport,
                sleep=sleep,
            )
            _write_hashed_cache(cache_path, payload)
            archive_path = _archive_snapshot(
                root,
                key=source_id,
                suffix=".html",
                payload=payload,
                retrieved_at=retrieved_at,
            )
            source_retrieved = _iso_utc(retrieved_at)
        parsed = parse_dataset_page(spec, payload)
        editions.extend(parsed)
        page_records.append(
            {
                "source_id": source_id,
                "dataset_id": spec.dataset_id,
                "url": spec.page_url,
                "retrieved_at": source_retrieved,
                "sha256": _sha256(payload),
                "bytes": len(payload),
                "cache_path": cache_path.relative_to(root).as_posix(),
                "cache_sidecar_path": sidecar_path.relative_to(root).as_posix(),
                "archive_path": archive_path.relative_to(root).as_posix(),
                "edition_count": len(parsed),
                **metadata,
            }
        )
    if prior and set(prior) != {str(record["source_id"]) for record in page_records}:
        raise ValueError("ONS prior catalog manifest contains stale sources; use --refresh")
    if refresh:
        _remove_refresh_catalog_orphans(root, page_records)
    validate_catalog_coverage(
        editions,
        expected_counts=expected_counts,
        required_dataset_ids=tuple(spec.dataset_id for spec in dataset_specs),
    )
    editions.sort(key=lambda item: (item.edition_year, item.edition, item.dataset_id))
    catalog_path = root / "normalized" / "ons_gdp_realtime_edition_catalog.csv"
    _write_csv(catalog_path, _catalog_rows(editions), CATALOG_COLUMNS)
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "dataset_kind": CATALOG_DATASET_KIND,
        "program_version": PROGRAM_VERSION,
        "provider": PROVIDER,
        "license": LICENSE_URL,
        "official_domains": [ALLOWED_HOST],
        "retrieved_at": _iso_utc(retrieved_at),
        "scope": "ABMI and YBHA editions 2016-2025; GBP macro state reference only",
        "directional_alpha_registered": False,
        "catalog_complete": True,
        "workbooks_downloaded": False,
        "normalization_complete": False,
        "normalization_blocker": (
            "historical edition pages repeat the latest page release date; only "
            "workbook-embedded original publication dates are accepted"
        ),
        "growth_rate_policy": "same edition only; downloader computes no growth rates",
        "expected_counts": dict(expected_counts),
        "edition_count": len(editions),
        "listed_workbook_bytes": sum(
            item.listed_size_bytes or 0 for item in editions
        ),
        "catalog_path": str(catalog_path.relative_to(root)),
        "catalog_sha256": _sha256(catalog_path.read_bytes()),
        "catalog_pages": sorted(page_records, key=lambda item: str(item["dataset_id"])),
    }
    manifest_path = root / "manifests" / "ons_gdp_realtime_catalog_manifest.json"
    _write_manifest_pair(
        root,
        latest_path=manifest_path,
        archive_prefix="ons_gdp_realtime_catalog_manifest",
        manifest=manifest,
        retrieved_at=retrieved_at,
    )
    return editions, catalog_path, manifest_path


WORKBOOK_AUDIT_COLUMNS: Final[tuple[str, ...]] = (
    "source_id",
    "dataset_id",
    "series_code",
    "edition",
    "edition_title",
    "workbook_url",
    "workbook_format",
    "bytes",
    "sha256",
    "cache_path",
    "cache_sidecar_path",
    "archive_path",
    "retrieved_at",
    "release_date",
    "release_date_quality",
    "normalization_status",
    "normalized_rows",
    "content_type",
    "etag",
    "last_modified",
)


def download_workbooks(
    output_directory: str | Path,
    editions: Sequence[EditionSpec],
    *,
    refresh: bool = False,
    timeout: float = 60.0,
    retries: int = 3,
    request_delay: float = DEFAULT_REQUEST_DELAY_SECONDS,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: datetime | None = None,
    require_complete_normalization: bool = True,
) -> tuple[Path | None, Path, Path]:
    """Archive edition workbooks and normalize only a complete verified set.

    Missing workbook-embedded release dates are catalogued as blockers. If any
    edition is blocked, no partial normalized observation file is published.
    """
    if not editions:
        raise ValueError("editions cannot be empty")
    if request_delay < 0:
        raise ValueError("request_delay cannot be negative")
    root = _prepare_root(output_directory)
    retrieved_at = (now or datetime.now(UTC)).astimezone(UTC)
    prior = {} if refresh else _workbook_prior_sources(root, editions=editions)
    rows_by_edition: list[list[dict[str, object]]] = []
    audit_rows: list[dict[str, object]] = []
    blockers: list[str] = []
    for position, spec in enumerate(editions):
        source_id = f"{spec.dataset_id}/{spec.edition}"
        suffix = f".{spec.workbook_format}"
        cache_path = (
            root
            / "raw"
            / "cache"
            / spec.dataset_id
            / f"{spec.edition}{suffix}"
        )
        sidecar_path = _cache_sidecar(cache_path)
        prior_record = prior.get(source_id)
        metadata: dict[str, str] = {}
        if cache_path.exists() and not refresh:
            if prior_record is None:
                raise ValueError(f"{source_id}: cached workbook has no prior manifest record")
            payload = _read_hashed_cache(cache_path)
            if (
                prior_record.get("bytes") != len(payload)
                or prior_record.get("sha256") != _sha256(payload)
                or prior_record.get("workbook_url") != spec.workbook_url
            ):
                raise ValueError(f"{source_id}: cached workbook disagrees with prior manifest")
            archive_path = _manifest_file(
                root,
                prior_record.get("archive_path"),
                field=f"{source_id} archive_path",
            )
            source_retrieved = prior_record.get("retrieved_at")
            if not isinstance(source_retrieved, str) or not source_retrieved:
                raise ValueError(f"{source_id}: prior workbook retrieval timestamp is invalid")
            metadata = {
                key: str(prior_record.get(key, ""))
                for key in ("content_type", "etag", "last_modified")
            }
        else:
            if not refresh and (prior_record is not None or sidecar_path.exists()):
                raise ValueError(f"{source_id}: prior workbook cache is incomplete; use --refresh")
            if position and request_delay:
                sleep(request_delay)
            payload, metadata = _fetch(
                spec.workbook_url,
                workbook=True,
                timeout=timeout,
                retries=retries,
                transport=transport,
                sleep=sleep,
            )
            _validate_workbook_payload(spec, payload)
            _write_hashed_cache(cache_path, payload)
            archive_path = _archive_snapshot(
                root,
                key=source_id,
                suffix=suffix,
                payload=payload,
                retrieved_at=retrieved_at,
            )
            source_retrieved = _iso_utc(retrieved_at)
        _validate_workbook_payload(spec, payload)
        release_date_text = ""
        release_quality = "unavailable"
        normalized_rows: list[dict[str, object]] = []
        try:
            normalized_rows = normalize_workbook(spec, payload)
        except ReleaseDateUnavailable as error:
            status = "blocked_missing_workbook_original_publication_date"
            blockers.append(f"{spec.dataset_id}/{spec.edition}: {error}")
        else:
            status = "normalized_true_edition"
            release_date_text = str(normalized_rows[0]["release_date"])
            release_quality = "official_workbook_original_publication_date"
            rows_by_edition.append(normalized_rows)
        audit_rows.append(
            {
                "source_id": source_id,
                "dataset_id": spec.dataset_id,
                "series_code": spec.series_code,
                "edition": spec.edition,
                "edition_title": spec.edition_title,
                "workbook_url": spec.workbook_url,
                "workbook_format": spec.workbook_format,
                "bytes": len(payload),
                "sha256": _sha256(payload),
                "cache_path": str(cache_path.relative_to(root)),
                "cache_sidecar_path": str(sidecar_path.relative_to(root)),
                "archive_path": str(archive_path.relative_to(root)),
                "retrieved_at": source_retrieved,
                "release_date": release_date_text,
                "release_date_quality": release_quality,
                "normalization_status": status,
                "normalized_rows": len(normalized_rows),
                "content_type": metadata.get("content_type", ""),
                "etag": metadata.get("etag", ""),
                "last_modified": metadata.get("last_modified", ""),
            }
        )

    if prior and set(prior) != {str(record["source_id"]) for record in audit_rows}:
        raise ValueError("ONS prior workbook manifest contains stale sources; use --refresh")
    if refresh:
        _remove_refresh_workbook_orphans(root, audit_rows)

    audit_path = root / "normalized" / "ons_gdp_realtime_workbook_audit.csv"
    _write_csv(audit_path, audit_rows, WORKBOOK_AUDIT_COLUMNS)
    normalized_path: Path | None = None
    normalized_rows_combined: list[dict[str, object]] = []
    if not blockers:
        normalized_rows_combined = combine_edition_rows(rows_by_edition)
        normalized_rows_combined.sort(
            key=lambda row: (
                str(row["release_date"]),
                str(row["series_code"]),
                str(row["edition"]),
                str(row["observation_period"]),
            )
        )
        normalized_path = (
            root / "normalized" / "ons_gdp_realtime_observations.csv"
        )
        _write_csv(normalized_path, normalized_rows_combined, OUTPUT_COLUMNS)
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "dataset_kind": WORKBOOK_DATASET_KIND,
        "program_version": PROGRAM_VERSION,
        "provider": PROVIDER,
        "license": LICENSE_URL,
        "retrieved_at": _iso_utc(retrieved_at),
        "edition_count": len(editions),
        "workbooks_downloaded": True,
        "normalization_complete": not blockers,
        "normalization_blockers": blockers,
        "partial_normalized_file_written": False,
        "normalized_rows": len(normalized_rows_combined),
        "normalized_path": (
            str(normalized_path.relative_to(root)) if normalized_path else ""
        ),
        "normalized_sha256": (
            _sha256(normalized_path.read_bytes()) if normalized_path else ""
        ),
        "workbook_audit_path": str(audit_path.relative_to(root)),
        "workbook_audit_sha256": _sha256(audit_path.read_bytes()),
        "growth_rate_policy": "same edition only; downloader computes no growth rates",
        "strict_intraday_eligible": False,
        "use_scope": "GBP macro state reference only; no directional alpha",
        "sources": audit_rows,
    }
    manifest_path = root / "manifests" / "ons_gdp_realtime_workbook_manifest.json"
    _write_manifest_pair(
        root,
        latest_path=manifest_path,
        archive_prefix="ons_gdp_realtime_workbook_manifest",
        manifest=manifest,
        retrieved_at=retrieved_at,
    )
    if blockers and require_complete_normalization:
        raise ValueError(
            "ONS normalization is incomplete; fail-closed workbook catalog written: "
            f"{len(blockers)} edition(s) lack verified release dates"
        )
    return normalized_path, audit_path, manifest_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the official ONS ABMI/YBHA 2016-2025 edition catalog."
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/ons_gdp_realtime"))
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument(
        "--request-delay", type=float, default=DEFAULT_REQUEST_DELAY_SECONDS
    )
    parser.add_argument(
        "--download-workbooks",
        action="store_true",
        help="Archive all catalogued workbooks; normalization remains fail closed.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    editions, catalog, manifest = build_catalog(
        args.output_dir,
        refresh=args.refresh,
        timeout=args.timeout,
        retries=args.retries,
        request_delay=args.request_delay,
    )
    print(f"catalogued {len(editions)} official edition workbooks")
    print(catalog)
    print(manifest)
    if args.download_workbooks:
        normalized, audit, workbook_manifest = download_workbooks(
            args.output_dir,
            editions,
            refresh=args.refresh,
            timeout=max(args.timeout, 60.0),
            retries=args.retries,
            request_delay=args.request_delay,
            require_complete_normalization=False,
        )
        print(audit)
        print(workbook_manifest)
        print(normalized or "No partial normalized file was written.")
    else:
        print("Normalization remains fail-closed until each workbook release date is verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
