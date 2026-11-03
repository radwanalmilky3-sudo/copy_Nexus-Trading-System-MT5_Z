#!/usr/bin/env python3
"""Download one HTTPS object with resumable, verified byte ranges."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final
from urllib.parse import urlparse

import httpx

RANGE_PATTERN: Final = re.compile(r"bytes (\d+)-(\d+)/(\d+)")
SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class Segment:
    index: int
    start: int
    end: int

    @property
    def size(self) -> int:
        return self.end - self.start + 1


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_url(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
    ):
        raise ValueError("URL must be an absolute HTTPS URL without credentials or a custom port")
    return value


def _object_metadata(url: str, *, timeout: float) -> tuple[int, str]:
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        response = client.head(url)
        response.raise_for_status()
        if response.url.scheme != "https":
            raise ValueError("redirect downgraded the download URL from HTTPS")
        length = response.headers.get("content-length")
        if length is None or not length.isdigit() or int(length) <= 0:
            raise ValueError("server did not provide a positive Content-Length")
        if response.headers.get("accept-ranges", "").lower() != "bytes":
            raise ValueError("server does not advertise byte-range support")
        return int(length), response.headers.get("etag", "")


def _segments(total_bytes: int, connections: int) -> tuple[Segment, ...]:
    if connections < 1:
        raise ValueError("connections must be positive")
    width, remainder = divmod(total_bytes, connections)
    output: list[Segment] = []
    start = 0
    for index in range(connections):
        size = width + (1 if index < remainder else 0)
        output.append(Segment(index=index, start=start, end=start + size - 1))
        start += size
    return tuple(output)


def _load_or_create_state(
    state_path: Path,
    *,
    url: str,
    total_bytes: int,
    etag: str,
    connections: int,
) -> tuple[Segment, ...]:
    expected_segments = _segments(total_bytes, connections)
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(f"cannot read range-download state: {state_path}") from error
        if (
            not isinstance(state, dict)
            or state.get("url") != url
            or state.get("bytes") != total_bytes
            or state.get("etag", "") != etag
            or state.get("segments") != [asdict(segment) for segment in expected_segments]
        ):
            raise ValueError("existing range-download state does not match the remote object")
        return expected_segments
    _atomic_json(
        state_path,
        {
            "schema_version": 1,
            "url": url,
            "bytes": total_bytes,
            "etag": etag,
            "segments": [asdict(segment) for segment in expected_segments],
        },
    )
    return expected_segments


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    if response is not None:
        retry_after = response.headers.get("retry-after", "").strip()
        if retry_after.isdigit():
            return min(60.0, max(float(retry_after), 0.5 * (2**attempt)))
    return min(30.0, 0.5 * (2**attempt))


def _download_segment(
    *,
    url: str,
    segment: Segment,
    path: Path,
    chunk_bytes: int,
    timeout: float,
    retries: int,
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        current = path.stat().st_size if path.exists() else 0
        if current > segment.size:
            raise ValueError(f"segment {segment.index} is larger than its frozen range")
        if current == segment.size:
            return current
        request_start = segment.start + current
        request_end = min(segment.end, request_start + chunk_bytes - 1)
        for attempt in range(retries + 1):
            response: httpx.Response | None = None
            try:
                with httpx.Client(follow_redirects=True, timeout=timeout) as client:
                    with client.stream(
                        "GET",
                        url,
                        headers={"Range": f"bytes={request_start}-{request_end}"},
                    ) as response:
                        if response.status_code != 206:
                            response.raise_for_status()
                            raise ValueError(
                                "segment "
                                f"{segment.index}: expected HTTP 206, got {response.status_code}"
                            )
                        match = RANGE_PATTERN.fullmatch(
                            response.headers.get("content-range", "")
                        )
                        if match is None:
                            raise ValueError(f"segment {segment.index}: invalid Content-Range")
                        start, end, _ = (int(value) for value in match.groups())
                        if start != request_start or end != request_end:
                            raise ValueError(
                                f"segment {segment.index}: server returned unexpected Content-Range"
                            )
                        with path.open("ab") as handle:
                            for chunk in response.iter_bytes():
                                handle.write(chunk)
                actual = path.stat().st_size
                expected = current + request_end - request_start + 1
                if actual != expected:
                    raise ValueError(
                        f"segment {segment.index}: expected {expected} bytes, got {actual}"
                    )
                break
            except (httpx.HTTPError, OSError, ValueError) as error:
                if attempt == retries:
                    raise ValueError(
                        f"segment {segment.index} failed after {retries + 1} attempts"
                    ) from error
                time.sleep(_retry_delay(response, attempt))


def _assemble(parts_directory: Path, output: Path, segments: tuple[Segment, ...]) -> None:
    temporary = output.with_name(f".{output.name}.{os.getpid()}.assemble.tmp")
    try:
        with temporary.open("wb") as destination:
            for segment in segments:
                part = parts_directory / f"{segment.index:03d}.part"
                if not part.is_file() or part.stat().st_size != segment.size:
                    raise ValueError(f"segment {segment.index} is incomplete during assembly")
                with part.open("rb") as source:
                    shutil.copyfileobj(source, destination, length=8 * 1024 * 1024)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", type=_validate_url)
    parser.add_argument("output", type=Path)
    parser.add_argument("--sha256", dest="expected_sha256")
    parser.add_argument("--connections", type=int, default=8)
    parser.add_argument(
        "--chunk-bytes",
        type=int,
        default=8 * 1024 * 1024,
        help="maximum bytes per HTTP Range request within each resumable segment",
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--keep-parts", action="store_true")
    args = parser.parse_args(argv)
    if (
        args.connections < 1
        or args.chunk_bytes < 1
        or args.timeout <= 0
        or args.retries < 0
    ):
        parser.error(
            "connections, chunk-bytes, and timeout must be positive; retries cannot be negative"
        )
    expected_hash = (args.expected_sha256 or "").lower()
    if expected_hash and SHA256_PATTERN.fullmatch(expected_hash) is None:
        parser.error("--sha256 must be a lowercase SHA-256 digest")

    total_bytes, etag = _object_metadata(args.url, timeout=args.timeout)
    if args.output.is_file() and args.output.stat().st_size == total_bytes and expected_hash:
        if _sha256_file(args.output) == expected_hash:
            print(f"already verified: {args.output}")
            return 0
    parts_directory = args.output.with_name(f".{args.output.name}.ranges")
    state_path = parts_directory / "state.json"
    segments = _load_or_create_state(
        state_path,
        url=args.url,
        total_bytes=total_bytes,
        etag=etag,
        connections=args.connections,
    )
    with ThreadPoolExecutor(max_workers=args.connections) as executor:
        futures = {
            executor.submit(
                _download_segment,
                url=args.url,
                segment=segment,
                path=parts_directory / f"{segment.index:03d}.part",
                chunk_bytes=args.chunk_bytes,
                timeout=args.timeout,
                retries=args.retries,
            ): segment
            for segment in segments
        }
        for future in as_completed(futures):
            segment = futures[future]
            size = future.result()
            print(
                f"segment {segment.index + 1}/{len(segments)} complete: {size:,} bytes",
                flush=True,
            )
    _assemble(parts_directory, args.output, segments)
    if args.output.stat().st_size != total_bytes:
        raise ValueError("assembled output size does not match Content-Length")
    actual_hash = _sha256_file(args.output)
    if expected_hash and actual_hash != expected_hash:
        raise ValueError("assembled output SHA-256 does not match the expected digest")
    print(f"verified download: {args.output} sha256={actual_hash}")
    if not args.keep_parts:
        shutil.rmtree(parts_directory)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, httpx.HTTPError) as error:
        print(f"range download failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
