#!/usr/bin/env python3
"""Build a raw-source-audited 2016-2025 CFTC COT release calendar.

The output is deliberately not advertised as a point-in-time positioning
vintage archive.  Annual CFTC release pages are tentative schedules; the 2019
catch-up sequence is partly rule-derived; and the 2025 catch-up table describes
intended dates.  Only the seven 2023 ION rows whose official announcements say
"Today, staff is issuing" are marked as verified actual publication dates, and
even those rows retain an unknown publication time.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Final

import httpx

from fx_system.cftc_release_calendar import CFTC_RELEASE_COLUMNS

GENERATION_VERSION: Final = "cftc-cot-release-calendar-v1"
START_YEAR: Final = 2016
END_YEAR: Final = 2025
TIMEZONE: Final = "America/New_York"
GENERAL_RELEASE_TIME: Final = "15:30"


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    url: str
    filename: str
    role: str
    publisher: str = "U.S. Commodity Futures Trading Commission"
    year: int | None = None


def _annual_source(year: int, timestamp: str, *, original_scheme: str) -> SourceSpec:
    original = (
        f"{original_scheme}://www.cftc.gov/MarketReports/CommitmentsofTraders/"
        "ReleaseSchedule/index.htm"
    )
    return SourceSpec(
        source_id=f"cftc_release_schedule_{year}",
        url=f"https://web.archive.org/web/{timestamp}id_/{original}",
        filename=f"cftc_release_schedule_{year}_{timestamp}.html",
        role=(
            f"Fixed Internet Archive capture of the official tentative {year} "
            "COT release schedule"
        ),
        year=year,
    )


ANNUAL_SOURCES: Final[tuple[SourceSpec, ...]] = (
    _annual_source(2016, "20160114131752", original_scheme="http"),
    _annual_source(2017, "20170125184928", original_scheme="http"),
    _annual_source(2018, "20180113071010", original_scheme="https"),
    _annual_source(2019, "20190416141729", original_scheme="https"),
    _annual_source(2020, "20200108001415", original_scheme="https"),
    _annual_source(2021, "20210119172806", original_scheme="https"),
    _annual_source(2022, "20220116212942", original_scheme="https"),
    _annual_source(2023, "20230128132242", original_scheme="https"),
    _annual_source(2024, "20240222133806", original_scheme="https"),
    _annual_source(2025, "20250113190352", original_scheme="https"),
)
SPECIAL_SOURCE: Final = SourceSpec(
    source_id="cftc_historical_special_announcements",
    url=(
        "https://www.cftc.gov/MarketReports/CommitmentsofTraders/"
        "HistoricalSpecialAnnouncements/index.htm"
    ),
    filename="cftc_historical_special_announcements.html",
    role=(
        "Official historical announcements for the 2018/19 funding lapse, "
        "2021 Juneteenth, 2023 ION incident, and 2025 exceptions"
    ),
)
SHUTDOWN_2019_SOURCE: Final = SourceSpec(
    source_id="cftc_press_release_7864_19",
    url="https://www.cftc.gov/PressRoom/PressReleases/7864-19",
    filename="cftc_press_release_7864_19.html",
    role="Official 2019 funding-lapse catch-up release rule",
)
SOURCES: Final[tuple[SourceSpec, ...]] = (
    *ANNUAL_SOURCES,
    SPECIAL_SOURCE,
    SHUTDOWN_2019_SOURCE,
)

# These seven official announcements say "Today, staff is issuing" and name
# the originally scheduled date.  They establish an actual publication date,
# but do not establish an exact intraday time.
ION_ACTUAL_BY_ORIGINAL_RELEASE: Final[dict[date, date]] = {
    date(2023, 2, 3): date(2023, 2, 24),
    date(2023, 2, 10): date(2023, 3, 3),
    date(2023, 2, 17): date(2023, 3, 8),
    date(2023, 2, 24): date(2023, 3, 10),
    date(2023, 3, 3): date(2023, 3, 14),
    date(2023, 3, 10): date(2023, 3, 16),
    date(2023, 3, 17): date(2023, 3, 21),
}

# The December 9 table calls these "New Publish Date" values and describes
# them as intended publication dates.  It is the final, shortened catch-up
# table, but that wording is not proof of actual publication.  Accordingly,
# none of these rows is marked verified_actual.
SHUTDOWN_2025_FINAL_TABLE: Final[tuple[tuple[date, date, date], ...]] = (
    (date(2025, 9, 30), date(2025, 10, 3), date(2025, 11, 19)),
    (date(2025, 10, 7), date(2025, 10, 10), date(2025, 11, 21)),
    (date(2025, 10, 14), date(2025, 10, 17), date(2025, 11, 25)),
    (date(2025, 10, 21), date(2025, 10, 24), date(2025, 12, 2)),
    (date(2025, 10, 28), date(2025, 10, 31), date(2025, 12, 5)),
    (date(2025, 11, 4), date(2025, 11, 7), date(2025, 12, 9)),
    (date(2025, 11, 10), date(2025, 11, 14), date(2025, 12, 10)),
    (date(2025, 11, 18), date(2025, 11, 21), date(2025, 12, 12)),
    (date(2025, 11, 25), date(2025, 12, 1), date(2025, 12, 15)),
    (date(2025, 12, 2), date(2025, 12, 5), date(2025, 12, 17)),
    (date(2025, 12, 9), date(2025, 12, 12), date(2025, 12, 19)),
    (date(2025, 12, 16), date(2025, 12, 19), date(2025, 12, 23)),
    (date(2025, 12, 23), date(2025, 12, 29), date(2025, 12, 29)),
)

# PR 7864-19 gives the first report/date pair and then only the rule "one
# report on Tuesday and another on Friday ... until current".  Rows after the
# first are consequently rule-derived, not verified actual releases.
SHUTDOWN_2019_CATCHUP: Final[tuple[tuple[date, date, date], ...]] = (
    (date(2018, 12, 24), date(2018, 12, 28), date(2019, 2, 1)),
    (date(2018, 12, 31), date(2019, 1, 4), date(2019, 2, 5)),
    (date(2019, 1, 8), date(2019, 1, 11), date(2019, 2, 8)),
    (date(2019, 1, 15), date(2019, 1, 18), date(2019, 2, 12)),
    (date(2019, 1, 22), date(2019, 1, 25), date(2019, 2, 15)),
    (date(2019, 1, 29), date(2019, 2, 1), date(2019, 2, 19)),
    (date(2019, 2, 5), date(2019, 2, 8), date(2019, 2, 22)),
    (date(2019, 2, 12), date(2019, 2, 15), date(2019, 2, 26)),
    (date(2019, 2, 19), date(2019, 2, 22), date(2019, 3, 1)),
    (date(2019, 2, 26), date(2019, 3, 1), date(2019, 3, 5)),
    (date(2019, 3, 5), date(2019, 3, 8), date(2019, 3, 8)),
)

MONTH_BY_NAME: Final = {
    name.lower(): month
    for month, name in enumerate(calendar.month_name)
    if month
}


class _HTMLBlocks(HTMLParser):
    """Small dependency-free HTML table/block text extractor."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self.paragraphs: list[str] = []
        self.all_text_parts: list[str] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None
        self._paragraph_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell_parts = []
        elif tag == "p":
            self._paragraph_parts = []

    def handle_data(self, data: str) -> None:
        self.all_text_parts.append(data)
        if self._cell_parts is not None:
            self._cell_parts.append(data)
        if self._paragraph_parts is not None:
            self._paragraph_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell_parts is not None:
            assert self._row is not None
            self._row.append(_normalize_text(" ".join(self._cell_parts)))
            self._cell_parts = None
        elif tag == "tr" and self._row is not None:
            assert self._table is not None
            self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None
        elif tag == "p" and self._paragraph_parts is not None:
            value = _normalize_text(" ".join(self._paragraph_parts))
            if value:
                self.paragraphs.append(value)
            self._paragraph_parts = None


