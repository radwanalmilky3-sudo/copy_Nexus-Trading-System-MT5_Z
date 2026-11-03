from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "audit_treasury_tic_revisions.py"
SPEC = importlib.util.spec_from_file_location("treasury_tic_revision_audit", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
audit = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit
SPEC.loader.exec_module(audit)

CATALOG_COLUMNS = (
    "archive_id",
    "available_time",
    "reference_month",
    "file_date",
    "downloaded",
    "sha256",
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _values(seed: int) -> list[int]:
    return [seed + index for index in range(32)]


def _npr_csv(observations: list[tuple[str, list[int]]], *, numeric: bool = False) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    if numeric:
        writer.writerow(["", *range(1, 33)])
    else:
        writer.writerow(
            [
                "",
                "TIC monthly reports on Cross-Border Portfolio Financial Flows",
                *([""] * 31),
            ]
        )
        writer.writerow(["table -->", *[f"[{index}]" for index in range(1, 33)]])
    for period, values in observations:
        writer.writerow([period, *values])
    return output.getvalue().encode()


def _npr_txt(observations: list[tuple[str, list[int]]]) -> bytes:
    lines = ["TIC monthly reports on Cross-Border Portfolio Financial Flows"]
    lines.extend(f"{period} " + " ".join(map(str, values)) for period, values in observations)
    return ("\r\n".join(lines) + "\r\n").encode()


def _npr_html(observations: list[tuple[str, list[int]]]) -> bytes:
    rows = []
    for period, values in observations:
        cells = "".join(f"<td>{value}</td>" for value in values)
        rows.append(f"<tr><th>{period}</th>{cells}</tr>")
    return (
        '<table border="1" class="dataframe"><tbody>'
        + "".join(rows)
        + "</tbody></table>"
    ).encode()


def _zip_payload(
    npr_name: str, npr_payload: bytes, *, tressect_payload: bytes | None = None
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(npr_name, npr_payload)
        archive.writestr("mfh.txt", "MAJOR FOREIGN HOLDERS\n")
        archive.writestr("mfhhis01.txt", "MAJOR FOREIGN HOLDERS HISTORY\n")
        if tressect_payload is not None:
            archive.writestr("tressect.txt", tressect_payload)
        archive.writestr(
            "bctype_history.txt", "2019-Jan " + " ".join(["1"] * 44) + "\n"
        )
        archive.writestr(
            "bltype_history.txt", "2019-Jan " + " ".join(["1"] * 48) + "\n"
        )
        archive.writestr(
            "totalticliabs_hist.txt", "2019-Jan " + " ".join(["1"] * 29) + "\n"
        )
    return output.getvalue()


def _tressect_payload(latest: str = "2020-01") -> bytes:
    year, month = (int(value) for value in latest.split("-"))
    periods: list[str] = []
    while (year, month) >= (1978, 1):
        periods.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year -= 1
            month = 12
    header = """NET PURCHASES OF U.S. TREASURY BONDS & NOTES BY MAJOR FOREIGN SECTOR:
FOREIGN OFFICIAL INSTITUTIONS, OTHER FOREIGNERS, AND INTERNATIONAL & REGIONAL ORGANIZATIONS
(IN MILLIONS OF DOLLARS)
(NEGATIVE FIGURES INDICATE NET SALES BY FOREIGNERS TO U.S. RESIDENTS)
MONTH TOTAL FOREIGN OFFICIAL OTHER FOREIGNERS INTERNATIONAL REGIONAL ORGANIZATIONS
"""
    rows = [f"{period} 4 1 2 1" for period in periods]
    return (header + "\n".join(rows) + "\n").encode()


def _write_inputs(
    root: Path,
    releases: list[tuple[str, str, str, bytes]],
    *,
    bad_zip_sha: bool = False,
) -> tuple[Path, Path]:
    raw = root / "raw"
    raw.mkdir(parents=True)
    catalog_rows: list[dict[str, object]] = []
    downloads: list[dict[str, object]] = []
    for release_id, available_time, reference_month, payload in releases:
        file_date = release_id[-10:].replace("-", "")
        path = raw / f"ticrel_{file_date}.zip"
        path.write_bytes(payload)
        digest = _sha256(payload)
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = sorted(archive.namelist())
        catalog_rows.append(
            {
                "archive_id": release_id,
                "available_time": available_time,
                "reference_month": reference_month,
                "file_date": file_date,
                "downloaded": True,
                "sha256": digest,
            }
        )
        downloads.append(
            {
                "archive_id": release_id,
                "raw_path": str(path),
                "sha256": "0" * 64 if bad_zip_sha else digest,
                "members_sha256": _sha256("\n".join(names).encode()),
            }
        )
    catalog_path = root / "release_catalog.csv"
    with catalog_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CATALOG_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(catalog_rows)
    manifest = {
        "release_count": len(releases),
        "catalog_sha256": _sha256(catalog_path.read_bytes()),
        "downloads": downloads,
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, catalog_path


def test_phase_one_audits_csv_text_and_html_vintages(tmp_path: Path) -> None:
    jan = _values(10)
    jan_revised = [999, *jan[1:]]
    feb = _values(50)
    feb_revised = [feb[0], 777, *feb[2:]]
    mar = _values(90)
    releases = [
        (
            "tic_release_2020-01-15",
            "2020-01-16T00:00:00Z",
            "2020-01-01",
            _zip_payload("npr_history.csv", _npr_csv([("2020-Jan", jan)])),
        ),
        (
            "tic_release_2020-02-15",
            "2020-02-16T00:00:00Z",
            "2020-02-01",
            _zip_payload(
                "npr_history.txt",
                _npr_txt([("2020-Jan", jan_revised), ("2020-Feb", feb)]),
            ),
        ),
        (
            "tic_release_2020-03-15",
            "2020-03-16T00:00:00Z",
            "2020-03-01",
            _zip_payload(
                "npr_history.html",
                _npr_html(
                    [
                        ("2020-Jan", jan_revised),
                        ("2020-Feb", feb_revised),
                        ("2020-Mar", mar),
                    ]
                ),
            ),
        ),
    ]
    manifest_path, catalog_path = _write_inputs(tmp_path, releases)
    output = tmp_path / "outputs"

    result = audit.run_audit(manifest_path, catalog_path, output)

    assert result["release_count"] == 3
    assert result["verified_zip_count"] == 3
    assert result["inventory_row_count"] == 21
    assert result["npr_vintage_count"] == 3
    assert result["npr_revision_transition_count"] == 2
    assert result["factor_registry_modified"] is False
    assert result["outcome_evaluations_added"] == 0
    assert result["strict_pit_eligible"] is False

    with (output / "member_inventory.csv").open(newline="") as handle:
        inventory = list(csv.DictReader(handle))
    npr = [row for row in inventory if row["series_id"] == "npr_history"]
    assert [row["layout"] for row in npr] == ["csv", "fixed_width", "html_table"]
    assert [row["available_time"] for row in npr] == [
        "2020-01-16T00:00:00Z",
        "2020-02-16T00:00:00Z",
        "2020-03-16T00:00:00Z",
    ]
    assert all(row["parser_status"] == "parsed_revision_audited" for row in npr)
    assert all(
        row["parser_status"] == "parser_pending"
        for row in inventory
        if row["series_id"] not in {"npr_history", "tressect"}
    )
    assert all(
        row["parser_status"] == "member_absent"
        for row in inventory
        if row["series_id"] == "tressect"
    )

    with (output / "revision_summary.csv").open(newline="") as handle:
        revisions = list(csv.DictReader(handle))
    assert [row["added_observations"] for row in revisions] == ["1", "1"]
    assert [row["changed_observations"] for row in revisions] == ["1", "1"]
    assert [row["changed_cells"] for row in revisions] == ["1", "1"]
    assert [row["earliest_revised_period"] for row in revisions] == [
        "2020-01",
        "2020-02",
    ]
    saved_manifest = json.loads((output / "audit_manifest.json").read_text())
    assert saved_manifest["series_status"]["npr_history"].endswith("research_only")
    assert saved_manifest["series_status"]["bctype_history"] == "parser_pending"


def test_numeric_header_csv_is_an_explicit_npr_schema() -> None:
    payload = _npr_csv([("2022-Dec", _values(1))], numeric=True)

    schema_id, encoding, layout, observations = audit._parse_npr(
        payload, "npr_history.csv"
    )

    assert schema_id == "npr_csv_numeric_32_v1"
    assert encoding == "utf-8"
    assert layout == "csv"
    assert len(observations["2022-12"]) == 32


def test_tressect_parser_validates_semantics_and_accounting_rounding() -> None:
    payload = _tressect_payload()
    schema_id, encoding, layout, observations = audit._tressect_rows(
        payload, "tressect.txt"
    )

    assert schema_id == "tressect_txt_fixed_4_v1"
    assert encoding == "utf-8"
    assert layout == "fixed_width"
    assert len(observations) == 505
    assert observations["2020-01"] == (4, 1, 2, 1)

    rounded = payload.replace(b"2020-01 4 1 2 1", b"2020-01 5 1 2 1")
    _, _, _, rounded_observations = audit._tressect_rows(rounded, "tressect.txt")
    assert rounded_observations["2020-01"][0] == 5


def test_tressect_parser_fails_on_bad_accounting_or_header() -> None:
    payload = _tressect_payload().replace(b"2020-01 4 1 2 1", b"2020-01 7 1 2 1")
    with pytest.raises(ValueError, match="accounting identity"):
        audit._tressect_rows(payload, "tressect.txt")
    with pytest.raises(ValueError, match="header semantics"):
        audit._tressect_rows(
            _tressect_payload().replace(b"IN MILLIONS", b"IN UNITS"),
            "tressect.txt",
        )


def test_run_audit_materializes_tressect_vintages_and_revisions(tmp_path: Path) -> None:
    january = _tressect_payload("2020-01")
    february = _tressect_payload("2020-02").replace(
        b"2020-01 4 1 2 1", b"2020-01 5 2 2 1"
    )
    releases = [
        (
            "tic_release_2020-01-15",
            "2020-01-16T00:00:00Z",
            "2020-01-01",
            _zip_payload(
                "npr_history.csv",
                _npr_csv([("2020-Jan", _values(1))]),
                tressect_payload=january,
            ),
        ),
        (
            "tic_release_2020-02-15",
            "2020-02-16T00:00:00Z",
            "2020-02-01",
            _zip_payload(
                "npr_history.csv",
                _npr_csv(
                    [("2020-Jan", _values(1)), ("2020-Feb", _values(2))]
                ),
                tressect_payload=february,
            ),
        ),
    ]
    manifest_path, catalog_path = _write_inputs(tmp_path, releases)
    output = tmp_path / "outputs"

    result = audit.run_audit(manifest_path, catalog_path, output)

    assert result["tressect_vintage_count"] == 2
    assert result["tressect_revision_transition_count"] == 1
    assert result["series_status"]["tressect"].endswith("research_only")
    with (output / "tressect_revision_summary.csv").open(newline="") as handle:
        revisions = list(csv.DictReader(handle))
    assert revisions[0]["added_observations"] == "1"
    assert revisions[0]["changed_observations"] == "1"
    assert revisions[0]["changed_cells"] == "2"
    with (output / "tressect_vintages.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1011


def test_unknown_npr_schema_fails_closed(tmp_path: Path) -> None:
    malformed = _npr_csv([("2020-Jan", _values(1)[:-1])])
    releases = [
        (
            "tic_release_2020-01-15",
            "2020-01-16T00:00:00Z",
            "2020-01-01",
            _zip_payload("npr_history.csv", malformed),
        )
    ]
    manifest_path, catalog_path = _write_inputs(tmp_path, releases)

    with pytest.raises(ValueError, match="unknown NPR CSV schema"):
        audit.run_audit(manifest_path, catalog_path, tmp_path / "outputs")


def test_zip_hash_mismatch_fails_before_parsing(tmp_path: Path) -> None:
    releases = [
        (
            "tic_release_2020-01-15",
            "2020-01-16T00:00:00Z",
            "2020-01-01",
            _zip_payload("npr_history.csv", _npr_csv([("2020-Jan", _values(1))])),
        )
    ]
    manifest_path, catalog_path = _write_inputs(tmp_path, releases, bad_zip_sha=True)

    with pytest.raises(ValueError, match="ZIP SHA-256 mismatch"):
        audit.run_audit(manifest_path, catalog_path, tmp_path / "outputs")
