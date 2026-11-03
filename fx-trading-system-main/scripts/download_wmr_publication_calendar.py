#!/usr/bin/env python3
"""Build a hash-audited 2016-2025 Tokyo/ECB/WMR event calendar.

The WMR service exceptions are transcribed from public official WM/Reuters,
Refinitiv, and LSEG service-alteration PDFs preserved by the Internet Archive.
The ECB event dates come directly from the official daily 2:15 p.m. CET
reference-rate series.  Raw documents are retained locally but are not meant
for redistribution; consult each publisher's terms.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import httpx

START_DATE: Final = date(2016, 1, 1)
END_DATE: Final = date(2025, 12, 31)
GENERATION_VERSION: Final = "wmr-ecb-calendar-v1"


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    url: str
    filename: str
    media_type: str
    role: str
    publisher: str


SOURCES: Final[tuple[SourceSpec, ...]] = (
    SourceSpec(
        "wmr_schedule_2016_2021",
        "https://web.archive.org/web/20160614054105id_/http://wmcompany.com/"
        "pdfs/WMReutersServiceAlterationsfor2016-2021.pdf",
        "wmr_service_alterations_2016_2021.pdf",
        "application/pdf",
        "Official WMR spot-service exceptions for 2016-2021",
        "WM/Reuters, archived by Internet Archive",
    ),
    SourceSpec(
        "wmr_schedule_2022",
        "https://web.archive.org/web/20220119024936id_/https://www.refinitiv.com/"
        "content/dam/marketing/en_us/documents/methodology/"
        "wm-refinitiv-service-alterations.pdf",
        "wmr_service_alterations_2022.pdf",
        "application/pdf",
        "Official WMR spot-service exceptions for 2022",
        "Refinitiv, archived by Internet Archive",
    ),
    SourceSpec(
        "wmr_schedule_2023_2024",
        "https://web.archive.org/web/20231203074040id_/https://www.lseg.com/"
        "content/dam/ftse-russell/en_us/documents/methodology/"
        "wmr-service-alterations.pdf",
        "wmr_service_alterations_2023_2024.pdf",
        "application/pdf",
        "Official WMR spot-service exceptions for 2023-2024",
        "LSEG, archived by Internet Archive",
    ),
    SourceSpec(
        "wmr_schedule_2025",
        "https://web.archive.org/web/20250828215810id_/https://www.lseg.com/"
        "content/dam/ftse-russell/en_us/documents/methodology/"
        "wmr-service-alterations.pdf",
        "wmr_service_alterations_2025.pdf",
        "application/pdf",
        "Official WMR spot-service exceptions for 2025",
        "LSEG, archived by Internet Archive",
    ),
    SourceSpec(
        "wmr_methodology",
        "https://www.lseg.com/content/dam/ftse-russell/en_us/documents/"
        "ground-rules/wmr-fx-methodology.pdf",
        "wmr_fx_methodology.pdf",
        "application/pdf",
        "Official normal timing, Tokyo 09:55, and London 16:00 methodology",
        "LSEG",
    ),
    SourceSpec(
        "ecb_reference_dates",
        "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?"
        "startPeriod=2016-01-01&endPeriod=2025-12-31&format=csvdata",
        "ecb_usd_eur_reference_2016_2025.csv",
        "text/csv",
        "Official dates of the ECB 2:15 p.m. CET reference rate",
        "European Central Bank",
    ),
)

SCHEDULE_SOURCE_BY_YEAR: Final[dict[int, str]] = {
    **{year: "wmr_schedule_2016_2021" for year in range(2016, 2022)},
    2022: "wmr_schedule_2022",
    2023: "wmr_schedule_2023_2024",
    2024: "wmr_schedule_2023_2024",
    2025: "wmr_schedule_2025",
}

# Every listed date appears in the corresponding official service-alteration
# schedule.  The tuple contains the event fixes still published on that date.
# A normal weekday not listed here publishes both; weekends publish neither.
WMR_SERVICE_EXCEPTIONS: Final[dict[date, tuple[str, ...]]] = {
    date(2016, 1, 1): (),
    date(2016, 3, 25): (),
    date(2016, 5, 30): ("tokyo_fix", "wmr_fix"),
    date(2016, 12, 26): (),
    date(2017, 1, 2): (),
    date(2017, 4, 14): (),
    date(2017, 5, 29): ("tokyo_fix", "wmr_fix"),
    date(2017, 12, 25): (),
    date(2017, 12, 26): ("wmr_fix",),
    date(2018, 1, 1): (),
    date(2018, 3, 30): (),
    date(2018, 5, 28): ("tokyo_fix", "wmr_fix"),
    date(2018, 12, 24): ("tokyo_fix", "wmr_fix"),
    date(2018, 12, 25): (),
    date(2018, 12, 26): ("wmr_fix",),
    date(2018, 12, 31): ("tokyo_fix", "wmr_fix"),
    date(2019, 1, 1): (),
    date(2019, 4, 19): (),
    date(2019, 5, 27): ("tokyo_fix", "wmr_fix"),
    date(2019, 12, 24): ("tokyo_fix", "wmr_fix"),
    date(2019, 12, 25): (),
    date(2019, 12, 26): ("wmr_fix",),
    date(2019, 12, 31): ("tokyo_fix", "wmr_fix"),
    date(2020, 1, 1): (),
    date(2020, 4, 10): (),
    date(2020, 5, 25): ("tokyo_fix", "wmr_fix"),
    date(2020, 12, 24): ("tokyo_fix", "wmr_fix"),
    date(2020, 12, 25): (),
    date(2020, 12, 31): ("tokyo_fix", "wmr_fix"),
    date(2021, 1, 1): (),
    date(2021, 4, 2): (),
    date(2021, 5, 31): ("tokyo_fix", "wmr_fix"),
    date(2021, 12, 24): ("tokyo_fix",),
    date(2021, 12, 31): ("tokyo_fix", "wmr_fix"),
    date(2022, 4, 15): (),
    date(2022, 5, 30): ("tokyo_fix", "wmr_fix"),
    date(2022, 12, 26): (),
    date(2023, 1, 2): (),
    date(2023, 4, 7): (),
    date(2023, 5, 29): ("tokyo_fix", "wmr_fix"),
    date(2023, 12, 25): (),
    date(2023, 12, 26): ("wmr_fix",),
    date(2024, 1, 1): (),
    date(2024, 3, 29): (),
    date(2024, 5, 27): ("tokyo_fix", "wmr_fix"),
    date(2024, 12, 25): (),
    date(2024, 12, 26): ("wmr_fix",),
    date(2024, 12, 31): ("tokyo_fix", "wmr_fix"),
    date(2025, 1, 1): (),
    date(2025, 4, 18): (),
    date(2025, 5, 26): ("tokyo_fix", "wmr_fix"),
    date(2025, 12, 24): ("tokyo_fix", "wmr_fix"),
    date(2025, 12, 25): (),
    date(2025, 12, 26): ("wmr_fix",),
    date(2025, 12, 31): ("tokyo_fix", "wmr_fix"),
}

EVENT_FIELDS: Final[dict[str, tuple[str, str]]] = {
    "tokyo_fix": ("09:55", "Asia/Tokyo"),
    "ecb_fix": ("14:15", "Europe/Berlin"),
    "wmr_fix": ("16:00", "Europe/London"),
}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _source_map() -> dict[str, SourceSpec]:
    return {source.source_id: source for source in SOURCES}


def _validate_raw(source: SourceSpec, payload: bytes) -> None:
    if source.media_type == "application/pdf":
        if not payload.startswith(b"%PDF") or len(payload) < 1_000:
            raise ValueError(f"{source.source_id}: response is not a plausible PDF")
        return
    text = payload.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    required = {"TIME_PERIOD", "TITLE_COMPL"}
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise ValueError(f"{source.source_id}: ECB CSV columns are incomplete")
    rows = list(reader)
    if not rows or not all("2.15 pm (C.E.T.)" in str(row["TITLE_COMPL"]) for row in rows):
        raise ValueError(f"{source.source_id}: ECB series is not the 2:15 p.m. CET fix")


def _ecb_dates(payload: bytes) -> set[date]:
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    dates = {date.fromisoformat(str(row["TIME_PERIOD"])) for row in reader}
    if not dates or min(dates) < START_DATE or max(dates) > END_DATE:
        raise ValueError("ECB observation dates fall outside the frozen range")
    return dates


def _calendar_rows(
    ecb_dates: set[date],
    *,
    retrieved_at: datetime,
) -> list[dict[str, str]]:
    sources = _source_map()
    rows: list[dict[str, str]] = []
    current = START_DATE
    while current <= END_DATE:
        normal_wmr_events: tuple[str, ...] = (
            ("tokyo_fix", "wmr_fix") if current.weekday() < 5 else ()
        )
        published_wmr_events = WMR_SERVICE_EXCEPTIONS.get(
            current, normal_wmr_events
        )
        for event_name in ("tokyo_fix", "ecb_fix", "wmr_fix"):
            local_time, timezone = EVENT_FIELDS[event_name]
            if event_name == "ecb_fix":
                published = current in ecb_dates
                source_id = "ecb_reference_dates"
            else:
                published = event_name in published_wmr_events
                source_id = SCHEDULE_SOURCE_BY_YEAR[current.year]
            rows.append(
                {
                    "event_name": event_name,
                    "local_date": current.isoformat(),
                    "status": "published" if published else "not_published",
                    "local_time": local_time,
                    "timezone": timezone,
                    "source_url": sources[source_id].url,
                    "quality": "verified",
                    "retrieved_at": _iso_utc(retrieved_at),
                }
            )
        current += timedelta(days=1)
    return rows


def _calendar_csv(rows: list[dict[str, str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=(
            "event_name",
            "local_date",
            "status",
            "local_time",
            "timezone",
            "source_url",
            "quality",
            "retrieved_at",
        ),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def download_calendar(
    output_directory: str | Path,
    *,
    refresh: bool = False,
    transport: httpx.BaseTransport | None = None,
    now: datetime | None = None,
) -> tuple[Path, Path]:
    output = Path(output_directory)
    raw_directory = output / "raw"
    raw_directory.mkdir(parents=True, exist_ok=True)
    calendar_path = output / "benchmark_publication_calendar_2016_2025.csv"
    manifest_path = output / "benchmark_publication_calendar_2016_2025.manifest.json"
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
    with httpx.Client(
        transport=transport,
        follow_redirects=True,
        timeout=60,
        headers={"User-Agent": "fx-factor-research-calendar/1.0"},
    ) as client:
        for source in SOURCES:
            path = raw_directory / source.filename
            if path.is_file() and not refresh:
                payload = path.read_bytes()
                retrieval = prior_retrievals.get(source.source_id, _iso_utc(retrieved_at))
            else:
                response = client.get(source.url)
                response.raise_for_status()
                payload = bytes(response.content)
                _atomic_write(path, payload)
                retrieval = _iso_utc(retrieved_at)
            _validate_raw(source, payload)
            raw_payloads[source.source_id] = payload
            source_records.append(
                {
                    "source_id": source.source_id,
                    "url": source.url,
                    "publisher": source.publisher,
                    "role": source.role,
                    "media_type": source.media_type,
                    "retrieved_at": retrieval,
                    "raw_path": str(path.relative_to(output)),
                    "raw_bytes": len(payload),
                    "raw_sha256": _sha256_bytes(payload),
                }
            )

    ecb_dates = _ecb_dates(raw_payloads["ecb_reference_dates"])
    rows = _calendar_rows(ecb_dates, retrieved_at=retrieved_at)
    calendar_payload = _calendar_csv(rows)
    _atomic_write(calendar_path, calendar_payload)
    exception_contract = json.dumps(
        {
            value.isoformat(): list(events)
            for value, events in sorted(WMR_SERVICE_EXCEPTIONS.items())
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    counts: dict[str, dict[str, int]] = {}
    for row in rows:
        event_counts = counts.setdefault(row["event_name"], {})
        event_counts[row["status"]] = event_counts.get(row["status"], 0) + 1
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "dataset_kind": "benchmark_publication_calendar",
        "generation_version": GENERATION_VERSION,
        "created_at": _iso_utc(retrieved_at),
        "calendar_file": calendar_path.name,
        "calendar_sha256": _sha256_bytes(calendar_payload),
        "coverage_start": START_DATE.isoformat(),
        "coverage_end": END_DATE.isoformat(),
        "rows": len(rows),
        "counts": counts,
        "wmr_exception_contract_sha256": _sha256_bytes(exception_contract),
        "weekend_rule": "not_published; WMR methodology limits normal service to Monday-Friday",
        "ecb_rule": "published iff official ECB 2:15 p.m. CET series has TIME_PERIOD",
        "research_role": "event occurrence calendar; not an alpha signal",
        "redistribution_note": (
            "Raw publisher documents are retained for private audit; review publisher terms "
            "before redistribution."
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
        description="Download official evidence and build the 2016-2025 FX event calendar"
    )
    parser.add_argument("--output-dir", default="data/benchmark_calendars")
    parser.add_argument("--refresh", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    calendar_path, manifest_path = download_calendar(
        args.output_dir, refresh=args.refresh
    )
    print(f"Calendar: {calendar_path}")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
