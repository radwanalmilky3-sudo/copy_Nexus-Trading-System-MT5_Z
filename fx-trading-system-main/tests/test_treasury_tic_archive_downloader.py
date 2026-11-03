from __future__ import annotations

import csv
import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path

import httpx
import pytest

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "download_treasury_tic_archives.py"
SPEC = importlib.util.spec_from_file_location("treasury_tic_archives", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
downloader = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = downloader
SPEC.loader.exec_module(downloader)

PAGE = (
    b'<html><body><a href="https://www.treasury.gov/resource-center/'
    b'data-chart-center/tic/Documents/ticrel_20180919.zip">09/18/2018</a> '
    b'TIC Data for July 2018<br><a href="https://www.treasury.gov/resource-center/'
    b'data-chart-center/tic/Documents/ticrel_20251017.zip">10/17/2025</a> '
    b'TIC Data for August 2025 (released 11-18-2025)<br></body></html>'
)


def _zip_payload(
    *,
    npr: bool = True,
    npr_suffix: str = "csv",
    unsafe: bool = False,
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if npr:
            archive.writestr(
                f"npr_history.{npr_suffix}", "date,value\n2025-08,1\n"
            )
        archive.writestr("mfh.txt", "test holdings\n")
        archive.writestr("bctype_history.txt", "test claims\n")
        if unsafe:
            archive.writestr("../escape.txt", "bad")
    return output.getvalue()


def _transport(payload: bytes) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == downloader.ARCHIVE_PAGE:
            return httpx.Response(200, content=PAGE)
        if url == downloader.DESCRIPTION_URL:
            return httpx.Response(200, content=b"official descriptions")
        if "ticrel_" in url:
            return httpx.Response(200, content=payload)
        raise AssertionError(url)

    return httpx.MockTransport(handler)


def test_release_catalog_preserves_filename_mismatch_and_shutdown_exception() -> None:
    releases = downloader.parse_release_page(PAGE, start_year=2018, end_year=2025)
    assert len(releases) == 2
    old, shutdown = releases
    assert old.anchor_date.isoformat() == "2018-09-18"
    assert old.file_date == "20180919"
    assert old.reference_month == "2018-07-01"
    assert old.availability_basis_date.isoformat() == "2018-09-19"
    assert old.availability_basis_evidence == "later_official_zip_file_date"
    assert old.available_time == "2018-09-20T00:00:00Z"
    assert shutdown.anchor_date.isoformat() == "2025-10-17"
    assert shutdown.actual_release_date.isoformat() == "2025-11-18"
    assert shutdown.available_time == "2025-11-19T00:00:00Z"
    assert (
        shutdown.release_date_evidence
        == "official_archive_explicit_actual_release_exception"
    )


def test_download_archives_zip_members_but_keeps_pit_gate_closed(tmp_path: Path) -> None:
    manifest = downloader.run_download(
        tmp_path,
        start_year=2018,
        end_year=2025,
        download_zips=True,
        refresh=False,
        delay_seconds=0,
        transport=_transport(_zip_payload()),
    )

    assert manifest["release_count"] == 2
    assert manifest["downloaded_count"] == 2
    assert manifest["downloaded_bytes"] > 0
    assert manifest["strict_pit_eligible"] is False
    assert manifest["is_treasury_basis"] is False
    assert manifest["is_fx_order_flow"] is False
    assert manifest["factor_registry_modified"] is False
    assert manifest["outcome_evaluations_added"] == 0
    assert all(Path(item["raw_path"]).is_file() for item in manifest["downloads"])
    assert all(Path(item["archive_path"]).is_file() for item in manifest["downloads"])
    assert all("npr_history.csv" in item["members_of_interest"] for item in manifest["downloads"])

    rows = list(csv.DictReader((tmp_path / "release_catalog.csv").open()))
    assert len(rows) == 2
    shutdown = next(row for row in rows if row["anchor_date"] == "2025-10-17")
    assert shutdown["actual_release_date"] == "2025-11-18"
    assert shutdown["availability_basis_date"] == "2025-11-18"
    assert (
        shutdown["availability_basis_evidence"]
        == "official_archive_explicit_actual_release_exception"
    )
    assert shutdown["strict_pit_eligible"] == "False"
    assert (
        shutdown["pit_blocker"]
        == "series_parser_and_cross_release_revision_audit_pending"
    )
    assert json.loads((tmp_path / "manifest.json").read_text())["release_count"] == 2


def test_zip_contract_rejects_path_traversal_and_missing_history(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsafe TIC ZIP member"):
        downloader._safe_members(_zip_payload(unsafe=True))
    with pytest.raises(ValueError, match="npr_history member absent"):
        downloader.run_download(
            tmp_path,
            start_year=2018,
            end_year=2025,
            download_zips=True,
            refresh=False,
            delay_seconds=0,
            transport=_transport(_zip_payload(npr=False)),
        )


def test_download_accepts_historical_npr_text_variant(tmp_path: Path) -> None:
    manifest = downloader.run_download(
        tmp_path,
        start_year=2018,
        end_year=2025,
        download_zips=True,
        refresh=False,
        delay_seconds=0,
        transport=_transport(_zip_payload(npr_suffix="txt")),
    )

    assert manifest["downloaded_count"] == 2
    assert all(
        "npr_history.txt" in item["members_of_interest"]
        for item in manifest["downloads"]
    )
