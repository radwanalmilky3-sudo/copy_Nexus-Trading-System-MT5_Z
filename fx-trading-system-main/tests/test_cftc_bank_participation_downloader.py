from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "download_cftc_bank_participation.py"
SPEC = importlib.util.spec_from_file_location("cftc_bpr_downloader", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
downloader = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = downloader
SPEC.loader.exec_module(downloader)


def _data_rows(width: int, values: list[list[str]]) -> str:
    rows: list[str] = []
    for index, row in enumerate(values):
        contract = '<td rowspan="3">CME EURO FX</td>' if index == 0 else ""
        assert len(row) == width - 1
        rows.append(f"<tr>{contract}{''.join(f'<td>{value}</td>' for value in row)}</tr>")
    return "".join(rows)


def _futures_page(report_date: str = "3/5/2024") -> bytes:
    header = [
        "COMMODITY",
        "BANK TYPE",
        "BANK COUNT",
        "LONG FUTURES",
        "%",
        "SHORT FUTURES",
        "%",
        "OPEN INTEREST",
    ]
    data = _data_rows(
        8,
        [
            ["U.S.", "", "1,234", "12.5", "2,345", "23.5", "9,876"],
            ["NON U.S.", "4", "3,210", "32.5", "1,200", "12.1", ""],
            ["", "7", "4,444", "45.0", "3,545", "35.6", ""],
        ],
    )
    return (
        "<html><body><h1>CFTC Bank Participation Report Futures IN CONTRACT</h1>"
        f"<table><tr><td></td><td colspan='7'>REPORT DATE: {report_date}</td></tr>"
        f"<tr>{''.join(f'<th>{value}</th>' for value in header)}</tr>{data}</table>"
        "</body></html>"
    ).encode()


def _options_page(report_date: str = "3/5/2024") -> bytes:
    header = [
        "COMMODITY",
        "BANK TYPE",
        "BANK COUNT",
        "LONG CALLS",
        "%",
        "SHORT CALLS",
        "%",
        "CALL O.I.",
        "LONG PUTS",
        "%",
        "SHORT PUTS",
        "%",
        "PUT O.I.",
    ]
    data = _data_rows(
        13,
        [
            [
                "U.S.",
                "",
                "1,111",
                "11.1",
                "2,222",
                "22.2",
                "10,000",
                "3,333",
                "33.3",
                "4,444",
                "44.4",
                "20,000",
            ],
            [
                "NON U.S.",
                "5",
                "2,000",
                "20.0",
                "1,000",
                "10.0",
                "",
                "1,500",
                "15.0",
                "2,500",
                "25.0",
                "",
            ],
            [
                "",
                "9",
                "3,111",
                "31.1",
                "3,222",
                "32.2",
                "",
                "4,833",
                "48.3",
                "6,944",
                "69.4",
                "",
            ],
        ],
    )
    return (
        "<html><body><h1>CFTC IN CONTRACTS-NOT DELTA ADJUSTED</h1>"
        f"<table><tr><td></td><td colspan='12'>REPORT DATE: {report_date}</td></tr>"
        f"<tr>{''.join(f'<th>{value}</th>' for value in header)}</tr>{data}</table>"
        "</body></html>"
    ).encode()


def _report(year: int, month: int, report_type: str) -> downloader.ReportLink:
    suffix = "f" if report_type == "futures" else "o"
    token = list(downloader.MONTH_TOKENS)[(month - 1) * 2]
    return downloader.ReportLink(
        year,
        month,
        report_type,
        f"https://www.cftc.gov/MarketReports/BankParticipation/dea{token}{year % 100:02d}{suffix}",
    )


def test_futures_parser_expands_rowspan_empty_counts_and_comma_numbers() -> None:
    report = _report(2024, 3, "futures")
    rows = downloader.parse_report(
        report,
        _futures_page(),
        retrieved_at=datetime(2026, 7, 16, tzinfo=UTC),
    )

    assert len(rows) == 3
    keyed = {row["bank_type"]: row for row in rows}
    assert set(keyed) == {"U.S.", "NON U.S.", "COMBINED"}
    assert keyed["U.S."]["bank_count"] is None
    assert keyed["U.S."]["long_futures_contracts"] == 1_234
    assert keyed["COMBINED"]["bank_count"] == 7
    assert {row["open_interest"] for row in rows} == {9_876}
    assert all(row["contract"] == "CME EURO FX" for row in rows)
    assert all(row["currency"] == "EUR" for row in rows)
    assert not any(row["long_calls_contracts"] for row in rows)
    assert all(
        row["fx_contract_coverage_quality"]
        == "explicitly_audited_official_page_non_disclosure"
        for row in rows
    )
    assert all("CME NEW ZEALAND DOLLAR" in row["page_missing_fx_contracts"] for row in rows)
    assert all(
        row["value_vintage_quality"]
        == "official_permanent_report_current_copy_not_verified_as_published_vintage"
        for row in rows
    )
    assert not any(row["strict_pit_eligible"] for row in rows)


def test_options_keep_call_and_put_columns_separate_from_futures() -> None:
    report = _report(2024, 3, "options")
    rows = downloader.parse_report(
        report,
        _options_page(),
        retrieved_at=datetime(2026, 7, 16, tzinfo=UTC),
    )

    combined = next(row for row in rows if row["bank_type"] == "COMBINED")
    assert combined["option_basis"] == "contracts_not_delta_adjusted"
    assert combined["long_calls_contracts"] == 3_111
    assert combined["short_calls_contracts"] == 3_222
    assert combined["long_puts_contracts"] == 4_833
    assert combined["short_puts_contracts"] == 6_944
    assert combined["call_open_interest"] == 10_000
    assert combined["put_open_interest"] == 20_000
    assert combined["long_futures_contracts"] == ""
    assert combined["open_interest"] == ""


def test_valid_page_with_no_frozen_fx_contracts_is_audited_without_zero_fill() -> None:
    report = _report(2016, 10, "options")
    payload = _options_page("10/4/2016").replace(
        b"CME EURO FX", b"NYME CRUDE OIL AVG PRICE OPTIONS"
    )

    rows = downloader.parse_report(
        report,
        payload,
        retrieved_at=datetime(2026, 7, 16, tzinfo=UTC),
    )
    coverage = downloader._page_coverage(report, rows)

    assert rows == []
    assert coverage["disclosed_fx_contracts"] == ""
    assert set(coverage["missing_fx_contracts"].split("|")) == set(
        downloader.FX_CONTRACTS
    )
    assert (
        coverage["coverage_quality"]
        == "explicitly_audited_official_page_non_disclosure"
    )


def test_incomplete_generation_resume_requires_hash_verified_pairs(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    retrieved = datetime(2026, 7, 16, 12, 0, 0, 123456, tzinfo=UTC)
    generation = downloader._new_cache_generation(root, retrieved)
    payload, record = downloader._load_source(
        root,
        source_id="bpr_index",
        url=downloader.INDEX_URL,
        cache_directory=generation,
        refresh=True,
        timeout=10,
        retries=0,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"<html>CFTC index</html>")
        ),
        sleep=lambda _: None,
        retrieved_at=retrieved,
    )
    assert payload == b"<html>CFTC index</html>"

    selected, records = downloader._load_incomplete_generation(root, generation)
    assert selected == generation
    assert records["bpr_index"]["sha256"] == record["sha256"]

    (generation / "bpr_index.html").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="identity/hash mismatch"):
        downloader._load_incomplete_generation(root, generation)


