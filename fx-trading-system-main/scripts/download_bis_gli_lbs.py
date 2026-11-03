#!/usr/bin/env python3
"""Archive official BIS GLI/LBS current snapshots and optional bulk ZIPs.

The BIS bulk files are current vintages, not release-by-release archives.  This
tool therefore preserves retrieval evidence and content hashes while keeping
the strict PIT gate closed.  It does not interpret global liquidity or
locational banking statistics as FX order flow or directional alpha.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Final
from urllib.parse import urlparse

import httpx

PROGRAM_VERSION: Final = "bis-gli-lbs-current-snapshot-v1.1"
PROVIDER: Final = "Bank for International Settlements"
ALLOWED_HOSTS: Final[frozenset[str]] = frozenset(
    {"data.bis.org", "www.bis.org", "bis.org"}
)
DEFAULT_OUTPUT_DIR: Final = Path("data/bis_gli_lbs")
CHUNK_BYTES: Final = 1024 * 1024
MAX_HTML_BYTES: Final = 4 * 1024 * 1024
MAX_DOCUMENT_BYTES: Final = 16 * 1024 * 1024
MAX_GLI_ZIP_BYTES: Final = 64 * 1024 * 1024
MAX_LBS_ZIP_BYTES: Final = 768 * 1024 * 1024
MAX_ZIP_MEMBERS: Final = 1_000
# The official 2026-06 LBS flat CSV advertises 17,672,650,002 uncompressed
# bytes inside a ~356 MB ZIP.  We inventory its central directory but never
# extract it.  These finite limits admit that observed file while still
# rejecting an unexpected multi-file or extreme-ratio archive.
MAX_ZIP_MEMBER_BYTES: Final = 24 * 1024 * 1024 * 1024
MAX_ZIP_UNCOMPRESSED_BYTES: Final = 24 * 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO: Final = 100


@dataclass(frozen=True)
class Resource:
    resource_id: str
    url: str
    raw_name: str
    kind: str
    maximum_bytes: int
    required_markers: tuple[bytes, ...] = ()


BASE_RESOURCES: Final[tuple[Resource, ...]] = (
    Resource(
        "gli_topic",
        "https://data.bis.org/topics/GLI",
        "gli_topic.html",
        "html",
        MAX_HTML_BYTES,
        (b"gli_methodology.pdf", b"/bulkdownload"),
    ),
    Resource(
        "lbs_topic",
        "https://data.bis.org/topics/LBS",
        "lbs_topic.html",
        "html",
        MAX_HTML_BYTES,
        (b"bankstatsguide.pdf", b"ibs_breakrev_summary.pdf", b"/bulkdownload"),
    ),
    Resource(
        "bulk_download_page",
        "https://data.bis.org/bulkdownload",
        "bulk_download.html",
        "html",
        MAX_HTML_BYTES,
        (b"WS_GLI_csv_flat.zip", b"WS_LBS_D_PUB_csv_flat.zip"),
    ),
    Resource(
        "gli_methodology",
        "https://www.bis.org/statistics/gli/gli_methodology.pdf",
        "gli_methodology.pdf",
        "pdf",
        MAX_DOCUMENT_BYTES,
    ),
    Resource(
        "lbs_guide",
        "https://www.bis.org/statistics/bankstatsguide.pdf",
        "lbs_guide.pdf",
        "pdf",
        MAX_DOCUMENT_BYTES,
    ),
    Resource(
        "lbs_break_revision_summary",
        "https://www.bis.org/statistics/bankstats/ibs_breakrev_summary.pdf",
        "lbs_break_revision_summary.pdf",
        "pdf",
        MAX_DOCUMENT_BYTES,
    ),
)

GLI_BULK: Final = Resource(
    "gli_bulk_flat_csv",
    "https://data.bis.org/static/bulk/WS_GLI_csv_flat.zip",
    "WS_GLI_csv_flat.zip",
    "zip",
    MAX_GLI_ZIP_BYTES,
)
LBS_BULK: Final = Resource(
    "lbs_bulk_flat_csv",
    "https://data.bis.org/static/bulk/WS_LBS_D_PUB_csv_flat.zip",
    "WS_LBS_D_PUB_csv_flat.zip",
    "zip",
    MAX_LBS_ZIP_BYTES,
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"refusing non-BIS URL: {url}")


def _load_prior_manifest(path: Path) -> dict[str, dict[str, object]]:
    if not path.is_file():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid existing BIS manifest: {error}") from error
    if not isinstance(document, dict) or not isinstance(document.get("resources"), list):
        raise ValueError("existing BIS manifest lacks resources")
    resources: dict[str, dict[str, object]] = {}
    for item in document["resources"]:
        if not isinstance(item, dict) or not isinstance(item.get("resource_id"), str):
            raise ValueError("existing BIS manifest has an invalid resource")
        resource_id = str(item["resource_id"])
        if resource_id in resources:
            raise ValueError("existing BIS manifest has duplicate resource IDs")
        resources[resource_id] = item
    return resources


def _hash_file(path: Path, maximum_bytes: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            total += len(chunk)
            if total > maximum_bytes:
                raise ValueError(f"existing BIS file exceeds size contract: {path}")
            digest.update(chunk)
    return digest.hexdigest(), total


def _content_range_start(value: str) -> int | None:
    match = re.fullmatch(r"bytes\s+(\d+)-\d+/(?:\d+|\*)", value.strip(), re.I)
    return int(match.group(1)) if match is not None else None


def _stream_download(
    client: httpx.Client,
    resource: Resource,
    raw_path: Path,
) -> dict[str, object]:
    _validate_url(resource.url)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    partial = raw_path.with_suffix(raw_path.suffix + ".part")
    partial_bytes = partial.stat().st_size if partial.is_file() else 0
    if partial_bytes > resource.maximum_bytes:
        raise ValueError(f"partial BIS file exceeds size contract: {partial}")
    headers = {"Range": f"bytes={partial_bytes}-"} if partial_bytes else {}
    with client.stream("GET", resource.url, headers=headers) as response:
        response.raise_for_status()
        if response.url.host not in ALLOWED_HOSTS:
            raise ValueError(f"BIS redirect left allowed hosts: {response.url}")
        append = False
        if partial_bytes and response.status_code == 206:
            start = _content_range_start(response.headers.get("Content-Range", ""))
            if start != partial_bytes:
                raise ValueError("BIS range response does not resume at the requested byte")
            append = True
        elif partial_bytes and response.status_code != 200:
            raise ValueError(f"unexpected BIS resume status: {response.status_code}")
        initial = partial_bytes if append else 0
        declared = response.headers.get("Content-Length")
        if declared is not None:
            try:
                declared_total = initial + int(declared)
            except ValueError as error:
                raise ValueError("invalid BIS Content-Length") from error
            if declared_total > resource.maximum_bytes:
                raise ValueError(
                    f"BIS response exceeds size contract for {resource.resource_id}"
                )
        total = initial
        mode = "ab" if append else "wb"
        with partial.open(mode) as handle:
            for chunk in response.iter_bytes(chunk_size=CHUNK_BYTES):
                total += len(chunk)
                if total > resource.maximum_bytes:
                    raise ValueError(
                        f"BIS response exceeds size contract for {resource.resource_id}"
                    )
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        partial.replace(raw_path)
        return {
            "final_url": str(response.url),
            "content_type": response.headers.get("Content-Type", ""),
            "etag": response.headers.get("ETag", ""),
            "last_modified": response.headers.get("Last-Modified", ""),
            "bytes": total,
        }


def _validate_content(resource: Resource, raw_path: Path) -> None:
    with raw_path.open("rb") as handle:
        prefix = handle.read(min(resource.maximum_bytes, MAX_HTML_BYTES))
    if resource.kind == "html":
        lowered = prefix.lower()
        if b"<html" not in lowered and b"<!doctype html" not in lowered:
            raise ValueError(f"BIS HTML signature absent: {resource.resource_id}")
        for marker in resource.required_markers:
            if marker.lower() not in lowered:
                raise ValueError(
                    f"BIS HTML required marker absent for {resource.resource_id}: "
                    f"{marker.decode(errors='replace')}"
                )
    elif resource.kind == "pdf":
        if not prefix.startswith(b"%PDF-"):
            raise ValueError(f"BIS PDF signature absent: {resource.resource_id}")
    elif resource.kind == "zip":
        if not zipfile.is_zipfile(raw_path):
            raise ValueError(f"BIS ZIP signature absent: {resource.resource_id}")
    else:
        raise ValueError(f"unknown BIS resource kind: {resource.kind}")


def _zip_inventory(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if not 1 <= len(infos) <= MAX_ZIP_MEMBERS:
            raise ValueError(f"BIS ZIP member count outside contract: {len(infos)}")
        names: list[str] = []
        total = 0
        for info in infos:
            member = PurePosixPath(info.filename)
            mode = (info.external_attr >> 16) & 0o170000
            ratio = info.file_size / max(info.compress_size, 1)
            if (
                member.is_absolute()
                or ".." in member.parts
                or info.flag_bits & 0x1
                or mode == stat.S_IFLNK
            ):
                raise ValueError(f"unsafe BIS ZIP member: {info.filename!r}")
            if info.file_size > MAX_ZIP_MEMBER_BYTES:
                raise ValueError(f"oversized BIS ZIP member: {info.filename!r}")
            if ratio > MAX_COMPRESSION_RATIO:
                raise ValueError(f"suspicious BIS ZIP compression ratio: {info.filename!r}")
            total += info.file_size
            names.append(info.filename)
        if total > MAX_ZIP_UNCOMPRESSED_BYTES:
            raise ValueError("BIS ZIP exceeds uncompressed size contract")
        if len(names) != len(set(names)):
            raise ValueError("BIS ZIP contains duplicate member names")
    names.sort()
    return {
        "member_count": len(names),
        "uncompressed_bytes": total,
        "archive_extracted": False,
        "members": names,
        "members_sha256": _sha256("\n".join(names).encode()),
    }


def _archive_copy(raw_path: Path, archive_path: Path, expected_sha: str) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if archive_path.is_file():
        actual, _ = _hash_file(archive_path, raw_path.stat().st_size)
        if actual != expected_sha:
            raise ValueError(f"content-addressed BIS archive hash mismatch: {archive_path}")
        return
    temporary = archive_path.with_suffix(archive_path.suffix + ".tmp")
    digest = hashlib.sha256()
    with raw_path.open("rb") as source, temporary.open("wb") as destination:
        while chunk := source.read(CHUNK_BYTES):
            digest.update(chunk)
            destination.write(chunk)
        destination.flush()
        os.fsync(destination.fileno())
    if digest.hexdigest() != expected_sha:
        raise ValueError(f"BIS source changed while archiving: {raw_path}")
    temporary.replace(archive_path)


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def run_download(
    output_dir: Path,
    *,
    download_gli: bool,
    download_lbs: bool,
    refresh: bool,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, object]:
    resources = [*BASE_RESOURCES]
    if download_gli:
        resources.append(GLI_BULK)
    if download_lbs:
        resources.append(LBS_BULK)
    manifest_path = output_dir / "manifest.json"
    prior = _load_prior_manifest(manifest_path)
    checked_at = _utc_now()
    records: list[dict[str, object]] = []
    headers = {"User-Agent": f"fx-portfolio-system/{PROGRAM_VERSION}"}
    with httpx.Client(
        timeout=120,
        follow_redirects=True,
        trust_env=False,
        headers=headers,
        transport=transport,
    ) as client:
        for resource in resources:
            raw_path = output_dir / "raw" / resource.raw_name
            previous = prior.get(resource.resource_id)
            reused = False
            response_metadata: dict[str, object]
            if raw_path.is_file() and not refresh:
                if previous is None or not isinstance(previous.get("sha256"), str):
                    raise ValueError(
                        f"cannot reuse BIS raw file without prior SHA evidence: {raw_path}"
                    )
                digest, size = _hash_file(raw_path, resource.maximum_bytes)
                if digest != previous["sha256"]:
                    raise ValueError(f"reused BIS raw file SHA mismatch: {raw_path}")
                response_metadata = {
                    "final_url": previous.get("final_url", resource.url),
                    "content_type": previous.get("content_type", ""),
                    "etag": previous.get("etag", ""),
                    "last_modified": previous.get("last_modified", ""),
                    "bytes": size,
                }
                retrieved_at = previous.get("retrieved_at_utc", "")
                reused = True
            else:
                response_metadata = _stream_download(client, resource, raw_path)
                digest, size = _hash_file(raw_path, resource.maximum_bytes)
                if size != response_metadata["bytes"]:
                    raise ValueError(f"BIS streamed byte count mismatch: {resource.resource_id}")
                retrieved_at = checked_at
            _validate_content(resource, raw_path)
            suffix = "".join(Path(resource.raw_name).suffixes)
            archive_path = output_dir / "archive" / f"{digest}{suffix}"
            _archive_copy(raw_path, archive_path, digest)
            zip_metadata: dict[str, object] = {}
            if resource.kind == "zip":
                zip_metadata = _zip_inventory(raw_path)
            records.append(
                {
                    "resource_id": resource.resource_id,
                    "source_url": resource.url,
                    "final_url": response_metadata["final_url"],
                    "kind": resource.kind,
                    "raw_path": str(raw_path),
                    "archive_path": str(archive_path),
                    "bytes": size,
                    "sha256": digest,
                    "content_type": response_metadata["content_type"],
                    "etag": response_metadata["etag"],
                    "last_modified": response_metadata["last_modified"],
                    "retrieved_at_utc": retrieved_at,
                    "verified_at_utc": checked_at,
                    "reused_verified": reused,
                    **zip_metadata,
                }
            )
    result: dict[str, object] = {
        "schema_version": 1,
        "program_version": PROGRAM_VERSION,
        "generated_at_utc": checked_at,
        "provider": PROVIDER,
        "source_hosts": sorted(ALLOWED_HOSTS),
        "vintage_model": "official_current_snapshot_not_release_archive",
        "current_vintage_only": True,
        "resource_count": len(records),
        "download_gli_bulk": download_gli,
        "download_lbs_bulk": download_lbs,
        "downloaded_bytes": sum(int(record["bytes"]) for record in records),
        "resources": records,
        "strict_pit_eligible": False,
        "pit_blocker": "current_snapshot_without_release_vintage_history",
        "is_fx_order_flow": False,
        "is_directional_alpha": False,
        "allowed_research_role": "low_frequency_global_liquidity_and_banking_state_candidate",
        "factor_registry_modified": False,
        "outcome_evaluations_added": 0,
    }
    _atomic_json(manifest_path, result)
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--download-gli", action="store_true")
    parser.add_argument("--download-lbs", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run_download(
            args.output_dir,
            download_gli=args.download_gli,
            download_lbs=args.download_lbs,
            refresh=args.refresh,
        )
    except (httpx.HTTPError, OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"BIS GLI/LBS download failed: {error}", file=sys.stderr)
        return 1
    print(
        f"resources={result['resource_count']} bytes={result['downloaded_bytes']} "
        f"output={args.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
