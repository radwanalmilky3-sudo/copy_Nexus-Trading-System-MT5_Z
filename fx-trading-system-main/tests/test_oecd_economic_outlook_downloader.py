from __future__ import annotations

import csv
import dataclasses
import gzip
import hashlib
import importlib.util
import io
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "download_oecd_economic_outlook.py"
SPEC = importlib.util.spec_from_file_location("oecd_economic_outlook_downloader", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
downloader = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = downloader
SPEC.loader.exec_module(downloader)

ECONOMY_NAMES = {
    "USA": "United States",
    "GBR": "United Kingdom",
    "JPN": "Japan",
    "CHE": "Switzerland",
    "CAN": "Canada",
    "AUS": "Australia",
    "NZL": "New Zealand",
    "EA15": "Euro area (15 countries)",
    "EA16": "Euro area (16 countries)",
    "EA17": "Euro area (17 countries)",
}
MEASURE_NAMES = {
    "GDPV_ANNPCT": "Gross domestic product, volume, growth",
    "CPI_YTYPCT": "Headline inflation",
    "UNR": "Unemployment rate",
    "CBGDPR": "Current account balance as a percentage of GDP",
    "NLGQ": "General government net lending as a percentage of GDP",
}


def _payload(
    spec: downloader.SourceSpec,
    *,
    modern: bool | None = None,
    target_period: int | None = None,
    duplicate: bool = False,
) -> bytes:
    modern = spec.api_generation == "versioned_modern" if modern is None else modern
    target = target_period or spec.end_period
    if modern:
        area_code, area_name = "REF_AREA", "Reference area"
        measure_code, measure_name = "MEASURE", "Measure"
        frequency_code, frequency_name = "FREQ", "Frequency of observation"
        status_name = "Observation status"
        unit_name, multiplier_name = "Unit of measure", "Unit multiplier"
    else:
        area_code, area_name = "LOCATION", "Country"
        measure_code, measure_name = "VARIABLE", "Variable"
        frequency_code, frequency_name = "FREQUENCY", "Frequency"
        status_name = "Observation Status"
        unit_name, multiplier_name = "Unit of Measures", "Multiplier"
    fieldnames = [
        "STRUCTURE",
        "STRUCTURE_ID",
        "STRUCTURE_NAME",
        "ACTION",
        area_code,
        area_name,
        measure_code,
        measure_name,
        frequency_code,
        frequency_name,
        "TIME_PERIOD",
        "Time",
        "OBS_VALUE",
        "Observation Value",
        "OBS_STATUS",
        status_name,
        "UNIT_MEASURE",
        unit_name,
        "UNIT_MULT",
        multiplier_name,
        "BASE_PER",
        "Base reference period",
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    rows: list[dict[str, object]] = []
    for economy_index, economy in enumerate(spec.economy_codes):
        for measure_index, measure in enumerate(downloader.MEASURES):
            rows.append(
                {
                    "STRUCTURE": "DATAFLOW",
                    "STRUCTURE_ID": f"OECD.TEST:{spec.flow_id}(1.0)",
                    "STRUCTURE_NAME": f"Economic Outlook No {spec.edition}",
                    "ACTION": "I",
                    area_code: economy,
                    area_name: ECONOMY_NAMES[economy],
                    measure_code: measure,
                    measure_name: MEASURE_NAMES[measure],
                    frequency_code: "A",
                    frequency_name: "Annual",
                    "TIME_PERIOD": str(target),
                    "OBS_VALUE": 1.0 + economy_index + measure_index / 10,
                    "OBS_STATUS": "A",
                    status_name: "Normal value",
                    "UNIT_MEASURE": "PC",
                    unit_name: "Percentage",
                    "UNIT_MULT": "0",
                    multiplier_name: "Units",
                    "BASE_PER": "2015",
                }
            )
    if duplicate:
        rows.append(dict(rows[0]))
    writer.writerows(rows)
    return output.getvalue().encode()


def _transport_for(
    spec: downloader.SourceSpec,
    payload: bytes,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == spec.url
        return httpx.Response(200, headers={"Content-Type": "text/csv"}, content=payload)

    return httpx.MockTransport(handler)


@pytest.fixture
def eo100_legacy_fixture() -> tuple[downloader.SourceSpec, bytes]:
    spec = next(item for item in downloader.SOURCES if item.source_id == "eo100_baseline")
    return spec, _payload(spec)


@pytest.fixture
def eo118_modern_fixture() -> tuple[downloader.SourceSpec, bytes]:
    spec = next(item for item in downloader.SOURCES if item.source_id == "eo118_baseline")
    return spec, _payload(spec)


def test_frozen_sources_cover_legacy_eo107_and_versioned_modern_flows() -> None:
    assert len(downloader.SOURCES) == 21
    assert [item.edition for item in downloader.SOURCES].count(107) == 2
    scenarios = {
        item.scenario: item for item in downloader.SOURCES if item.edition == 107
    }
    assert scenarios["single_hit"].flow_id == "DF_EO107_INTERNET_1"
    assert scenarios["double_hit"].flow_id == "DF_EO107_INTERNET_2"
    modern = {item.edition: item for item in downloader.SOURCES if item.edition >= 115}
    assert ",1.1/" in modern[115].url
    assert ",1.4/" in modern[118].url
    assert all("format=csvfilewithlabels" in item.url for item in downloader.SOURCES)
    assert all(".A?startPeriod=" in item.url for item in downloader.SOURCES)
    for item in downloader.SOURCES:
        downloader._validate_source_spec(item)


def test_euro_aggregate_code_drift_is_preserved_and_never_auto_spliced(
    eo100_legacy_fixture: tuple[downloader.SourceSpec, bytes],
) -> None:
    eo99 = next(item for item in downloader.SOURCES if item.edition == 99)
    eo101 = next(item for item in downloader.SOURCES if item.edition == 101)
    eo104 = next(item for item in downloader.SOURCES if item.edition == 104)
    assert downloader._euro_codes(eo99.edition) == ("EA15",)
    assert downloader._euro_codes(eo101.edition) == ("EA16",)
    assert downloader._euro_codes(eo104.edition) == ("EA17",)

    spec, payload = eo100_legacy_fixture
    rows = downloader.normalize_payload(spec, payload)
    euro_rows = [row for row in rows if row["currency"] == "EUR"]
    assert {row["aggregate_variant"] for row in euro_rows} == {"EA15", "EA16"}
    assert {row["economy_name"] for row in euro_rows} == {
        "Euro area (15 countries)",
        "Euro area (16 countries)",
    }
    assert all(row["composition_break"] is True for row in euro_rows)
    assert all(
        row["currency_mapping_quality"]
        == "ambiguous_composition_requires_explicit_selection"
        for row in euro_rows
    )
    assert all(
        row["cross_edition_comparability"] == "composition_specific_no_automatic_splice"
        for row in euro_rows
    )


def test_legacy_parser_keeps_future_target_units_and_date_only_availability(
    eo100_legacy_fixture: tuple[downloader.SourceSpec, bytes],
) -> None:
    spec, payload = eo100_legacy_fixture
    rows = downloader.normalize_payload(spec, payload)

    assert len(rows) == len(spec.economy_codes) * len(downloader.MEASURES)
    assert {row["target_period"] for row in rows} == {"2018"}
    assert {row["forecast_horizon_years"] for row in rows} == {2}
    assert all(row["is_future_target"] is True for row in rows)
    # EO100 was published on Saturday; the next weekday is Monday.
    assert {row["available_time"] for row in rows} == {"2016-12-19T00:00:00Z"}
    assert {row["frequency_code"] for row in rows} == {"A"}
    assert {row["frequency_name"] for row in rows} == {"Annual"}
    assert {row["unit_code"] for row in rows} == {"PC"}
    assert {row["unit_name"] for row in rows} == {"Percentage"}
    assert all(row["release_kind"] == "official_date_only_forecast_edition" for row in rows)
    assert not any(row["is_actual_release_vintage"] for row in rows)
    assert not any(row["is_consensus_surprise"] for row in rows)
    assert not any(row["strict_intraday_eligible"] for row in rows)


def test_modern_schema_normalizes_to_the_same_contract(
    eo118_modern_fixture: tuple[downloader.SourceSpec, bytes],
) -> None:
    spec, payload = eo118_modern_fixture
    rows = downloader.normalize_payload(spec, payload)

    assert {row["economy_code"] for row in rows} == set(spec.economy_codes)
    assert {row["measure_code"] for row in rows} == set(downloader.MEASURES)
    assert {row["raw_sha256"] for row in rows} == {hashlib.sha256(payload).hexdigest()}
    assert {row["scenario"] for row in rows} == {"baseline"}


def test_eo107_single_and_double_hit_remain_separate_normalized_keys(
    tmp_path: Path,
) -> None:
    single = next(item for item in downloader.SOURCES if item.source_id == "eo107_single_hit")
    double = next(item for item in downloader.SOURCES if item.source_id == "eo107_double_hit")
    single_rows = downloader.normalize_payload(single, _payload(single))
    double_rows = downloader.normalize_payload(double, _payload(double))

    output = tmp_path / "eo107.csv.gz"
    downloader._write_normalized([*single_rows, *double_rows], output)
    with gzip.open(output, "rt", encoding="utf-8") as handle:
        result = list(csv.DictReader(handle))
    assert {row["scenario"] for row in result} == {"single_hit", "double_hit"}
    assert len(result) == len(single_rows) + len(double_rows)


def test_duplicate_and_out_of_gate_rows_fail_closed(
    eo100_legacy_fixture: tuple[downloader.SourceSpec, bytes],
) -> None:
    spec, _ = eo100_legacy_fixture
    with pytest.raises(ValueError, match="duplicate observation key"):
        downloader.normalize_payload(spec, _payload(spec, duplicate=True))
    with pytest.raises(ValueError, match="escaped the query gate"):
        downloader.normalize_payload(
            spec,
            _payload(spec, target_period=spec.end_period + 1),
        )


def test_fetch_rejects_unsafe_host_and_oversized_response() -> None:
    spec = downloader.SOURCES[0]
    unsafe = dataclasses.replace(
        spec,
        url=spec.url.replace("sdmx.oecd.org", "example.test"),
    )
    with pytest.raises(ValueError, match="official OECD"):
        downloader._validate_source_spec(unsafe)

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"Content-Length": "9999"},
            content=b"small body",
        )
    )
    with pytest.raises(ValueError, match="size gate"):
        downloader._fetch(
            spec,
            timeout=1,
            retries=0,
            transport=transport,
            max_response_bytes=100,
        )


