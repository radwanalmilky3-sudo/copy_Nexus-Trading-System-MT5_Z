from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, date, datetime, time
from pathlib import Path

import httpx
import pytest

from fx_system.central_bank_calendar import (
    CentralBankManifestError,
    load_central_bank_calendar,
)

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "download_central_bank_calendar.py"
SPEC = importlib.util.spec_from_file_location("central_bank_calendar_downloader", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
downloader = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = downloader
SPEC.loader.exec_module(downloader)


def _html(body: str) -> bytes:
    padding = " evidence" * 50
    return f"<!doctype html><html><body>{body}{padding}</body></html>".encode()


def test_fed_parser_uses_statement_actual_time_not_metadata() -> None:
    index = _html(
        '<a href="/newsevents/pressreleases/monetary20200315a.htm">Statement</a>'
        '<a href="/newsevents/pressreleases/monetary20250822a.htm">Strategy</a>'
    )
    links = downloader._parse_fed_index(index)
    assert [(link.event_date, link.url) for link in links] == [
        (
            date(2020, 3, 15),
            "https://www.federalreserve.gov/newsevents/pressreleases/monetary20200315a.htm",
        )
    ]
    clock, raw = downloader._parse_fed_actual_time(
        _html('<meta content="17:01"><p class="releaseTime">For release at 5:00 p.m. EDT</p>')
    )
    assert clock == time(17, 0)
    assert raw == "For release at 5:00 p.m. EDT"


def test_ecb_parser_and_rule_switch_keep_emergency_date_only() -> None:
    payload = _html(
        '<dt isoDate="2022-06-15"><div class="date">15 June 2022</div></dt>'
        '<dd><div class="title"><a href="/press/pr/emergency.en.html">'
        "Statement after an ad hoc meeting</a></div></dd>"
        '<dt isoDate="2022-07-21"><div class="date">21 July 2022</div></dt>'
        '<dd><div class="title"><a href="/press/pr/regular.en.html">'
        "Monetary policy decisions</a></div></dd>"
    )
    links = downloader._parse_ecb_index(payload)
    assert [link.event_date for link in links] == [date(2022, 6, 15), date(2022, 7, 21)]
    assert downloader.ECB_UNSCHEDULED[links[0].event_date] == "policy_framework_decision"


def test_boj_parser_deduplicates_references_and_reads_actual_minute() -> None:
    payload = _html(
        "<table><tbody>"
        '<tr><td>May&nbsp;&nbsp;22,&nbsp;2020</td><td><a href="/reference.pdf">'
        "Reference [PDF]</a></td></tr>"
        '<tr><td>May&nbsp;&nbsp;22,&nbsp;2020</td><td><a href="/decision.htm">'
        "Statement on Monetary Policy</a></td></tr>"
        "</tbody></table>"
    )
    links = downloader._parse_boj_index(payload)
    assert len(links) == 1
    assert links[0].event_date == date(2020, 5, 22)
    assert links[0].url == "https://www.boj.or.jp/decision.htm"
    clock, raw = downloader._parse_boj_actual_time(
        _html(
            "Statement on Monetary Policy -- Friday, May 22, 2020 at 10:01 "
            "Minutes -- Monday, June 1, 2020 at 8:50"
        )
    )
    assert clock == time(10, 1)
    assert raw.endswith("at 10:01")


def test_partial_download_manifest_fails_closed_but_is_auditable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = downloader.SourceSpec(
        "rba_decisions_2020",
        "RBA",
        "https://www.rba.gov.au/test/2020/",
        "rba/2020.html",
        "official_decision_archive_html",
        "RBA decisions 2020",
    )
    monkeypatch.setattr(downloader, "RBA_YEAR_SOURCES", (spec,))
    monkeypatch.setattr(downloader, "RBA_EXPECTED_BY_YEAR", {2020: 2})
    rba_payload = _html(
        "<p>Decisions were announced at 2.30 pm after each meeting.</p>"
        '<a href="/media-releases/2020/mr-20-08.html">19 March 2020</a>'
        '<a href="/media-releases/2020/mr-20-06.html">3 March 2020</a>'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == spec.url:
            return httpx.Response(200, content=rba_payload)
        return httpx.Response(503, content=b"unavailable")

    now = datetime(2026, 7, 16, tzinfo=UTC)
    calendar_path, manifest_path = downloader.download_calendar(
        tmp_path,
        refresh=True,
        transport=httpx.MockTransport(handler),
        now=now,
        retries=0,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["complete"] is False
    assert manifest["authority_counts"]["RBA"] == 2
    assert {record["authority"] for record in manifest["adapters"]} == set(
        downloader.AUTHORITIES
    )
    assert next(
        record for record in manifest["adapters"] if record["authority"] == "RBA"
    )["status"] == "complete"
    assert all(
        (tmp_path / source["raw_path"]).is_file()
        and (tmp_path / source["sha256_path"]).is_file()
        for source in manifest["sources"]
    )

    with pytest.raises(CentralBankManifestError, match="incomplete adapters"):
        load_central_bank_calendar(
            calendar_path,
            manifest_path=manifest_path,
            knowledge_cutoff=now,
        )
    calendar = load_central_bank_calendar(
        calendar_path,
        manifest_path=manifest_path,
        knowledge_cutoff=now,
        require_complete=False,
    )
    emergency = calendar.event("rba.20200319.rate_decision")
    assert emergency.scheduled_status == "unscheduled"
    assert emergency.release_at_utc == datetime(2020, 3, 19, 3, 30, tzinfo=UTC)


def _build_cached_snapshot(
    tmp_path: Path,
) -> tuple[downloader.SourceSpec, dict[str, dict[str, object]]]:
    spec = downloader.SourceSpec(
        "rba_cache_test",
        "RBA",
        "https://www.rba.gov.au/cache-test/",
        "rba/cache-test.html",
        "official_decision_archive_html",
        "RBA cache fixture",
    )
    payload = _html("<p>Official RBA cache evidence at 2.30 pm.</p>")

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == spec.url
        return httpx.Response(200, content=payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        store = downloader.SnapshotStore(
            tmp_path,
            client,
            refresh=True,
            retrieved_at=datetime(2026, 7, 16, tzinfo=UTC),
            prior_sources={},
            retries=0,
        )
        store.get(spec)
        record = store.manifest_records()[0]
    return spec, {spec.source_id: record}


@pytest.mark.parametrize("tamper", ["raw", "sidecar", "manifest_hash"])
def test_cached_snapshot_tampering_is_never_rehashed_or_washed_clean(
    tmp_path: Path, tamper: str
) -> None:
    spec, prior = _build_cached_snapshot(tmp_path)
    record = prior[spec.source_id]
    raw = tmp_path / str(record["raw_path"])
    sidecar = tmp_path / str(record["sha256_path"])
    original_sidecar = sidecar.read_bytes()
    if tamper == "raw":
        raw.write_text("tampered raw", encoding="utf-8")
    elif tamper == "sidecar":
        sidecar.write_text("0" * 64 + f"  {raw.name}\n", encoding="ascii")
    else:
        record["raw_sha256"] = "0" * 64

    def no_request(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"tampered cache must not trigger implicit download: {request.url}")

    with httpx.Client(transport=httpx.MockTransport(no_request)) as client:
        store = downloader.SnapshotStore(
            tmp_path,
            client,
            refresh=False,
            retrieved_at=datetime(2026, 7, 16, tzinfo=UTC),
            prior_sources=prior,
            retries=0,
        )
        with pytest.raises(ValueError, match="cached|manifest"):
            store.get(spec)
    if tamper != "sidecar":
        assert sidecar.read_bytes() == original_sidecar


def test_orphan_cache_duplicate_manifest_and_cross_host_are_rejected(tmp_path: Path) -> None:
    spec, prior = _build_cached_snapshot(tmp_path)

    def no_request(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"invalid cache must not access network: {request.url}")

    with httpx.Client(transport=httpx.MockTransport(no_request)) as client:
        store = downloader.SnapshotStore(
            tmp_path,
            client,
            refresh=False,
            retrieved_at=datetime(2026, 7, 16, tzinfo=UTC),
            prior_sources={},
            retries=0,
        )
        with pytest.raises(ValueError, match="orphan raw cache"):
            store.get(spec)

        evil = downloader.SourceSpec(
            "evil_detail",
            "RBA",
            "https://example.com/detail.html",
            "rba/evil.html",
            "official_statement_html",
            "cross-host detail",
        )
        with pytest.raises(ValueError, match="official RBA HTTPS host"):
            store.get(evil)

    manifest_path = tmp_path / "duplicate.manifest.json"
    record = prior[spec.source_id]
    manifest_path.write_text(json.dumps({"sources": [record, record]}), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate source_id"):
        downloader._prior_source_records(manifest_path)


def test_retry_after_zero_is_honoured_before_retry(tmp_path: Path) -> None:
    spec = downloader.SourceSpec(
        "rba_retry_test",
        "RBA",
        "https://www.rba.gov.au/retry-test/",
        "rba/retry-test.html",
        "official_decision_archive_html",
        "RBA retry fixture",
    )
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, content=_html("official retry response"))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        store = downloader.SnapshotStore(
            tmp_path,
            client,
            refresh=True,
            retrieved_at=datetime(2026, 7, 16, tzinfo=UTC),
            prior_sources={},
            retries=1,
        )
        store.get(spec)
    assert attempts == 2
