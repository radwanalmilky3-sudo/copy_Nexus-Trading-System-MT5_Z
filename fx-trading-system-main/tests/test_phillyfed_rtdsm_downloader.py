from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "download_phillyfed_rtdsm.py"
SPEC = importlib.util.spec_from_file_location("phillyfed_rtdsm_downloader", SCRIPT_PATH)
assert SPEC and SPEC.loader
downloader = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = downloader
SPEC.loader.exec_module(downloader)


def _xlsx(sheet: str, frame: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name=sheet, index=False)
    return buffer.getvalue()


def test_cpi_wide_vintages_become_date_level_pit_long_rows() -> None:
    payload = _xlsx(
        "cpi",
        pd.DataFrame(
            {
                "DATE": ["2019:09", "2019:10", "2019:11", "2019:12", "2020:01"],
                "CPI19Q4": [100.0, 100.1, None, None, None],
                "CPI20Q1": [100.2, 100.3, 100.4, 100.5, 100.6],
                "CPI20Q3": [100.7, 100.8, 100.9, 101.0, 101.1],
            }
        ),
    )

    rows = downloader.parse_cpi_vintages(payload, "https://example.test/cpi.xlsx")
    result = pd.DataFrame(rows)

    assert len(result) == 12
    q1 = result[result["vintage_label"] == "CPI20Q1"]
    assert set(q1["vintage_period"]) == {"2020-Q1"}
    assert set(q1["vintage_date"]) == {"2020-02-15"}
    assert set(q1["available_time"]) == {"2020-02-16T05:00:00+00:00"}
    q3 = result[result["vintage_label"] == "CPI20Q3"]
    assert set(q3["available_time"]) == {"2020-08-16T04:00:00+00:00"}
    assert set(result["quality"]) == {"official_quarterly_vintage_date_level"}
    assert result["pit_eligible"].all()
    assert "2020-01-31T00:00:00+00:00" in set(q1["observation_time"])


def test_ip_uses_verified_g17_day_and_conservative_unresolved_month() -> None:
    archive = b"""
    <a href="20191217/">release</a>
    <a href="20200117/g17.pdf">release</a>
    <a href="20200214/">release</a>
    <a href="20200317/">release</a>
    <a href="20200415/">release</a>
    <a href="20200515/">release</a>
    <a href="20200616/">release</a>
    <a href="20200715/">release</a>
    <a href="20200814/">release</a>
    <a href="20200915/">release</a>
    <a href="20201016/">release</a>
    <a href="20201117/">release</a>
    <a href="20201215/">release</a>
    <a href="./Revisions/20200125/default_rev.htm">revision</a>
    """
    release_dates = downloader.parse_g17_release_dates(archive)
    release_dates.pop((2020, 2))
    payload = _xlsx(
        "ipt",
        pd.DataFrame(
            {
                "DATE": ["2019:10", "2019:11", "2019:12", "2020:01"],
                "IPT19M12": [101.0, 101.1, None, None],
                "IPT20M1": [101.2, 101.3, 101.4, None],
                "IPT20M2": [101.5, 101.6, 101.7, 101.8],
            }
        ),
    )

    rows = downloader.parse_ip_vintages(payload, release_dates)
    result = pd.DataFrame(rows)

    january = result[result["vintage_label"] == "IPT20M1"]
    assert set(january["vintage_date"]) == {"2020-01-17"}
    assert set(january["available_time"]) == {"2020-01-18T05:00:00+00:00"}
    assert set(january["availability_policy"]) == {"after_verified_g17_release_date"}
    february = result[result["vintage_label"] == "IPT20M2"]
    assert set(february["vintage_date"]) == {""}
    assert set(february["available_time"]) == {"2020-03-01T05:00:00+00:00"}
    assert set(february["quality"]) == {"official_monthly_vintage_conservative_month_end"}


def test_latest_ordinary_g17_release_wins_but_revision_links_do_not() -> None:
    filler = "".join(f'<a href="2021{month:02d}15/">release</a>' for month in range(1, 13))
    payload = (
        filler
        + '<a href="20211223/">later ordinary release</a>'
        + '<a href="./Revisions/20211229/default_rev.htm">revision</a>'
    ).encode()

    releases = downloader.parse_g17_release_dates(payload)

    assert releases[(2021, 12)].isoformat() == "2021-12-23"


def test_parser_rejects_observation_not_yet_available() -> None:
    payload = _xlsx(
        "cpi",
        pd.DataFrame(
            {
                "DATE": ["2020:01", "2020:02", "2020:03"],
                "CPI20Q1": [100.0, 100.1, 100.2],
                "CPI20Q2": [100.3, 100.4, 100.5],
            }
        ),
    )

    with pytest.raises(ValueError, match="at/after availability"):
        downloader.parse_cpi_vintages(payload)


def test_writer_rejects_duplicate_vintage_observation_key(tmp_path: Path) -> None:
    payload = _xlsx(
        "cpi",
        pd.DataFrame(
            {
                "DATE": ["2019:12", "2020:01"],
                "CPI20Q1": [100.0, 100.1],
                "CPI20Q2": [100.2, 100.3],
            }
        ),
    )
    rows = downloader.parse_cpi_vintages(payload)

    with pytest.raises(ValueError, match="duplicate"):
        downloader._write_vintages([rows[0], rows[0]], tmp_path / "vintages.csv")