def test_rule_derived_release_times_respect_new_york_dst_and_wait_until_next_day() -> None:
    retrieved = datetime(2026, 7, 16, tzinfo=UTC)
    standard = downloader._release_fields(
        date(2024, 3, 5),
        retrieved_at=retrieved,
        schedule={},
        special_payload=None,
    )
    daylight = downloader._release_fields(
        date(2024, 4, 2),
        retrieved_at=retrieved,
        schedule={},
        special_payload=None,
    )

    assert standard["release_timestamp_utc"] == "2024-03-08T20:30:00Z"
    assert standard["availability_time"] == "2024-03-09T05:00:00Z"
    assert daylight["release_timestamp_utc"] == "2024-04-05T19:30:00Z"
    assert daylight["availability_time"] == "2024-04-06T04:00:00Z"
    assert standard["release_verified_actual"] is False
    assert standard["strict_pit_eligible"] is False
    assert (
        standard["availability_quality"]
        == "rule_derived_exploratory_next_local_day_not_actual_verified"
    )


def _complete_discovery_html(*, omit: tuple[int, int, str] | None = None) -> bytes:
    links: list[str] = []
    month_tokens = [
        "jan",
        "feb",
        "mar",
        "apr",
        "may",
        "jun",
        "jul",
        "aug",
        "sep",
        "oct",
        "nov",
        "dec",
    ]
    for year in range(2016, 2026):
        for month, token in enumerate(month_tokens, start=1):
            for report_type, suffix in (("futures", "f"), ("options", "o")):
                if omit == (year, month, report_type):
                    continue
                links.append(
                    "<a href='/MarketReports/BankParticipationReports/"
                    f"dea{token}{year % 100:02d}{suffix}.html'>report</a>"
                )
    return ("<html><body>CFTC" + "".join(links) + "</body></html>").encode()


