#!/usr/bin/env python3
"""Audit Treasury TIC release vintages without opening factor outcomes.

Phase one fully parses ``npr_history`` and ``tressect`` and compares every
adjacent release vintage.  Other selected TIC tables are inventoried and
schema-gated, but stay ``parser_pending``.  A recognized filename is not
sufficient evidence of a usable point-in-time series: ZIP hashes, member
structure and the parser schema must all match the explicit contracts below.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import zipfile
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Final

PROGRAM_VERSION: Final = "treasury-tic-vintage-audit-v2"
NPR_VALUE_COUNT: Final = 32
TRESSECT_VALUE_COUNT: Final = 4
TRESSECT_FIRST_PERIOD: Final = "1978-01"
TRESSECT_SCHEMA_ID: Final = "tressect_txt_fixed_4_v1"
TRESSECT_COLUMNS: Final[tuple[str, ...]] = (
    "total_net_purchases_musd",
    "foreign_official_institutions_musd",
    "other_foreigners_musd",
    "international_regional_organizations_musd",
)
SERIES: Final[tuple[str, ...]] = (
    "npr_history",
    "mfh",
    "mfhhis01",
    "tressect",
    "bctype_history",
    "bltype_history",
    "totalticliabs_hist",
)
MONTHS: Final[dict[str, int]] = {
    month: index
    for index, month in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
        start=1,
    )
}
PERIOD_PATTERN: Final = re.compile(
    r"^\s*(?P<year>(?:19|20)\d{2})-"
    r"(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|0[1-9]|1[0-2])"
    r"(?:\s+|,|<|$)(?P<rest>.*)$"
)
INTEGER_PATTERN: Final = re.compile(r"[+-]?\d+")

INVENTORY_COLUMNS: Final[tuple[str, ...]] = (
    "release_id",
    "available_time",
    "reference_month",
    "series_id",
    "member_present",
    "member_name",
    "member_bytes",
    "member_sha256",
    "extension",
    "encoding",
    "layout",
    "schema_id",
    "parser_status",
    "expected_value_count",
    "observation_count",
    "first_observation",
    "last_observation",
    "issue_code",
)

SCHEMA_COLUMNS: Final[tuple[str, ...]] = (
    "schema_id",
    "series_id",
    "extension",
    "encoding",
    "layout",
    "expected_value_count",
    "parser_status",
    "first_release_id",
    "last_release_id",
    "release_count",
    "strict_pit_eligible",
    "pit_blocker",
)

REVISION_COLUMNS: Final[tuple[str, ...]] = (
    "series_id",
    "prior_release_id",
    "current_release_id",
    "prior_available_time",
    "current_available_time",
    "prior_schema_id",
    "current_schema_id",
    "schema_changed",
    "prior_latest_observation",
    "current_latest_observation",
    "overlap_observations",
    "added_observations",
    "dropped_observations",
    "changed_observations",
    "changed_cells",
    "earliest_revised_period",
    "latest_revised_period",
    "max_revision_age_months",
)

TRESSECT_VINTAGE_COLUMNS: Final[tuple[str, ...]] = (
    "release_id",
    "available_time",
    "reference_month",
    "observation_period",
    *TRESSECT_COLUMNS,
)


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        del attrs
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None:
            assert self._row is not None
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON: {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _read_catalog(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, UnicodeDecodeError, csv.Error) as error:
        raise ValueError(f"invalid release catalog: {path}: {error}") from error
    required = {
        "archive_id",
        "available_time",
        "reference_month",
        "file_date",
        "downloaded",
        "sha256",
    }
    if not rows or not required.issubset(rows[0]):
        raise ValueError("release catalog is empty or lacks required columns")
    if len({row["archive_id"] for row in rows}) != len(rows):
        raise ValueError("release catalog contains duplicate archive_id values")
    return rows


def _resolve_zip_path(raw_path: object, manifest_path: Path) -> Path:
    value = Path(str(raw_path))
    candidates = [value]
    if not value.is_absolute():
        candidates.extend(
            (
                manifest_path.parent / value,
                manifest_path.parent / "raw" / value.name,
            )
        )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ValueError(f"TIC raw ZIP is absent: {value}")


def _safe_member_names(archive: zipfile.ZipFile) -> list[str]:
    names: list[str] = []
    for info in archive.infolist():
        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts or info.flag_bits & 0x1:
            raise ValueError(f"unsafe TIC ZIP member: {info.filename!r}")
        names.append(info.filename)
    if len(names) != len(set(names)):
        raise ValueError("TIC ZIP contains duplicate member names")
    return sorted(names)


def _decode(payload: bytes) -> tuple[str, str]:
    try:
        return payload.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        try:
            return payload.decode("cp1252"), "windows-1252"
        except UnicodeDecodeError as error:
            raise ValueError("TIC member is neither UTF-8 nor Windows-1252") from error


def _period(value: str) -> str | None:
    match = PERIOD_PATTERN.match(value)
    if match is None:
        return None
    month_text = match.group("month")
    month = MONTHS.get(month_text, int(month_text) if month_text.isdigit() else 0)
    return f"{int(match.group('year')):04d}-{month:02d}"


def _month_index(period: str) -> int:
    year, month = (int(value) for value in period.split("-"))
    return year * 12 + month - 1


def _integer(value: str) -> int:
    normalized = value.strip().replace(",", "")
    if not INTEGER_PATTERN.fullmatch(normalized):
        raise ValueError(f"TIC value is not an integer: {value!r}")
    return int(normalized)


def _tressect_rows(
    payload: bytes, member_name: str
) -> tuple[str, str, str, dict[str, tuple[int, ...]]]:
    text, encoding = _decode(payload)
    if encoding != "utf-8" or PurePosixPath(member_name).suffix.lower() != ".txt":
        raise ValueError("unknown tressect encoding or extension")
    normalized = " ".join(text.upper().split())
    required_phrases = (
        "NET PURCHASES OF U.S. TREASURY BONDS & NOTES BY MAJOR FOREIGN SECTOR",
        (
            "FOREIGN OFFICIAL INSTITUTIONS, OTHER FOREIGNERS, AND "
            "INTERNATIONAL & REGIONAL ORGANIZATIONS"
        ),
        "IN MILLIONS OF DOLLARS",
        "NEGATIVE FIGURES INDICATE NET SALES BY FOREIGNERS TO U.S. RESIDENTS",
        "MONTH",
        "TOTAL",
        "FOREIGN OFFICIAL",
        "OTHER FOREIGNERS",
        "INTERNATIONAL",
        "REGIONAL ORGANIZATIONS",
    )
    missing = [phrase for phrase in required_phrases if phrase not in normalized]
    if missing:
        raise ValueError(f"unknown tressect header semantics: {missing}")
    observations: dict[str, tuple[int, ...]] = {}
    ordered_periods: list[str] = []
    for line in text.splitlines():
        match = re.match(
            r"^\s*(?P<period>\d{4}-(?:0[1-9]|1[0-2]))\s+(?P<rest>.*)$", line
        )
        if match is None:
            continue
        period = match.group("period")
        values = tuple(_integer(value) for value in match.group("rest").split())
        if len(values) != TRESSECT_VALUE_COUNT:
            raise ValueError(
                f"unknown tressect schema: {period} has {len(values)} values, "
                f"expected {TRESSECT_VALUE_COUNT}"
            )
        if period in observations:
            raise ValueError(f"duplicate tressect observation: {period}")
        accounting_residual = values[0] - sum(values[1:])
        if abs(accounting_residual) > 1:
            raise ValueError(
                f"tressect accounting identity failed beyond display rounding: {period}"
            )
        observations[period] = values
        ordered_periods.append(period)
    if not observations:
        raise ValueError("unknown tressect schema: no monthly observations")
    if ordered_periods != sorted(ordered_periods, key=_month_index, reverse=True):
        raise ValueError("tressect observations are not strictly descending")
    latest = ordered_periods[0]
    expected = list(range(_month_index(TRESSECT_FIRST_PERIOD), _month_index(latest) + 1))
    actual = [_month_index(period) for period in reversed(ordered_periods)]
    if actual != expected:
        raise ValueError("tressect history does not cover every month from 1978-01")
    return TRESSECT_SCHEMA_ID, encoding, "fixed_width", observations


def _npr_rows(
    rows: list[list[str]], *, source: str
) -> dict[str, tuple[int, ...]]:
    observations: dict[str, tuple[int, ...]] = {}
    for row in rows:
        if not row:
            continue
        period = _period(row[0])
        if period is None:
            continue
        values = tuple(_integer(value) for value in row[1:] if value.strip())
        if len(values) != NPR_VALUE_COUNT:
            raise ValueError(
                f"unknown NPR {source} schema: {period} has {len(values)} values, "
                f"expected {NPR_VALUE_COUNT}"
            )
        if period in observations:
            raise ValueError(f"duplicate NPR observation: {period}")
        observations[period] = values
    if not observations:
        raise ValueError(f"unknown NPR {source} schema: no monthly observations")
    ordered = sorted(observations, key=_month_index)
    expected = list(range(_month_index(ordered[0]), _month_index(ordered[-1]) + 1))
    actual = [_month_index(period) for period in ordered]
    if actual != expected:
        raise ValueError("NPR history contains a monthly coverage gap")
    return observations


def _parse_npr(
    payload: bytes, member_name: str
) -> tuple[str, str, str, dict[str, tuple[int, ...]]]:
    text, encoding = _decode(payload)
    if encoding != "utf-8":
        raise ValueError(f"unknown NPR encoding: {encoding}")
    extension = PurePosixPath(member_name).suffix.lower()
    if extension == ".csv":
        try:
            rows = list(csv.reader(io.StringIO(text)))
        except csv.Error as error:
            raise ValueError(f"invalid NPR CSV: {error}") from error
        bracketed = "[1]" in text and "[32]" in text and "TIC monthly reports" in text
        numeric = any(
            len(row) == NPR_VALUE_COUNT + 1
            and [value.strip() for value in row[1:]] == [str(i) for i in range(1, 33)]
            for row in rows
        )
        if bracketed:
            schema_id = "npr_csv_bracketed_32_v1"
        elif numeric:
            schema_id = "npr_csv_numeric_32_v1"
        else:
            raise ValueError("unknown NPR CSV header schema")
        return schema_id, encoding, "csv", _npr_rows(rows, source="CSV")
    if extension == ".txt":
        if "TIC monthly reports on Cross-Border Portfolio Financial Flows" not in text:
            raise ValueError("unknown NPR TXT header schema")
        rows: list[list[str]] = []
        for line in text.splitlines():
            match = PERIOD_PATTERN.match(line)
            if match is not None:
                rows.append(
                    [
                        f"{match.group('year')}-{match.group('month')}",
                        *match.group("rest").split(),
                    ]
                )
        return (
            "npr_fixed_width_32_v1",
            encoding,
            "fixed_width",
            _npr_rows(rows, source="TXT"),
        )
    if extension == ".html":
        if not re.search(r"<table\b[^>]*class=[\"']dataframe[\"']", text, re.I):
            raise ValueError("unknown NPR HTML table schema")
        parser = _TableParser()
        parser.feed(text)
        return (
            "npr_dataframe_html_32_v1",
            encoding,
            "html_table",
            _npr_rows(parser.rows, source="HTML"),
        )
    raise ValueError(f"unknown NPR extension: {extension or '<none>'}")


def _date_row_width(text: str) -> int | None:
    widths: set[int] = set()
    for line in text.splitlines():
        match = PERIOD_PATTERN.match(line)
        if match is not None:
            widths.add(len(match.group("rest").split()))
    if not widths:
        return None
    if len(widths) != 1:
        raise ValueError(f"inventory-only TIC table has mixed date-row widths: {sorted(widths)}")
    return next(iter(widths))


def _inventory_schema(
    series_id: str, payload: bytes, member_name: str
) -> tuple[str, str, str, str]:
    text, encoding = _decode(payload)
    extension = PurePosixPath(member_name).suffix.lower()
    layout = "html_table" if extension == ".html" else "tab" if "\t" in text else "fixed_width"
    width = _date_row_width(text) if extension == ".txt" else None

    if series_id == "mfh" and (extension, encoding, layout) == (
        ".txt",
        "utf-8",
        "fixed_width",
    ):
        return "mfh_txt_fixed_inventory_v1", encoding, layout, ""
    if series_id == "mfhhis01":
        if (extension, encoding, layout) == (".txt", "utf-8", "fixed_width"):
            return "mfhhis01_txt_fixed_inventory_v1", encoding, layout, ""
        if (extension, encoding, layout) == (".txt", "utf-8", "tab"):
            return "mfhhis01_txt_tab_inventory_v1", encoding, layout, ""
        if (extension, encoding, layout) == (
            ".html",
            "windows-1252",
            "html_table",
        ):
            return "mfhhis01_excel_html_cp1252_inventory_v1", encoding, layout, ""
    allowed_widths: dict[str, set[int]] = {
        "tressect": {4},
        "bctype_history": {41, 44},
        "bltype_history": {42, 48},
        "totalticliabs_hist": {29},
    }
    if (
        series_id in allowed_widths
        and extension == ".txt"
        and encoding == "utf-8"
        and layout == "fixed_width"
        and width in allowed_widths[series_id]
    ):
        assert width is not None
        schema_id = f"{series_id}_txt_fixed_{width}_inventory_v1"
        return schema_id, encoding, layout, str(width)
    raise ValueError(
        f"unknown {series_id} inventory schema: extension={extension!r} "
        f"encoding={encoding!r} layout={layout!r} width={width!r}"
    )


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    _atomic_bytes(path, output.getvalue().encode("utf-8"))


def _write_json(path: Path, value: dict[str, object]) -> None:
    _atomic_bytes(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def _revision_rows(
    vintages: list[dict[str, object]], *, series_id: str
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for prior, current in zip(vintages, vintages[1:], strict=False):
        prior_data = prior["observations"]
        current_data = current["observations"]
        assert isinstance(prior_data, dict) and isinstance(current_data, dict)
        prior_periods = set(prior_data)
        current_periods = set(current_data)
        overlap = prior_periods & current_periods
        changed = sorted(
            (period for period in overlap if prior_data[period] != current_data[period]),
            key=_month_index,
        )
        changed_cells = sum(
            sum(
                old != new
                for old, new in zip(
                    prior_data[period], current_data[period], strict=True
                )
            )
            for period in changed
        )
        current_latest = max(current_periods, key=_month_index)
        max_age = (
            max(_month_index(current_latest) - _month_index(period) for period in changed)
            if changed
            else ""
        )
        output.append(
            {
                "series_id": series_id,
                "prior_release_id": prior["release_id"],
                "current_release_id": current["release_id"],
                "prior_available_time": prior["available_time"],
                "current_available_time": current["available_time"],
                "prior_schema_id": prior["schema_id"],
                "current_schema_id": current["schema_id"],
                "schema_changed": prior["schema_id"] != current["schema_id"],
                "prior_latest_observation": max(prior_periods, key=_month_index),
                "current_latest_observation": current_latest,
                "overlap_observations": len(overlap),
                "added_observations": len(current_periods - prior_periods),
                "dropped_observations": len(prior_periods - current_periods),
                "changed_observations": len(changed),
                "changed_cells": changed_cells,
                "earliest_revised_period": changed[0] if changed else "",
                "latest_revised_period": changed[-1] if changed else "",
                "max_revision_age_months": max_age,
            }
        )
    return output


def run_audit(
    manifest_path: Path,
    catalog_path: Path,
    output_dir: Path,
) -> dict[str, object]:
    manifest = _load_json(manifest_path)
    catalog_payload = catalog_path.read_bytes()
    expected_catalog_sha = manifest.get("catalog_sha256")
    if (
        not isinstance(expected_catalog_sha, str)
        or _sha256(catalog_payload) != expected_catalog_sha
    ):
        raise ValueError("release catalog SHA-256 does not match download manifest")
    catalog = _read_catalog(catalog_path)
    release_count = manifest.get("release_count")
    if not isinstance(release_count, int) or release_count != len(catalog):
        raise ValueError("release catalog count does not match download manifest")
    downloads_value = manifest.get("downloads")
    if not isinstance(downloads_value, list):
        raise ValueError("download manifest lacks downloads")
    downloads = {
        str(item.get("archive_id")): item
        for item in downloads_value
        if isinstance(item, dict)
    }
    if len(downloads) != len(downloads_value):
        raise ValueError("download manifest has duplicate or invalid downloads")

    inventory: list[dict[str, object]] = []
    vintages: list[dict[str, object]] = []
    tressect_vintages: list[dict[str, object]] = []
    schemas: dict[str, dict[str, object]] = {}
    verified_zip_count = 0

    for release in catalog:
        release_id = release["archive_id"]
        if not _truthy(release["downloaded"]):
            raise ValueError(f"catalog release was not downloaded: {release_id}")
        download = downloads.get(release_id)
        if download is None:
            raise ValueError(f"download manifest lacks release: {release_id}")
        zip_path = _resolve_zip_path(download.get("raw_path"), manifest_path)
        zip_payload = zip_path.read_bytes()
        digest = _sha256(zip_payload)
        if digest != download.get("sha256") or digest != release["sha256"]:
            raise ValueError(f"ZIP SHA-256 mismatch: {release_id}")
        try:
            archive = zipfile.ZipFile(io.BytesIO(zip_payload))
        except zipfile.BadZipFile as error:
            raise ValueError(f"invalid TIC ZIP: {release_id}") from error
        with archive:
            member_names = _safe_member_names(archive)
            expected_members_sha = download.get("members_sha256")
            if not isinstance(expected_members_sha, str) or _sha256(
                "\n".join(member_names).encode()
            ) != expected_members_sha:
                raise ValueError(f"member inventory SHA-256 mismatch: {release_id}")
            verified_zip_count += 1
            for series_id in SERIES:
                matching = [
                    name
                    for name in member_names
                    if PurePosixPath(name).stem.lower() == series_id
                ]
                if len(matching) > 1:
                    raise ValueError(f"multiple {series_id} members in {release_id}")
                common: dict[str, object] = {
                    "release_id": release_id,
                    "available_time": release["available_time"],
                    "reference_month": release["reference_month"],
                    "series_id": series_id,
                }
                if not matching:
                    inventory.append(
                        {
                            **common,
                            "member_present": False,
                            "member_name": "",
                            "member_bytes": "",
                            "member_sha256": "",
                            "extension": "",
                            "encoding": "",
                            "layout": "",
                            "schema_id": "",
                            "parser_status": "member_absent",
                            "expected_value_count": "",
                            "observation_count": "",
                            "first_observation": "",
                            "last_observation": "",
                            "issue_code": "member_absent",
                        }
                    )
                    continue
                member_name = matching[0]
                payload = archive.read(member_name)
                if series_id == "npr_history":
                    schema_id, encoding, layout, observations = _parse_npr(
                        payload, member_name
                    )
                    latest = max(observations, key=_month_index)
                    if latest != release["reference_month"][:7]:
                        raise ValueError(
                            f"NPR latest observation {latest} does not match "
                            f"reference month {release['reference_month']}: {release_id}"
                        )
                    first = min(observations, key=_month_index)
                    status = "parsed_revision_audited"
                    expected_count: str | int = NPR_VALUE_COUNT
                    vintages.append(
                        {
                            "release_id": release_id,
                            "available_time": release["available_time"],
                            "schema_id": schema_id,
                            "observations": observations,
                        }
                    )
                elif series_id == "tressect":
                    schema_id, encoding, layout, observations = _tressect_rows(
                        payload, member_name
                    )
                    latest = max(observations, key=_month_index)
                    if latest != release["reference_month"][:7]:
                        raise ValueError(
                            f"tressect latest observation {latest} does not match "
                            f"reference month {release['reference_month']}: {release_id}"
                        )
                    first = min(observations, key=_month_index)
                    status = "parsed_revision_audited"
                    expected_count = TRESSECT_VALUE_COUNT
                    tressect_vintages.append(
                        {
                            "release_id": release_id,
                            "available_time": release["available_time"],
                            "reference_month": release["reference_month"],
                            "schema_id": schema_id,
                            "observations": observations,
                        }
                    )
                else:
                    schema_id, encoding, layout, expected_count = _inventory_schema(
                        series_id, payload, member_name
                    )
                    observations = {}
                    first = ""
                    latest = ""
                    status = "parser_pending"
                extension = PurePosixPath(member_name).suffix.lower()
                inventory.append(
                    {
                        **common,
                        "member_present": True,
                        "member_name": member_name,
                        "member_bytes": len(payload),
                        "member_sha256": _sha256(payload),
                        "extension": extension,
                        "encoding": encoding,
                        "layout": layout,
                        "schema_id": schema_id,
                        "parser_status": status,
                        "expected_value_count": expected_count,
                        "observation_count": len(observations) if observations else "",
                        "first_observation": first,
                        "last_observation": latest,
                        "issue_code": ""
                        if series_id in {"npr_history", "tressect"}
                        else "parser_pending",
                    }
                )
                schema = schemas.get(schema_id)
                if schema is None:
                    schemas[schema_id] = {
                        "schema_id": schema_id,
                        "series_id": series_id,
                        "extension": extension,
                        "encoding": encoding,
                        "layout": layout,
                        "expected_value_count": expected_count,
                        "parser_status": status,
                        "first_release_id": release_id,
                        "last_release_id": release_id,
                        "release_count": 1,
                        "strict_pit_eligible": False,
                        "pit_blocker": (
                            "phase_one_research_only_no_factor_registration"
                            if series_id in {"npr_history", "tressect"}
                            else "series_parser_and_revision_audit_pending"
                        ),
                    }
                else:
                    schema["last_release_id"] = release_id
                    schema["release_count"] = int(schema["release_count"]) + 1

    if len(vintages) != len(catalog):
        raise ValueError("npr_history must be present in every audited release")
    revisions = _revision_rows(vintages, series_id="npr_history")
    tressect_revisions = _revision_rows(tressect_vintages, series_id="tressect")
    schema_rows = sorted(
        schemas.values(), key=lambda row: (str(row["series_id"]), str(row["schema_id"]))
    )
    inventory_path = output_dir / "member_inventory.csv"
    schema_path = output_dir / "schema_catalog.csv"
    revision_path = output_dir / "revision_summary.csv"
    tressect_revision_path = output_dir / "tressect_revision_summary.csv"
    tressect_vintage_path = output_dir / "tressect_vintages.csv"
    _write_csv(inventory_path, INVENTORY_COLUMNS, inventory)
    _write_csv(schema_path, SCHEMA_COLUMNS, schema_rows)
    _write_csv(revision_path, REVISION_COLUMNS, revisions)
    _write_csv(tressect_revision_path, REVISION_COLUMNS, tressect_revisions)
    tressect_rows = [
        {
            "release_id": vintage["release_id"],
            "available_time": vintage["available_time"],
            "reference_month": vintage["reference_month"],
            "observation_period": period,
            **dict(zip(TRESSECT_COLUMNS, values, strict=True)),
        }
        for vintage in tressect_vintages
        for period, values in sorted(
            vintage["observations"].items(), key=lambda item: _month_index(item[0])
        )
    ]
    _write_csv(tressect_vintage_path, TRESSECT_VINTAGE_COLUMNS, tressect_rows)
    accounting_residual_counts: dict[str, int] = {}
    for row in tressect_rows:
        residual = int(row["total_net_purchases_musd"]) - sum(
            int(row[column]) for column in TRESSECT_COLUMNS[1:]
        )
        accounting_residual_counts[str(residual)] = (
            accounting_residual_counts.get(str(residual), 0) + 1
        )

    output_hashes = {
        path.name: _sha256(path.read_bytes())
        for path in (
            inventory_path,
            schema_path,
            revision_path,
            tressect_revision_path,
            tressect_vintage_path,
        )
    }
    result: dict[str, object] = {
        "schema_version": 1,
        "program_version": PROGRAM_VERSION,
        "generated_at_utc": _utc_now(),
        "input_manifest": str(manifest_path),
        "input_manifest_sha256": _sha256(manifest_path.read_bytes()),
        "input_catalog": str(catalog_path),
        "input_catalog_sha256": _sha256(catalog_payload),
        "release_count": len(catalog),
        "verified_zip_count": verified_zip_count,
        "inventory_row_count": len(inventory),
        "schema_count": len(schema_rows),
        "npr_vintage_count": len(vintages),
        "npr_revision_transition_count": len(revisions),
        "tressect_vintage_count": len(tressect_vintages),
        "tressect_revision_transition_count": len(tressect_revisions),
        "tressect_observation_row_count": len(tressect_rows),
        "tressect_accounting_residual_musd_counts": accounting_residual_counts,
            "tressect_max_abs_accounting_residual_musd": max(
                (abs(int(residual)) for residual in accounting_residual_counts),
                default=0,
            ),
        "tressect_revision_observation_count": sum(
            int(row["changed_observations"]) for row in tressect_revisions
        ),
        "tressect_revision_changed_cell_count": sum(
            int(row["changed_cells"]) for row in tressect_revisions
        ),
        "series_status": {
            series_id: (
                "parsed_revision_audited_research_only"
                if series_id == "npr_history"
                else "parsed_revision_audited_research_only"
                if series_id == "tressect" and tressect_vintages
                else "parser_pending"
            )
            for series_id in SERIES
        },
        "output_hashes": output_hashes,
        "factor_registry_modified": False,
        "outcome_evaluations_added": 0,
        "strict_pit_eligible": False,
        "pit_blocker": "phase_one_parsed_research_only_no_factor_registration",
    }
    _write_json(output_dir / "audit_manifest.json", result)
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, default=Path("data/treasury_tic/manifest.json")
    )
    parser.add_argument(
        "--catalog", type=Path, default=Path("data/treasury_tic/release_catalog.csv")
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("outputs/treasury_tic_revision_audit")
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run_audit(args.manifest, args.catalog, args.output_dir)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"Treasury TIC revision audit failed: {error}", file=sys.stderr)
        return 1
    print(
        f"releases={result['release_count']} verified_zips={result['verified_zip_count']} "
        f"npr_vintages={result['npr_vintage_count']} output={args.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