def _normalize_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def _html_blocks(payload: bytes) -> _HTMLBlocks:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("CFTC source is not valid UTF-8 HTML") from error
    parser = _HTMLBlocks()
    try:
        parser.feed(text)
        parser.close()
    except Exception as error:
        raise ValueError("CFTC source contains malformed HTML") from error
    return parser


def _parse_annual_release_dates(payload: bytes, year: int) -> list[tuple[date, str]]:
    blocks = _html_blocks(payload)
    candidates: list[list[tuple[date, str]]] = []
    for table in blocks.tables:
        parsed: list[tuple[date, str]] = []
        for row in table:
            if not row:
                continue
            month = MONTH_BY_NAME.get(row[0].strip().lower())
            if month is None:
                continue
            for raw_day in row[1:]:
                token = raw_day.strip()
                if not token:
                    continue
                match = re.fullmatch(r"(\d{1,2})(\*{0,2})", token)
                if match is None:
                    raise ValueError(
                        f"CFTC {year} schedule has an unrecognized day cell {token!r}"
                    )
                parsed.append((date(year, month, int(match.group(1))), match.group(2)))
        if parsed:
            candidates.append(parsed)
    matching = [candidate for candidate in candidates if len(candidate) >= 48]
    if len(matching) != 1:
        raise ValueError(
            f"CFTC {year} schedule must contain one complete 12-month release table"
        )
    releases = matching[0]
    if len(releases) not in {51, 52, 53}:
        raise ValueError(f"CFTC {year} schedule has implausible row count {len(releases)}")
    if len({value for value, _ in releases}) != len(releases):
        raise ValueError(f"CFTC {year} schedule has duplicate release dates")
    if {value.month for value, _ in releases} != set(range(1, 13)):
        raise ValueError(f"CFTC {year} schedule does not cover every month")
    return sorted(releases)