def _current_official_gap_html(
    *, extra_omit: tuple[int, int, str] | None = None
) -> bytes:
    links: list[str] = []
    month_tokens = downloader.INFERRED_MONTH_TOKENS
    for year in range(2016, 2026):
        for month, token in enumerate(month_tokens, start=1):
            for report_type, suffix in (("futures", "f"), ("options", "o")):
                key = (year, month, report_type)
                if key in downloader.INFERRED_DISCOVERY_KEYS or key == extra_omit:
                    continue
                links.append(
                    "<a href='/MarketReports/BankParticipationReports/"
                    f"dea{token}{year % 100:02d}{suffix}'>report</a>"
                )
    return ("<html><body>CFTC" + "".join(links) + "</body></html>").encode()


def test_discovery_freezes_complete_month_type_coverage_and_rejects_missing_month() -> None:
    links = downloader.discover_links([_complete_discovery_html()])
    assert len(links) == 240
    assert {(link.year, link.month) for link in links} == {
        (year, month) for year in range(2016, 2026) for month in range(1, 13)
    }

    with pytest.raises(ValueError, match="discovery is incomplete"):
        downloader.discover_links(
            [_complete_discovery_html(omit=(2020, 7, "options"))]
        )


def test_only_frozen_78_index_gaps_receive_transparent_inferred_candidates() -> None:
    assert len(downloader.INFERRED_DISCOVERY_KEYS) == 78

    links = downloader.discover_links_with_inferred_candidates(
        [_current_official_gap_html()]
    )

    assert len(links) == 240
    inferred = [
        report
        for report in links
        if report.discovery_method == downloader.INFERRED_DISCOVERY_METHOD
    ]
    assert len(inferred) == 78
    april_2019 = next(
        report
        for report in inferred
        if (report.year, report.month, report.report_type) == (2019, 4, "futures")
    )
    january_2020 = next(
        report
        for report in inferred
        if (report.year, report.month, report.report_type) == (2020, 1, "options")
    )
    assert april_2019.url.endswith("/BankParticipationReports/deaapr19f")
    assert january_2020.url.endswith("/BankParticipationReports/deajan20o")


def test_new_unapproved_discovery_gap_still_fails_closed() -> None:
    with pytest.raises(ValueError, match="new gaps outside the frozen inferred set"):
        downloader.discover_links_with_inferred_candidates(
            [_current_official_gap_html(extra_omit=(2018, 5, "futures"))]
        )


def test_inferred_candidate_requires_matching_body_report_date_and_schema() -> None:
    report = downloader._inferred_candidate((2020, 1, "futures"))
    rows = downloader.parse_report(
        report,
        _futures_page("1/7/2020"),
        retrieved_at=datetime(2026, 7, 16, tzinfo=UTC),
    )
    assert {row["source_discovery_method"] for row in rows} == {
        "inferred_official_path_validated_by_page_body"
    }
    assert {row["source_discovery_verification"] for row in rows} == {
        "unique_report_date_and_report_type_schema_verified"
    }

    with pytest.raises(ValueError, match="report date does not match"):
        downloader.parse_report(
            report,
            _futures_page("2/4/2020"),
            retrieved_at=datetime(2026, 7, 16, tzinfo=UTC),
        )

    with pytest.raises(ValueError, match="report table header drifted"):
        downloader.parse_report(
            report,
            _options_page("1/7/2020"),
            retrieved_at=datetime(2026, 7, 16, tzinfo=UTC),
        )


