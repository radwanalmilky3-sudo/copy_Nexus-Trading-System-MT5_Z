from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd
import pytest

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "download_ons_gdp_realtime.py"
VALID_WORKBOOK_URI = (
    "/economy/grossdomesticproductgdp/datasets/realtimedatabaseforukgdpabmi/"
    "q42025first/abmi.xlsx"
)
SPEC = importlib.util.spec_from_file_location("ons_gdp_realtime_downloader", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
downloader = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = downloader
SPEC.loader.exec_module(downloader)


def _page(spec: downloader.DatasetSpec, editions: list[tuple[str, str]]) -> bytes:
    items = []
    dataset_path = httpx.URL(spec.page_url).path
    for title, slug in editions:
        items.append(
            f"""
            <div>
              <h3>{title} edition of this dataset</h3>
              <a href="/file?uri={dataset_path}/{slug}/{spec.dataset_id}.xlsx">
                <span>xlsx (100.0 KB)</span>
              </a>
            </div>
            """
        )
    return (
        f"""<!doctype html><html><head><title>{spec.series_code}</title></head>
        <body>{''.join(items)}
        <footer><a href="{downloader.LICENSE_URL}">OGL v3.0</a></footer>
        </body></html>"""
    ).encode()


def _catalog_pair() -> tuple[list[downloader.EditionSpec], dict[str, bytes]]:
    pages: dict[str, bytes] = {}
    editions: list[downloader.EditionSpec] = []
    for spec in downloader.DATASETS:
        payload = _page(
            spec,
            [("Quarter 4 (Oct to Dec) 2025, first estimate", "q42025first")],
        )
        pages[spec.page_url] = payload
        editions.extend(
            downloader.parse_dataset_page(
                spec, payload, start_year=2025, end_year=2025
            )
        )
    return editions, pages


def _xlsx(
    series_code: str,
    *,
    release_text: str | None = (
        "The data tables in this spreadsheet were originally published at "
        "07:00 12th February 2026."
    ),
    values: tuple[float, float, float] = (101.0, 102.0, 103.0),
    include_future: bool = False,
    latest_header: str = "Feb-26\n1st",
) -> bytes:
    cover_values = [
        f"Real-time database for GDP ({series_code})",
        "These figures are seasonally adjusted.",
    ]
    if release_text is not None:
        cover_values.append(release_text)
    table = [
        [f"Real-time database ({series_code}), 2018 -", None, None],
        ["This worksheet contains one table.", None, None],
        ["Source: Office for National Statistics", None, None],
        ["Publication date and time period", "Dec-25\nQNA", latest_header],
        ["Q1 2024", 100.0, values[0]],
        ["Q2 2024", 101.0, values[1]],
        ["Q4 2025", 102.0, values[2]],
    ]
    if include_future:
        table.append(["Q1 2026", None, 104.0])
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame(cover_values).to_excel(
            writer, sheet_name="Cover_sheet", header=False, index=False
        )
        pd.DataFrame([["Table of Contents"]]).to_excel(
            writer, sheet_name="Table_of_contents", header=False, index=False
        )
        pd.DataFrame(table).to_excel(
            writer, sheet_name="2018 - ", header=False, index=False
        )
    return buffer.getvalue()


def _transport(payloads: dict[str, bytes]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url not in payloads:
            raise AssertionError(f"unexpected request: {url}")
        content_type = (
            "text/html"
            if not request.url.path.endswith("/file")
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        return httpx.Response(
            200,
            headers={"Content-Type": content_type, "ETag": '"fixture"'},
            content=payloads[url],
        )

    return httpx.MockTransport(handler)


def test_official_pages_enumerate_exact_abmi_ybha_editions_and_sizes() -> None:
    editions, _ = _catalog_pair()

    downloader.validate_catalog_coverage(
        editions,
        expected_counts={2025: 1},
        required_dataset_ids=("abmi", "ybha"),
    )
    assert {item.series_code for item in editions} == {"ABMI", "YBHA"}
    assert {item.edition for item in editions} == {"q42025first"}
    assert all(item.listed_size_bytes == 102_400 for item in editions)
    assert all(
        item.workbook_url.startswith("https://www.ons.gov.uk/file?uri=")
        for item in editions
    )


@pytest.mark.parametrize(
    "url",
    [
        f"http://www.ons.gov.uk/file?uri={VALID_WORKBOOK_URI}",
        f"https://www.ons.gov.uk:444/file?uri={VALID_WORKBOOK_URI}",
        f"https://user@www.ons.gov.uk/file?uri={VALID_WORKBOOK_URI}",
        f"https://www.ons.gov.uk/file?uri={VALID_WORKBOOK_URI}#fragment",
    ],
)
def test_official_url_gate_rejects_noncanonical_origins(url: str) -> None:
    with pytest.raises(ValueError):
        downloader._validate_official_url(url, workbook=True)


def test_catalog_rejects_unsafe_edition_slug() -> None:
    spec = downloader.DATASETS[0]
    payload = _page(spec, [("Quarter 4 2025", "..")])

    with pytest.raises(ValueError, match="unsafe edition slug"):
        downloader.parse_dataset_page(spec, payload, start_year=2025, end_year=2025)


def test_zero_retry_after_still_uses_polite_backoff() -> None:
    spec = downloader.DATASETS[0]
    payload = _page(spec, [("Quarter 4 2025", "q42025first")])
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, content=payload)

    downloaded, _ = downloader._fetch(
        spec.page_url,
        workbook=False,
        timeout=1,
        retries=1,
        transport=httpx.MockTransport(handler),
        sleep=delays.append,
    )

    assert downloaded == payload
    assert attempts == 2
    assert delays == [0.75]


def test_catalog_fails_closed_when_an_edition_or_series_is_missing() -> None:
    editions, _ = _catalog_pair()

    with pytest.raises(ValueError, match="dataset coverage mismatch"):
        downloader.validate_catalog_coverage(
            [item for item in editions if item.dataset_id != "ybha"],
            expected_counts={2025: 1},
            required_dataset_ids=("abmi", "ybha"),
        )


def test_catalog_matches_semantic_editions_despite_official_slug_drift() -> None:
    editions, _ = _catalog_pair()
    abmi = next(item for item in editions if item.dataset_id == "abmi")
    ybha = next(item for item in editions if item.dataset_id == "ybha")
    drifted_abmi = replace(
        abmi,
        edition="quarter3julytosept2025firstestimateedition",
        edition_title="Quarter 3 (July to Sept) 2025, first estimate edition",
    )
    drifted_ybha = replace(
        ybha,
        edition="quarter3julytosept2025firstestimate",
        edition_title="Quarter 3 (July to Sept) 2025, first estimate",
    )
    downloader.validate_catalog_coverage(
        [drifted_abmi, drifted_ybha],
        expected_counts={2025: 1},
    )

    mismatched = replace(drifted_ybha, edition_title="Quarter 2 2025, first estimate")
    with pytest.raises(ValueError, match="semantic edition coverage"):
        downloader.validate_catalog_coverage(
            [drifted_abmi, mismatched],
            expected_counts={2025: 1},
        )
    with pytest.raises(ValueError, match="year coverage mismatch"):
        downloader.validate_catalog_coverage(
            editions,
            expected_counts={2024: 1},
            required_dataset_ids=("abmi", "ybha"),
        )


def test_workbook_schema_normalizes_latest_true_edition_column() -> None:
    editions, _ = _catalog_pair()
    spec = next(item for item in editions if item.series_code == "ABMI")
    payload = _xlsx("ABMI")

    rows = downloader.normalize_workbook(spec, payload)

    assert [row["observation_period"] for row in rows] == [
        "2024-Q1",
        "2024-Q2",
        "2025-Q4",
    ]
    assert [row["value"] for row in rows] == [101.0, 102.0, 103.0]
    assert {row["release_date"] for row in rows} == {"2026-02-12"}
    assert {row["available_time"] for row in rows} == {"2026-02-13T00:00:00Z"}
    assert {row["series_code"] for row in rows} == {"ABMI"}
    assert {row["price_basis"] for row in rows} == {"chained_volume_measure"}
    assert {row["seasonal_adjustment"] for row in rows} == {
        "seasonally_adjusted"
    }
    assert {row["frequency"] for row in rows} == {"quarterly"}
    assert {row["unit"] for row in rows} == {"GBP_million"}
    assert {row["source_sha256"] for row in rows} == {
        hashlib.sha256(payload).hexdigest()
    }
    assert {row["growth_rate_policy"] for row in rows} == {
        "same_edition_only_not_computed_by_downloader"
    }


def test_future_observation_and_wrong_series_workbook_are_rejected() -> None:
    editions, _ = _catalog_pair()
    abmi = next(item for item in editions if item.series_code == "ABMI")

    with pytest.raises(ValueError, match="future observation 2026-Q1"):
        downloader.normalize_workbook(abmi, _xlsx("ABMI", include_future=True))
    with pytest.raises(ValueError, match="lacks series code ABMI"):
        downloader.normalize_workbook(abmi, _xlsx("YBHA"))


def test_missing_original_publication_date_fails_closed_instead_of_using_page_date() -> None:
    editions, _ = _catalog_pair()
    spec = editions[0]

    with pytest.raises(
        downloader.ReleaseDateUnavailable,
        match="original publication date",
    ):
        downloader.normalize_workbook(spec, _xlsx(spec.series_code, release_text=None))


def test_revisions_remain_attached_to_their_edition_without_latest_backfill() -> None:
    editions, _ = _catalog_pair()
    first = next(item for item in editions if item.series_code == "ABMI")
    second = replace(
        first,
        edition="q42025qna",
        edition_title="Quarter 4 (Oct to Dec) 2025, quarterly national accounts",
    )
    first_rows = downloader.normalize_workbook(
        first, _xlsx("ABMI", values=(101.0, 102.0, 103.0))
    )
    second_rows = downloader.normalize_workbook(
        second, _xlsx("ABMI", values=(111.0, 112.0, 113.0))
    )

    combined = downloader.combine_edition_rows([first_rows, second_rows])
    q1 = [row for row in combined if row["observation_period"] == "2024-Q1"]

    assert len(q1) == 2
    assert {(row["edition"], row["value"]) for row in q1} == {
        ("q42025first", 101.0),
        ("q42025qna", 111.0),
    }


def test_catalog_cache_archive_manifest_and_hash_tamper_gate(tmp_path: Path) -> None:
    _, pages = _catalog_pair()
    now = datetime(2026, 7, 16, 12, tzinfo=UTC)

    editions, catalog_path, manifest_path = downloader.build_catalog(
        tmp_path,
        refresh=True,
        transport=_transport(pages),
        request_delay=0,
        now=now,
        expected_counts={2025: 1},
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert len(editions) == 2
    assert manifest["catalog_complete"] is True
    assert manifest["normalization_complete"] is False
    assert manifest["edition_count"] == 2
    assert hashlib.sha256(catalog_path.read_bytes()).hexdigest() == manifest[
        "catalog_sha256"
    ]
    assert all((tmp_path / row["archive_path"]).is_file() for row in manifest["catalog_pages"])
    assert not list(tmp_path.rglob("*.tmp"))

    cache = tmp_path / "raw" / "catalog_pages" / "abmi.html"
    cache.write_bytes(cache.read_bytes() + b" ")
    with pytest.raises(ValueError, match="cached response hash differs"):
        downloader.build_catalog(
            tmp_path,
            refresh=False,
            transport=_transport(pages),
            request_delay=0,
            now=now,
            expected_counts={2025: 1},
        )


@pytest.mark.parametrize("tamper", ["cache_and_sidecar", "catalog", "archive_manifest", "orphan"])
def test_catalog_prior_manifest_rejects_cache_washing_and_orphans(
    tmp_path: Path, tamper: str
) -> None:
    _, pages = _catalog_pair()
    now = datetime(2026, 7, 16, 12, tzinfo=UTC)
    _, catalog_path, manifest_path = downloader.build_catalog(
        tmp_path,
        refresh=True,
        transport=_transport(pages),
        request_delay=0,
        now=now,
        expected_counts={2025: 1},
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if tamper == "cache_and_sidecar":
        cache = tmp_path / manifest["catalog_pages"][0]["cache_path"]
        changed = cache.read_bytes() + b" changed"
        cache.write_bytes(changed)
        downloader._cache_sidecar(cache).write_bytes(downloader._digest_sidecar_payload(changed))
        match = "prior catalog cache disagrees"
    elif tamper == "catalog":
        catalog_path.write_bytes(catalog_path.read_bytes() + b"changed")
        match = "normalized catalog hash"
    elif tamper == "archive_manifest":
        archive = tmp_path / manifest["manifest_archive_path"]
        archive.write_bytes(archive.read_bytes() + b"changed")
        match = "latest and archived manifests disagree"
    else:
        orphan = tmp_path / "raw/catalog_pages/orphan.html"
        orphan.write_bytes(b"orphan")
        downloader._cache_sidecar(orphan).write_bytes(
            downloader._digest_sidecar_payload(b"orphan")
        )
        match = "orphan or missing files"

    with pytest.raises(ValueError, match=match):
        downloader.build_catalog(
            tmp_path,
            refresh=False,
            transport=_transport(pages),
            request_delay=0,
            now=now,
            expected_counts={2025: 1},
        )


def test_workbook_download_archives_hashes_and_writes_complete_normalized_panel(
    tmp_path: Path,
) -> None:
    editions, _ = _catalog_pair()
    payloads = {
        item.workbook_url: _xlsx(item.series_code)
        for item in editions
    }
    now = datetime(2026, 7, 16, 13, tzinfo=UTC)

    normalized, audit, manifest_path = downloader.download_workbooks(
        tmp_path,
        editions,
        refresh=True,
        transport=_transport(payloads),
        request_delay=0,
        now=now,
    )
    assert normalized is not None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frame = pd.read_csv(normalized)

    assert manifest["normalization_complete"] is True
    assert manifest["partial_normalized_file_written"] is False
    assert set(frame["series_code"]) == {"ABMI", "YBHA"}
    assert len(frame) == 6
    assert audit.is_file()
    assert all((tmp_path / row["archive_path"]).is_file() for row in manifest["sources"])
    assert not list(tmp_path.rglob("*.tmp"))

    first_cache = tmp_path / manifest["sources"][0]["cache_path"]
    first_cache.write_bytes(first_cache.read_bytes() + b" ")
    with pytest.raises(ValueError, match="cached response hash differs"):
        downloader.download_workbooks(
            tmp_path,
            editions,
            refresh=False,
            transport=_transport(payloads),
            request_delay=0,
            now=now,
        )


def test_incomplete_workbook_dates_write_only_fail_closed_audit(tmp_path: Path) -> None:
    editions, _ = _catalog_pair()
    payloads = {
        item.workbook_url: _xlsx(
            item.series_code,
            release_text=(
                None
                if item.series_code == "ABMI"
                else "The data tables in this spreadsheet were originally "
                "published at 07:00 12th February 2026."
            ),
        )
        for item in editions
    }

    normalized, audit, manifest_path = downloader.download_workbooks(
        tmp_path,
        editions,
        refresh=True,
        transport=_transport(payloads),
        request_delay=0,
        require_complete_normalization=False,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert normalized is None
    assert audit.is_file()
    assert manifest["normalization_complete"] is False
    assert manifest["partial_normalized_file_written"] is False
    assert len(manifest["normalization_blockers"]) == 1
    assert not (tmp_path / "normalized" / "ons_gdp_realtime_observations.csv").exists()
