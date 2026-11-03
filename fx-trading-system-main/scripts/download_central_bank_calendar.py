#!/usr/bin/env python3
"""Build a hash-audited 2016-2025 central-bank policy blackout calendar.

Version 1 implements official adapters for the Fed, ECB, BoJ and RBA.  The
BoE, SNB, BoC and RBNZ adapters are deliberately declared ``fail_closed`` in
the manifest until their historical archives have equally strict parsers.
Partial output is useful for audit and development, but the formal loader
rejects it unless every adapter is complete.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import re
import time as time_module
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx

START_DATE: Final = date(2016, 1, 1)
END_DATE: Final = date(2025, 12, 31)
GENERATION_VERSION: Final = "central-bank-policy-calendar-v1"
MAX_RESPONSE_BYTES: Final = 8 * 1024 * 1024
MIN_REQUEST_INTERVAL_SECONDS: Final = 0.10
MAX_RETRY_AFTER_SECONDS: Final = 60.0
AUTHORITIES: Final[tuple[str, ...]] = (
    "FED",
    "ECB",
    "BOE",
    "BOJ",
    "SNB",
    "BOC",
    "RBA",
    "RBNZ",
)
IMPLEMENTED_AUTHORITIES: Final[tuple[str, ...]] = ("FED", "ECB", "BOJ", "RBA")
OFFICIAL_HOST_BY_AUTHORITY: Final[dict[str, str]] = {
    "FED": "www.federalreserve.gov",
    "ECB": "www.ecb.europa.eu",
    "BOJ": "www.boj.or.jp",
    "RBA": "www.rba.gov.au",
}
CALENDAR_COLUMNS: Final[tuple[str, ...]] = (
    "event_id",
    "currency",
    "authority",
    "event_type",
    "scheduled_status",
    "decision_date_local",
    "release_time_local",
    "release_tzid",
    "release_time_raw",
    "release_at_utc",
    "timestamp_quality",
    "rule_id",
    "rule_effective_from",
    "rule_effective_to",
    "source_url",
    "source_document_type",
    "source_title",
    "retrieved_at_utc",
    "source_sha256",
    "supersedes_event_id",
    "cancelled",
    "notes",
)


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    authority: str
    url: str
    filename: str
    document_type: str
    title: str


@dataclass(frozen=True)
class Snapshot:
    spec: SourceSpec
    payload: bytes
    retrieved_at: str
    raw_path: Path
    sha256_path: Path
    sha256: str


@dataclass(frozen=True)
class ParsedLink:
    event_date: date
    url: str
    title: str


FED_INDEX_SOURCES: Final[tuple[SourceSpec, ...]] = tuple(
    SourceSpec(
        f"fed_fomc_{year}",
        "FED",
        f"https://www.federalreserve.gov/monetarypolicy/fomchistorical{year}.htm",
        f"fed/fomc_{year}.html",
        "official_meeting_archive_html",
        f"Federal Reserve FOMC historical materials {year}",
    )
    for year in range(2016, 2021)
) + (
    SourceSpec(
        "fed_fomc_current_archive",
        "FED",
        "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        "fed/fomc_calendars.html",
        "official_meeting_calendar_html",
        "Federal Reserve FOMC calendars and information",
    ),
)

ECB_YEAR_SOURCES: Final[tuple[SourceSpec, ...]] = tuple(
    SourceSpec(
        f"ecb_mopo_{year}",
        "ECB",
        f"https://www.ecb.europa.eu/press/govcdec/mopo/{year}/html/"
        "index_include.en.html",
        f"ecb/monetary_policy_decisions_{year}.html",
        "official_decision_archive_html",
        f"ECB monetary policy decisions {year}",
    )
    for year in range(2016, 2026)
)

BOJ_YEAR_SOURCES: Final[tuple[SourceSpec, ...]] = tuple(
    SourceSpec(
        f"boj_policy_{year}",
        "BOJ",
        f"https://www.boj.or.jp/en/mopo/mpmdeci/state_{year}/index.htm",
        f"boj/statements_on_monetary_policy_{year}.html",
        "official_decision_archive_html",
        f"Bank of Japan statements on monetary policy {year}",
    )
    for year in range(2016, 2026)
)

RBA_YEAR_SOURCES: Final[tuple[SourceSpec, ...]] = tuple(
    SourceSpec(
        f"rba_decisions_{year}",
        "RBA",
        f"https://www.rba.gov.au/monetary-policy/int-rate-decisions/{year}/",
        f"rba/monetary_policy_decisions_{year}.html",
        "official_decision_archive_html",
        f"Reserve Bank of Australia monetary policy decisions {year}",
    )
    for year in range(2016, 2026)
)

FED_EXPECTED_BY_YEAR: Final[dict[int, int]] = {
    **{year: 8 for year in range(2016, 2026)},
    2020: 9,
}
ECB_EXPECTED_BY_YEAR: Final[dict[int, int]] = {
    **{year: 8 for year in range(2016, 2026)},
    2020: 9,
    2022: 9,
}
BOJ_EXPECTED_BY_YEAR: Final[dict[int, int]] = {
    **{year: 8 for year in range(2016, 2026)},
    2020: 9,
}
RBA_EXPECTED_BY_YEAR: Final[dict[int, int]] = {
    **{year: 11 for year in range(2016, 2024)},
    2020: 12,
    2024: 8,
    2025: 8,
}

FED_UNSCHEDULED: Final[frozenset[date]] = frozenset(
    {date(2020, 3, 3), date(2020, 3, 15)}
)
FED_NON_MEETING_RELEASES: Final[frozenset[date]] = frozenset(
    {
        date(2019, 10, 11),
        date(2020, 3, 23),
        date(2020, 3, 31),
        date(2020, 8, 27),
        date(2025, 8, 22),
    }
)
ECB_UNSCHEDULED: Final[dict[date, str]] = {
    date(2020, 3, 18): "asset_purchase_decision",
    date(2022, 6, 15): "policy_framework_decision",
}
BOJ_UNSCHEDULED: Final[dict[date, str]] = {
    date(2020, 3, 16): "rate_decision",
    date(2020, 5, 22): "asset_purchase_decision",
}
RBA_UNSCHEDULED: Final[frozenset[date]] = frozenset({date(2020, 3, 19)})

_TAG_PATTERN: Final = re.compile(r"<[^>]+>")
_HASH_PATTERN: Final = re.compile(r"[0-9a-f]{64}")
_FED_LINK_PATTERN: Final = re.compile(
    r'href="(?P<href>/newsevents/pressreleases/monetary(?P<day>\d{8})a\.htm)"',
    re.IGNORECASE,
)
_FED_TIME_PATTERN: Final = re.compile(
    r"For\s+release\s+at\s+(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*"
    r"(?P<period>[ap])\.m\.\s*(?P<zone>EST|EDT)",
    re.IGNORECASE,
)
_ECB_ROW_PATTERN: Final = re.compile(
    r'<dt\s+isoDate="(?P<day>\d{4}-\d{2}-\d{2})".*?</dt>\s*<dd>.*?'
    r'<div\s+class="title"><a\s+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_BOJ_ROW_PATTERN: Final = re.compile(
    r"<tr>\s*<td>(?P<day>.*?)</td>\s*<td><a\s+href=\"(?P<href>[^\"]+)\"[^>]*>"
    r"(?P<title>.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
_BOJ_ACTUAL_TIME_PATTERN: Final = re.compile(
    r"--\s*(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*"
    r"[A-Za-z]+\s+\d{1,2}(?:,\s+\d{4})?\s+at\s+(?P<time>\d{1,2}:\d{2})",
    re.IGNORECASE,
)
_RBA_LINK_PATTERN_TEMPLATE: Final = (
    r'<a\s+href="(?P<href>/media-releases/{year}/[^"]+)">(?P<day>[^<]+)</a>'
)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _clean_html(value: str) -> str:
    return " ".join(html.unescape(_TAG_PATTERN.sub("", value)).replace("\xa0", " ").split())


def _local_to_utc(day: date, clock: time, tzid: str) -> str:
    value = datetime.combine(day, clock, tzinfo=ZoneInfo(tzid)).astimezone(UTC)
    return _iso_utc(value)


def _validate_html(spec: SourceSpec, payload: bytes) -> None:
    if len(payload) < 300:
        raise ValueError(f"{spec.source_id}: response is implausibly small")
    text = payload.decode("utf-8-sig", errors="strict")
    lowered = text.lower()
    if "<html" not in lowered and "<dt" not in lowered:
        raise ValueError(f"{spec.source_id}: response is not HTML")
    if "website unavailable" in lowered or "enable javascript and cookies" in lowered:
        raise ValueError(f"{spec.source_id}: upstream challenge/error page received")


def _validate_official_source_url(spec: SourceSpec) -> None:
    expected_host = OFFICIAL_HOST_BY_AUTHORITY.get(spec.authority)
    parsed = urlparse(spec.url)
    if (
        expected_host is None
        or parsed.scheme != "https"
        or parsed.hostname != expected_host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
    ):
        raise ValueError(
            f"{spec.source_id}: URL must stay on the official {spec.authority} HTTPS host"
        )


def _retry_after_seconds(value: str | None) -> float:
    if value is None:
        return 0.0
    stripped = value.strip()
    if stripped.isdigit():
        return float(stripped)
    try:
        parsed = parsedate_to_datetime(stripped)
    except (TypeError, ValueError) as error:
        raise ValueError("invalid Retry-After response header") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Retry-After HTTP date must include a timezone")
    return max(0.0, (parsed.astimezone(UTC) - datetime.now(UTC)).total_seconds())


class SnapshotStore:
    def __init__(
        self,
        output: Path,
        client: httpx.Client,
        *,
        refresh: bool,
        retrieved_at: datetime,
        prior_sources: dict[str, dict[str, Any]],
        retries: int,
    ) -> None:
        self.output = output
        self.client = client
        self.refresh = refresh
        self.retrieved_at = retrieved_at
        self.prior_sources = prior_sources
        self.retries = retries
        self.snapshots: dict[str, Snapshot] = {}
        self._last_request_at: float | None = None

    def get(self, spec: SourceSpec) -> Snapshot:
        _validate_official_source_url(spec)
        existing = self.snapshots.get(spec.source_id)
        if existing is not None:
            if existing.spec.url != spec.url:
                raise ValueError(f"duplicate source_id with different URL: {spec.source_id}")
            return existing
        raw_path = self.output / "raw" / spec.filename
        sidecar_path = raw_path.with_suffix(raw_path.suffix + ".sha256")
        prior = self.prior_sources.get(spec.source_id, {})
        if raw_path.is_file() and not self.refresh:
            payload, retrieval, digest = self._verified_cached_payload(
                spec,
                raw_path=raw_path,
                sidecar_path=sidecar_path,
                prior=prior,
            )
        else:
            if prior and not self.refresh:
                raise ValueError(
                    f"{spec.source_id}: prior manifest cache file is missing; use --refresh"
                )
            payload = self._request(spec.url)
            retrieval = _iso_utc(self.retrieved_at)
            digest = _sha256_bytes(payload)
            _atomic_write(raw_path, payload)
            _atomic_write(sidecar_path, f"{digest}  {raw_path.name}\n".encode("ascii"))
        _validate_html(spec, payload)
        snapshot = Snapshot(
            spec=spec,
            payload=payload,
            retrieved_at=retrieval,
            raw_path=raw_path,
            sha256_path=sidecar_path,
            sha256=digest,
        )
        self.snapshots[spec.source_id] = snapshot
        return snapshot

    def _verified_cached_payload(
        self,
        spec: SourceSpec,
        *,
        raw_path: Path,
        sidecar_path: Path,
        prior: dict[str, Any],
    ) -> tuple[bytes, str, str]:
        if not prior:
            raise ValueError(
                f"{spec.source_id}: orphan raw cache has no prior manifest record; use --refresh"
            )
        expected_raw_path = str(raw_path.relative_to(self.output))
        expected_sidecar_path = str(sidecar_path.relative_to(self.output))
        if prior.get("url") != spec.url:
            raise ValueError(f"{spec.source_id}: cached URL differs from the prior manifest")
        if prior.get("raw_path") != expected_raw_path:
            raise ValueError(f"{spec.source_id}: cached raw_path differs from the prior manifest")
        if prior.get("sha256_path") != expected_sidecar_path:
            raise ValueError(
                f"{spec.source_id}: cached sha256_path differs from the prior manifest"
            )
        prior_hash = prior.get("raw_sha256")
        if not isinstance(prior_hash, str) or _HASH_PATTERN.fullmatch(prior_hash) is None:
            raise ValueError(f"{spec.source_id}: prior manifest SHA-256 is invalid")
        retrieval = prior.get("retrieved_at")
        if not isinstance(retrieval, str) or not retrieval:
            raise ValueError(f"{spec.source_id}: prior retrieval timestamp is missing")
        if not sidecar_path.is_file():
            raise ValueError(f"{spec.source_id}: cached SHA-256 sidecar is missing; use --refresh")
        try:
            sidecar_fields = sidecar_path.read_text(encoding="ascii").strip().split()
        except (OSError, UnicodeError) as error:
            raise ValueError(f"{spec.source_id}: cached SHA-256 sidecar is unreadable") from error
        if len(sidecar_fields) != 2 or sidecar_fields != [prior_hash, raw_path.name]:
            raise ValueError(f"{spec.source_id}: cached SHA-256 sidecar does not match manifest")
        payload = raw_path.read_bytes()
        if _sha256_bytes(payload) != prior_hash:
            raise ValueError(f"{spec.source_id}: cached raw SHA-256 does not match manifest")
        raw_bytes = prior.get("raw_bytes")
        if not isinstance(raw_bytes, int) or raw_bytes != len(payload):
            raise ValueError(f"{spec.source_id}: cached raw size does not match manifest")
        return payload, retrieval, prior_hash

    def _request(self, url: str) -> bytes:
        parsed_url = urlparse(url)
        if (
            parsed_url.scheme != "https"
            or parsed_url.hostname not in set(OFFICIAL_HOST_BY_AUTHORITY.values())
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.port not in {None, 443}
        ):
            raise ValueError("request URL is outside the official central-bank host allowlist")
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self._respect_minimum_interval()
            try:
                response = self.client.get(url)
                if response.status_code == 429:
                    retry_after = _retry_after_seconds(response.headers.get("retry-after"))
                    if retry_after > MAX_RETRY_AFTER_SECONDS:
                        raise ValueError(
                            f"Retry-After exceeds {MAX_RETRY_AFTER_SECONDS:g} seconds"
                        )
                    if attempt < self.retries:
                        time_module.sleep(retry_after)
                        continue
                response.raise_for_status()
                length = response.headers.get("content-length")
                if length is not None and int(length) > MAX_RESPONSE_BYTES:
                    raise ValueError(f"response exceeds {MAX_RESPONSE_BYTES} bytes")
                payload = bytes(response.content)
                if len(payload) > MAX_RESPONSE_BYTES:
                    raise ValueError(f"response exceeds {MAX_RESPONSE_BYTES} bytes")
                return payload
            except (httpx.HTTPError, ValueError) as error:
                last_error = error
                if attempt == self.retries:
                    break
                time_module.sleep(min(0.25 * (2**attempt), 2.0))
        raise ValueError(
            f"download failed after {self.retries + 1} attempts: {url}"
        ) from last_error

    def _respect_minimum_interval(self) -> None:
        now = time_module.monotonic()
        if self._last_request_at is not None:
            remaining = MIN_REQUEST_INTERVAL_SECONDS - (now - self._last_request_at)
            if remaining > 0:
                time_module.sleep(remaining)
        self._last_request_at = time_module.monotonic()

    def manifest_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for source_id in sorted(self.snapshots):
            snapshot = self.snapshots[source_id]
            records.append(
                {
                    "source_id": source_id,
                    "authority": snapshot.spec.authority,
                    "url": snapshot.spec.url,
                    "document_type": snapshot.spec.document_type,
                    "title": snapshot.spec.title,
                    "retrieved_at": snapshot.retrieved_at,
                    "raw_path": str(snapshot.raw_path.relative_to(self.output)),
                    "sha256_path": str(snapshot.sha256_path.relative_to(self.output)),
                    "raw_bytes": len(snapshot.payload),
                    "raw_sha256": snapshot.sha256,
                }
            )
        return records


def _row(
    *,
    event_id: str,
    currency: str,
    authority: str,
    event_type: str,
    scheduled_status: str,
    event_date: date,
    local_time: time | None,
    tzid: str,
    release_time_raw: str,
    quality: str,
    rule_id: str | None,
    rule_from: date | None,
    rule_to: date | None,
    snapshot: Snapshot,
    notes: str,
) -> dict[str, str]:
    return {
        "event_id": event_id,
        "currency": currency,
        "authority": authority,
        "event_type": event_type,
        "scheduled_status": scheduled_status,
        "decision_date_local": event_date.isoformat(),
        "release_time_local": local_time.strftime("%H:%M") if local_time else "",
        "release_tzid": tzid,
        "release_time_raw": release_time_raw,
        "release_at_utc": _local_to_utc(event_date, local_time, tzid) if local_time else "",
        "timestamp_quality": quality,
        "rule_id": rule_id or "",
        "rule_effective_from": rule_from.isoformat() if rule_from else "",
        "rule_effective_to": rule_to.isoformat() if rule_to else "",
        "source_url": snapshot.spec.url,
        "source_document_type": snapshot.spec.document_type,
        "source_title": snapshot.spec.title,
        "retrieved_at_utc": snapshot.retrieved_at,
        "source_sha256": snapshot.sha256,
        "supersedes_event_id": "",
        "cancelled": "false",
        "notes": notes,
    }


def _assert_year_counts(
    authority: str,
    links: list[ParsedLink],
    expected: dict[int, int],
) -> None:
    counts = {year: 0 for year in expected}
    for link in links:
        if link.event_date.year in counts:
            counts[link.event_date.year] += 1
    if counts != expected:
        raise ValueError(f"{authority}: archive coverage mismatch; counts={counts}")


def _parse_fed_index(payload: bytes) -> list[ParsedLink]:
    text = payload.decode("utf-8-sig")
    links: dict[date, ParsedLink] = {}
    for match in _FED_LINK_PATTERN.finditer(text):
        day = datetime.strptime(match.group("day"), "%Y%m%d").date()
        if START_DATE <= day <= END_DATE and day not in FED_NON_MEETING_RELEASES:
            url = urljoin("https://www.federalreserve.gov", match.group("href"))
            links[day] = ParsedLink(day, url, "FOMC statement")
    return sorted(links.values(), key=lambda link: link.event_date)


def _parse_fed_actual_time(payload: bytes) -> tuple[time, str]:
    text = _clean_html(payload.decode("utf-8-sig"))
    match = _FED_TIME_PATTERN.search(text)
    if match is None:
        raise ValueError("Fed statement does not contain an official release time")
    hour = int(match.group("hour")) % 12
    if match.group("period").lower() == "p":
        hour += 12
    minute = int(match.group("minute") or "0")
    raw = match.group(0)
    return time(hour, minute), raw


def _fed_events(store: SnapshotStore) -> list[dict[str, str]]:
    links_by_date: dict[date, ParsedLink] = {}
    for spec in FED_INDEX_SOURCES:
        for link in _parse_fed_index(store.get(spec).payload):
            links_by_date[link.event_date] = link
    links = sorted(links_by_date.values(), key=lambda link: link.event_date)
    _assert_year_counts("FED", links, FED_EXPECTED_BY_YEAR)
    rows: list[dict[str, str]] = []
    for link in links:
        day_token = link.event_date.strftime("%Y%m%d")
        spec = SourceSpec(
            f"fed_statement_{day_token}",
            "FED",
            link.url,
            f"fed/statements/monetary{day_token}a.html",
            "official_statement_html",
            f"Federal Reserve FOMC statement {link.event_date.isoformat()}",
        )
        snapshot = store.get(spec)
        local_time, raw = _parse_fed_actual_time(snapshot.payload)
        rows.append(
            _row(
                event_id=f"fed.{day_token}.rate_decision",
                currency="USD",
                authority="FED",
                event_type="rate_decision",
                scheduled_status=(
                    "unscheduled" if link.event_date in FED_UNSCHEDULED else "scheduled"
                ),
                event_date=link.event_date,
                local_time=local_time,
                tzid="America/New_York",
                release_time_raw=raw,
                quality="verified_actual_publication",
                rule_id=None,
                rule_from=None,
                rule_to=None,
                snapshot=snapshot,
                notes="Actual publication clock transcribed from the official statement.",
            )
        )
    return rows


def _parse_ecb_index(payload: bytes) -> list[ParsedLink]:
    text = payload.decode("utf-8-sig")
    links: dict[date, ParsedLink] = {}
    for match in _ECB_ROW_PATTERN.finditer(text):
        day = date.fromisoformat(match.group("day"))
        title = _clean_html(match.group("title"))
        if title.casefold() != "monetary policy decisions" and day not in ECB_UNSCHEDULED:
            continue
        links[day] = ParsedLink(
            day,
            urljoin("https://www.ecb.europa.eu", html.unescape(match.group("href"))),
            title,
        )
    return sorted(links.values(), key=lambda link: link.event_date)


def _ecb_events(store: SnapshotStore) -> list[dict[str, str]]:
    links: list[ParsedLink] = []
    source_by_year: dict[int, Snapshot] = {}
    source_by_date: dict[date, Snapshot] = {}
    for spec in ECB_YEAR_SOURCES:
        snapshot = store.get(spec)
        year = int(spec.source_id.rsplit("_", 1)[1])
        source_by_year[year] = snapshot
        year_links = _parse_ecb_index(snapshot.payload)
        links.extend(year_links)
        source_by_date.update({link.event_date: snapshot for link in year_links})
    emergency_spec = SourceSpec(
        "ecb_ad_hoc_20220615",
        "ECB",
        "https://www.ecb.europa.eu/press/pr/date/2022/html/"
        "ecb.pr220615~2aa3900e0a.en.html",
        "ecb/ad_hoc_meeting_20220615.html",
        "official_statement_html",
        "Statement after the ad hoc meeting of the ECB Governing Council",
    )
    emergency_snapshot = store.get(emergency_spec)
    emergency_text = _clean_html(emergency_snapshot.payload.decode("utf-8-sig"))
    if (
        "Statement after the ad hoc meeting of the ECB Governing Council"
        not in emergency_text
        or "15 June 2022" not in emergency_text
    ):
        raise ValueError("ECB 2022-06-15 ad hoc meeting evidence is incomplete")
    emergency_link = ParsedLink(
        date(2022, 6, 15),
        emergency_spec.url,
        emergency_spec.title,
    )
    links.append(emergency_link)
    source_by_date[emergency_link.event_date] = emergency_snapshot
    links = sorted(
        {link.event_date: link for link in links}.values(),
        key=lambda item: item.event_date,
    )
    _assert_year_counts("ECB", links, ECB_EXPECTED_BY_YEAR)
    rows: list[dict[str, str]] = []
    for link in links:
        event_type = ECB_UNSCHEDULED.get(link.event_date, "rate_decision")
        day_token = link.event_date.strftime("%Y%m%d")
        if link.event_date in ECB_UNSCHEDULED:
            local_time = None
            quality = "official_date_only"
            raw = "Official archive establishes the local date; no publication minute used."
            rule_id = None
            rule_from = None
            rule_to = None
        elif link.event_date < date(2022, 7, 21):
            local_time = time(13, 45)
            quality = "official_rule_derived"
            raw = "ECB decision announcement rule: 13:45 Frankfurt time"
            rule_id = "ecb.decision_release.1345.pre_20220721"
            rule_from = START_DATE
            rule_to = date(2022, 7, 20)
        else:
            local_time = time(14, 15)
            quality = "official_rule_derived"
            raw = "ECB decision announcement rule: 14:15 Frankfurt time"
            rule_id = "ecb.decision_release.1415.from_20220721"
            rule_from = date(2022, 7, 21)
            rule_to = END_DATE
        rows.append(
            _row(
                event_id=f"ecb.{day_token}.{event_type}",
                currency="EUR",
                authority="ECB",
                event_type=event_type,
                scheduled_status=(
                    "unscheduled" if link.event_date in ECB_UNSCHEDULED else "scheduled"
                ),
                event_date=link.event_date,
                local_time=local_time,
                tzid="Europe/Berlin",
                release_time_raw=raw,
                quality=quality,
                rule_id=rule_id,
                rule_from=rule_from,
                rule_to=rule_to,
                snapshot=source_by_date.get(
                    link.event_date, source_by_year[link.event_date.year]
                ),
                notes=(
                    "Official archive event date; timing rule is outcome-blind. "
                    f"Archive title: {link.title}"
                ),
            )
        )
    return rows


_BOJ_MONTHS: Final[dict[str, int]] = {
    "Jan.": 1,
    "Feb.": 2,
    "Mar.": 3,
    "Apr.": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "Aug.": 8,
    "Sept.": 9,
    "Oct.": 10,
    "Nov.": 11,
    "Dec.": 12,
}


def _parse_boj_date(value: str) -> date:
    cleaned = _clean_html(value)
    match = re.fullmatch(r"([A-Za-z]+\.?) (\d{1,2}), (\d{4})", cleaned)
    if match is None or match.group(1) not in _BOJ_MONTHS:
        raise ValueError(f"unrecognized BoJ event date {cleaned!r}")
    return date(int(match.group(3)), _BOJ_MONTHS[match.group(1)], int(match.group(2)))


def _parse_boj_index(payload: bytes) -> list[ParsedLink]:
    text = payload.decode("utf-8-sig")
    candidates: dict[date, list[ParsedLink]] = {}
    for match in _BOJ_ROW_PATTERN.finditer(text):
        day = _parse_boj_date(match.group("day"))
        if not START_DATE <= day <= END_DATE:
            continue
        candidates.setdefault(day, []).append(
            ParsedLink(
                day,
                urljoin("https://www.boj.or.jp", match.group("href")),
                _clean_html(match.group("title")),
            )
        )
    selected: list[ParsedLink] = []
    for _day, links in candidates.items():
        html_links = [link for link in links if link.url.endswith(".htm")]
        selected.append((html_links or links)[0])
    return sorted(selected, key=lambda link: link.event_date)


def _parse_boj_actual_time(payload: bytes) -> tuple[time, str]:
    text = _clean_html(payload.decode("utf-8-sig"))
    match = _BOJ_ACTUAL_TIME_PATTERN.search(text)
    if match is None:
        raise ValueError("BoJ decision page does not contain its official publication minute")
    raw = match.group(0)
    return time.fromisoformat(match.group("time").zfill(5)), raw


def _boj_events(store: SnapshotStore) -> list[dict[str, str]]:
    links: list[ParsedLink] = []
    index_by_year: dict[int, Snapshot] = {}
    for spec in BOJ_YEAR_SOURCES:
        snapshot = store.get(spec)
        year = int(spec.source_id.rsplit("_", 1)[1])
        index_by_year[year] = snapshot
        links.extend(_parse_boj_index(snapshot.payload))
    links = sorted(
        {link.event_date: link for link in links}.values(),
        key=lambda item: item.event_date,
    )
    _assert_year_counts("BOJ", links, BOJ_EXPECTED_BY_YEAR)
    rows: list[dict[str, str]] = []
    for link in links:
        day_token = link.event_date.strftime("%Y%m%d")
        event_type = BOJ_UNSCHEDULED.get(link.event_date, "rate_decision")
        if link.event_date.year >= 2018:
            if not link.url.endswith(".htm"):
                raise ValueError(f"BOJ {link.event_date}: actual-time HTML source is missing")
            spec = SourceSpec(
                f"boj_statement_{day_token}",
                "BOJ",
                link.url,
                f"boj/statements/{Path(link.url).name}",
                "official_statement_html",
                f"Bank of Japan policy decision {link.event_date.isoformat()}",
            )
            snapshot = store.get(spec)
            local_time, raw = _parse_boj_actual_time(snapshot.payload)
            quality = "verified_actual_publication"
        else:
            snapshot = index_by_year[link.event_date.year]
            local_time = None
            raw = "Official archive establishes the local date; no publication minute used."
            quality = "official_date_only"
        rows.append(
            _row(
                event_id=f"boj.{day_token}.{event_type}",
                currency="JPY",
                authority="BOJ",
                event_type=event_type,
                scheduled_status=(
                    "unscheduled" if link.event_date in BOJ_UNSCHEDULED else "scheduled"
                ),
                event_date=link.event_date,
                local_time=local_time,
                tzid="Asia/Tokyo",
                release_time_raw=raw,
                quality=quality,
                rule_id=None,
                rule_from=None,
                rule_to=None,
                snapshot=snapshot,
                notes=(
                    "BoJ has no fixed decision publication time. "
                    f"Official archive title: {link.title}"
                ),
            )
        )
    return rows


def _parse_rba_index(payload: bytes, year: int) -> list[ParsedLink]:
    text = payload.decode("utf-8-sig")
    pattern = re.compile(_RBA_LINK_PATTERN_TEMPLATE.format(year=year), re.IGNORECASE)
    links: dict[date, ParsedLink] = {}
    for match in pattern.finditer(text):
        cleaned = _clean_html(match.group("day"))
        try:
            day = datetime.strptime(cleaned, "%d %B %Y").date()
        except ValueError:
            continue
        links[day] = ParsedLink(
            day,
            urljoin("https://www.rba.gov.au", match.group("href")),
            "Monetary policy decision",
        )
    return sorted(links.values(), key=lambda link: link.event_date)


def _rba_events(store: SnapshotStore) -> list[dict[str, str]]:
    links: list[ParsedLink] = []
    source_by_year: dict[int, Snapshot] = {}
    for spec in RBA_YEAR_SOURCES:
        snapshot = store.get(spec)
        year = int(spec.source_id.rsplit("_", 1)[1])
        source_by_year[year] = snapshot
        text = _clean_html(snapshot.payload.decode("utf-8-sig"))
        if "2.30 pm" not in text and "2:30 pm" not in text:
            raise ValueError(f"RBA {year}: official 2.30 pm publication rule is missing")
        links.extend(_parse_rba_index(snapshot.payload, year))
    links = sorted(
        {link.event_date: link for link in links}.values(),
        key=lambda item: item.event_date,
    )
    _assert_year_counts("RBA", links, RBA_EXPECTED_BY_YEAR)
    rows: list[dict[str, str]] = []
    for link in links:
        day_token = link.event_date.strftime("%Y%m%d")
        rows.append(
            _row(
                event_id=f"rba.{day_token}.rate_decision",
                currency="AUD",
                authority="RBA",
                event_type="rate_decision",
                scheduled_status=(
                    "unscheduled" if link.event_date in RBA_UNSCHEDULED else "scheduled"
                ),
                event_date=link.event_date,
                local_time=time(14, 30),
                tzid="Australia/Sydney",
                release_time_raw="Official archive rule: decision announced at 2.30 pm",
                quality="official_rule_derived",
                rule_id="rba.decision_release.1430",
                rule_from=START_DATE,
                rule_to=END_DATE,
                snapshot=source_by_year[link.event_date.year],
                notes="Official event date and outcome-blind 14:30 Sydney publication rule.",
            )
        )
    return rows


def _calendar_csv(rows: list[dict[str, str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CALENDAR_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _prior_source_records(manifest_path: Path) -> dict[str, dict[str, Any]]:
    if not manifest_path.is_file():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("prior manifest is unreadable; use --refresh") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("sources"), list):
        raise ValueError("prior manifest sources are invalid; use --refresh")
    records: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(payload["sources"]):
        if not isinstance(record, dict) or not isinstance(record.get("source_id"), str):
            raise ValueError(f"prior manifest source {index} is invalid; use --refresh")
        source_id = record["source_id"]
        if source_id in records:
            raise ValueError(
                f"prior manifest has duplicate source_id {source_id!r}; use --refresh"
            )
        records[source_id] = record
    return records


def download_calendar(
    output_directory: str | Path,
    *,
    refresh: bool = False,
    transport: httpx.BaseTransport | None = None,
    now: datetime | None = None,
    retries: int = 2,
) -> tuple[Path, Path]:
    """Download official evidence and write a deterministic partial calendar."""

    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    calendar_path = output / "central_bank_policy_events_2016_2025.csv"
    manifest_path = output / "central_bank_policy_events_2016_2025.manifest.json"
    retrieved_at = (now or datetime.now(UTC)).astimezone(UTC)
    prior_sources = _prior_source_records(manifest_path) if not refresh else {}
    rows: list[dict[str, str]] = []
    adapter_records: list[dict[str, Any]] = []
    builders = {
        "FED": _fed_events,
        "ECB": _ecb_events,
        "BOJ": _boj_events,
        "RBA": _rba_events,
    }
    with httpx.Client(
        transport=transport,
        follow_redirects=True,
        timeout=60,
        headers={"User-Agent": "fx-factor-research-central-bank-calendar/1.0"},
    ) as client:
        store = SnapshotStore(
            output,
            client,
            refresh=refresh,
            retrieved_at=retrieved_at,
            prior_sources=prior_sources,
            retries=retries,
        )
        for authority in AUTHORITIES:
            builder = builders.get(authority)
            if builder is None:
                adapter_records.append(
                    {
                        "authority": authority,
                        "status": "fail_closed",
                        "row_count": 0,
                        "reason": "historical official-source adapter not yet implemented",
                    }
                )
                continue
            try:
                authority_rows = builder(store)
            except (OSError, UnicodeError, ValueError, httpx.HTTPError) as error:
                adapter_records.append(
                    {
                        "authority": authority,
                        "status": "fail_closed",
                        "row_count": 0,
                        "reason": f"{type(error).__name__}: {error}",
                    }
                )
            else:
                rows.extend(authority_rows)
                adapter_records.append(
                    {
                        "authority": authority,
                        "status": "complete",
                        "row_count": len(authority_rows),
                        "reason": "official archive coverage matched the frozen count contract",
                    }
                )
        source_records = store.manifest_records()

    rows.sort(
        key=lambda row: (
            row["decision_date_local"],
            row["release_at_utc"] or "9999-12-31T23:59:59Z",
            row["authority"],
            row["event_type"],
            row["event_id"],
        )
    )
    calendar_payload = _calendar_csv(rows)
    _atomic_write(calendar_path, calendar_payload)
    quality_counts: dict[str, int] = {}
    authority_counts = {authority: 0 for authority in AUTHORITIES}
    for row in rows:
        quality_counts[row["timestamp_quality"]] = (
            quality_counts.get(row["timestamp_quality"], 0) + 1
        )
        authority_counts[row["authority"]] += 1
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "dataset_kind": "central_bank_policy_event_calendar",
        "generation_version": GENERATION_VERSION,
        "created_at": _iso_utc(retrieved_at),
        "coverage_start": START_DATE.isoformat(),
        "coverage_end": END_DATE.isoformat(),
        "calendar_file": calendar_path.name,
        "calendar_sha256": _sha256_bytes(calendar_payload),
        "rows": len(rows),
        "authority_counts": authority_counts,
        "timestamp_quality_counts": quality_counts,
        "research_role": "announcement-risk blackout control; not directional alpha",
        "outcome_blind": True,
        "complete": all(record["status"] == "complete" for record in adapter_records),
        "adapters": adapter_records,
        "sources": source_records,
    }
    _atomic_write(
        manifest_path,
        json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8"),
    )
    return calendar_path, manifest_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the 2016-2025 official central-bank policy blackout calendar"
    )
    parser.add_argument("--output-dir", default="data/central_bank_calendars")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--retries", type=int, default=2)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.retries < 0:
        raise SystemExit("--retries cannot be negative")
    calendar_path, manifest_path = download_calendar(
        args.output_dir,
        refresh=args.refresh,
        retries=args.retries,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    print(f"Calendar: {calendar_path}")
    print(f"Manifest: {manifest_path}")
    if not manifest["complete"]:
        incomplete = [
            record["authority"]
            for record in manifest["adapters"]
            if record["status"] != "complete"
        ]
        print(f"Formal status: FAIL CLOSED; incomplete adapters={','.join(incomplete)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