def test_cloudflare_archive_challenge_with_zero_retry_after_fails_immediately() -> None:
    spec = downloader.SOURCES[0]
    calls = 0
    sleeps: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            429,
            headers={
                "Retry-After": "0",
                "Server": "cloudflare",
                "CF-Ray": "fixture-LAX",
                "Set-Cookie": "__cf_bm=fixture; Secure",
            },
        )

    with pytest.raises(ValueError, match="official archive access blocked by Cloudflare"):
        downloader._fetch(
            spec,
            timeout=1,
            retries=3,
            transport=httpx.MockTransport(handler),
            sleep=sleeps.append,
        )
    assert calls == 1
    assert sleeps == []


@pytest.mark.parametrize(
    ("retry_after", "expected_delay"),
    [("7", 7.0), ("999", downloader.MAX_RETRY_AFTER_SECONDS)],
)
def test_positive_retry_after_is_respected_with_a_cap(
    retry_after: str,
    expected_delay: float,
) -> None:
    spec = downloader.SOURCES[0]
    calls = 0
    sleeps: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                headers={
                    "Retry-After": retry_after,
                    "Server": "cloudflare",
                    "CF-Ray": "fixture-LAX",
                },
            )
        return httpx.Response(200, content=b"small official CSV fixture")

    payload, _ = downloader._fetch(
        spec,
        timeout=1,
        retries=1,
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )
    assert payload == b"small official CSV fixture"
    assert calls == 2
    assert sleeps == [expected_delay]