def test_writer_produces_deterministic_gzip_csv(tmp_path: Path) -> None:
    payload = _xlsx(
        "cpi",
        pd.DataFrame(
            {
                "DATE": ["2019:12", "2020:01"],
                "CPI20Q1": [100.0, 100.1],
                "CPI20Q2": [100.2, 100.3],
            }
        ),
    )
    rows = downloader.parse_cpi_vintages(payload)
    path = tmp_path / "vintages.csv.gz"

    first_hash = downloader._write_vintages(list(reversed(rows)), path)
    first_payload = path.read_bytes()
    second_hash = downloader._write_vintages(rows, path)

    assert first_hash == second_hash == hashlib.sha256(first_payload).hexdigest()
    result = pd.read_csv(path)
    assert len(result) == 4
    assert result["pit_eligible"].all()


def _manifest_fixture(root: Path, *, schema_version: int = 2) -> Path:
    retrieved = datetime(2026, 7, 16, 1, 2, 3, tzinfo=UTC).isoformat()
    sources: list[dict[str, object]] = []
    for index, (key, (url, relative)) in enumerate(downloader.SOURCE_CONTRACT.items()):
        payload = f"source-{index}".encode()
        raw = root / relative
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        archive = root / "archive" / key / "2026" / f"fixture_{digest[:16]}.bin"
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(payload)
        sources.append(
            {
                "key": key,
                "url": url,
                "path": relative,
                "archive_path": archive.relative_to(root).as_posix(),
                "retrieved_at": retrieved,
                "bytes": len(payload),
                "sha256": digest,
            }
        )
    normalized = root / "normalized" / "phillyfed_rtdsm_vintages.csv.gz"
    normalized.parent.mkdir(parents=True)
    normalized.write_bytes(b"normalized")
    archive_manifest = root / "manifests" / "rtdsm_fixture.json"
    manifest = {
        "schema_version": schema_version,
        "program_version": (
            downloader.PROGRAM_VERSION if schema_version == 2 else "phillyfed-rtdsm-v2"
        ),
        "normalized_path": normalized.relative_to(root).as_posix(),
        "normalized_sha256": hashlib.sha256(normalized.read_bytes()).hexdigest(),
        "sources": sources,
    }
    if schema_version == 2:
        manifest["manifest_archive_path"] = archive_manifest.relative_to(root).as_posix()
    payload = (json.dumps(manifest, indent=2) + "\n").encode()
    latest = root / "phillyfed_rtdsm_manifest.json"
    latest.write_bytes(payload)
    if schema_version == 2:
        digest = hashlib.sha256(payload).hexdigest()
        archive_manifest.parent.mkdir(parents=True)
        archive_manifest.write_bytes(payload)
        latest.with_suffix(".sha256").write_text(
            f"{digest}  {latest.name}\n", encoding="ascii"
        )
        archive_manifest.with_suffix(".json.sha256").write_text(
            f"{digest}  {archive_manifest.name}\n", encoding="ascii"
        )
    return latest


def test_complete_manifest_raw_archive_and_normalized_chain_is_reusable(
    tmp_path: Path,
) -> None:
    latest = _manifest_fixture(tmp_path)

    manifest = downloader._load_previous_manifest(
        tmp_path.resolve(), latest, allow_legacy_migration=False
    )

    assert manifest["schema_version"] == 2
    assert len(manifest["sources"]) == 3


@pytest.mark.parametrize("target", ["raw", "archive", "normalized", "manifest", "sidecar"])
def test_cached_integrity_tampering_fails_closed(tmp_path: Path, target: str) -> None:
    latest = _manifest_fixture(tmp_path)
    manifest = json.loads(latest.read_text(encoding="utf-8"))
    if target == "raw":
        (tmp_path / manifest["sources"][0]["path"]).write_bytes(b"tampered")
    elif target == "archive":
        (tmp_path / manifest["sources"][0]["archive_path"]).write_bytes(b"tampered")
    elif target == "normalized":
        (tmp_path / manifest["normalized_path"]).write_bytes(b"tampered")
    elif target == "manifest":
        latest.write_bytes(latest.read_bytes() + b"\n")
    else:
        latest.with_suffix(".sha256").write_text(
            f"{'0' * 64}  {latest.name}\n", encoding="ascii"
        )

    with pytest.raises(ValueError, match="SHA-256|manifest|source"):
        downloader._load_previous_manifest(
            tmp_path.resolve(), latest, allow_legacy_migration=False
        )


def test_orphan_cache_rejected_and_v2_requires_explicit_refresh_migration(
    tmp_path: Path,
) -> None:
    orphan_root = tmp_path / "orphan"
    first_relative = next(iter(downloader.SOURCE_CONTRACT.values()))[1]
    orphan = orphan_root / first_relative
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"orphan")
    with pytest.raises(ValueError, match="partial|orphan"):
        downloader._load_previous_manifest(
            orphan_root.resolve(),
            orphan_root / "phillyfed_rtdsm_manifest.json",
            allow_legacy_migration=False,
        )

    legacy_root = tmp_path / "legacy"
    latest = _manifest_fixture(legacy_root, schema_version=1)
    with pytest.raises(ValueError, match="requires --refresh"):
        downloader._load_previous_manifest(
            legacy_root.resolve(), latest, allow_legacy_migration=False
        )
    migrated = downloader._load_previous_manifest(
        legacy_root.resolve(), latest, allow_legacy_migration=True
    )
    assert migrated["program_version"] == "phillyfed-rtdsm-v2"
