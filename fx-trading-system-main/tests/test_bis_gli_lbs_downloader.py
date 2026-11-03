from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path

import httpx
import pytest

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "download_bis_gli_lbs.py"
SPEC = importlib.util.spec_from_file_location("bis_gli_lbs_downloader", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
downloader = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = downloader
SPEC.loader.exec_module(downloader)


def test_lbs_limit_admits_observed_official_flat_csv_without_extracting() -> None:
    assert downloader.MAX_ZIP_MEMBER_BYTES >= 17_672_650_002
    assert downloader.MAX_ZIP_UNCOMPRESSED_BYTES >= 17_672_650_002
    assert downloader.MAX_COMPRESSION_RATIO >= 50


def _zip_payload(*, unsafe: bool = False) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("data.csv", "TIME_PERIOD,OBS_VALUE\n2025-Q1,1\n")
        archive.writestr("../escape.csv" if unsafe else "codes.csv", "code,label\nA,All\n")
    return output.getvalue()


def _payloads(*, unsafe_gli: bool = False) -> dict[str, bytes]:
    return {
        downloader.BASE_RESOURCES[0].url: (
            b"<!doctype html><html>gli_methodology.pdf /bulkdownload</html>"
        ),
        downloader.BASE_RESOURCES[1].url: (
            b"<!doctype html><html>bankstatsguide.pdf "
            b"ibs_breakrev_summary.pdf /bulkdownload</html>"
        ),
        downloader.BASE_RESOURCES[2].url: (
            b"<!doctype html><html>WS_GLI_csv_flat.zip "
            b"WS_LBS_D_PUB_csv_flat.zip</html>"
        ),
        downloader.BASE_RESOURCES[3].url: b"%PDF-1.7 GLI methodology",
        downloader.BASE_RESOURCES[4].url: b"%PDF-1.7 LBS guide",
        downloader.BASE_RESOURCES[5].url: b"%PDF-1.7 break revision summary",
        downloader.GLI_BULK.url: _zip_payload(unsafe=unsafe_gli),
        downloader.LBS_BULK.url: _zip_payload(),
    }


def _transport(payloads: dict[str, bytes]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = payloads.get(str(request.url))
        if payload is None:
            raise AssertionError(f"unexpected request: {request.url}")
        if request.headers.get("Range"):
            raise AssertionError("unexpected range request")
        kind = "application/zip" if str(request.url).endswith(".zip") else "text/html"
        if str(request.url).endswith(".pdf"):
            kind = "application/pdf"
        return httpx.Response(
            200,
            content=payload,
            headers={
                "Content-Type": kind,
                "Content-Length": str(len(payload)),
                "ETag": '"fixture"',
            },
        )

    return httpx.MockTransport(handler)


def test_default_archives_official_current_snapshot_contract(tmp_path: Path) -> None:
    result = downloader.run_download(
        tmp_path,
        download_gli=False,
        download_lbs=False,
        refresh=False,
        transport=_transport(_payloads()),
    )

    assert result["resource_count"] == 6
    assert result["current_vintage_only"] is True
    assert result["vintage_model"] == "official_current_snapshot_not_release_archive"
    assert result["strict_pit_eligible"] is False
    assert result["is_fx_order_flow"] is False
    assert result["is_directional_alpha"] is False
    assert result["factor_registry_modified"] is False
    assert result["outcome_evaluations_added"] == 0
    assert result["download_gli_bulk"] is False
    assert result["download_lbs_bulk"] is False
    for record in result["resources"]:
        raw_path = Path(record["raw_path"])
        archive_path = Path(record["archive_path"])
        assert raw_path.is_file()
        assert archive_path.is_file()
        assert hashlib.sha256(raw_path.read_bytes()).hexdigest() == record["sha256"]
        assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == record["sha256"]
    assert json.loads((tmp_path / "manifest.json").read_text())["resource_count"] == 6


def test_optional_bulk_zips_get_safe_member_inventory(tmp_path: Path) -> None:
    result = downloader.run_download(
        tmp_path,
        download_gli=True,
        download_lbs=True,
        refresh=False,
        transport=_transport(_payloads()),
    )

    assert result["resource_count"] == 8
    bulk = [record for record in result["resources"] if record["kind"] == "zip"]
    assert {record["resource_id"] for record in bulk} == {
        "gli_bulk_flat_csv",
        "lbs_bulk_flat_csv",
    }
    assert all(record["member_count"] == 2 for record in bulk)
    assert all(record["members"] == ["codes.csv", "data.csv"] for record in bulk)
    assert all(len(record["members_sha256"]) == 64 for record in bulk)


def test_existing_raw_is_reused_only_when_manifest_sha_matches(tmp_path: Path) -> None:
    downloader.run_download(
        tmp_path,
        download_gli=False,
        download_lbs=False,
        refresh=False,
        transport=_transport(_payloads()),
    )
    (tmp_path / "raw" / "gli_topic.html").write_bytes(b"corrupted")

    def no_network(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"network should not be reached: {request.url}")

    with pytest.raises(ValueError, match="reused BIS raw file SHA mismatch"):
        downloader.run_download(
            tmp_path,
            download_gli=False,
            download_lbs=False,
            refresh=False,
            transport=httpx.MockTransport(no_network),
        )


def test_partial_bulk_download_resumes_with_range(tmp_path: Path) -> None:
    payloads = _payloads()
    downloader.run_download(
        tmp_path,
        download_gli=False,
        download_lbs=False,
        refresh=False,
        transport=_transport(payloads),
    )
    payload = payloads[downloader.GLI_BULK.url]
    split = len(payload) // 2
    partial = tmp_path / "raw" / "WS_GLI_csv_flat.zip.part"
    partial.write_bytes(payload[:split])
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert str(request.url) == downloader.GLI_BULK.url
        assert request.headers["Range"] == f"bytes={split}-"
        remainder = payload[split:]
        return httpx.Response(
            206,
            content=remainder,
            headers={
                "Content-Type": "application/zip",
                "Content-Length": str(len(remainder)),
                "Content-Range": f"bytes {split}-{len(payload) - 1}/{len(payload)}",
            },
        )

    result = downloader.run_download(
        tmp_path,
        download_gli=True,
        download_lbs=False,
        refresh=False,
        transport=httpx.MockTransport(handler),
    )

    assert len(requests) == 1
    assert (tmp_path / "raw" / "WS_GLI_csv_flat.zip").read_bytes() == payload
    assert result["resource_count"] == 7


def test_unsafe_bulk_member_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsafe BIS ZIP member"):
        downloader.run_download(
            tmp_path,
            download_gli=True,
            download_lbs=False,
            refresh=False,
            transport=_transport(_payloads(unsafe_gli=True)),
        )