def _validate_annual_source(source: SourceSpec, payload: bytes) -> None:
    assert source.year is not None
    text = _normalize_text(" ".join(_html_blocks(payload).all_text_parts))
    required = (
        "reports are released at 3:30 p.m. Eastern time",
        "tentative schedule",
        "Federal holidays may delay release",
    )
    if not all(anchor in text for anchor in required):
        raise ValueError(f"{source.source_id}: official schedule explanatory text is missing")
    _parse_annual_release_dates(payload, source.year)


def _format_cftc_date(value: date, *, zero_pad: bool = False) -> str:
    day = f"{value.day:02d}" if zero_pad else str(value.day)
    return f"{calendar.month_name[value.month]} {day}, {value.year}"


def _table_date(value: str) -> date:
    cleaned = value.rstrip("+*").strip()
    return datetime.strptime(cleaned, "%m/%d/%Y").date()


def _validate_special_source(payload: bytes) -> None:
    blocks = _html_blocks(payload)
    paragraphs = [_normalize_text(value) for value in blocks.paragraphs]
    joined = "\n".join(paragraphs)
    anchors = (
        "Since December 25, 2018 and January 1, 2019 (both Federal Holidays) are on Tuesday",
        "June 17, 2021:",
        "data from Tuesday June 15th",
        "Monday June 21, 2021",
        "January 07, 2025:",
        "Monday, January 13, 2025",
        "interrupted from October 1 – November 12 due to a lapse in federal appropriations",
    )
    if not all(anchor in joined for anchor in anchors):
        raise ValueError("CFTC historical special-announcement anchors are incomplete")

    for original, actual in ION_ACTUAL_BY_ORIGINAL_RELEASE.items():
        actual_labels = {_format_cftc_date(actual), _format_cftc_date(actual, zero_pad=True)}
        original_labels = {
            _format_cftc_date(original),
            _format_cftc_date(original, zero_pad=True),
        }
        matched = any(
            any(paragraph.startswith(f"{label}:") for label in actual_labels)
            and "Today, staff is issuing" in paragraph
            and any(
                f"originally scheduled to be published on {label}" in paragraph
                for label in original_labels
            )
            for paragraph in paragraphs
        )
        if not matched:
            raise ValueError(
                "CFTC ION actual-publication transcription is not supported for "
                f"{original.isoformat()} -> {actual.isoformat()}"
            )

    expected_2025 = set(SHUTDOWN_2025_FINAL_TABLE)
    table_matches: list[set[tuple[date, date, date]]] = []
    for table in blocks.tables:
        if not table or table[0][:3] != [
            "COT Report Date",
            "Original Publish Date",
            "New Publish Date",
        ]:
            continue
        parsed: set[tuple[date, date, date]] = set()
        try:
            for row in table[1:]:
                if len(row) >= 3 and all(row[:3]):
                    parsed.add(tuple(_table_date(value) for value in row[:3]))  # type: ignore[arg-type]
        except ValueError:
            continue
        table_matches.append(parsed)
    if expected_2025 not in table_matches:
        raise ValueError("CFTC final 2025 catch-up table does not match frozen transcription")


def _validate_shutdown_2019_source(payload: bytes) -> None:
    text = _normalize_text(" ".join(_html_blocks(payload).all_text_parts))
    anchors = (
        "Release Number 7864-19",
        "The last COT report was published on December 21, 2018",
        "based on data from Monday, December 24, 2018",
        "publish this report on Friday, February 1, 2019",
        "one report on Tuesday and another on Friday of each week until the reports are current",
    )
    if not all(anchor in text for anchor in anchors):
        raise ValueError("CFTC press release 7864-19 catch-up rule is incomplete")


