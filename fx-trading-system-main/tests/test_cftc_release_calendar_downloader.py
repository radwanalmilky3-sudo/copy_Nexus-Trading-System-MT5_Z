from __future__ import annotations

import calendar
import importlib.util
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from fx_system.cftc_release_calendar import (
    CFTCReleaseManifestError,
    load_cftc_release_calendar,
)

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "download_cftc_release_calendar.py"
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "cftc_release_calendar"
SPEC = importlib.util.spec_from_file_location("cftc_release_calendar_downloader", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
downloader = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = downloader
SPEC.loader.exec_module(downloader)


def _fixture(name: str) -> bytes:
    return (FIXTURE_ROOT / name).read_bytes()


def _annual_payload(year: int) -> bytes:
    """Create a complete offline annual page around the frozen exception dates."""

    current = date(year, 1, 1)
    releases: set[date] = set()
    while current.year == year:
        if current.weekday() == 4:
            releases.add(current)
        current += timedelta(days=1)

    required_originals = {
        original
        for _, original, _ in (
            *downloader.SHUTDOWN_2019_CATCHUP,
            *downloader.SHUTDOWN_2025_FINAL_TABLE,
        )
        if original.year == year
    }
    required_originals.update(
        original
        for original in downloader.ION_ACTUAL_BY_ORIGINAL_RELEASE
        if original.year == year
    )
    if year == 2021:
        required_originals.add(date(2021, 6, 18))
    if year == 2025:
        required_originals.add(date(2025, 1, 10))
        # The official tentative page schedules the post-Thanksgiving and
        # post-Christmas publications on Mondays.
        releases.difference_update({date(2025, 11, 28), date(2025, 12, 26)})
    releases.update(required_originals)

    rows: list[str] = []
    for month in range(1, 13):
        days = sorted(value.day for value in releases if value.month == month)
        cells = "".join(f"<td>{day:02d}</td>" for day in days)
        rows.append(f"<tr><td>{calendar.month_name[month]}</td>{cells}</tr>")
    return (
        "<!doctype html><html><body>"
        "<p>The Commitments of Traders reports are released at 3:30 p.m. Eastern time. "
        "The release usually includes data from the previous Tuesday. The following is a "
        "tentative schedule of releases. Federal holidays may delay release by one or two "
        "days.</p><table><tr><th>"
        f"{year}</th><th>Dates</th></tr>{''.join(rows)}</table>"
        "<p>*Delayed release date due to a Federal holiday.</p>"
        "</body></html>"
    ).encode()


def _transport() -> httpx.MockTransport:
    annual_by_url = {
        source.url: _annual_payload(source.year)
        for source in downloader.ANNUAL_SOURCES
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url in annual_by_url:
            return httpx.Response(200, content=annual_by_url[url])
        if url == downloader.SPECIAL_SOURCE.url:
            return httpx.Response(
                200,
                content=_fixture("historical_special_announcements.html"),
            )
        if url == downloader.SHUTDOWN_2019_SOURCE.url:
            return httpx.Response(200, content=_fixture("press_release_7864_19.html"))
        raise AssertionError(f"unexpected test URL {url}")

    return httpx.MockTransport(handler)


def test_offline_annual_fixture_preserves_tentative_markers() -> None:
    payload = _fixture("annual_2023.html")
    downloader._validate_annual_source(downloader.ANNUAL_SOURCES[7], payload)
    releases = downloader._parse_annual_release_dates(payload, 2023)

    assert len(releases) == 52
    assert (date(2023, 7, 7), "**") in releases
    assert (date(2023, 11, 13), "*") in releases
    assert (date(2023, 2, 3), "") in releases


def test_offline_exception_fixtures_support_only_the_claimed_mappings() -> None:
    special = _fixture("historical_special_announcements.html")
    press_release = _fixture("press_release_7864_19.html")

    downloader._validate_special_source(special)
    downloader._validate_shutdown_2019_source(press_release)

    broken = special.replace(
        b"Today, staff is issuing the Commitments of Traders report that was originally "
        b"scheduled to be published on February 17, 2023.",
        b"Publication timing was not stated.",
    )
    with pytest.raises(ValueError, match="ION actual-publication transcription"):
        downloader._validate_special_source(broken)


def test_calendar_keeps_tentative_announced_actual_and_derived_evidence_separate(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 16, 5, 0, tzinfo=UTC)
    calendar_path, manifest_path = downloader.download_calendar(
        tmp_path,
        refresh=True,
        transport=_transport(),
        now=now,
    )
    calendar_data = load_cftc_release_calendar(
        calendar_path,
        manifest_path=manifest_path,
        knowledge_cutoff=now,
    )

    shutdown_first = calendar_data.for_report_date("2018-12-24")
    assert shutdown_first.mapped_release_date == date(2019, 2, 1)
    assert shutdown_first.date_evidence_kind == "official_exception_announced"
    assert shutdown_first.verified_actual is False

    shutdown_derived = calendar_data.for_report_date("2018-12-31")
    assert shutdown_derived.mapped_release_date == date(2019, 2, 5)
    assert shutdown_derived.date_evidence_kind == "rule_derived_mapping"
    assert shutdown_derived.verified_actual is False

    juneteenth = calendar_data.for_report_date("2021-06-15")
    assert juneteenth.mapped_release_date == date(2021, 6, 21)
    assert juneteenth.date_evidence_kind == "official_exception_announced"
    assert juneteenth.verified_actual is False

    ion = calendar_data.for_report_date("2023-01-31")
    assert ion.mapped_release_date == date(2023, 2, 24)
    assert ion.date_evidence_kind == "official_exception_actual"
    assert ion.verified_actual is True
    assert ion.mapped_release_time_local is None
    assert ion.verified_actual_timestamp_utc is None

    shutdown_2025 = calendar_data.for_report_date("2025-09-30")
    assert shutdown_2025.mapped_release_date == date(2025, 11, 19)
    assert shutdown_2025.date_evidence_kind == "official_exception_announced"
    assert shutdown_2025.verified_actual is False
    assert shutdown_2025.mapped_release_time_local is None

    ordinary = calendar_data.for_report_date("2020-01-07")
    assert ordinary.date_evidence_kind == "official_tentative_schedule"
    assert ordinary.verified_actual is False
    assert ordinary.mapped_release_timestamp_utc is not None

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["verified_actual_date_rows"] == 7
    assert manifest["verified_actual_timestamp_rows"] == 0
    assert manifest["date_evidence_counts"]["rule_derived_mapping"] == 10
    assert len(manifest["sources"]) == 12
    assert all(
        (tmp_path / source["raw_path"]).is_file()
        and (tmp_path / source["sha256_path"]).is_file()
        for source in manifest["sources"]
    )


def test_raw_sha_sidecars_are_part_of_the_load_contract(tmp_path: Path) -> None:
    now = datetime(2026, 7, 16, 5, 0, tzinfo=UTC)
    calendar_path, manifest_path = downloader.download_calendar(
        tmp_path,
        refresh=True,
        transport=_transport(),
        now=now,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sidecar = tmp_path / manifest["sources"][0]["sha256_path"]
    sidecar.write_text("0" * 64 + "  corrupted.html\n", encoding="ascii")

    with pytest.raises(CFTCReleaseManifestError, match="sidecar does not match"):
        load_cftc_release_calendar(
            calendar_path,
            manifest_path=manifest_path,
            knowledge_cutoff=now,
        )