def test_discovery_retains_official_duplicate_pages_for_value_comparison() -> None:
    payload = _complete_discovery_html() + (
        b'<a href="/MarketReports/BankParticipationReports/deajan18f">alias</a>'
    )
    links = downloader.discover_links([payload])
    report = next(
        report
        for report in links
        if (report.year, report.month, report.report_type) == (2018, 1, "futures")
    )
    assert report.url.endswith("deajan18f.html")
    assert report.alternate_urls == (
        "https://www.cftc.gov/MarketReports/BankParticipationReports/deajan18f",
    )

    first = downloader.parse_report(
        report,
        _futures_page("1/2/2018"),
        retrieved_at=datetime(2026, 7, 16, tzinfo=UTC),
    )
    alternate = downloader.parse_report(
        downloader.ReportLink(2018, 1, "futures", report.alternate_urls[0]),
        _futures_page("1/2/2018"),
        retrieved_at=datetime(2026, 7, 16, tzinfo=UTC),
    )
    assert downloader._normalized_page_signature(first) == downloader._normalized_page_signature(
        alternate
    )


def test_discovery_link_whitelist_rejects_external_or_non_bpr_paths() -> None:
    assert (
        downloader._parse_report_link(
            "https://evil.example/MarketReports/BankParticipation/deajan20f"
        )
        is None
    )
    assert downloader._parse_report_link("/MarketReports/Other/deajan20f") is None
    assert downloader._parse_report_link("http://www.cftc.gov/x") is None
    valid = downloader._parse_report_link(
        "/MarketReports/BankParticipationReports/deaseptember18f"
    )
    assert valid is not None
    assert (valid.year, valid.month, valid.report_type) == (2018, 9, "futures")
    february_2019 = downloader._parse_report_link(
        "/MarketReports/BankParticipationReports/deajfeb19f"
    )
    march_2019 = downloader._parse_report_link(
        "/MarketReports/BankParticipationReports/deajmar19f"
    )
    assert february_2019 is not None and february_2019.month == 2
    assert march_2019 is not None and march_2019.month == 3
    with pytest.raises(ValueError, match="unrecognized CFTC BPR month token"):
        downloader._parse_report_link(
            "/MarketReports/BankParticipationReports/deajmar20f"
        )


def test_search_pager_accepts_official_query_only_next_link() -> None:
    query = downloader._search_query(2016, "futures")
    payload = (
        b'<html><body><a rel="next" href="?keys=%22Bank%20Participation%20Report%20'
        b'Futures%22%20AND%202016&amp;page=1">Next</a></body></html>'
    )
    assert downloader._next_search_page(
        payload,
        expected_page=1,
        expected_query=query,
    )


def test_cached_source_hash_tampering_is_rejected(tmp_path: Path) -> None:
    payload = b"<html><body>CFTC official fixture</body></html>"
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=payload))
    now = datetime(2026, 7, 16, tzinfo=UTC)
    _, manifest = downloader._load_source(
        tmp_path,
        source_id="fixture",
        url=downloader.INDEX_URL,
        refresh=True,
        timeout=1,
        retries=0,
        transport=transport,
        sleep=lambda _seconds: None,
        retrieved_at=now,
    )
    cache = tmp_path / manifest["cache_path"]
    cache.write_bytes(payload + b"tampered")

    with pytest.raises(ValueError, match="URL/hash verification failed"):
        downloader._load_source(
            tmp_path,
            source_id="fixture",
            url=downloader.INDEX_URL,
            prior=manifest,
            refresh=False,
            timeout=1,
            retries=0,
            transport=transport,
            sleep=lambda _seconds: None,
            retrieved_at=now,
        )


@pytest.mark.parametrize("tamper", ["raw_and_metadata", "metadata", "prior", "archive"])
def test_cached_source_cannot_be_washed_clean_without_prior_manifest(
    tmp_path: Path, tamper: str
) -> None:
    payload = b"<html><body>CFTC official fixture</body></html>"
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=payload))
    now = datetime(2026, 7, 16, tzinfo=UTC)
    _, prior = downloader._load_source(
        tmp_path,
        source_id="fixture",
        url=downloader.INDEX_URL,
        refresh=True,
        timeout=1,
        retries=0,
        transport=transport,
        sleep=lambda _seconds: None,
        retrieved_at=now,
    )
    cache = tmp_path / prior["cache_path"]
    metadata_path = tmp_path / prior["cache_metadata_path"]
    archive_path = tmp_path / prior["archive_path"]
    if tamper == "raw_and_metadata":
        changed = payload + b" changed"
        cache.write_bytes(changed)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["bytes"] = len(changed)
        metadata["sha256"] = downloader._sha256(changed)
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    elif tamper == "metadata":
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["retrieved_at"] = "2026-07-17T00:00:00Z"
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    elif tamper == "prior":
        prior["sha256"] = "0" * 64
    else:
        archive_path.write_bytes(payload + b" changed")

    with pytest.raises(ValueError, match="metadata differs|verification failed|archived snapshot"):
        downloader._load_source(
            tmp_path,
            source_id="fixture",
            url=downloader.INDEX_URL,
            prior=prior,
            refresh=False,
            timeout=1,
            retries=0,
            transport=transport,
            sleep=lambda _seconds: None,
            retrieved_at=now,
        )


