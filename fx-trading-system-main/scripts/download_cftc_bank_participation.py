#!/usr/bin/env python3
"""Download and normalize official monthly CFTC Bank Participation Reports.

This is a Bank Participation Report (BPR) archive, not Commitments of Traders
data and not spot-FX order flow.  Links are first enumerated from CFTC's own
report page and Solr content index.  Those official indexes currently omit a
frozen set of 78 2019--2022 month/type keys.  For only those keys, the program
uses one transparently inferred official-path candidate and accepts it only
after the page's unique report date and full Futures/Options schema verify the
requested month and type.  It still requires exactly one accepted Futures and
one Options page for every month from 2016-01 through 2025-12.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import os
import re
import sys
import time as time_module
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Final, Literal
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx

PROGRAM_VERSION: Final = "cftc-bank-participation-v3.2"
MANIFEST_SCHEMA_VERSION: Final = 3
HOST: Final = "www.cftc.gov"
BASE_URL: Final = f"https://{HOST}"
INDEX_URL: Final = f"{BASE_URL}/MarketReports/BankParticipationReports/index.htm"
SCHEDULE_URL: Final = (
    f"{BASE_URL}/MarketReports/BankParticipationReports/ReleaseSchedule/index.htm"
)
SPECIAL_URL: Final = (
    f"{BASE_URL}/MarketReports/BankParticipationReports/"
    "HistoricalSpecialAnnouncements/index.htm"
)
SEARCH_URL: Final = f"{BASE_URL}/solr-search/content"
START_YEAR: Final = 2016
END_YEAR: Final = 2025
MAX_RESPONSE_BYTES: Final = 2 * 1024 * 1024
DEFAULT_REQUEST_DELAY: Final = 0.75
NEW_YORK: Final = ZoneInfo("America/New_York")
CACHE_GENERATIONS_RELATIVE: Final = Path("raw") / "cache" / "generations"

ReportType = Literal["futures", "options"]

REPORT_PATH = re.compile(
    r"^/MarketReports/(?:BankParticipationReports|BankParticipation)/"
    r"dea(?P<month>[a-z]+)(?P<year>\d{2})(?P<kind>[fo])(?:\.html)?$",
    re.IGNORECASE,
)
MONTH_TOKENS: Final[dict[str, int]] = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
EXCEPTIONAL_MONTH_TOKENS: Final[dict[tuple[str, str, str], int]] = {
    # Official CFTC search titles and page bodies identify these post-shutdown
    # paths as the February and March 2019 Futures reports respectively.
    ("jfeb", "19", "f"): 2,
    ("jmar", "19", "f"): 3,
}
INFERRED_MONTH_TOKENS: Final[tuple[str, ...]] = (
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
)
# This set is evidence about the current official indexes, not a general license
# to synthesize any missing BPR URL.  Re-audit and amend it if CFTC discovery
# changes.  2019-02/03 Futures are already enumerated under jfeb/jmar aliases.
INFERRED_DISCOVERY_KEYS: Final[frozenset[tuple[int, int, str]]] = frozenset(
    {
        *(
            (2019, month, report_type)
            for month in (4, 11, 12)
            for report_type in ("futures", "options")
        ),
        *(
            (year, month, report_type)
            for year in range(2020, 2023)
            for month in range(1, 13)
            for report_type in ("futures", "options")
        ),
    }
)
INFERRED_DISCOVERY_METHOD: Final = "inferred_official_path_validated_by_page_body"
INFERRED_DISCOVERY_VERIFICATION: Final = (
    "unique_report_date_and_report_type_schema_verified"
)
FX_CONTRACTS: Final[dict[str, str]] = {
    "CME AUSTRALIAN DOLLAR": "AUD",
    "CME CANADIAN DOLLAR": "CAD",
    "CME SWISS FRANC": "CHF",
    "CME EURO FX": "EUR",
    "CME BRITISH POUND": "GBP",
    "CME JAPANESE YEN": "JPY",
    "CME NEW ZEALAND DOLLAR": "NZD",
}

OUTPUT_COLUMNS: Final[tuple[str, ...]] = (
    "report_date",
    "report_month",
    "report_type",
    "option_basis",
    "contract",
    "market",
    "currency",
    "page_disclosed_fx_contracts",
    "page_missing_fx_contracts",
    "fx_contract_coverage_quality",
    "bank_type",
    "bank_type_raw",
    "bank_count",
    "long_futures_contracts",
    "long_futures_oi_pct",
    "short_futures_contracts",
    "short_futures_oi_pct",
    "open_interest",
    "long_calls_contracts",
    "long_calls_oi_pct",
    "short_calls_contracts",
    "short_calls_oi_pct",
    "call_open_interest",
    "long_puts_contracts",
    "long_puts_oi_pct",
    "short_puts_contracts",
    "short_puts_oi_pct",
    "put_open_interest",
    "direction_convention",
    "release_date",
    "release_time_local",
    "release_timezone",
    "release_timestamp_utc",
    "release_date_quality",
    "release_time_quality",
    "release_verified_actual",
    "strict_pit_eligible",
    "availability_time",
    "availability_quality",
    "release_evidence_url",
    "value_vintage_quality",
    "source_discovery_method",
    "source_discovery_verification",
    "source_url",
    "source_sha256",
)


@dataclass(frozen=True)
class Cell:
    text: str
    rowspan: int = 1
    colspan: int = 1


@dataclass(frozen=True)
class Table:
    rows: tuple[tuple[Cell, ...], ...]
    heading: str
    caption: str


@dataclass(frozen=True)
class Link:
    href: str
    text: str
    rel: str


@dataclass(frozen=True)
class ReportLink:
    year: int
    month: int
    report_type: ReportType
    url: str
    alternate_urls: tuple[str, ...] = ()
    discovery_method: str = "official_index_or_search_link"

    @property
    def source_id(self) -> str:
        return f"bpr_{self.year:04d}_{self.month:02d}_{self.report_type}"


class _HTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[Table] = []
        self.links: list[Link] = []
        self.text_parts: list[str] = []
        self._heading = ""
        self._heading_parts: list[str] | None = None
        self._caption_parts: list[str] | None = None
        self._current_caption = ""
        self._table_rows: list[tuple[Cell, ...]] | None = None
        self._row: list[Cell] | None = None
        self._cell_parts: list[str] | None = None
        self._cell_rowspan = 1
        self._cell_colspan = 1
        self._link_parts: list[str] | None = None
        self._link_href = ""
        self._link_rel = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        if tag in {"h1", "h2", "h3"}:
            self._heading_parts = []
        elif tag == "table":
            if self._table_rows is not None:
                raise ValueError("nested CFTC HTML tables are unsupported")
            self._table_rows = []
            self._caption_parts = None
            self._current_caption = ""
        elif tag == "caption" and self._table_rows is not None:
            self._caption_parts = []
        elif tag == "tr" and self._table_rows is not None:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell_parts = []
            self._cell_rowspan = _positive_span(attributes.get("rowspan", "1"))
            self._cell_colspan = _positive_span(attributes.get("colspan", "1"))
        elif tag == "a":
            self._link_parts = []
            self._link_href = attributes.get("href", "")
            self._link_rel = attributes.get("rel", "")

    def handle_data(self, data: str) -> None:
        self.text_parts.append(data)
        if self._heading_parts is not None:
            self._heading_parts.append(data)
        if self._caption_parts is not None:
            self._caption_parts.append(data)
        if self._cell_parts is not None:
            self._cell_parts.append(data)
        if self._link_parts is not None:
            self._link_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h1", "h2", "h3"} and self._heading_parts is not None:
            heading = _clean(" ".join(self._heading_parts))
            if heading:
                self._heading = heading
            self._heading_parts = None
        elif tag in {"td", "th"} and self._cell_parts is not None:
            assert self._row is not None
            self._row.append(
                Cell(
                    _clean(" ".join(self._cell_parts)),
                    self._cell_rowspan,
                    self._cell_colspan,
                )
            )
            self._cell_parts = None
        elif tag == "tr" and self._row is not None:
            assert self._table_rows is not None
            self._table_rows.append(tuple(self._row))
            self._row = None
        elif tag == "caption" and self._caption_parts is not None:
            self._current_caption = _clean(" ".join(self._caption_parts))
            self._caption_parts = None
        elif tag == "table" and self._table_rows is not None:
            self.tables.append(
                Table(tuple(self._table_rows), self._heading, self._current_caption)
            )
            self._table_rows = None
            self._caption_parts = None
        elif tag == "a" and self._link_parts is not None:
            self.links.append(
                Link(self._link_href, _clean(" ".join(self._link_parts)), self._link_rel)
            )
            self._link_parts = None


def _clean(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def _positive_span(value: str) -> int:
    try:
        result = int(value)
    except ValueError as error:
        raise ValueError(f"invalid HTML table span {value!r}") from error
    if not 1 <= result <= 20:
        raise ValueError(f"invalid HTML table span {value!r}")
    return result


def _parse_html(payload: bytes) -> _HTML:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("CFTC response is not valid UTF-8 HTML") from error
    parser = _HTML()
    parser.feed(text)
    parser.close()
    return parser


def _expand_rows(table: Table) -> list[list[str]]:
    pending: dict[int, tuple[str, int]] = {}
    expanded: list[list[str]] = []
    for raw_row in table.rows:
        row: list[str] = []
        column = 0
        for cell in raw_row:
            column = _consume_pending(pending, row, column)
            for offset in range(cell.colspan):
                row.append(cell.text)
                if cell.rowspan > 1:
                    pending[column + offset] = (cell.text, cell.rowspan - 1)
            column += cell.colspan
        _consume_pending(pending, row, column)
        expanded.append(row)
    if pending:
        raise ValueError("CFTC table ended before its rowspans were complete")
    return expanded


def _consume_pending(
    pending: dict[int, tuple[str, int]],
    row: list[str],
    column: int,
) -> int:
    while column in pending:
        text, remaining = pending[column]
        row.append(text)
        if remaining == 1:
            del pending[column]
        else:
            pending[column] = (text, remaining - 1)
        column += 1
    return column


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(payload)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _parse_report_link(href: str) -> ReportLink | None:
    absolute = urljoin(BASE_URL, href)
    parsed = urlparse(absolute)
    if parsed.scheme != "https" or parsed.hostname != HOST or parsed.query or parsed.fragment:
        return None
    match = REPORT_PATH.fullmatch(parsed.path)
    if match is None:
        return None
    month_token = match.group("month").lower()
    year_token = match.group("year")
    kind_token = match.group("kind").lower()
    month = MONTH_TOKENS.get(month_token) or EXCEPTIONAL_MONTH_TOKENS.get(
        (month_token, year_token, kind_token)
    )
    if month is None:
        raise ValueError(f"unrecognized CFTC BPR month token in {href!r}")
    year = 2000 + int(year_token)
    report_type: ReportType = "futures" if kind_token == "f" else "options"
    return ReportLink(year, month, report_type, absolute)


def _enumerated_link_map(
    payloads: Iterable[bytes],
) -> dict[tuple[int, int, str], dict[str, ReportLink]]:
    by_key: dict[tuple[int, int, str], dict[str, ReportLink]] = {}
    for payload in payloads:
        parser = _parse_html(payload)
        for anchor in parser.links:
            report = _parse_report_link(anchor.href)
            if report is None or not START_YEAR <= report.year <= END_YEAR:
                continue
            key = (report.year, report.month, report.report_type)
            by_key.setdefault(key, {})[report.url] = report
    return by_key


def _expected_report_keys() -> set[tuple[int, int, str]]:
    return {
        (year, month, report_type)
        for year in range(START_YEAR, END_YEAR + 1)
        for month in range(1, 13)
        for report_type in ("futures", "options")
    }


def _finalize_discovery(
    by_key: dict[tuple[int, int, str], dict[str, ReportLink]],
) -> tuple[ReportLink, ...]:
    expected = _expected_report_keys()
    missing = sorted(expected - set(by_key))
    extra = sorted(set(by_key) - expected)
    if missing or extra:
        raise ValueError(
            f"CFTC BPR discovery is incomplete: missing={missing[:8]} ({len(missing)}), "
            f"extra={extra[:8]} ({len(extra)})"
        )
    reports: list[ReportLink] = []
    for key in sorted(by_key):
        urls = sorted(
            by_key[key],
            key=lambda url: (not urlparse(url).path.lower().endswith(".html"), url),
        )
        selected = by_key[key][urls[0]]
        reports.append(
            ReportLink(
                selected.year,
                selected.month,
                selected.report_type,
                selected.url,
                tuple(urls[1:]),
                selected.discovery_method,
            )
        )
    return tuple(reports)


def discover_links(payloads: Iterable[bytes]) -> tuple[ReportLink, ...]:
    """Require complete official link enumeration without inferred candidates."""

    return _finalize_discovery(_enumerated_link_map(payloads))


def _inferred_candidate(key: tuple[int, int, str]) -> ReportLink:
    if key not in INFERRED_DISCOVERY_KEYS:
        raise ValueError(f"CFTC BPR key is not approved for inferred discovery: {key}")
    year, month, report_type_raw = key
    report_type: ReportType = "futures" if report_type_raw == "futures" else "options"
    kind = "f" if report_type == "futures" else "o"
    token = INFERRED_MONTH_TOKENS[month - 1]
    url = (
        f"{BASE_URL}/MarketReports/BankParticipationReports/"
        f"dea{token}{year % 100:02d}{kind}"
    )
    return ReportLink(
        year,
        month,
        report_type,
        url,
        # This is a fixed, auditable fallback rather than a result of automatic
        # discovery.  ``parse_report`` must still validate its unique REPORT
        # DATE and exact Futures/Options schema before any row can be emitted.
        discovery_method=INFERRED_DISCOVERY_METHOD,
    )


def discover_links_with_inferred_candidates(
    payloads: Iterable[bytes],
) -> tuple[ReportLink, ...]:
    """Fill only audited current-index gaps with fixed, body-verified candidates."""

    by_key = _enumerated_link_map(payloads)
    missing = _expected_report_keys() - set(by_key)
    unapproved = sorted(missing - INFERRED_DISCOVERY_KEYS)
    if unapproved:
        raise ValueError(
            "CFTC BPR discovery has new gaps outside the frozen inferred set: "
            f"{unapproved[:8]} ({len(unapproved)})"
        )
    for key in sorted(missing):
        candidate = _inferred_candidate(key)
        by_key[key] = {candidate.url: candidate}
    return _finalize_discovery(by_key)


def _normalized_page_signature(rows: list[dict[str, object]]) -> tuple[str, ...]:
    columns = OUTPUT_COLUMNS[:-2]
    return tuple(
        sorted(
            json.dumps(
                {column: row[column] for column in columns},
                sort_keys=True,
                separators=(",", ":"),
            )
            for row in rows
        )
    )


def _page_coverage(
    report: ReportLink, rows: list[dict[str, object]]
) -> dict[str, str]:
    disclosed = sorted({str(row["contract"]) for row in rows})
    missing = sorted(set(FX_CONTRACTS) - {contract.upper() for contract in disclosed})
    verification = (
        INFERRED_DISCOVERY_VERIFICATION
        if report.discovery_method == INFERRED_DISCOVERY_METHOD
        else "official_link_enumerated"
    )
    return {
        "discovery_verification": verification,
        "disclosed_fx_contracts": "|".join(disclosed),
        "missing_fx_contracts": "|".join(missing),
        "coverage_quality": (
            "all_frozen_fx_contracts_disclosed"
            if not missing
            else "explicitly_audited_official_page_non_disclosure"
        ),
    }


def _integer(value: str, *, field: str, optional: bool = False) -> int | None:
    token = value.replace(",", "").strip()
    if optional and not token:
        return None
    if not re.fullmatch(r"\d+", token):
        raise ValueError(f"invalid {field}: {value!r}")
    return int(token)


def _percent(value: str, *, field: str) -> float:
    token = value.strip().removesuffix("%")
    try:
        result = float(token)
    except ValueError as error:
        raise ValueError(f"invalid {field}: {value!r}") from error
    if not math.isfinite(result) or not 0 <= result <= 100:
        raise ValueError(f"invalid {field}: {value!r}")
    return result


def _report_date(parser: _HTML) -> date:
    matches = {
        date(int(year), int(month), int(day))
        for month, day, year in re.findall(
            r"REPORT\s+DATE\s*:\s*(\d{1,2})/(\d{1,2})/(\d{4})",
            _clean(" ".join(parser.text_parts)),
            flags=re.IGNORECASE,
        )
    }
    if len(matches) != 1:
        raise ValueError(f"CFTC BPR page must contain one report date, found {sorted(matches)}")
    return matches.pop()


def _bank_type(raw: str) -> str:
    normalized = raw.upper().replace(" ", "")
    if normalized in {"U.S.", "US", "U.S"}:
        return "U.S."
    if normalized in {"NONU.S.", "NONUS", "NON-U.S."}:
        return "NON U.S."
    if normalized in {"", "TOTAL", "COMBINED"}:
        return "COMBINED"
    raise ValueError(f"unexpected CFTC bank type {raw!r}")


def _option_basis(heading: str, page_text: str) -> str:
    evidence = f"{heading} {page_text}".upper()
    if "NOT DELTA ADJUSTED" in evidence:
        return "contracts_not_delta_adjusted"
    if "DELTA ADJUSTED" in evidence:
        return "delta_adjusted"
    if "OPTIONS IN CONTRACT" in evidence:
        return "contracts_unspecified_delta_treatment"
    return "official_options_basis_not_stated"


def parse_report(
    report: ReportLink,
    payload: bytes,
    *,
    retrieved_at: datetime,
    schedule: dict[date, tuple[date, str]] | None = None,
    special_payload: bytes | None = None,
) -> list[dict[str, object]]:
    parser = _parse_html(payload)
    report_date = _report_date(parser)
    if (report_date.year, report_date.month) != (report.year, report.month):
        raise ValueError(f"{report.source_id}: report date does not match discovered month")
    page_text = _clean(" ".join(parser.text_parts))
    release = _release_fields(
        report_date,
        retrieved_at=retrieved_at,
        schedule=schedule or {},
        special_payload=special_payload,
    )
    discovery_verification = (
        INFERRED_DISCOVERY_VERIFICATION
        if report.discovery_method == INFERRED_DISCOVERY_METHOD
        else "official_link_enumerated"
    )
    raw_hash = _sha256(payload)
    output: list[dict[str, object]] = []
    found_tables = 0
    for table in parser.tables:
        rows = _expand_rows(table)
        header_index = next(
            (
                index
                for index, row in enumerate(rows)
                if len(row) >= 3
                and tuple(value.upper() for value in row[:3])
                == ("COMMODITY", "BANK TYPE", "BANK COUNT")
            ),
            None,
        )
        if header_index is None:
            continue
        header = [value.upper() for value in rows[header_index]]
        futures_header = [
            "COMMODITY",
            "BANK TYPE",
            "BANK COUNT",
            "LONG FUTURES",
            "%",
            "SHORT FUTURES",
            "%",
            "OPEN INTEREST",
        ]
        options_header = [
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
        expected = futures_header if report.report_type == "futures" else options_header
        if header != expected:
            raise ValueError(f"{report.source_id}: report table header drifted: {header}")
        found_tables += 1
        basis = "not_applicable" if report.report_type == "futures" else _option_basis(
            table.heading, page_text
        )
        table_rows: list[dict[str, object]] = []
        for row in rows[header_index + 1 :]:
            if len(row) != len(expected) or not any(row):
                continue
            contract = row[0].strip()
            contract_key = contract.upper()
            currency = FX_CONTRACTS.get(contract_key)
            if currency is None:
                continue
            bank_type = _bank_type(row[1])
            common: dict[str, object] = {
                "report_date": report_date.isoformat(),
                "report_month": f"{report.year:04d}-{report.month:02d}",
                "report_type": report.report_type,
                "option_basis": basis,
                "contract": contract,
                "market": contract.split(maxsplit=1)[0],
                "currency": currency,
                "page_disclosed_fx_contracts": "",
                "page_missing_fx_contracts": "",
                "fx_contract_coverage_quality": "",
                "bank_type": bank_type,
                "bank_type_raw": row[1],
                "bank_count": _integer(row[2], field="bank_count", optional=True),
                "long_futures_contracts": "",
                "long_futures_oi_pct": "",
                "short_futures_contracts": "",
                "short_futures_oi_pct": "",
                "open_interest": "",
                "long_calls_contracts": "",
                "long_calls_oi_pct": "",
                "short_calls_contracts": "",
                "short_calls_oi_pct": "",
                "call_open_interest": "",
                "long_puts_contracts": "",
                "long_puts_oi_pct": "",
                "short_puts_contracts": "",
                "short_puts_oi_pct": "",
                "put_open_interest": "",
                "direction_convention": "official_contract_orientation_no_fx_inversion",
                **release,
                "value_vintage_quality": (
                    "official_corrected_permanent_report_current_copy"
                    if report.year == 2018 and report.month == 12
                    else "official_permanent_report_current_copy_not_verified_as_published_vintage"
                ),
                "source_discovery_method": report.discovery_method,
                "source_discovery_verification": discovery_verification,
                "source_url": report.url,
                "source_sha256": raw_hash,
            }
            if report.report_type == "futures":
                common.update(
                    {
                        "long_futures_contracts": _integer(row[3], field="long futures"),
                        "long_futures_oi_pct": _percent(row[4], field="long futures pct"),
                        "short_futures_contracts": _integer(row[5], field="short futures"),
                        "short_futures_oi_pct": _percent(row[6], field="short futures pct"),
                        "open_interest": _integer(
                            row[7], field="open interest", optional=True
                        ),
                    }
                )
            else:
                common.update(
                    {
                        "long_calls_contracts": _integer(row[3], field="long calls"),
                        "long_calls_oi_pct": _percent(row[4], field="long calls pct"),
                        "short_calls_contracts": _integer(row[5], field="short calls"),
                        "short_calls_oi_pct": _percent(row[6], field="short calls pct"),
                        "call_open_interest": _integer(
                            row[7], field="call open interest", optional=True
                        ),
                        "long_puts_contracts": _integer(row[8], field="long puts"),
                        "long_puts_oi_pct": _percent(row[9], field="long puts pct"),
                        "short_puts_contracts": _integer(row[10], field="short puts"),
                        "short_puts_oi_pct": _percent(row[11], field="short puts pct"),
                        "put_open_interest": _integer(
                            row[12], field="put open interest", optional=True
                        ),
                    }
                )
            table_rows.append(common)
        _validate_bank_groups(report, table_rows, basis)
        _propagate_open_interest(table_rows, report.report_type)
        output.extend(table_rows)
    if found_tables != 1:
        raise ValueError(f"{report.source_id}: expected one report table, found {found_tables}")
    coverage = _page_coverage(report, output)
    for row in output:
        row["page_disclosed_fx_contracts"] = coverage["disclosed_fx_contracts"]
        row["page_missing_fx_contracts"] = coverage["missing_fx_contracts"]
        row["fx_contract_coverage_quality"] = coverage["coverage_quality"]
    return output


def _validate_bank_groups(
    report: ReportLink,
    rows: list[dict[str, object]],
    basis: str,
) -> None:
    groups: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        groups.setdefault(str(row["contract"]), []).append(row)
    for contract, group in groups.items():
        bank_types = [str(row["bank_type"]) for row in group]
        if sorted(bank_types) != ["COMBINED", "NON U.S.", "U.S."]:
            raise ValueError(
                f"{report.source_id}: {contract} {basis} bank rows are incomplete: {bank_types}"
            )


def _propagate_open_interest(rows: list[dict[str, object]], report_type: str) -> None:
    fields = (
        ("open_interest",)
        if report_type == "futures"
        else ("call_open_interest", "put_open_interest")
    )
    contracts = {str(row["contract"]) for row in rows}
    for contract in contracts:
        group = [row for row in rows if row["contract"] == contract]
        for field in fields:
            values = {row[field] for row in group if row[field] != "" and row[field] is not None}
            if len(values) != 1:
                raise ValueError(f"{contract}: expected one official {field}, found {values}")
            value = values.pop()
            for row in group:
                row[field] = value


def parse_release_schedule(payload: bytes) -> dict[date, tuple[date, str]]:
    parser = _parse_html(payload)
    mappings: dict[date, tuple[date, str]] = {}
    for table in parser.tables:
        if not re.fullmatch(r"20\d{2}", table.caption):
            continue
        year = int(table.caption)
        rows = _expand_rows(table)
        for row in rows:
            if len(row) < 3 or row[0].strip().lower() not in MONTH_TOKENS:
                continue
            month = MONTH_TOKENS[row[0].strip().lower()]
            report_match = re.fullmatch(r"(\d{1,2})(\**)", row[1].strip())
            release_match = re.fullmatch(r"(\d{1,2})(\**)", row[2].strip())
            if report_match is None or release_match is None:
                raise ValueError(f"unrecognized CFTC BPR schedule row: {row}")
            report_date = date(year, month, int(report_match.group(1)))
            release_date = date(year, month, int(release_match.group(1)))
            marker = release_match.group(2)
            if report_date in mappings:
                raise ValueError(f"duplicate CFTC BPR schedule report date {report_date}")
            mappings[report_date] = (release_date, marker)
    if not mappings:
        raise ValueError("CFTC BPR release schedule contains no dated rows")
    return mappings


def _release_fields(
    report_date: date,
    *,
    retrieved_at: datetime,
    schedule: dict[date, tuple[date, str]],
    special_payload: bytes | None,
) -> dict[str, object]:
    special_text = (
        _clean(" ".join(_parse_html(special_payload).text_parts))
        if special_payload
        else ""
    )
    if report_date.year == 2018 and report_date.month == 12:
        if "March 13, 2019" not in special_text:
            raise ValueError("December 2018 CFTC BPR correction evidence is missing")
    shutdown_without_bpr_release_evidence = report_date.year == 2019 and report_date.month == 1
    if shutdown_without_bpr_release_evidence:
        if "March 13, 2019" not in special_text:
            raise ValueError("2019 CFTC BPR special page evidence is missing or drifted")
        return {
            "release_date": "",
            "release_time_local": "",
            "release_timezone": "America/New_York",
            "release_timestamp_utc": "",
            "release_date_quality": (
                "federal_shutdown_period_no_bpr_specific_release_date_evidence"
            ),
            "release_time_quality": "unknown_not_actual",
            "release_verified_actual": False,
            "strict_pit_eligible": False,
            "availability_time": _iso(retrieved_at),
            "availability_quality": (
                "conservative_retrieval_missing_historical_exception_evidence"
            ),
            "release_evidence_url": SPECIAL_URL,
        }
    interrupted = date(2025, 10, 1) <= report_date <= date(2025, 11, 12)
    if interrupted:
        if "interrupted from October 1 – November 12" not in special_text:
            raise ValueError(
                "2025 CFTC BPR interruption lacks official special-announcement evidence"
            )
        return {
            "release_date": "",
            "release_time_local": "",
            "release_timezone": "America/New_York",
            "release_timestamp_utc": "",
            "release_date_quality": "official_exception_no_complete_release_date",
            "release_time_quality": "unknown_not_actual",
            "release_verified_actual": False,
            "strict_pit_eligible": False,
            "availability_time": _iso(retrieved_at),
            "availability_quality": "conservative_retrieval_after_official_exception",
            "release_evidence_url": SPECIAL_URL,
        }
    if report_date in schedule:
        release_date, marker = schedule[report_date]
        date_quality = (
            "official_exception_announced_intended_not_actual"
            if marker
            else "official_tentative_schedule_not_actual"
        )
        evidence_url = SCHEDULE_URL
    else:
        days_until_friday = (4 - report_date.weekday()) % 7
        if days_until_friday == 0:
            days_until_friday = 7
        release_date = report_date + timedelta(days=days_until_friday)
        date_quality = "rule_derived_from_official_first_friday_policy"
        evidence_url = SCHEDULE_URL
    scheduled = datetime.combine(
        release_date,
        time(15, 30),
        tzinfo=NEW_YORK,
    )
    conservative = datetime.combine(
        release_date + timedelta(days=1),
        time.min,
        tzinfo=NEW_YORK,
    )
    return {
        "release_date": release_date.isoformat(),
        "release_time_local": "15:30",
        "release_timezone": "America/New_York",
        "release_timestamp_utc": _iso(scheduled),
        "release_date_quality": date_quality,
        "release_time_quality": "inherited_general_rule_not_actual",
        "release_verified_actual": False,
        "strict_pit_eligible": False,
        "availability_time": _iso(conservative),
        "availability_quality": (
            "rule_derived_exploratory_next_local_day_not_actual_verified"
        ),
        "release_evidence_url": evidence_url,
    }


def _search_query(year: int, report_type: ReportType) -> str:
    label = "Futures" if report_type == "futures" else "Options"
    return f'"Bank Participation Report {label}" AND {year}'


def _search_url(year: int, report_type: ReportType, page: int) -> str:
    return f"{SEARCH_URL}?{urlencode({'keys': _search_query(year, report_type), 'page': page})}"


def _next_search_page(
    payload: bytes,
    *,
    expected_page: int,
    expected_query: str,
) -> bool:
    parser = _parse_html(payload)
    next_links = [anchor.href for anchor in parser.links if "next" in anchor.rel.split()]
    if not next_links:
        return False
    if len(next_links) != 1:
        raise ValueError("CFTC search index contains duplicate next-page links")
    # Drupal emits query-only pager links.  Resolve them against the frozen
    # search endpoint, otherwise ``urljoin(BASE_URL, "?page=1")`` loses the
    # ``/solr-search/content`` path even though the official link is valid.
    parsed = urlparse(urljoin(SEARCH_URL, next_links[0]))
    query = parse_qs(parsed.query)
    if parsed.hostname not in {None, HOST} or parsed.path != "/solr-search/content":
        raise ValueError("CFTC search next page escaped the official index")
    if query.get("keys") != [expected_query]:
        raise ValueError("CFTC search pagination changed the frozen discovery query")
    if query.get("page") != [str(expected_page)]:
        raise ValueError("CFTC search pagination is not sequential")
    return True


def _retry_after_seconds(value: str) -> float | None:
    """Return a non-negative numeric Retry-After value when CFTC supplied one."""

    token = value.strip()
    if not token:
        return None
    try:
        seconds = float(token)
    except ValueError:
        # HTTP-date values cannot be safely interpreted without the response
        # Date clock.  Fall back to the deliberately slow exponential policy.
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _fetch(
    url: str,
    *,
    timeout: float,
    retries: int,
    transport: httpx.BaseTransport | None,
    sleep: Callable[[float], None],
) -> tuple[bytes, dict[str, str]]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != HOST:
        raise ValueError(f"refusing non-CFTC URL: {url}")
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with httpx.Client(
                transport=transport,
                follow_redirects=True,
                timeout=timeout,
                headers={"User-Agent": f"{PROGRAM_VERSION} (+public research archive)"},
            ) as client:
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    if response.url.scheme != "https" or response.url.host != HOST:
                        raise ValueError("CFTC BPR redirect escaped the official HTTPS host")
                    declared = response.headers.get("Content-Length")
                    if declared and int(declared) > MAX_RESPONSE_BYTES:
                        raise ValueError("CFTC BPR response exceeds declared size limit")
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > MAX_RESPONSE_BYTES:
                            raise ValueError("CFTC BPR response exceeds streamed size limit")
                        chunks.append(chunk)
                    payload = b"".join(chunks)
                    if not payload:
                        raise ValueError("CFTC BPR response is empty")
                    return payload, {
                        "content_type": response.headers.get("Content-Type", ""),
                        "etag": response.headers.get("ETag", ""),
                        "last_modified": response.headers.get("Last-Modified", ""),
                    }
        except ValueError:
            raise
        except httpx.HTTPStatusError as error:
            last_error = error
            status_code = error.response.status_code
            if status_code == 403:
                raise RuntimeError(
                    f"CFTC returned HTTP 403 for official BPR request {url}. The downloader "
                    "will not bypass access controls; retry later from an approved network "
                    "or obtain an official manual export."
                ) from error
            if status_code < 500 and status_code != 429:
                raise
            if attempt < retries:
                retry_after = _retry_after_seconds(error.response.headers.get("Retry-After", ""))
                if retry_after is not None and retry_after > 60:
                    raise RuntimeError(
                        "CFTC requested Retry-After "
                        f"{retry_after:g} seconds; refusing to poll before that interval. "
                        "Run the downloader again after the stated interval."
                    ) from error
                delay = (
                    max(DEFAULT_REQUEST_DELAY, retry_after)
                    if retry_after is not None
                    else 0.75 * (2**attempt)
                )
                sleep(delay)
        except (httpx.HTTPError, OSError) as error:
            last_error = error
            if attempt < retries:
                sleep(min(8.0, 0.75 * (2**attempt)))
    assert last_error is not None
    raise last_error


def _load_source(
    root: Path,
    *,
    source_id: str,
    url: str,
    prior: dict[str, object] | None = None,
    cache_directory: Path | None = None,
    refresh: bool,
    timeout: float,
    retries: int,
    transport: httpx.BaseTransport | None,
    sleep: Callable[[float], None],
    retrieved_at: datetime,
) -> tuple[bytes, dict[str, object]]:
    cache_root = cache_directory or root / "raw" / "cache"
    cache = cache_root / f"{source_id}.html"
    sidecar = cache.with_suffix(".meta.json")
    if cache.is_file() and not refresh:
        if prior is None:
            raise ValueError(f"{source_id}: orphan cached source has no prior manifest record")
        if cache.is_symlink() or sidecar.is_symlink():
            raise ValueError(f"{source_id}: cached source or metadata cannot be a symlink")
        try:
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"{source_id}: cached source lacks valid metadata") from error
        expected_cache = cache.relative_to(root).as_posix()
        expected_sidecar = sidecar.relative_to(root).as_posix()
        if (
            prior.get("source_id") != source_id
            or prior.get("url") != url
            or prior.get("cache_path") != expected_cache
            or prior.get("cache_metadata_path") != expected_sidecar
        ):
            raise ValueError(f"{source_id}: prior manifest cache identity does not match")
        payload = cache.read_bytes()
        digest = _sha256(payload)
        for field in (
            "source_id",
            "url",
            "retrieved_at",
            "bytes",
            "sha256",
            "content_type",
            "etag",
            "last_modified",
        ):
            if metadata.get(field) != prior.get(field):
                raise ValueError(
                    f"{source_id}: cached metadata differs from the prior manifest at {field}"
                )
        if (
            metadata.get("source_id") != source_id
            or metadata.get("url") != url
            or metadata.get("bytes") != len(payload)
            or metadata.get("sha256") != digest
        ):
            raise ValueError(f"{source_id}: cached source URL/hash verification failed")
        try:
            source_retrieved = datetime.fromisoformat(
                str(metadata["retrieved_at"]).replace("Z", "+00:00")
            )
        except ValueError as error:
            raise ValueError(f"{source_id}: cached retrieval timestamp is invalid") from error
        if source_retrieved.tzinfo is None or _iso(source_retrieved) != metadata["retrieved_at"]:
            raise ValueError(f"{source_id}: cached retrieval timestamp is not canonical UTC")
        archive = _manifest_file(
            root,
            prior.get("archive_path"),
            field=f"{source_id} prior archive_path",
        )
        if archive.is_symlink() or not archive.is_file() or _sha256(archive.read_bytes()) != digest:
            raise ValueError(f"{source_id}: archived snapshot hash mismatch")
        status = "cached"
        response_metadata = {
            key: str(metadata.get(key, ""))
            for key in ("content_type", "etag", "last_modified")
        }
    else:
        if not refresh and (prior is not None or sidecar.exists()):
            raise ValueError(f"{source_id}: prior cache is incomplete; use --refresh")
        payload, response_metadata = _fetch(
            url,
            timeout=timeout,
            retries=retries,
            transport=transport,
            sleep=sleep,
        )
        parser = _parse_html(payload)
        if "CFTC" not in _clean(" ".join(parser.text_parts)):
            raise ValueError(f"{source_id}: response is not a recognizable CFTC page")
        _atomic_write(cache, payload)
        source_retrieved = retrieved_at
        status = "downloaded"
        metadata = {
            "source_id": source_id,
            "url": url,
            "retrieved_at": _iso(source_retrieved),
            "bytes": len(payload),
            "sha256": _sha256(payload),
            **response_metadata,
        }
        _atomic_write(sidecar, (json.dumps(metadata, indent=2) + "\n").encode())
    digest = _sha256(payload)
    archive = (
        root
        / "raw"
        / "archive"
        / source_id
        / f"{source_retrieved.strftime('%Y%m%dT%H%M%S%fZ')}_{digest[:16]}.html"
    )
    if archive.exists() and _sha256(archive.read_bytes()) != digest:
        raise ValueError(f"{source_id}: archived snapshot hash mismatch")
    if not archive.exists():
        _atomic_write(archive, payload)
    return payload, {
        "source_id": source_id,
        "url": url,
        "status": status,
        "retrieved_at": _iso(source_retrieved),
        "bytes": len(payload),
        "sha256": digest,
        "cache_path": cache.relative_to(root).as_posix(),
        "cache_metadata_path": sidecar.relative_to(root).as_posix(),
        "archive_path": archive.relative_to(root).as_posix(),
        **response_metadata,
    }


def _manifest_file(root: Path, value: object, *, field: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError(f"{field} is not a safe relative path")
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"{field} escapes the output directory")
    return path


def _new_cache_generation(root: Path, retrieved_at: datetime) -> Path:
    """Create an isolated cache generation without deleting earlier attempts."""

    generations = root / CACHE_GENERATIONS_RELATIVE
    generations.mkdir(parents=True, exist_ok=True)
    if generations.is_symlink() or not generations.is_dir():
        raise ValueError("CFTC BPR cache generations directory must be a regular directory")
    timestamp = retrieved_at.strftime("%Y%m%dT%H%M%S%fZ")
    for _ in range(10):
        candidate = generations / f"{timestamp}_{uuid4().hex[:12]}"
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise RuntimeError("could not allocate an isolated CFTC BPR cache generation")


def _cache_generation_from_sources(
    root: Path,
    sources: dict[str, dict[str, object]],
) -> Path:
    """Recover the single manifest-authorized cache generation from sources."""

    if not sources:
        raise ValueError("prior CFTC BPR manifest has no source records")
    directories = {
        _manifest_file(root, record.get("cache_path"), field=f"{source_id} cache_path").parent
        for source_id, record in sources.items()
    }
    if len(directories) != 1:
        raise ValueError("prior CFTC BPR sources span multiple cache generations")
    return directories.pop()


def _load_incomplete_generation(
    root: Path, generation: Path
) -> tuple[Path, dict[str, dict[str, object]]]:
    generations_root = (root / CACHE_GENERATIONS_RELATIVE).resolve()
    resolved = generation.expanduser().resolve()
    if (
        resolved.parent != generations_root
        or resolved.is_symlink()
        or not resolved.is_dir()
    ):
        raise ValueError("resume generation must be a regular direct child of cache/generations")
    files = {path.name: path for path in resolved.iterdir() if path.is_file()}
    if any(path.is_dir() or path.is_symlink() for path in resolved.iterdir()):
        raise ValueError("resume generation contains a directory or symlink")
    html_ids = {name[:-5] for name in files if name.endswith(".html")}
    metadata_ids = {name[:-10] for name in files if name.endswith(".meta.json")}
    if not html_ids or html_ids != metadata_ids or len(files) != 2 * len(html_ids):
        raise ValueError("resume generation must contain complete HTML/metadata pairs only")
    records: dict[str, dict[str, object]] = {}
    for source_id in sorted(html_ids):
        cache = files[f"{source_id}.html"]
        sidecar = files[f"{source_id}.meta.json"]
        try:
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(f"{source_id}: invalid resume metadata") from error
        if not isinstance(metadata, dict):
            raise ValueError(f"{source_id}: invalid resume metadata object")
        payload = cache.read_bytes()
        digest = _sha256(payload)
        url = metadata.get("url")
        if not isinstance(url, str):
            raise ValueError(f"{source_id}: resume metadata lacks URL")
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != HOST:
            raise ValueError(f"{source_id}: resume URL is not official CFTC HTTPS")
        retrieved_value = metadata.get("retrieved_at")
        try:
            retrieved_at = datetime.fromisoformat(
                str(retrieved_value).replace("Z", "+00:00")
            )
        except ValueError as error:
            raise ValueError(f"{source_id}: invalid resume retrieval timestamp") from error
        if retrieved_at.tzinfo is None or _iso(retrieved_at) != retrieved_value:
            raise ValueError(f"{source_id}: non-canonical resume retrieval timestamp")
        if (
            metadata.get("source_id") != source_id
            or metadata.get("bytes") != len(payload)
            or metadata.get("sha256") != digest
        ):
            raise ValueError(f"{source_id}: resume cache identity/hash mismatch")
        archive_root = root / "raw" / "archive" / source_id
        candidates = sorted(archive_root.glob(f"*_{digest[:16]}.html"))
        if not candidates or any(
            path.is_symlink()
            or not path.is_file()
            or _sha256(path.read_bytes()) != digest
            for path in candidates
        ):
            raise ValueError(f"{source_id}: resume archive hash mismatch")
        archive = candidates[-1]
        records[source_id] = {
            **metadata,
            "cache_path": cache.relative_to(root).as_posix(),
            "cache_metadata_path": sidecar.relative_to(root).as_posix(),
            "archive_path": archive.relative_to(root).as_posix(),
        }
    return resolved, records


def _load_prior_sources(root: Path) -> dict[str, dict[str, object]]:
    manifest_path = root / "cftc_bank_participation_manifest.json"
    manifest_sidecar = manifest_path.with_suffix(".sha256")
    cache_root = root / "raw" / "cache"
    if not manifest_path.exists() and not manifest_sidecar.exists():
        if cache_root.exists() and any(path.is_file() for path in cache_root.rglob("*")):
            raise ValueError("orphan CFTC BPR cache exists without a prior manifest; use --refresh")
        return {}
    if (
        not manifest_path.is_file()
        or not manifest_sidecar.is_file()
        or manifest_path.is_symlink()
        or manifest_sidecar.is_symlink()
    ):
        raise ValueError("prior CFTC BPR manifest and SHA-256 sidecar must both be regular files")
    payload = manifest_path.read_bytes()
    expected_hash = _sha256(payload)
    try:
        sidecar_fields = manifest_sidecar.read_text(encoding="ascii").strip().split()
    except (OSError, UnicodeError) as error:
        raise ValueError("prior CFTC BPR manifest sidecar is unreadable") from error
    if sidecar_fields != [expected_hash]:
        raise ValueError("prior CFTC BPR manifest SHA-256 verification failed")
    try:
        manifest = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("prior CFTC BPR manifest is unreadable") from error
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION
        or manifest.get("program_version") != PROGRAM_VERSION
        or manifest.get("dataset_kind")
        != "cftc_bank_participation_reports_not_cot_not_spot_order_flow"
    ):
        raise ValueError("prior CFTC BPR manifest contract is invalid; use --refresh")
    normalized = _manifest_file(
        root,
        manifest.get("normalized_path"),
        field="prior normalized_path",
    )
    normalized_hash = manifest.get("normalized_sha256")
    if (
        not isinstance(normalized_hash, str)
        or not re.fullmatch(r"[0-9a-f]{64}", normalized_hash)
        or normalized.is_symlink()
        or not normalized.is_file()
        or _sha256(normalized.read_bytes()) != normalized_hash
    ):
        raise ValueError("prior normalized CFTC BPR output hash verification failed")
    cache_generation = _manifest_file(
        root,
        manifest.get("cache_generation"),
        field="prior cache_generation",
    )
    generations_root = (root / CACHE_GENERATIONS_RELATIVE).resolve()
    if (
        cache_generation.is_symlink()
        or not cache_generation.is_dir()
        or cache_generation.parent != generations_root
    ):
        raise ValueError("prior CFTC BPR cache generation is invalid")
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("prior CFTC BPR manifest has no source records")
    records: dict[str, dict[str, object]] = {}
    expected_cache_files: set[Path] = set()
    for index, record in enumerate(sources):
        if not isinstance(record, dict):
            raise ValueError(f"prior CFTC BPR source record {index} is invalid")
        source_id = record.get("source_id")
        if not isinstance(source_id, str) or not source_id or source_id in records:
            raise ValueError(f"prior CFTC BPR source_id at record {index} is invalid")
        digest = record.get("sha256")
        size = record.get("bytes")
        if (
            not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or not isinstance(size, int)
            or size <= 0
        ):
            raise ValueError(f"prior CFTC BPR source record {source_id} hash/size is invalid")
        for field in ("cache_path", "cache_metadata_path", "archive_path"):
            path = _manifest_file(root, record.get(field), field=f"{source_id} {field}")
            if field != "archive_path":
                expected_name = (
                    f"{source_id}.html"
                    if field == "cache_path"
                    else f"{source_id}.meta.json"
                )
                if path.parent != cache_generation or path.name != expected_name:
                    raise ValueError(
                        f"prior CFTC BPR source {source_id} is outside its cache generation"
                    )
                if path in expected_cache_files:
                    raise ValueError(f"prior CFTC BPR source cache path is duplicated: {path}")
                expected_cache_files.add(path)
        records[source_id] = record
    actual_cache_files = (
        {path.resolve() for path in cache_generation.rglob("*") if path.is_file()}
        if cache_generation.exists()
        else set()
    )
    if actual_cache_files != expected_cache_files:
        raise ValueError(
            "prior CFTC BPR cache generation has missing or orphan files; use --refresh"
        )
    return records


def _write_rows(rows: list[dict[str, object]], path: Path) -> str:
    keys = {
        (
            row["report_date"],
            row["report_type"],
            row["option_basis"],
            row["contract"],
            row["bank_type"],
        )
        for row in rows
    }
    if not rows or len(keys) != len(rows):
        raise ValueError("normalized CFTC BPR rows are empty or duplicated")
    ordered = sorted(rows, key=lambda row: tuple(str(row[field]) for field in OUTPUT_COLUMNS[:9]))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as binary:
            with gzip.GzipFile(filename="", mode="wb", fileobj=binary, mtime=0) as compressed:
                with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text:
                    writer = csv.DictWriter(text, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
                    writer.writeheader()
                    writer.writerows(ordered)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return _sha256(path.read_bytes())


def download_bpr(
    output_directory: str | Path,
    *,
    refresh: bool = False,
    timeout: float = 60.0,
    retries: int = 3,
    request_delay: float = DEFAULT_REQUEST_DELAY,
    resume_generation: Path | None = None,
    transport: httpx.BaseTransport | None = None,
    now: datetime | None = None,
    sleep: Callable[[float], None] = time_module.sleep,
) -> tuple[Path, Path]:
    if timeout <= 0 or not 0 <= retries <= 10 or request_delay < 0:
        raise ValueError("invalid timeout, retries, or request delay")
    root = Path(output_directory).expanduser().resolve()
    retrieved_at = (now or datetime.now(UTC)).astimezone(UTC)
    if refresh and resume_generation is not None:
        raise ValueError("--refresh and --resume-generation are mutually exclusive")
    resume_incomplete = resume_generation is not None
    if resume_generation is not None:
        cache_directory, prior_sources = _load_incomplete_generation(
            root, resume_generation
        )
    else:
        prior_sources = {} if refresh else _load_prior_sources(root)
        cache_directory = (
            _cache_generation_from_sources(root, prior_sources)
            if prior_sources
            else _new_cache_generation(root, retrieved_at)
        )
    source_records: list[dict[str, object]] = []
    network_loads = 0

    def load(source_id: str, url: str) -> bytes:
        nonlocal network_loads
        if prior_sources and source_id not in prior_sources and not resume_incomplete:
            raise ValueError(
                f"{source_id}: source is absent from the prior manifest; use --refresh"
            )
        if network_loads and request_delay:
            sleep(request_delay)
        payload, record = _load_source(
            root,
            source_id=source_id,
            url=url,
            prior=prior_sources.get(source_id),
            cache_directory=cache_directory,
            refresh=refresh,
            timeout=timeout,
            retries=retries,
            transport=transport,
            sleep=sleep,
            retrieved_at=retrieved_at,
        )
        if record["status"] == "downloaded":
            network_loads += 1
        source_records.append(record)
        return payload

    index_payload = load("bpr_index", INDEX_URL)
    schedule_payload = load("bpr_release_schedule", SCHEDULE_URL)
    special_payload = load("bpr_special_announcements", SPECIAL_URL)
    search_payloads: list[bytes] = []
    for year in range(START_YEAR, END_YEAR + 1):
        for report_type in ("futures", "options"):
            for page in range(5):
                payload = load(
                    f"bpr_search_{year}_{report_type}_{page}",
                    _search_url(year, report_type, page),
                )
                search_payloads.append(payload)
                if not _next_search_page(
                    payload,
                    expected_page=page + 1,
                    expected_query=_search_query(year, report_type),
                ):
                    break
            else:
                raise ValueError(f"CFTC search pagination exceeded five pages for {year}")
    links = discover_links_with_inferred_candidates([index_payload, *search_payloads])
    schedule = parse_release_schedule(schedule_payload)
    rows: list[dict[str, object]] = []
    for report in links:
        selected_source_index = len(source_records)
        payload = load(report.source_id, report.url)
        report_rows = parse_report(
            report,
            payload,
            retrieved_at=retrieved_at,
            schedule=schedule,
            special_payload=special_payload,
        )
        coverage = _page_coverage(report, report_rows)
        source_records[selected_source_index].update(
            {
                "discovery_method": report.discovery_method,
                "discovery_verification": coverage["discovery_verification"],
                "disclosed_fx_contracts": coverage["disclosed_fx_contracts"],
                "missing_fx_contracts": coverage["missing_fx_contracts"],
                "fx_contract_coverage_quality": coverage["coverage_quality"],
            }
        )
        expected_signature = _normalized_page_signature(report_rows)
        for alias_number, alias_url in enumerate(report.alternate_urls, start=1):
            alias_source_index = len(source_records)
            alias_payload = load(f"{report.source_id}_alias_{alias_number}", alias_url)
            alias_rows = parse_report(
                ReportLink(report.year, report.month, report.report_type, alias_url),
                alias_payload,
                retrieved_at=retrieved_at,
                schedule=schedule,
                special_payload=special_payload,
            )
            alias_coverage = _page_coverage(report, alias_rows)
            if _normalized_page_signature(alias_rows) != expected_signature:
                raise ValueError(
                    f"CFTC BPR official duplicate pages disagree for "
                    f"{report.year:04d}-{report.month:02d} {report.report_type}"
                )
            source_records[alias_source_index].update(
                {
                    "alias_of": report.source_id,
                    "discovery_method": "official_duplicate_alias_link",
                    "discovery_verification": "body_report_date_and_schema_verified",
                    "disclosed_fx_contracts": alias_coverage["disclosed_fx_contracts"],
                    "missing_fx_contracts": alias_coverage["missing_fx_contracts"],
                    "fx_contract_coverage_quality": alias_coverage["coverage_quality"],
                }
            )
        rows.extend(report_rows)
    if prior_sources and set(prior_sources) != {
        str(record["source_id"]) for record in source_records
    }:
        raise ValueError("prior CFTC BPR manifest contains stale source records; use --refresh")
    disclosed_contracts = {str(row["contract"]).upper() for row in rows}
    if disclosed_contracts != set(FX_CONTRACTS):
        raise ValueError(
            "complete CFTC BPR archive did not disclose every frozen FX contract at least once; "
            f"missing={sorted(set(FX_CONTRACTS) - disclosed_contracts)}"
        )
    normalized = root / "normalized" / "cftc_bank_participation_fx.csv.gz"
    normalized_hash = _write_rows(rows, normalized)
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "program_version": PROGRAM_VERSION,
        "dataset_kind": "cftc_bank_participation_reports_not_cot_not_spot_order_flow",
        "retrieved_at": _iso(retrieved_at),
        "cache_generation": cache_directory.relative_to(root).as_posix(),
        "coverage": {"start": "2016-01", "end": "2025-12", "monthly_pages": 240},
        "discovery": {
            "officially_enumerated_pages": sum(
                report.discovery_method == "official_index_or_search_link"
                for report in links
            ),
            "inferred_candidate_pages_body_verified": sum(
                report.discovery_method == INFERRED_DISCOVERY_METHOD
                for report in links
            ),
            "frozen_inferred_key_allowlist_size": len(INFERRED_DISCOVERY_KEYS),
            "inferred_candidate_policy": (
                "single official-host historical-directory path; accept only after unique "
                "report date and exact report-type schema verification"
            ),
        },
        "rows": len(rows),
        "contracts": sorted({str(row["contract"]) for row in rows}),
        "pages_with_missing_frozen_fx_contracts": sum(
            1
            for source in source_records
            if source.get("missing_fx_contracts")
        ),
        "pages_with_zero_disclosed_frozen_fx_contracts": sum(
            1
            for source in source_records
            if source.get("missing_fx_contracts") and not source.get("disclosed_fx_contracts")
        ),
        "normalized_path": normalized.relative_to(root).as_posix(),
        "normalized_sha256": normalized_hash,
        "sources": source_records,
        "limitations": [
            "BPR bank positions are futures/options aggregates, not signed spot-FX order flow.",
            "Futures long/short and options call/put columns retain official contract orientation.",
            "Scheduled or rule-derived release times are not verified actual publication times.",
            "Every row has strict_pit_eligible=false because permanent pages are current copies "
            "and historical actual release timestamps/exceptions are incomplete.",
            "Each report page records its disclosed and missing frozen FX contracts; absent "
            "contracts are never filled with zero.",
            "The January 2019 shutdown period uses retrieval time because the official BPR "
            "special page does not provide a report-specific publication date.",
            "The October-November 2025 interruption uses retrieval time when no complete release "
            "date evidence is available.",
            "The December 2018 permanent page is a corrected report, not its original snapshot.",
            "The official BPR page and Solr index currently enumerate only 162 of the 240 "
            "required month/type keys. The remaining frozen 78 keys use one transparent "
            "inferred official historical-path candidate, labelled "
            "inferred_official_path_validated_by_page_body only after unique body REPORT DATE "
            "and exact report-type schema verification.",
            "Each refresh writes a new manifest-authorized cache generation and never deletes "
            "an earlier incomplete cache attempt; only the generation named by this manifest is "
            "trusted on a later non-refresh run.",
        ],
    }
    manifest_path = root / "cftc_bank_participation_manifest.json"
    manifest_payload = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode()
    _atomic_write(manifest_path, manifest_payload)
    _atomic_write(
        manifest_path.with_suffix(".sha256"),
        f"{_sha256(manifest_payload)}\n".encode(),
    )
    _atomic_write(
        root
        / "manifests"
        / f"cftc_bpr_{retrieved_at.strftime('%Y%m%dT%H%M%S%fZ')}.json",
        manifest_payload,
    )
    return normalized, manifest_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/cftc_bank_participation"))
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument(
        "--resume-generation",
        type=Path,
        help="Resume a hash-verified incomplete raw/cache/generations child",
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--request-delay", type=float, default=DEFAULT_REQUEST_DELAY)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        normalized, manifest = download_bpr(
            args.output,
            refresh=args.refresh,
            timeout=args.timeout,
            retries=args.retries,
            request_delay=args.request_delay,
            resume_generation=args.resume_generation,
        )
    except Exception as error:
        print(f"CFTC BPR download failed: {error}", file=sys.stderr)
        return 1
    print(f"Wrote {normalized}")
    print(f"Wrote {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
