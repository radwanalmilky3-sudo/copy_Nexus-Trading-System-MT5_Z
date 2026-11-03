from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "download_alfred_ecb_spf_catalogs.py"
SPEC = importlib.util.spec_from_file_location("alfred_ecb_spf_catalogs", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
downloader = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = downloader
SPEC.loader.exec_module(downloader)

NOW = datetime(2026, 7, 17, 1, 2, 3, tzinfo=UTC)


def _index(*links: str) -> bytes:
    anchors = "\n".join(links)
    return (
        "<html><title>ECB Survey of Professional Forecasters</title>"
        f"<body>{anchors}</body></html>"
    ).encode()


def _release(period: str, attachment: str) -> bytes:
    return (
        "<html><title>Survey of Professional Forecasters "
        f"{period}</title><a href='{attachment}'>Download results</a></html>"
    ).encode()


def _ecb_transport(
    *,
    unsafe: bool = False,
    unavailable_release: bool = False,
) -> tuple[httpx.MockTransport, list[str]]:
    requests: list[str] = []
    first_url = (
        "https://www.ecb.europa.eu/stats/ecb_surveys/"
        "survey_of_professional_forecasters/html/ecb.spf2016q1.en.html"
    )
    fourth_url = (
        "https://www.ecb.europa.eu/stats/ecb_surveys/"
        "survey_of_professional_forecasters/html/ecb.spf2025q4.en.html"
    )
    catalog_url = (
        "https://www.ecb.europa.eu/stats/ecb_surveys/"
        "survey_of_professional_forecasters/html/all-releases.en.html"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        url = str(request.url)
        if url == downloader.ECB_INDEX_URL:
            external = (
                "<a href='https://evil.example/spf2020q1.html'>"
                "Survey of Professional Forecasters 2020 Q1</a>"
                if unsafe
                else ""
            )
            return httpx.Response(
                200,
                content=_index(
                    "<a href='/stats/ecb_surveys/survey_of_professional_forecasters/"
                    "html/ecb.spf2025q4.en.html'>Survey of Professional Forecasters "
                    "fourth quarter of 2025</a>",
                    "<a href='/stats/ecb_surveys/survey_of_professional_forecasters/"
                    "html/ecb.spf2015q4.en.html'>Survey of Professional Forecasters "
                    "fourth quarter of 2015</a>",
                    "<a href='all-releases.en.html'>SHOW ALL RELEASES</a>",
                    "<a href='/press/pubbydate/html/index.en.html?"
                    "name_of_publication=Survey%20of%20Professional%20Forecasters'>"
                    "Full reports</a>",
                    external,
                ),
                request=request,
            )
        if url == catalog_url:
            return httpx.Response(
                200,
                content=_index(
                    "<a href='/stats/ecb_surveys/survey_of_professional_forecasters/"
                    "html/ecb.spf2016q1.en.html'>Survey of Professional Forecasters "
                    "first quarter of 2016</a>",
                    "<a href='/stats/ecb_surveys/survey_of_professional_forecasters/"
                    "html/ecb.spf2025q4.en.html'>Survey of Professional Forecasters "
                    "fourth quarter of 2025</a>",
                ),
                request=request,
            )
        if request.url.path == "/press/pubbydate/html/index.en.html":
            assert request.url.params["name_of_publication"] == (
                "Survey of Professional Forecasters"
            )
            return httpx.Response(200, content=_index(), request=request)
        if url == first_url:
            if unavailable_release:
                return httpx.Response(404, content=b"not found", request=request)
            return httpx.Response(
                200,
                content=_release("2016 Q1", "/shared/files/spf/results_2016q1.pdf"),
                request=request,
            )
        if url == fourth_url:
            return httpx.Response(
                200,
                content=_release("2025 Q4", "/shared/files/spf/results_2025q4.xlsx"),
                request=request,
            )
        if url.endswith("results_2016q1.pdf"):
            return httpx.Response(200, content=b"%PDF-1.7\nfixture\n%%EOF\n", request=request)
        if url.endswith("results_2025q4.xlsx"):
            return httpx.Response(200, content=b"PK\x03\x04fixture", request=request)
        raise AssertionError(f"unexpected request: {url}")

    return httpx.MockTransport(handler), requests


def _load_manifest(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_ecb_index_discovers_and_archives_only_official_release_evidence(
    tmp_path: Path,
) -> None:
    transport, requests = _ecb_transport()
    with httpx.Client(transport=transport, follow_redirects=False) as client:
        manifest_path = downloader.download_catalogs(
            tmp_path,
            client=client,
            fred_api_key="",
            retrieved_at=NOW,
        )

    manifest = _load_manifest(manifest_path)
    assert manifest["strict_pit"] is False
    assert manifest["is_intraday_surprise_data"] is False
    assert manifest["return_labels_opened"] is False
    assert manifest["factor_outcome_evaluations_added"] == 0
    assert manifest["trading_approval"] is False
    assert manifest["ecb_spf"]["discovered_release_period_count"] == 2
    assert {row["period"] for row in manifest["ecb_spf"]["releases"]} == {
        "2016-Q1",
        "2025-Q4",
    }
    assert len(manifest["ecb_spf"]["missing_release_periods"]) == 38
    assert all("evil.example" not in url for url in requests)
    assert not any("api.stlouisfed.org" in url for url in requests)
    assert manifest["alfred"]["status"] == "blocked_fred_api_key_required"
    assert manifest["alfred"]["current_vintage_fallback_used"] is False
    assert {row["status"] for row in manifest["alfred"]["series"]} == {
        "blocked_fred_api_key_required"
    }

    source_kinds = [source["kind"] for source in manifest["sources"]]
    assert source_kinds.count("index") == 1
    assert source_kinds.count("release_catalog_page") == 2
    assert source_kinds.count("release_page") == 2
    assert source_kinds.count("attachment") == 2
    for source in manifest["sources"]:
        raw = tmp_path / source["raw_path"]
        archive = tmp_path / source["archive_path"]
        assert raw.read_bytes() == archive.read_bytes()
        assert hashlib.sha256(raw.read_bytes()).hexdigest() == source["sha256"]
        assert Path(f"{raw}.sha256").is_file()
        assert Path(f"{archive}.sha256").is_file()
    assert downloader.validate_existing_catalog(tmp_path) == manifest


def test_matching_external_ecb_release_link_is_rejected_not_silently_followed(
    tmp_path: Path,
) -> None:
    transport, requests = _ecb_transport(unsafe=True)
    with httpx.Client(transport=transport) as client:
        with pytest.raises(downloader.CatalogError, match="non-official ECB"):
            downloader.download_catalogs(
                tmp_path,
                client=client,
                fred_api_key="",
                retrieved_at=NOW,
            )
    assert not any("evil.example" in url for url in requests)
    with pytest.raises(downloader.CatalogError, match="unsafe"):
        downloader._validate_ecb_url(
            "https://www.ecb.europa.eu/official.html?redirect=https://evil.example"
        )
    with pytest.raises(downloader.CatalogError, match="unsafe"):
        downloader._validate_ecb_url(
            "https://www.ecb.europa.eu/stats/%2e%2e/private/spf2020q1.html"
        )
    assert downloader._validate_ecb_url(
        "https://www.ecb.europa.eu/official.pdf?c7eb903d4f58c79a8584ee555b2708fc"
    ).endswith("c7eb903d4f58c79a8584ee555b2708fc")


def test_missing_api_key_is_explicitly_blocked_without_current_vintage_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert str(request.url) == downloader.ECB_INDEX_URL
        return httpx.Response(200, content=_index(), request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        path = downloader.download_catalogs(tmp_path, client=client, retrieved_at=NOW)

    manifest = _load_manifest(path)
    assert calls == [downloader.ECB_INDEX_URL]
    assert "FRED_API_KEY is required" in manifest["availability_blockers"]["alfred"]
    assert all(record["strict_pit"] is False for record in manifest["alfred"]["series"])
    assert all(record["is_intraday_surprise"] is False for record in manifest["alfred"]["series"])


def test_discovered_but_unavailable_ecb_release_stays_catalogued_and_blocked(
    tmp_path: Path,
) -> None:
    transport, _ = _ecb_transport(unavailable_release=True)
    with httpx.Client(transport=transport) as client:
        path = downloader.download_catalogs(
            tmp_path,
            client=client,
            fred_api_key="",
            retrieved_at=NOW,
        )

    manifest = _load_manifest(path)
    release = next(row for row in manifest["ecb_spf"]["releases"] if row["period"] == "2016-Q1")
    assert manifest["ecb_spf"]["status"] == "catalogued"
    assert release["status"] == "blocked_discovered_release_unavailable"
    assert release["attachments"] == []
    assert "HTTP 404" in release["blocker"]


def test_api_key_catalogues_metadata_and_vintage_dates_but_never_persists_secret(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if str(request.url.copy_with(query=None)) == downloader.ECB_INDEX_URL:
            return httpx.Response(200, content=_index(), request=request)
        assert request.url.host == downloader.FRED_API_HOST
        assert request.url.params["api_key"] == "secret-key"
        series_id = request.url.params["series_id"]
        if request.url.path == "/fred/series":
            payload = {"seriess": [{"id": series_id, "title": f"Title {series_id}"}]}
        elif request.url.path == "/fred/series/vintagedates":
            payload = {
                "count": 2,
                "offset": 0,
                "limit": 1000,
                "vintage_dates": ["2016-01-15", "2025-12-15"],
            }
        else:
            raise AssertionError(request.url.path)
        return httpx.Response(200, json=payload, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        path = downloader.download_catalogs(
            tmp_path,
            client=client,
            fred_api_key="secret-key",
            retrieved_at=NOW,
        )

    manifest_bytes = path.read_bytes()
    manifest = json.loads(manifest_bytes)
    assert b"secret-key" not in manifest_bytes
    assert manifest["alfred"]["status"] == "catalogued_vintage_dates_values_still_blocked"
    assert {record["vintage_date_count"] for record in manifest["alfred"]["series"]} == {2}
    assert {record["status"] for record in manifest["alfred"]["series"]} == {
        "vintage_dates_catalogued_values_not_downloaded"
    }
    alfred_sources = [source for source in manifest["sources"] if source["provider"] == "alfred"]
    assert len(alfred_sources) == 2 * len(downloader.ALFRED_SERIES)
    assert all("secret-key" not in source["source_url"] for source in alfred_sources)
    assert not any("observations" in str(request.url) for request in requests)


def test_verified_cache_reuse_and_tamper_gate(tmp_path: Path) -> None:
    transport, _ = _ecb_transport()
    with httpx.Client(transport=transport) as client:
        path = downloader.download_catalogs(
            tmp_path,
            client=client,
            fred_api_key="",
            retrieved_at=NOW,
        )

    def forbidden(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"verified cache must not request {request.url}")

    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        assert downloader.download_catalogs(tmp_path, client=client, fred_api_key="") == path

    manifest = _load_manifest(path)
    raw = tmp_path / manifest["sources"][0]["raw_path"]
    raw.write_bytes(raw.read_bytes() + b"tampered")
    with pytest.raises(downloader.CatalogError, match="SHA-256"):
        downloader.validate_existing_catalog(tmp_path)