def _validate_source(source: SourceSpec, payload: bytes) -> None:
    if b"<html" not in payload[:10_000].lower() or len(payload) < 500:
        raise ValueError(f"{source.source_id}: response is not plausible HTML")
    if source.year is not None:
        _validate_annual_source(source, payload)
    elif source.source_id == SPECIAL_SOURCE.source_id:
        _validate_special_source(payload)
    elif source.source_id == SHUTDOWN_2019_SOURCE.source_id:
        _validate_shutdown_2019_source(payload)
    else:  # pragma: no cover - SOURCES is frozen above.
        raise ValueError(f"unknown CFTC source {source.source_id!r}")


def _previous_weekday(value: date, weekday: int) -> date:
    days_back = (value.weekday() - weekday) % 7
    if days_back == 0:
        days_back = 7
    return value - timedelta(days=days_back)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _source_map() -> dict[str, SourceSpec]:
    return {source.source_id: source for source in SOURCES}


def _base_row(
    release_date: date,
    marker: str,
    *,
    source: SourceSpec,
    retrieved_at: str,
) -> dict[str, str]:
    report_weekday = 0 if marker == "**" else 1
    report_date = _previous_weekday(release_date, report_weekday)
    report_rule = (
        "official ** footnote: use prior Monday data due to Tuesday U.S. holiday"
        if marker == "**"
        else "general annual-page rule: release usually includes prior Tuesday data"
    )
    return {
        "report_date": report_date.isoformat(),
        "original_release_date": release_date.isoformat(),
        "mapped_release_date": release_date.isoformat(),
        "mapped_release_time_local": GENERAL_RELEASE_TIME,
        "timezone": TIMEZONE,
        "date_evidence_kind": "official_tentative_schedule",
        "time_evidence_kind": "official_tentative_schedule",
        "verified_actual": "false",
        "source_id": source.source_id,
        "source_url": source.url,
        "mapping_note": (
            f"Tentative release date/time; report_date is rule-derived ({report_rule}). "
            "This row is not proof of actual publication."
        ),
        "retrieved_at": retrieved_at,
    }


def _override_row(
    row: dict[str, str],
    *,
    report_date: date | None = None,
    mapped_release_date: date,
    date_evidence_kind: str,
    time_evidence_kind: str,
    verified_actual: bool,
    source: SourceSpec,
    note: str,
    retrieved_at: str,
) -> None:
    if report_date is not None:
        row["report_date"] = report_date.isoformat()
    row["mapped_release_date"] = mapped_release_date.isoformat()
    row["date_evidence_kind"] = date_evidence_kind
    row["time_evidence_kind"] = time_evidence_kind
    row["mapped_release_time_local"] = (
        "" if time_evidence_kind == "date_only_no_verified_time" else GENERAL_RELEASE_TIME
    )
    row["verified_actual"] = "true" if verified_actual else "false"
    row["source_id"] = source.source_id
    row["source_url"] = source.url
    row["mapping_note"] = note
    row["retrieved_at"] = retrieved_at


