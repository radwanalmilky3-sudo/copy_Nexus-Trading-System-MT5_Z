#!/usr/bin/env python3
"""Archive official ECB SPF discovery evidence and an ALFRED vintage catalog.

ECB release pages and attachments are followed only when they are discovered
on the official ECB SPF index.  ALFRED series are a small, frozen catalog; the
program does not download current FRED observations as a substitute for
point-in-time data.  Without ``FRED_API_KEY`` the ALFRED vintage API is marked
blocked and no FRED API request is made.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, Final
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx

PROGRAM_VERSION: Final = "alfred-ecb-spf-catalog-v1"
SCHEMA_VERSION: Final = 1
START_YEAR: Final = 2016
END_YEAR: Final = 2025
MAX_RESPONSE_BYTES: Final = 16 * 1024 * 1024
MAX_REDIRECTS: Final = 5

ECB_HOSTS: Final = frozenset({"www.ecb.europa.eu", "ecb.europa.eu"})
FRED_API_HOST: Final = "api.stlouisfed.org"
ECB_INDEX_URL: Final = (
    "https://www.ecb.europa.eu/stats/ecb_surveys/"
    "survey_of_professional_forecasters/html/index.en.html"
)
ECB_REUSE_URL: Final = "https://www.ecb.europa.eu/services/disclaimer/html/index.en.html"
FRED_TERMS_URL: Final = "https://fred.stlouisfed.org/legal/"
FRED_API_BASE: Final = "https://api.stlouisfed.org/fred"

_SPF_MARKERS = (
    "survey of professional forecasters",
    "survey_of_professional_forecasters",
    "professional-forecasters",
    "professional_forecasters",
    "ecb.spf",
)
_QUARTER_NAMES = {"first": 1, "second": 2, "third": 3, "fourth": 4}
_ATTACHMENT_SUFFIXES = frozenset({".csv", ".pdf", ".xls", ".xlsx", ".zip"})
_SHA256_LINE = re.compile(r"([0-9a-f]{64})  (.+)")
_ECB_CONTENT_QUERY = re.compile(r"[0-9a-f]{32}", re.IGNORECASE)


@dataclass(frozen=True)
class AlfredSeries:
    series_id: str
    title: str
    frequency: str
    research_role: str


ALFRED_SERIES: Final[tuple[AlfredSeries, ...]] = (
    AlfredSeries(
        "CPIAUCSL",
        "Consumer Price Index for All Urban Consumers",
        "monthly",
        "us_inflation_state",
    ),
    AlfredSeries("INDPRO", "Industrial Production: Total Index", "monthly", "us_activity_state"),
    AlfredSeries("PAYEMS", "All Employees, Total Nonfarm", "monthly", "us_labour_state"),
    AlfredSeries("UNRATE", "Civilian Unemployment Rate", "monthly", "us_labour_state"),
    AlfredSeries("GDPC1", "Real Gross Domestic Product", "quarterly", "us_activity_state"),
)


class CatalogError(ValueError):
    """The discovery, archive, or manifest contract is invalid."""


class SourceUnavailableError(CatalogError):
    """An official source was unavailable without creating a security issue."""


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a" or self._href is not None:
            return
        attributes = {key.casefold(): value for key, value in attrs}
        href = attributes.get("href")
        if href:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "a" and self._href is not None:
            text = " ".join(" ".join(self._text).split())
            self.anchors.append((self._href, text))
            self._href = None
            self._text = []


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
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


def _safe_relative(root: Path, relative: object, label: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise CatalogError(f"{label} path is missing")
    path = (root / relative).resolve()
    if root.resolve() not in path.parents:
        raise CatalogError(f"{label} path escaped output root")
    return path


def _sidecar(path: Path) -> Path:
    return Path(f"{path}.sha256")


def _write_hashed(path: Path, payload: bytes) -> str:
    digest = _sha256(payload)
    _atomic_write(path, payload)
    _atomic_write(_sidecar(path), f"{digest}  {path.name}\n".encode("ascii"))
    return digest


def _read_sidecar(path: Path) -> str:
    sidecar = _sidecar(path)
    try:
        line = sidecar.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError) as error:
        raise CatalogError(f"missing or unreadable SHA-256 sidecar: {sidecar}") from error
    match = _SHA256_LINE.fullmatch(line)
    if match is None or match.group(2) != path.name:
        raise CatalogError(f"invalid SHA-256 sidecar: {sidecar}")
    return match.group(1)


def _validate_ecb_url(url: str) -> str:
    parsed = urlparse(url)
    decoded_path = unquote(parsed.path)
    query_allowed = not parsed.query or _ECB_CONTENT_QUERY.fullmatch(parsed.query) is not None
    if parsed.path == "/press/pubbydate/html/index.en.html" and parsed.query:
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
        query_allowed = query in (
            {"name_of_publication": ["Survey of Professional Forecasters"]},
            {
                "search_term": ["Survey of Professional Forecasters"],
                "name_of_publication": ["Press release"],
            },
        )
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ECB_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or not query_allowed
        or parsed.fragment
        or not parsed.path.startswith("/")
        or "\\" in decoded_path
        or ".." in PurePosixPath(decoded_path).parts
    ):
        raise CatalogError(f"unsafe or non-official ECB URL: {url}")
    return url


def _validate_fred_api_url(url: str) -> str:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != FRED_API_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/fred/")
    ):
        raise CatalogError(f"unsafe FRED API URL: {url}")
    return url


def _fetch(
    client: httpx.Client,
    url: str,
    *,
    provider: str,
    params: Mapping[str, object] | None = None,
) -> tuple[bytes, str]:
    validator = _validate_ecb_url if provider == "ecb" else _validate_fred_api_url
    current = validator(url)
    request_params = params
    for _ in range(MAX_REDIRECTS + 1):
        try:
            response = client.get(current, params=request_params)
        except httpx.HTTPError as error:
            raise SourceUnavailableError(
                f"{provider} request failed: {type(error).__name__}"
            ) from error
        request_params = None
        if response.is_redirect:
            location = response.headers.get("location")
            if not location:
                raise SourceUnavailableError(f"{provider} redirect lacks Location")
            current = validator(urljoin(str(response.url), location))
            continue
        if response.status_code != 200:
            raise SourceUnavailableError(
                f"{provider} source returned HTTP {response.status_code}"
            )
        final_url = (
            str(response.url)
            if provider == "ecb"
            else str(response.url.copy_with(query=None, fragment=None))
        )
        validator(final_url)
        declared = response.headers.get("content-length")
        if declared is not None and int(declared) > MAX_RESPONSE_BYTES:
            raise SourceUnavailableError(f"{provider} response exceeds declared size limit")
        payload = response.content
        if not payload or len(payload) > MAX_RESPONSE_BYTES:
            raise SourceUnavailableError(f"{provider} response is empty or oversized")
        return payload, final_url
    raise SourceUnavailableError(f"{provider} source exceeded redirect limit")


def _html(payload: bytes, label: str, *, require_spf_marker: bool) -> str:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SourceUnavailableError(f"{label} is not UTF-8 HTML") from error
    folded = text.casefold()
    if "<html" not in folded or "<title>error" in folded or "page not found" in folded:
        raise SourceUnavailableError(f"{label} is a soft error page")
    if require_spf_marker and not any(marker in folded for marker in _SPF_MARKERS):
        raise SourceUnavailableError(f"{label} lacks an ECB SPF marker")
    return text


def _anchors(html: str) -> list[tuple[str, str]]:
    parser = _AnchorParser()
    parser.feed(html)
    parser.close()
    return parser.anchors


def _release_period(text: str) -> tuple[int, int] | None:
    normalized = " ".join(text.casefold().replace("_", " ").replace("-", " ").split())
    patterns = (
        re.search(r"(20\d{2})\s*q([1-4])\b", normalized),
        re.search(r"\bq([1-4])\s*(20\d{2})\b", normalized),
        re.search(r"\b(20\d{2})\D{0,40}(first|second|third|fourth) quarter\b", normalized),
        re.search(r"\b(first|second|third|fourth) quarter(?: of)?\D{0,20}(20\d{2})\b", normalized),
    )
    first, second, third, fourth = patterns
    if first is not None:
        year, quarter = int(first.group(1)), int(first.group(2))
    elif second is not None:
        quarter, year = int(second.group(1)), int(second.group(2))
    elif third is not None:
        year, quarter = int(third.group(1)), _QUARTER_NAMES[third.group(2)]
    elif fourth is not None:
        quarter, year = _QUARTER_NAMES[fourth.group(1)], int(fourth.group(2))
    else:
        return None
    if not START_YEAR <= year <= END_YEAR:
        return None
    return year, quarter


def discover_ecb_release_catalog_pages(index_html: str) -> list[dict[str, str]]:
    """Return official all-release pages explicitly linked by the SPF index."""

    index_path = Path(urlparse(ECB_INDEX_URL).path)
    found: dict[str, dict[str, str]] = {}
    for href, anchor_text in _anchors(index_html):
        normalized_text = " ".join(anchor_text.casefold().split())
        candidate_path = Path(urlparse(href).path)
        is_all_releases = (
            "all releases" in normalized_text or "all-releases" in candidate_path.name
        )
        is_full_reports = normalized_text == "full reports"
        is_filtered_press_releases = (
            normalized_text == "press releases" and "pubbydate" in href
        )
        if not (is_all_releases or is_full_reports or is_filtered_press_releases):
            continue
        url = _validate_ecb_url(urljoin(ECB_INDEX_URL, href))
        parsed = urlparse(url)
        if is_all_releases:
            if (
                Path(parsed.path).parent != index_path.parent
                or "all-releases" not in Path(parsed.path).name.casefold()
            ):
                raise CatalogError("ECB all-release discovery escaped the SPF index directory")
        elif parsed.path != "/press/pubbydate/html/index.en.html":
            raise CatalogError("ECB filtered release discovery escaped the publication index")
        found[url] = {
            "url": url,
            "anchor_text": anchor_text,
            "discovered_from": ECB_INDEX_URL,
        }
    return sorted(found.values(), key=lambda row: row["url"])


def discover_ecb_release_pages(
    index_html: str,
    *,
    page_url: str = ECB_INDEX_URL,
) -> list[dict[str, object]]:
    """Discover 2016--2025 SPF release pages without synthesizing any URL."""

    found: dict[str, dict[str, object]] = {}
    for href, anchor_text in _anchors(index_html):
        combined = f"{anchor_text} {href}"
        if not any(marker in combined.casefold() for marker in _SPF_MARKERS):
            continue
        period = _release_period(combined)
        if period is None:
            continue
        candidate = urljoin(page_url, href)
        if Path(urlparse(candidate).path).suffix.casefold() != ".html":
            continue
        url = _validate_ecb_url(candidate)
        if url == ECB_INDEX_URL:
            continue
        year, quarter = period
        found[url] = {
            "year": year,
            "quarter": quarter,
            "period": f"{year}-Q{quarter}",
            "url": url,
            "anchor_text": anchor_text,
            "discovered_from": page_url,
        }
    return sorted(found.values(), key=lambda row: (row["year"], row["quarter"], row["url"]))


def discover_ecb_attachments(release_url: str, release_html: str) -> list[dict[str, str]]:
    """Return only official attachment URLs explicitly linked by a release page."""

    found: dict[str, dict[str, str]] = {}
    for href, anchor_text in _anchors(release_html):
        suffix = Path(urlparse(href).path).suffix.casefold()
        if suffix not in _ATTACHMENT_SUFFIXES:
            continue
        url = _validate_ecb_url(urljoin(release_url, href))
        found[url] = {
            "url": url,
            "anchor_text": anchor_text,
            "suffix": suffix,
            "discovered_from": release_url,
        }
    return sorted(found.values(), key=lambda row: row["url"])


def _validate_attachment(payload: bytes, suffix: str) -> None:
    if suffix == ".pdf" and not payload.startswith(b"%PDF-"):
        raise SourceUnavailableError("ECB attachment is not a PDF")
    if suffix in {".xlsx", ".zip"} and not payload.startswith(b"PK"):
        raise SourceUnavailableError("ECB attachment is not a ZIP-based file")
    if suffix == ".xls" and not payload.startswith(b"\xd0\xcf\x11\xe0"):
        raise SourceUnavailableError("ECB attachment is not an XLS file")
    if suffix == ".csv":
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise SourceUnavailableError("ECB CSV attachment is not UTF-8") from error
        if "\n" not in text or "," not in text.splitlines()[0]:
            raise SourceUnavailableError("ECB CSV attachment has no tabular header")


def _archive_source(
    root: Path,
    *,
    provider: str,
    kind: str,
    source_id: str,
    source_url: str,
    discovered_from: str | None,
    relative_raw: str,
    payload: bytes,
    retrieved_at: datetime,
) -> dict[str, object]:
    digest = _sha256(payload)
    raw_path = _safe_relative(root, relative_raw, f"{source_id} raw")
    _write_hashed(raw_path, payload)
    suffixes = "".join(raw_path.suffixes) or ".bin"
    archive_path = (
        root
        / "archive"
        / provider
        / kind
        / f"{retrieved_at.year:04d}"
        / f"{retrieved_at.strftime('%Y%m%dT%H%M%S%fZ')}_{digest[:16]}{suffixes}"
    )
    if archive_path.exists():
        if _file_sha256(archive_path) != digest:
            raise CatalogError(f"archive digest collision: {archive_path}")
        if _read_sidecar(archive_path) != digest:
            raise CatalogError(f"archive sidecar mismatch: {archive_path}")
    else:
        _write_hashed(archive_path, payload)
    return {
        "source_id": source_id,
        "provider": provider,
        "kind": kind,
        "source_url": source_url,
        "discovered_from": discovered_from,
        "retrieved_at": retrieved_at.isoformat(),
        "raw_path": raw_path.relative_to(root).as_posix(),
        "raw_sha256_path": _sidecar(raw_path).relative_to(root).as_posix(),
        "archive_path": archive_path.relative_to(root).as_posix(),
        "archive_sha256_path": _sidecar(archive_path).relative_to(root).as_posix(),
        "bytes": len(payload),
        "sha256": digest,
    }


def _fred_catalog_record(series: AlfredSeries) -> dict[str, object]:
    return {
        "series_id": series.series_id,
        "title": series.title,
        "declared_frequency": series.frequency,
        "research_role": series.research_role,
        "alfred_page": f"https://alfred.stlouisfed.org/series?seid={series.series_id}",
        "strict_pit": False,
        "is_intraday_surprise": False,
        "availability_blocker": (
            "observation-by-vintage values and exact release timestamps are not parsed"
        ),
    }


def _json_object(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SourceUnavailableError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise SourceUnavailableError(f"{label} must be a JSON object")
    return value


def _download_alfred_series_catalog(
    root: Path,
    client: httpx.Client,
    series: AlfredSeries,
    api_key: str,
    retrieved_at: datetime,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    sources: list[dict[str, object]] = []
    common = {"api_key": api_key, "file_type": "json", "series_id": series.series_id}
    metadata_url = f"{FRED_API_BASE}/series"
    payload, _ = _fetch(client, metadata_url, provider="fred", params=common)
    if len(api_key) >= 8 and api_key.encode() in payload:
        raise SourceUnavailableError("FRED response echoed the API key; payload was not archived")
    metadata = _json_object(payload, f"FRED {series.series_id} metadata")
    rows = metadata.get("seriess")
    if (
        not isinstance(rows, list)
        or len(rows) != 1
        or not isinstance(rows[0], dict)
        or rows[0].get("id") != series.series_id
    ):
        raise SourceUnavailableError(f"FRED metadata disagrees for {series.series_id}")
    sources.append(
        _archive_source(
            root,
            provider="alfred",
            kind="series_metadata",
            source_id=f"alfred_{series.series_id}_metadata",
            source_url=f"{metadata_url}?series_id={series.series_id}&file_type=json&api_key=REDACTED",
            discovered_from=None,
            relative_raw=f"raw/alfred/{series.series_id}/series_metadata.json",
            payload=payload,
            retrieved_at=retrieved_at,
        )
    )

    endpoint = f"{FRED_API_BASE}/series/vintagedates"
    vintage_dates: list[str] = []
    offset = 0
    expected_count: int | None = None
    for _page_number in range(100):
        params = {
            **common,
            "realtime_start": f"{START_YEAR}-01-01",
            "realtime_end": f"{END_YEAR}-12-31",
            "limit": 1000,
            "offset": offset,
            "sort_order": "asc",
        }
        payload, _ = _fetch(client, endpoint, provider="fred", params=params)
        if len(api_key) >= 8 and api_key.encode() in payload:
            raise SourceUnavailableError(
                "FRED response echoed the API key; payload was not archived"
            )
        page = _json_object(payload, f"FRED {series.series_id} vintage dates")
        values = page.get("vintage_dates")
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise SourceUnavailableError(f"FRED vintage dates malformed for {series.series_id}")
        try:
            count = int(page["count"])
            response_offset = int(page["offset"])
            limit = int(page["limit"])
        except (KeyError, TypeError, ValueError) as error:
            raise SourceUnavailableError("FRED vintage pagination metadata is malformed") from error
        if response_offset != offset or limit <= 0 or count < 0:
            raise SourceUnavailableError("FRED vintage pagination is inconsistent")
        expected_count = count if expected_count is None else expected_count
        if count != expected_count:
            raise SourceUnavailableError("FRED vintage count changed during pagination")
        for value in values:
            try:
                parsed = datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError as error:
                raise SourceUnavailableError(f"invalid FRED vintage date: {value}") from error
            if not START_YEAR <= parsed.year <= END_YEAR:
                raise SourceUnavailableError(f"FRED vintage date escaped requested period: {value}")
        vintage_dates.extend(values)
        sources.append(
            _archive_source(
                root,
                provider="alfred",
                kind="vintage_date_page",
                source_id=f"alfred_{series.series_id}_vintages_{offset:06d}",
                source_url=(
                    f"{endpoint}?series_id={series.series_id}&realtime_start={START_YEAR}-01-01"
                    f"&realtime_end={END_YEAR}-12-31&offset={offset}&api_key=REDACTED"
                ),
                discovered_from=metadata_url,
                relative_raw=(
                    f"raw/alfred/{series.series_id}/vintage_dates_{offset:06d}.json"
                ),
                payload=payload,
                retrieved_at=retrieved_at,
            )
        )
        offset += len(values)
        if offset >= count:
            break
        if not values:
            raise SourceUnavailableError("FRED vintage pagination made no progress")
    else:
        raise SourceUnavailableError("FRED vintage pagination exceeded 100 pages")
    if expected_count is None or len(vintage_dates) != expected_count:
        raise SourceUnavailableError("FRED vintage date count is incomplete")
    if vintage_dates != sorted(set(vintage_dates)):
        raise SourceUnavailableError("FRED vintage dates are duplicate or unsorted")
    record = _fred_catalog_record(series)
    record.update(
        {
            "status": "vintage_dates_catalogued_values_not_downloaded",
            "vintage_date_count": len(vintage_dates),
            "first_vintage_date": vintage_dates[0] if vintage_dates else None,
            "last_vintage_date": vintage_dates[-1] if vintage_dates else None,
            "api_key_stored": False,
        }
    )
    return record, sources


def _write_manifest(root: Path, manifest: dict[str, object], retrieved_at: datetime) -> Path:
    manifest_path = root / "alfred_ecb_spf_catalog_manifest.json"
    payload = (json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()
    digest = _write_hashed(manifest_path, payload)
    archive = (
        root
        / "archive"
        / "manifests"
        / f"{retrieved_at.strftime('%Y%m%dT%H%M%S%fZ')}_{digest[:16]}.json"
    )
    _write_hashed(archive, payload)
    return manifest_path


def validate_existing_catalog(root: str | Path) -> dict[str, object]:
    base = Path(root).resolve()
    manifest_path = base / "alfred_ecb_spf_catalog_manifest.json"
    if not manifest_path.is_file():
        if (base / "raw").exists() or (base / "archive").exists():
            raise CatalogError("orphan catalog cache exists without a manifest")
        raise FileNotFoundError(manifest_path)
    expected_manifest_hash = _read_sidecar(manifest_path)
    if _file_sha256(manifest_path) != expected_manifest_hash:
        raise CatalogError("catalog manifest SHA-256 mismatch")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CatalogError("cannot read catalog manifest") from error
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("program_version") != PROGRAM_VERSION
        or manifest.get("strict_pit") is not False
        or manifest.get("factor_outcome_evaluations_added") != 0
    ):
        raise CatalogError("catalog manifest contract is incompatible")
    sources = manifest.get("sources")
    if not isinstance(sources, list):
        raise CatalogError("catalog manifest sources are missing")
    source_ids: set[str] = set()
    for record in sources:
        if not isinstance(record, dict) or not isinstance(record.get("source_id"), str):
            raise CatalogError("catalog source record is malformed")
        if record["source_id"] in source_ids:
            raise CatalogError("catalog source IDs are duplicated")
        source_ids.add(record["source_id"])
        digest = record.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise CatalogError("catalog source SHA-256 is malformed")
        for field in ("raw_path", "archive_path"):
            path = _safe_relative(base, record.get(field), field)
            if not path.is_file() or _read_sidecar(path) != digest or _file_sha256(path) != digest:
                raise CatalogError(f"catalog {field} SHA-256 mismatch")
    return manifest


def download_catalogs(
    output_directory: str | Path,
    *,
    client: httpx.Client | None = None,
    fred_api_key: str | None = None,
    refresh: bool = False,
    retrieved_at: datetime | None = None,
) -> Path:
    """Download official discovery evidence and write a fail-closed catalog."""

    root = Path(output_directory).resolve()
    manifest_path = root / "alfred_ecb_spf_catalog_manifest.json"
    if manifest_path.exists() and not refresh:
        validate_existing_catalog(root)
        return manifest_path
    if not manifest_path.exists() and not refresh and (
        (root / "raw").exists() or (root / "archive").exists()
    ):
        raise CatalogError("orphan catalog cache exists without a manifest; use --refresh")
    timestamp = retrieved_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise CatalogError("retrieved_at must be timezone-aware")
    timestamp = timestamp.astimezone(UTC)
    api_key = fred_api_key if fred_api_key is not None else os.environ.get("FRED_API_KEY")
    api_key = api_key.strip() if api_key else None
    owned_client = client is None
    active_client = client or httpx.Client(
        timeout=30,
        follow_redirects=False,
        headers={"User-Agent": f"{PROGRAM_VERSION} (+public research archive)"},
    )
    sources: list[dict[str, object]] = []
    ecb_releases: list[dict[str, object]] = []
    ecb_blockers: list[str] = []
    try:
        try:
            index_payload, index_final_url = _fetch(active_client, ECB_INDEX_URL, provider="ecb")
            index_html = _html(index_payload, "ECB SPF index", require_spf_marker=True)
            sources.append(
                _archive_source(
                    root,
                    provider="ecb_spf",
                    kind="index",
                    source_id="ecb_spf_index",
                    source_url=index_final_url,
                    discovered_from=None,
                    relative_raw="raw/ecb_spf/index.html",
                    payload=index_payload,
                    retrieved_at=timestamp,
                )
            )
            discovered_by_url = {
                str(record["url"]): record
                for record in discover_ecb_release_pages(index_html)
            }
            catalog_pages = discover_ecb_release_catalog_pages(index_html)
            for catalog_page in catalog_pages:
                catalog_url = catalog_page["url"]
                catalog_id = _sha256(catalog_url.encode())[:12]
                try:
                    catalog_payload, catalog_final_url = _fetch(
                        active_client, catalog_url, provider="ecb"
                    )
                    catalog_html = _html(
                        catalog_payload,
                        "ECB SPF all-releases page",
                        require_spf_marker=False,
                    )
                    sources.append(
                        _archive_source(
                            root,
                            provider="ecb_spf",
                            kind="release_catalog_page",
                            source_id=f"ecb_spf_release_catalog_{catalog_id}",
                            source_url=catalog_final_url,
                            discovered_from=ECB_INDEX_URL,
                            relative_raw=(
                                f"raw/ecb_spf/release_catalogs/{catalog_id}.html"
                            ),
                            payload=catalog_payload,
                            retrieved_at=timestamp,
                        )
                    )
                    for record in discover_ecb_release_pages(
                        catalog_html,
                        page_url=catalog_final_url,
                    ):
                        discovered_by_url.setdefault(str(record["url"]), record)
                except SourceUnavailableError as error:
                    ecb_blockers.append(
                        f"discovered ECB release catalog unavailable: {error}"
                    )
            discovered = sorted(
                discovered_by_url.values(),
                key=lambda row: (row["year"], row["quarter"], row["url"]),
            )
        except SourceUnavailableError as error:
            discovered = []
            ecb_blockers.append(str(error))

        for release in discovered:
            url = str(release["url"])
            period = str(release["period"])
            url_id = _sha256(url.encode())[:12]
            entry = dict(release)
            entry["status"] = "catalogued_release_page"
            entry["attachments"] = []
            try:
                payload, final_url = _fetch(active_client, url, provider="ecb")
                html = _html(payload, f"ECB SPF {period}", require_spf_marker=True)
                sources.append(
                    _archive_source(
                        root,
                        provider="ecb_spf",
                        kind="release_page",
                        source_id=f"ecb_spf_{period.lower()}_{url_id}_page",
                        source_url=final_url,
                        discovered_from=str(release["discovered_from"]),
                        relative_raw=f"raw/ecb_spf/releases/{period.lower()}_{url_id}.html",
                        payload=payload,
                        retrieved_at=timestamp,
                    )
                )
                attachments = discover_ecb_attachments(final_url, html)
                for attachment in attachments:
                    attachment_url = attachment["url"]
                    attachment_id = _sha256(attachment_url.encode())[:12]
                    try:
                        file_payload, file_final_url = _fetch(
                            active_client, attachment_url, provider="ecb"
                        )
                        _validate_attachment(file_payload, attachment["suffix"])
                        source = _archive_source(
                            root,
                            provider="ecb_spf",
                            kind="attachment",
                            source_id=(
                                f"ecb_spf_{period.lower()}_{attachment_id}_attachment"
                            ),
                            source_url=file_final_url,
                            discovered_from=final_url,
                            relative_raw=(
                                f"raw/ecb_spf/attachments/{period.lower()}_"
                                f"{attachment_id}{attachment['suffix']}"
                            ),
                            payload=file_payload,
                            retrieved_at=timestamp,
                        )
                        sources.append(source)
                        entry["attachments"].append(
                            {
                                **attachment,
                                "status": "archived_discovered_attachment",
                                "sha256": source["sha256"],
                            }
                        )
                    except SourceUnavailableError as error:
                        entry["attachments"].append(
                            {**attachment, "status": "blocked_unavailable", "blocker": str(error)}
                        )
            except SourceUnavailableError as error:
                entry["status"] = "blocked_discovered_release_unavailable"
                entry["blocker"] = str(error)
            ecb_releases.append(entry)

        alfred_records: list[dict[str, object]] = []
        if api_key is None:
            for series in ALFRED_SERIES:
                record = _fred_catalog_record(series)
                record.update(
                    {
                        "status": "blocked_fred_api_key_required",
                        "vintage_date_count": None,
                        "api_key_stored": False,
                    }
                )
                alfred_records.append(record)
            alfred_blocker = (
                "FRED_API_KEY is required for the official vintage API; current-vintage "
                "FRED CSV was deliberately not downloaded"
            )
        else:
            alfred_blocker = (
                "vintage dates are catalogued, but observation-by-vintage values and exact "
                "release timestamps are not yet parsed"
            )
            for series in ALFRED_SERIES:
                try:
                    record, series_sources = _download_alfred_series_catalog(
                        root, active_client, series, api_key, timestamp
                    )
                    sources.extend(series_sources)
                except SourceUnavailableError as error:
                    record = _fred_catalog_record(series)
                    record.update(
                        {
                            "status": "blocked_official_vintage_api_unavailable",
                            "blocker": str(error),
                            "vintage_date_count": None,
                            "api_key_stored": False,
                        }
                    )
                alfred_records.append(record)
    finally:
        if owned_client:
            active_client.close()

    expected_periods = {
        f"{year}-Q{quarter}"
        for year in range(START_YEAR, END_YEAR + 1)
        for quarter in range(1, 5)
    }
    discovered_periods = {str(record["period"]) for record in ecb_releases}
    missing_periods = sorted(expected_periods - discovered_periods)
    if missing_periods:
        ecb_blockers.append(
            "official index discovery did not expose all 2016-2025 quarters; no URL was guessed"
        )
    manifest: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "program_version": PROGRAM_VERSION,
        "retrieved_at": timestamp.isoformat(),
        "research_status": "catalogued_or_blocked_no_values_registered",
        "period": {"start_year": START_YEAR, "end_year": END_YEAR},
        "strict_pit": False,
        "is_intraday_surprise_data": False,
        "return_labels_opened": False,
        "factor_outcome_evaluations_added": 0,
        "trading_approval": False,
        "license_and_source": {
            "ecb_spf": {
                "provider": "European Central Bank",
                "official_index": ECB_INDEX_URL,
                "reuse_terms": ECB_REUSE_URL,
                "license_status": "official_reuse_terms_require_case_specific_review",
                "redistribution_approved_by_this_catalog": False,
            },
            "alfred": {
                "provider": "Federal Reserve Bank of St. Louis",
                "terms": FRED_TERMS_URL,
                "api_base": FRED_API_BASE,
                "license_status": "FRED_API_terms_and_upstream_series_notes_require_review",
                "redistribution_approved_by_this_catalog": False,
            },
        },
        "availability_blockers": {
            "ecb_spf": (
                "release pages/attachments are discovery evidence only; exact publication "
                "timestamps, attachment revision behavior, and value vintages are not normalized"
            ),
            "alfred": alfred_blocker,
        },
        "ecb_spf": {
            "status": "catalogued" if ecb_releases else "blocked_no_release_pages_discovered",
            "expected_release_period_count": 40,
            "discovered_release_period_count": len(discovered_periods),
            "missing_release_periods": missing_periods,
            "blockers": ecb_blockers,
            "releases": ecb_releases,
        },
        "alfred": {
            "status": (
                "blocked_fred_api_key_required"
                if api_key is None
                else "catalogued_vintage_dates_values_still_blocked"
            ),
            "api_key_stored": False,
            "current_vintage_fallback_used": False,
            "series": alfred_records,
        },
        "sources": sorted(sources, key=lambda item: item["source_id"]),
    }
    root.mkdir(parents=True, exist_ok=True)
    return _write_manifest(root, manifest, timestamp)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data/alfred_ecb_spf"))
    parser.add_argument("--fred-api-key", help="Defaults to FRED_API_KEY; never persisted")
    parser.add_argument("--refresh", action="store_true")
    return parser


def main() -> None:
    args = _parser().parse_args()
    manifest = download_catalogs(
        args.output_dir,
        fred_api_key=args.fred_api_key,
        refresh=args.refresh,
    )
    print(manifest)


if __name__ == "__main__":
    main()