def test_prior_manifest_hash_and_orphan_cache_fail_closed(tmp_path: Path) -> None:
    cache = tmp_path / "raw" / "cache" / "orphan.html"
    cache.parent.mkdir(parents=True)
    cache.write_text("orphan", encoding="utf-8")
    with pytest.raises(ValueError, match="orphan CFTC BPR cache"):
        downloader._load_prior_sources(tmp_path)

    cache.unlink()
    normalized = tmp_path / "normalized" / "fixture.csv.gz"
    normalized.parent.mkdir(parents=True)
    normalized.write_bytes(b"normalized")
    manifest = {
        "schema_version": downloader.MANIFEST_SCHEMA_VERSION,
        "program_version": downloader.PROGRAM_VERSION,
        "dataset_kind": "cftc_bank_participation_reports_not_cot_not_spot_order_flow",
        "normalized_path": normalized.relative_to(tmp_path).as_posix(),
        "normalized_sha256": downloader._sha256(normalized.read_bytes()),
        "sources": [],
    }
    manifest_path = tmp_path / "cftc_bank_participation_manifest.json"
    manifest_payload = json.dumps(manifest).encode()
    manifest_path.write_bytes(manifest_payload)
    manifest_path.with_suffix(".sha256").write_text(
        downloader._sha256(manifest_payload), encoding="ascii"
    )
    manifest_path.write_bytes(manifest_payload + b" ")
    with pytest.raises(ValueError, match="manifest SHA-256"):
        downloader._load_prior_sources(tmp_path)


def test_2025_interruption_is_not_upgraded_to_actual_release_time() -> None:
    special = (
        "<html><body>CFTC processing and publication of Bank Participation Reports were "
        "interrupted from October 1 – November 12 due to a lapse.</body></html>"
    ).encode()
    report = _report(2025, 10, "futures")
    retrieved = datetime(2026, 7, 16, 8, 30, tzinfo=UTC)
    rows = downloader.parse_report(
        report,
        _futures_page("10/7/2025"),
        retrieved_at=retrieved,
        special_payload=special,
    )

    assert {row["release_date"] for row in rows} == {""}
    assert {row["release_timestamp_utc"] for row in rows} == {""}
    assert {row["availability_time"] for row in rows} == {"2026-07-16T08:30:00Z"}
    assert {row["release_date_quality"] for row in rows} == {
        "official_exception_no_complete_release_date"
    }
    assert not any(row["release_verified_actual"] for row in rows)


def test_january_2019_shutdown_without_bpr_release_evidence_uses_retrieval_time() -> None:
    special = (
        b"<html><body>CFTC <strong>March 13, 2019:</strong> The Chicago Board of Trade "
        b"contracts were not originally included in the December 2018 report.</body></html>"
    )
    report = _report(2019, 1, "futures")
    retrieved = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    rows = downloader.parse_report(
        report,
        _futures_page("1/8/2019"),
        retrieved_at=retrieved,
        special_payload=special,
    )

    assert {row["release_date"] for row in rows} == {""}
    assert {row["availability_time"] for row in rows} == {"2026-07-16T09:00:00Z"}
    assert {row["release_date_quality"] for row in rows} == {
        "federal_shutdown_period_no_bpr_specific_release_date_evidence"
    }
    assert {row["availability_quality"] for row in rows} == {
        "conservative_retrieval_missing_historical_exception_evidence"
    }
    assert not any(row["strict_pit_eligible"] for row in rows)


def test_december_2018_known_correction_is_not_called_as_published_vintage() -> None:
    special = (
        b"<html><body>CFTC <strong>March 13, 2019:</strong> The Chicago Board of Trade "
        b"contracts were not originally included in the December 2018 report.</body></html>"
    )
    rows = downloader.parse_report(
        _report(2018, 12, "futures"),
        _futures_page("12/4/2018"),
        retrieved_at=datetime(2026, 7, 16, tzinfo=UTC),
        special_payload=special,
    )

    assert {row["value_vintage_quality"] for row in rows} == {
        "official_corrected_permanent_report_current_copy"
    }


