from __future__ import annotations

import importlib.util
import io
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from openpyxl import Workbook

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "download_cftc_weekly_swaps.py"
SPEC = importlib.util.spec_from_file_location("cftc_weekly_swaps_downloader", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
downloader = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = downloader
SPEC.loader.exec_module(downloader)


def _archive_html(link: str) -> bytes:
    return (
        "<html><body>CFTC archive contains previous publications. "
        "On October 17, 2018 FX swaps were first included. "
        "The CFTC did not issue a Weekly Swaps Report during this period. "
        f'<a href="{link}">24</a></body></html>'
    ).encode()


def _workbook_payload(
    edition: date = date(2018, 10, 24),
    reporting_period: date = date(2018, 10, 12),
    *,
    new_schema: bool = False,
    singular_exotic: bool = False,
    bad_total: bool = False,
) -> bytes:
    workbook = Workbook()
    contents = workbook.active
    contents.title = "Table of Contents"
    contents.append(["CFTC Swaps Report"])
    contents.append(["Release Date:", edition])
    contents.append(["Reporting Period As Of:", reporting_period])
    if new_schema and singular_exotic:
        raise ValueError("test fixture schema flags are mutually exclusive")
    if new_schema:
        headers = downloader.NEW_PRODUCT_HEADERS
    elif singular_exotic:
        headers = downloader.OLD_PRODUCT_HEADERS_SINGULAR_EXOTIC
    else:
        headers = downloader.OLD_PRODUCT_HEADERS
    for table_id in downloader.TABLES:
        sheet = workbook.create_sheet(table_id)
        sheet.append(headers)
        product_count = len(headers) - 2
        for row_number, label in enumerate(downloader.EXPECTED_ROW_LABELS):
            components = [row_number + index + 1 for index in range(product_count)]
            total = sum(components) + (
                3 if bad_total and table_id == "19b" and label == "EUR" else 0
            )
            sheet.append([label, *components, total])
        sheet.append(["1 Currency pairs having USD on one side. Other footnotes."])
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_archive_discovery_is_frozen_and_refuses_non_cftc_links() -> None:
    path = (
        "/sites/default/files/idc/groups/public/%40swapsreport/documents/file/"
        "CFTC_Swaps_Report_10_24_2018.xlsx"
    )
    reports = downloader.discover_reports(_archive_html(path), expected_counts={2018: 1})

    assert len(reports) == 1
    assert reports[0].edition_date == date(2018, 10, 24)
    assert reports[0].url == f"https://www.cftc.gov{path}"
    with pytest.raises(ValueError, match="coverage drifted"):
        downloader.discover_reports(_archive_html(path), expected_counts={2018: 2})
    with pytest.raises(ValueError, match="non-canonical CFTC URL"):
        downloader.discover_reports(
            _archive_html("https://example.com/CFTC_Swaps_Report_10_24_2018.xlsx"),
            expected_counts=None,
        )


def test_workbook_parser_preserves_old_schema_and_has_no_directional_claims() -> None:
    report = downloader.ReportLink(
        date(2018, 10, 24),
        "https://www.cftc.gov/sites/default/files/CFTC_Swaps_Report_10_24_2018.xlsx",
    )
    rows = downloader.parse_workbook(
        report,
        _workbook_payload(),
        retrieved_at=datetime(2026, 7, 16, tzinfo=UTC),
    )

    assert len(rows) == 3 * 10 * 6
    assert {row["currency"] for row in rows} == downloader.DISCLOSED_CURRENCIES
    assert {row["product_category"] for row in rows} == {
        "swaps_and_forwards",
        "ndf",
        "options",
        "exotics",
        "cross_currency",
        "total",
    }
    assert not any(row["strict_pit_eligible"] for row in rows)
    assert all("no_direction" in row["currency_pair_bucket"] for row in rows)
    assert all("original_publication" in row["value_vintage_quality"] for row in rows)
    assert {row["product_schema_regime"] for row in rows} == {
        "separate_exotics_cross_currency"
    }
    assert rows[0]["availability_time"] == "2018-10-25T04:00:00Z"


def test_new_schema_does_not_reconstruct_exotics_or_cross_currency() -> None:
    report = downloader.ReportLink(
        date(2023, 1, 2),
        "https://www.cftc.gov/sites/default/files/CFTC_Swaps_Report_01_02_2023.xlsx",
    )
    rows = downloader.parse_workbook(
        report,
        _workbook_payload(
            date(2023, 1, 2),
            date(2022, 12, 16),
            new_schema=True,
        ),
        retrieved_at=datetime(2026, 7, 16, tzinfo=UTC),
    )

    assert len(rows) == 3 * 10 * 5
    categories = {row["product_category"] for row in rows}
    assert "other_includes_cross_currency_and_exotics" in categories
    assert "exotics" not in categories
    assert "cross_currency" not in categories
    assert {row["methodology_regime"] for row in rows} == {
        "post_2022_12_09_methodology_improvement"
    }
    assert {row["product_schema_regime"] for row in rows} == {
        "merged_other_includes_cross_currency_and_exotics"
    }


def test_one_edition_singular_exotic_header_remains_a_separate_product() -> None:
    report = downloader.ReportLink(
        date(2022, 12, 19),
        "https://www.cftc.gov/sites/default/files/CFTC_Swaps_Report_12_19_2022.xlsx",
    )
    rows = downloader.parse_workbook(
        report,
        _workbook_payload(
            date(2022, 12, 19),
            date(2022, 12, 2),
            singular_exotic=True,
        ),
        retrieved_at=datetime(2026, 7, 16, tzinfo=UTC),
    )

    assert "exotics" in {row["product_category"] for row in rows}
    assert {row["methodology_regime"] for row in rows} == {
        "post_2022_12_09_methodology_improvement"
    }


def test_workbook_parser_fails_when_table_total_does_not_add_up() -> None:
    report = downloader.ReportLink(
        date(2018, 10, 24),
        "https://www.cftc.gov/sites/default/files/CFTC_Swaps_Report_10_24_2018.xlsx",
    )
    with pytest.raises(ValueError, match="Total does not add up"):
        downloader.parse_workbook(
            report,
            _workbook_payload(bad_total=True),
            retrieved_at=datetime(2026, 7, 16, tzinfo=UTC),
        )


def test_appropriations_catch_up_uses_retrieval_not_edition_date() -> None:
    retrieved = datetime(2026, 7, 16, 3, 4, 5, tzinfo=UTC)
    report = downloader.ReportLink(
        date(2025, 10, 6),
        "https://www.cftc.gov/sites/default/files/CFTC_Swaps_Report_10_06_2025.xlsx",
    )
    rows = downloader.parse_workbook(
        report,
        _workbook_payload(
            date(2025, 10, 6),
            date(2025, 9, 19),
            new_schema=True,
        ),
        retrieved_at=retrieved,
    )

    assert {row["availability_time"] for row in rows} == {"2026-07-16T03:04:05Z"}
    assert {row["release_date_quality"] for row in rows} == {
        "edition_label_not_actual_catch_up_publication_date"
    }


def _download_fixture(tmp_path: Path, *, refresh: bool = False) -> Path:
    workbook_url = (
        "https://www.cftc.gov/sites/default/files/"
        "CFTC_Swaps_Report_10_24_2018.xlsx"
    )
    responses = {
        downloader.ARCHIVE_URL: (
            _archive_html("/sites/default/files/CFTC_Swaps_Report_10_24_2018.xlsx"),
            "text/html",
        ),
        downloader.RELEASE_SCHEDULE_URL: (
            b"CFTC released at 3:30 p.m. Eastern time on Monday; processing was "
            b"interrupted from October 1 and will resume publication.",
            "text/html",
        ),
        downloader.EXPLANATORY_NOTES_URL: (
            b"CFTC Gross notional outstanding represents. Transaction dollar volume "
            b"represents. Transaction ticket volume represents.",
            "text/html",
        ),
        downloader.WEB_POLICY_URL: (
            b"CFTC Government information at the CFTC website is in the public domain.",
            "text/html",
        ),
        workbook_url: (
            _workbook_payload(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        payload, content_type = responses[str(request.url)]
        return httpx.Response(200, content=payload, headers={"Content-Type": content_type})

    output = tmp_path / "weekly_swaps"
    manifest = downloader.download(
        output,
        refresh=refresh,
        delay=0,
        retries=0,
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
        retrieved_at=datetime(2026, 7, 16, tzinfo=UTC),
        expected_counts={2018: 1},
    )
    assert manifest["report_count"] == 1
    assert manifest["normalized_rows"] == 180
    assert manifest["strict_pit_eligible"] is False
    assert manifest["missing_core_currency_disclosure"] == ["NZD"]
    return output


@pytest.mark.parametrize("tamper", ["cache", "normalized", "manifest_sidecar"])
def test_prior_run_hash_gates_refuse_tampering(tmp_path: Path, tamper: str) -> None:
    output = _download_fixture(tmp_path)
    if tamper == "cache":
        target = output / "raw/cache/weekly_swaps_20181024.xlsx"
        target.write_bytes(target.read_bytes() + b"tampered")
        match = "cached source hash verification failed"
    elif tamper == "normalized":
        target = output / "cftc_weekly_swaps_fx_activity.csv"
        target.write_bytes(target.read_bytes() + b"tampered")
        match = "normalized Weekly Swaps output hash"
    else:
        target = output / "cftc_weekly_swaps_manifest.sha256"
        target.write_text("0" * 64 + "\n", encoding="ascii")
        match = "manifest SHA-256 verification failed"

    with pytest.raises(ValueError, match=match):
        downloader.download(
            output,
            delay=0,
            retries=0,
            transport=httpx.MockTransport(lambda request: httpx.Response(500)),
            sleep=lambda _: None,
            retrieved_at=datetime(2026, 7, 16, tzinfo=UTC),
            expected_counts={2018: 1},
        )


def test_manifest_has_explicit_non_pit_and_archive_gap_disclosures(tmp_path: Path) -> None:
    output = _download_fixture(tmp_path)
    manifest = json.loads((output / "cftc_weekly_swaps_manifest.json").read_text())

    combined = " ".join(manifest["known_archive_issues"])
    assert "2023-01-30" in combined
    assert "2024-02-12" in combined and "2024-09-30" in combined
    assert "2025-10-06" in combined and "actual catch-up" in combined
    assert any(
        "No row is a profitability result, alpha estimate or trading approval" in limitation
        for limitation in manifest["research_limitations"]
    )


def test_refresh_can_rebuild_an_orphan_partial_cache(tmp_path: Path) -> None:
    orphan = tmp_path / "weekly_swaps/raw/cache/orphan.xlsx"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"partial")

    output = _download_fixture(tmp_path, refresh=True)
    manifest = json.loads((output / "cftc_weekly_swaps_manifest.json").read_text())

    assert manifest["report_count"] == 1
    assert not orphan.exists()


def test_retry_after_zero_still_uses_polite_backoff() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, content=b"CFTC evidence")

    payload, _ = downloader._fetch(
        downloader.ARCHIVE_URL,
        timeout=1,
        retries=1,
        maximum_bytes=1024,
        transport=httpx.MockTransport(handler),
        sleep=delays.append,
    )
    assert payload == b"CFTC evidence"
    assert delays == [0.75]