def _calendar_rows(
    annual_payloads: dict[int, bytes],
    *,
    retrieved_at_by_source: dict[str, str],
) -> list[dict[str, str]]:
    rows_by_original_release: dict[date, dict[str, str]] = {}
    for source in ANNUAL_SOURCES:
        assert source.year is not None
        for release_date, marker in _parse_annual_release_dates(
            annual_payloads[source.year], source.year
        ):
            if release_date in rows_by_original_release:
                raise ValueError(f"duplicate annual CFTC release date {release_date}")
            rows_by_original_release[release_date] = _base_row(
                release_date,
                marker,
                source=source,
                retrieved_at=retrieved_at_by_source[source.source_id],
            )

    special_retrieval = retrieved_at_by_source[SPECIAL_SOURCE.source_id]
    press_retrieval = retrieved_at_by_source[SHUTDOWN_2019_SOURCE.source_id]

    # The first 2019 catch-up date is explicitly announced by PR 7864-19.  The
    # remaining Tuesday/Friday dates are a transparent application of its rule.
    for index, (report_date, original, mapped) in enumerate(SHUTDOWN_2019_CATCHUP):
        row = rows_by_original_release.get(original)
        if row is None:
            raise ValueError(f"2019 shutdown override has no annual row for {original}")
        if index == 0:
            evidence = "official_exception_announced"
            note = (
                "PR 7864-19 explicitly expected the Dec. 24 report on Feb. 1; "
                "the wording is prospective and is not verified actual publication."
            )
        else:
            evidence = "rule_derived_mapping"
            note = (
                "Derived by assigning chronological backlog reports to the PR 7864-19 "
                "Tuesday/Friday catch-up rule until the original schedule is reached; "
                "not a verified actual publication date."
            )
        _override_row(
            row,
            report_date=report_date,
            mapped_release_date=mapped,
            date_evidence_kind=evidence,
            time_evidence_kind="inherited_general_rule",
            verified_actual=False,
            source=SHUTDOWN_2019_SOURCE,
            note=note,
            retrieved_at=press_retrieval,
        )

    juneteenth = rows_by_original_release[date(2021, 6, 18)]
    _override_row(
        juneteenth,
        mapped_release_date=date(2021, 6, 21),
        date_evidence_kind="official_exception_announced",
        time_evidence_kind="inherited_general_rule",
        verified_actual=False,
        source=SPECIAL_SOURCE,
        note=(
            "June 17 official announcement moved the June 15 report from June 18 to "
            "June 21 for the new federal holiday; prospective wording is not actual proof."
        ),
        retrieved_at=special_retrieval,
    )

    for original, actual in ION_ACTUAL_BY_ORIGINAL_RELEASE.items():
        row = rows_by_original_release[original]
        _override_row(
            row,
            mapped_release_date=actual,
            date_evidence_kind="official_exception_actual",
            time_evidence_kind="date_only_no_verified_time",
            verified_actual=True,
            source=SPECIAL_SOURCE,
            note=(
                "Official ION announcement says staff is issuing today and identifies "
                "the original scheduled release; actual date verified, exact time unstated."
            ),
            retrieved_at=special_retrieval,
        )

    carter = rows_by_original_release[date(2025, 1, 10)]
    _override_row(
        carter,
        mapped_release_date=date(2025, 1, 13),
        date_evidence_kind="official_exception_announced",
        time_evidence_kind="inherited_general_rule",
        verified_actual=False,
        source=SPECIAL_SOURCE,
        note=(
            "Official January 7 announcement moved the report to January 13 for the "
            "National Day of Mourning; prospective wording is not actual proof."
        ),
        retrieved_at=special_retrieval,
    )

    for report_date, original, mapped in SHUTDOWN_2025_FINAL_TABLE:
        row = rows_by_original_release.get(original)
        if row is None:
            raise ValueError(f"2025 shutdown override has no annual row for {original}")
        _override_row(
            row,
            report_date=report_date,
            mapped_release_date=mapped,
            date_evidence_kind="official_exception_announced",
            time_evidence_kind="date_only_no_verified_time",
            verified_actual=False,
            source=SPECIAL_SOURCE,
            note=(
                "December 9 official final catch-up table labels this an intended New "
                "Publish Date; neither actual publication nor an exact time is asserted."
            ),
            retrieved_at=special_retrieval,
        )

    rows = sorted(rows_by_original_release.values(), key=lambda row: row["report_date"])
    report_dates = [row["report_date"] for row in rows]
    if len(report_dates) != len(set(report_dates)):
        duplicates = sorted({value for value in report_dates if report_dates.count(value) > 1})
        raise ValueError(f"CFTC calendar has duplicate report dates {duplicates}")
    return rows