def test_download_archives_hashes_manifests_and_reuses_cache(tmp_path: Path) -> None:
    selected = (
        next(item for item in downloader.SOURCES if item.source_id == "eo100_baseline"),
        next(item for item in downloader.SOURCES if item.source_id == "eo107_single_hit"),
        next(item for item in downloader.SOURCES if item.source_id == "eo107_double_hit"),
        next(item for item in downloader.SOURCES if item.source_id == "eo118_baseline"),
    )
    payloads = {item.url: _payload(item) for item in selected}
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        return httpx.Response(
            200,
            headers={"Content-Type": "text/csv", "ETag": '"fixture"'},
            content=payloads[url],
        )

    now = datetime(2026, 7, 16, 4, 5, tzinfo=UTC)
    normalized_path, manifest_path = downloader.download_dataset(
        tmp_path,
        refresh=True,
        transport=httpx.MockTransport(handler),
        request_delay=0,
        now=now,
        sources=selected,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert len(calls) == 4
    assert manifest["rows"] == sum(
        len(item.economy_codes) * len(downloader.MEASURES) for item in selected
    )
    assert manifest["query_gate"]["full_dataflow_fallback"] is False
    assert manifest["euro_area_aggregate_variants"] == ["EA15", "EA16", "EA17"]
    assert hashlib.sha256(normalized_path.read_bytes()).hexdigest() == manifest[
        "normalized_sha256"
    ]
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert manifest_path.with_suffix(".sha256").read_text().strip() == manifest_hash
    assert all((tmp_path / item["cache_path"]).is_file() for item in manifest["sources"])
    assert all((tmp_path / item["archive_path"]).is_file() for item in manifest["sources"])
    assert not list(tmp_path.rglob("*.tmp"))

    def should_not_fetch(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("valid cached OECD sources must be reused")

    second_path, _ = downloader.download_dataset(
        tmp_path,
        refresh=False,
        transport=httpx.MockTransport(should_not_fetch),
        request_delay=0,
        now=now,
        sources=selected,
    )
    assert second_path.read_bytes() == normalized_path.read_bytes()


def test_tampered_manifest_fails_sidecar_verification(tmp_path: Path) -> None:
    spec = downloader.SOURCES[0]
    payload = _payload(spec)
    _, manifest_path = downloader.download_dataset(
        tmp_path,
        refresh=True,
        transport=_transport_for(spec, payload),
        request_delay=0,
        sources=(spec,),
    )
    manifest_path.write_bytes(manifest_path.read_bytes() + b" ")

    with pytest.raises(ValueError, match="manifest SHA-256 verification failed"):
        downloader.download_dataset(
            tmp_path,
            refresh=False,
            transport=_transport_for(spec, payload),
            request_delay=0,
            sources=(spec,),
        )


def test_manifest_source_without_valid_sha_is_rejected_even_with_fresh_sidecar(
    tmp_path: Path,
) -> None:
    spec = downloader.SOURCES[0]
    payload = _payload(spec)
    _, manifest_path = downloader.download_dataset(
        tmp_path,
        refresh=True,
        transport=_transport_for(spec, payload),
        request_delay=0,
        sources=(spec,),
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sources"][0].pop("sha256")
    tampered = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode()
    manifest_path.write_bytes(tampered)
    manifest_path.with_suffix(".sha256").write_text(
        hashlib.sha256(tampered).hexdigest() + "\n",
        encoding="ascii",
    )

    with pytest.raises(ValueError, match="invalid SHA-256"):
        downloader.download_dataset(
            tmp_path,
            refresh=False,
            request_delay=0,
            sources=(spec,),
        )


def test_orphan_cache_is_rejected_but_explicit_refresh_replaces_it(tmp_path: Path) -> None:
    spec = downloader.SOURCES[0]
    payload = _payload(spec)
    cache_path = tmp_path / "raw" / "cache" / f"{spec.source_id}.csv"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_bytes(payload)

    with pytest.raises(ValueError, match="orphan cache"):
        downloader.download_dataset(
            tmp_path,
            refresh=False,
            request_delay=0,
            sources=(spec,),
        )

    downloader.download_dataset(
        tmp_path,
        refresh=True,
        transport=_transport_for(spec, payload),
        request_delay=0,
        sources=(spec,),
    )
    assert cache_path.read_bytes() == payload


def test_tampered_cache_is_rejected_against_verified_manifest(tmp_path: Path) -> None:
    spec = downloader.SOURCES[0]
    payload = _payload(spec)
    downloader.download_dataset(
        tmp_path,
        refresh=True,
        transport=_transport_for(spec, payload),
        request_delay=0,
        sources=(spec,),
    )
    cache_path = tmp_path / "raw" / "cache" / f"{spec.source_id}.csv"
    cache_path.write_bytes(payload + b"\n")

    with pytest.raises(ValueError, match="cached response hash differs"):
        downloader.download_dataset(
            tmp_path,
            refresh=False,
            request_delay=0,
            sources=(spec,),
        )
