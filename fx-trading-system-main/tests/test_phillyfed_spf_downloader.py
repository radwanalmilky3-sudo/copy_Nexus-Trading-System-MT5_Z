from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "download_phillyfed_spf.py"
SPEC = importlib.util.spec_from_file_location("phillyfed_spf_downloader", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
downloader = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = downloader
SPEC.loader.exec_module(downloader)


def _release_text(*, omit: tuple[int, int] | None = None) -> bytes:
    lines = [
        "Deadline and Release Dates for the Survey of Professional Forecasters",
        "Survey True Deadline Date News Release Date",
        "1990 Q2 8/23/90* 8/31/90*",
        "     Q3 8/23/90 8/31/90",
        "     Q4 11/22/90 11/28/90",
    ]
    for year in range(2016, 2026):
        for quarter, month in enumerate((2, 5, 8, 11), start=1):
            if (year, quarter) == omit:
                continue
            prefix = f"{year} " if quarter == 1 else "     "
            deadline_day = 9
            release_day = 12
            if (year, quarter) == (2019, 1):
                month, deadline_day, release_day = 3, 12, 22
            lines.append(
                f"{prefix}Q{quarter} {month}/{deadline_day}/{year % 100:02d} "
                f"{month}/{release_day}/{year % 100:02d}"
            )
    return ("\n".join(lines) + "\n").encode()


def _xlsx() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as workbook:
        workbook.writestr("[Content_Types].xml", "<Types/>")
        workbook.writestr("xl/workbook.xml", "<workbook/>")
        workbook.writestr("xl/worksheets/sheet1.xml", "<worksheet/>")
    return output.getvalue()


def _payload(spec: downloader.SourceSpec) -> bytes:
    if spec.key == "spf_release_dates":
        return _release_text()
    if spec.kind == "xlsx":
        return _xlsx()
    if spec.kind == "pdf":
        return b"%PDF-1.4\nfixture\n%%EOF\n"
    if spec.kind == "terms":
        return (
            b"<html>informational, educational, and research purposes only; "
            b"you may not engage in excessive access</html>"
        )
    if spec.kind == "robots":
        return b"User-agent: *\nDisallow: /api/\n"
    return f"<html><title>{spec.expected_marker}</title></html>".encode()


def _fetcher(spec: downloader.SourceSpec, _timeout: float, _retries: int) -> bytes:
    return _payload(spec)


def _download(tmp_path: Path) -> tuple[Path, Path]:
    return downloader.download_dataset(
        tmp_path,
        refresh=False,
        timeout=1,
        retries=0,
        delay=0,
        fetcher=_fetcher,
        retrieved_at=datetime(2026, 7, 16, 1, 2, 3, tzinfo=UTC),
    )


def _rewrite_manifest(root: Path, manifest: dict[str, object]) -> None:
    payload = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode()
    digest = hashlib.sha256(payload).hexdigest()
    latest = root / "phillyfed_spf_manifest.json"
    archive = root / str(manifest["manifest_archive_path"])
    latest.write_bytes(payload)
    archive.write_bytes(payload)
    (root / "phillyfed_spf_manifest.sha256").write_text(
        f"{digest}  {latest.name}\n", encoding="ascii"
    )
    archive.with_suffix(archive.suffix + ".sha256").write_text(
        f"{digest}  {archive.name}\n", encoding="ascii"
    )


def test_release_parser_has_exact_2016_2025_date_only_coverage() -> None:
    rows = downloader.parse_release_dates(_release_text())

    assert len(rows) == 40
    assert rows[0]["survey_period"] == "2016-Q1"
    delayed = next(row for row in rows if row["survey_period"] == "2019-Q1")
    assert delayed["response_deadline_date"] == "2019-03-12"
    assert delayed["news_release_date"] == "2019-03-22"
    assert delayed["available_time"] == "2019-03-23T04:00:00+00:00"
    assert delayed["date_evidence_quality"] == "verified_official_historical_release_date"
    assert delayed["value_strict_pit_eligible"] is False
    assert delayed["strict_intraday_eligible"] is False


def test_release_parser_rejects_missing_and_duplicate_quarters() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        downloader.parse_release_dates(_release_text(omit=(2020, 2)))

    duplicate = _release_text() + b"2025 Q4 11/9/25 11/12/25\n"
    with pytest.raises(ValueError, match="duplicate"):
        downloader.parse_release_dates(duplicate)


def test_download_archives_sources_and_marks_values_non_strict(tmp_path: Path) -> None:
    normalized, manifest_path = _download(tmp_path)

    with normalized.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(rows) == 40
    assert {row["value_strict_pit_eligible"] for row in rows} == {"False"}
    assert manifest["complete"] is True
    assert manifest["research_status"] == "release_calendar_eligible_values_fail_closed"
    assert manifest["strict_pit"] == {
        "release_dates": True,
        "forecast_values": False,
        "strict_intraday": False,
    }
    assert len(manifest["sources"]) == len(downloader.SOURCES)
    assert downloader._validate_existing_dataset(tmp_path) == manifest


def test_verified_cache_reuse_performs_no_network_calls(tmp_path: Path) -> None:
    normalized, manifest = _download(tmp_path)

    def forbidden(*_args: object) -> bytes:
        raise AssertionError("verified cache should not call the network")

    reused = downloader.download_dataset(
        tmp_path,
        refresh=False,
        timeout=1,
        retries=0,
        delay=0,
        fetcher=forbidden,
    )
    assert reused == (normalized, manifest)


@pytest.mark.parametrize("target", ["raw", "archive", "normalized", "manifest", "sidecar"])
def test_raw_archive_normalized_manifest_and_sidecar_tampering_fail_closed(
    tmp_path: Path, target: str
) -> None:
    _, manifest_path = _download(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    first = manifest["sources"][0]
    if target == "raw":
        (tmp_path / first["path"]).write_bytes(b"tampered")
    elif target == "archive":
        (tmp_path / first["archive_path"]).write_bytes(b"tampered")
    elif target == "normalized":
        (tmp_path / manifest["normalized_path"]).write_bytes(b"tampered")
    elif target == "manifest":
        manifest_path.write_bytes(manifest_path.read_bytes() + b"\n")
    else:
        (tmp_path / "phillyfed_spf_manifest.sha256").write_text(
            f"{'0' * 64}  phillyfed_spf_manifest.json\n", encoding="ascii"
        )

    with pytest.raises(ValueError, match="SHA-256|manifest|response"):
        downloader._validate_existing_dataset(tmp_path)


def test_orphan_partial_cache_and_duplicate_manifest_sources_are_rejected(
    tmp_path: Path,
) -> None:
    orphan = tmp_path / downloader.SOURCES[0].relative_path
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(_payload(downloader.SOURCES[0]))
    with pytest.raises(ValueError, match="partial|orphan"):
        downloader._validate_existing_dataset(tmp_path)

    complete_root = tmp_path / "complete"
    _, manifest_path = _download(complete_root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sources"].append(dict(manifest["sources"][0]))
    _rewrite_manifest(complete_root, manifest)
    with pytest.raises(ValueError, match="source set|duplicate"):
        downloader._validate_existing_dataset(complete_root)


def test_source_payload_and_host_gates_reject_soft_errors_and_unsafe_urls() -> None:
    spec = downloader.SOURCES[0]
    with pytest.raises(ValueError, match="soft error"):
        downloader._validate_payload(
            spec,
            b"<html><title>Error - 404</title>Survey of Professional Forecasters</html>",
        )
    unsafe = downloader.SourceSpec(
        "unsafe", "https://example.test/file.xlsx", "raw/file.xlsx", "xlsx"
    )
    with pytest.raises(ValueError, match="official Philadelphia Fed"):
        downloader._validate_url(unsafe)


def test_terms_and_robots_evidence_are_semantically_gated() -> None:
    terms = next(spec for spec in downloader.SOURCES if spec.kind == "terms")
    robots = next(spec for spec in downloader.SOURCES if spec.kind == "robots")
    with pytest.raises(ValueError, match="excessive-access"):
        downloader._validate_payload(
            terms,
            b"<html>informational, educational, and research purposes only</html>",
        )
    with pytest.raises(ValueError, match="disallows"):
        downloader._validate_payload(
            robots,
            b"User-agent: *\nDisallow: /surveys-and-data\n",
        )