def test_release_schedule_parser_keeps_exception_marker_as_intended_not_actual() -> None:
    payload = b"""
    <html><body>CFTC<table><caption>2025</caption>
    <tr><td>Month</td><td>Report Date</td><td>Release Date</td></tr>
    <tr><td>December</td><td>02</td><td>17**</td></tr>
    </table></body></html>
    """
    schedule = downloader.parse_release_schedule(payload)
    assert schedule[date(2025, 12, 2)] == (date(2025, 12, 17), "**")
    release = downloader._release_fields(
        date(2025, 12, 2),
        retrieved_at=datetime(2026, 7, 16, tzinfo=UTC),
        schedule=schedule,
        special_payload=None,
    )
    assert release["release_date_quality"] == "official_exception_announced_intended_not_actual"
    assert release["release_verified_actual"] is False


def test_403_stops_without_access_control_bypass_or_retry() -> None:
    requests: list[httpx.Request] = []
    delays: list[float] = []

    def forbidden(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(403, request=request, content=b"CFTC access denied")

    with pytest.raises(RuntimeError, match="will not bypass access controls"):
        downloader._fetch(
            downloader.INDEX_URL,
            timeout=1,
            retries=3,
            transport=httpx.MockTransport(forbidden),
            sleep=delays.append,
        )

    assert len(requests) == 1
    assert delays == []


def test_429_honors_retry_after_before_one_retry() -> None:
    delays: list[float] = []
    calls = 0

    def rate_limited(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                request=request,
                headers={"Retry-After": "2"},
                content=b"CFTC rate limited",
            )
        return httpx.Response(200, request=request, content=b"CFTC official response")

    payload, _ = downloader._fetch(
        downloader.INDEX_URL,
        timeout=1,
        retries=1,
        transport=httpx.MockTransport(rate_limited),
        sleep=delays.append,
    )

    assert payload == b"CFTC official response"
    assert calls == 2
    assert delays == [2.0]


def test_manifest_authorized_cache_generation_ignores_preserved_legacy_attempt(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "raw" / "cache" / "bpr_index.html"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("partial unmanifested legacy attempt", encoding="utf-8")
    now = datetime(2026, 7, 16, tzinfo=UTC)
    generation = downloader._new_cache_generation(tmp_path, now)
    payload = b"<html><body>CFTC official fixture</body></html>"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, request=request, content=payload)
    )
    _, source = downloader._load_source(
        tmp_path,
        source_id="fixture",
        url=downloader.INDEX_URL,
        cache_directory=generation,
        refresh=True,
        timeout=1,
        retries=0,
        transport=transport,
        sleep=lambda _seconds: None,
        retrieved_at=now,
    )
    normalized = tmp_path / "normalized" / "fixture.csv.gz"
    normalized.parent.mkdir(parents=True)
    normalized.write_bytes(b"normalized")
    manifest = {
        "schema_version": downloader.MANIFEST_SCHEMA_VERSION,
        "program_version": downloader.PROGRAM_VERSION,
        "dataset_kind": "cftc_bank_participation_reports_not_cot_not_spot_order_flow",
        "normalized_path": normalized.relative_to(tmp_path).as_posix(),
        "normalized_sha256": downloader._sha256(normalized.read_bytes()),
        "cache_generation": generation.relative_to(tmp_path).as_posix(),
        "sources": [source],
    }
    manifest_path = tmp_path / "cftc_bank_participation_manifest.json"
    manifest_payload = json.dumps(manifest).encode()
    manifest_path.write_bytes(manifest_payload)
    manifest_path.with_suffix(".sha256").write_text(
        downloader._sha256(manifest_payload), encoding="ascii"
    )

    prior = downloader._load_prior_sources(tmp_path)
    assert set(prior) == {"fixture"}
    assert downloader._cache_generation_from_sources(tmp_path, prior) == generation

    _, cached = downloader._load_source(
        tmp_path,
        source_id="fixture",
        url=downloader.INDEX_URL,
        prior=prior["fixture"],
        cache_directory=generation,
        refresh=False,
        timeout=1,
        retries=0,
        transport=transport,
        sleep=lambda _seconds: None,
        retrieved_at=now,
    )
    assert cached["status"] == "cached"