def _calendar_csv(rows: list[dict[str, str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CFTC_RELEASE_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _mapping_contract_sha256() -> str:
    payload = {
        "ion_actual": {
            key.isoformat(): value.isoformat()
            for key, value in sorted(ION_ACTUAL_BY_ORIGINAL_RELEASE.items())
        },
        "shutdown_2019_rule_derived": [
            [item.isoformat() for item in row] for row in SHUTDOWN_2019_CATCHUP
        ],
        "shutdown_2025_final_announced": [
            [item.isoformat() for item in row] for row in SHUTDOWN_2025_FINAL_TABLE
        ],
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return _sha256_bytes(serialized)


def download_calendar(
    output_directory: str | Path,
    *,
    refresh: bool = False,
    transport: httpx.BaseTransport | None = None,
    now: datetime | None = None,
) -> tuple[Path, Path]:
    """Download official evidence and write the calendar plus audit manifest."""

    output = Path(output_directory)
    raw_directory = output / "raw"
    raw_directory.mkdir(parents=True, exist_ok=True)
    calendar_path = output / "cftc_cot_release_calendar_2016_2025.csv"
    manifest_path = output / "cftc_cot_release_calendar_2016_2025.manifest.json"
    retrieved_at = (now or datetime.now(UTC)).astimezone(UTC)

    prior_retrievals: dict[str, str] = {}
    if manifest_path.is_file() and not refresh:
        try:
            prior = json.loads(manifest_path.read_text(encoding="utf-8"))
            prior_retrievals = {
                str(item["source_id"]): str(item["retrieved_at"])
                for item in prior.get("sources", [])
                if isinstance(item, dict)
            }
        except (OSError, json.JSONDecodeError, KeyError):
            prior_retrievals = {}

    source_records: list[dict[str, Any]] = []
    raw_payloads: dict[str, bytes] = {}
    retrievals: dict[str, str] = {}
    with httpx.Client(
        transport=transport,
        follow_redirects=True,
        timeout=90,
        headers={"User-Agent": "fx-factor-research-cftc-calendar/1.0"},
    ) as client:
        for source in SOURCES:
            raw_path = raw_directory / source.filename
            sha_path = raw_path.with_suffix(raw_path.suffix + ".sha256")
            if raw_path.is_file() and not refresh:
                payload = raw_path.read_bytes()
                retrieval = prior_retrievals.get(source.source_id, _iso_utc(retrieved_at))
            else:
                response = client.get(source.url)
                response.raise_for_status()
                payload = bytes(response.content)
                _atomic_write(raw_path, payload)
                retrieval = _iso_utc(retrieved_at)
            _validate_source(source, payload)
            raw_hash = _sha256_bytes(payload)
            _atomic_write(
                sha_path,
                f"{raw_hash}  {raw_path.name}\n".encode("ascii"),
            )
            raw_payloads[source.source_id] = payload
            retrievals[source.source_id] = retrieval
            source_records.append(
                {
                    "source_id": source.source_id,
                    "url": source.url,
                    "publisher": source.publisher,
                    "role": source.role,
                    "retrieved_at": retrieval,
                    "raw_path": str(raw_path.relative_to(output)),
                    "sha256_path": str(sha_path.relative_to(output)),
                    "raw_bytes": len(payload),
                    "raw_sha256": raw_hash,
                    "fixed_wayback_snapshot": source.year is not None,
                }
            )

    annual_payloads = {
        source.year: raw_payloads[source.source_id]
        for source in ANNUAL_SOURCES
        if source.year is not None
    }
    rows = _calendar_rows(annual_payloads, retrieved_at_by_source=retrievals)
    calendar_payload = _calendar_csv(rows)
    _atomic_write(calendar_path, calendar_payload)

    evidence_counts: dict[str, int] = {}
    verified_actual_rows = 0
    for row in rows:
        kind = row["date_evidence_kind"]
        evidence_counts[kind] = evidence_counts.get(kind, 0) + 1
        verified_actual_rows += int(row["verified_actual"] == "true")
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "dataset_kind": "cftc_cot_release_calendar",
        "generation_version": GENERATION_VERSION,
        "created_at": _iso_utc(retrieved_at),
        "calendar_file": calendar_path.name,
        "calendar_sha256": _sha256_bytes(calendar_payload),
        "coverage_release_year_start": START_YEAR,
        "coverage_release_year_end": END_YEAR,
        "rows": len(rows),
        "date_evidence_counts": evidence_counts,
        "verified_actual_date_rows": verified_actual_rows,
        "verified_actual_timestamp_rows": 0,
        "mapping_contract_sha256": _mapping_contract_sha256(),
        "research_role": (
            "release-date evidence preparation only; not an alpha signal and not a "
            "point-in-time positioning-vintage archive"
        ),
        "quality_warning": (
            "Annual rows are official tentative schedules.  2019 rows after the first "
            "catch-up date are rule-derived.  The 2025 final table contains intended dates. "
            "Only ION issue dates are verified actual, and their exact times are unknown."
        ),
        "sources": source_records,
    }
    _atomic_write(
        manifest_path,
        json.dumps(manifest, indent=2, allow_nan=False).encode("utf-8"),
    )
    return calendar_path, manifest_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the hash-audited 2016-2025 CFTC COT release calendar"
    )
    parser.add_argument("--output-dir", default="data/cftc_release_calendar")
    parser.add_argument("--refresh", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    calendar_path, manifest_path = download_calendar(
        args.output_dir,
        refresh=args.refresh,
    )
    print(f"Calendar: {calendar_path}")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
