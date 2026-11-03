from __future__ import annotations

import csv
import importlib.util
import io
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from fx_system.publication_calendar import load_publication_calendar

SCRIPT_PATH = (
    Path(__file__).parents[1] / "scripts" / "download_wmr_publication_calendar.py"
)
SPEC = importlib.util.spec_from_file_location("wmr_publication_downloader", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
downloader = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = downloader
SPEC.loader.exec_module(downloader)


def _ecb_payload() -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=["TIME_PERIOD", "TITLE_COMPL"])
    writer.writeheader()
    for value in ("2016-01-04", "2025-12-31"):
        writer.writerow(
            {
                "TIME_PERIOD": value,
                "TITLE_COMPL": "ECB reference exchange rate, 2.15 pm (C.E.T.)",
            }
        )
    return output.getvalue().encode()


def _transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if "data-api.ecb.europa.eu" in request.url.host:
            return httpx.Response(200, content=_ecb_payload())
        return httpx.Response(200, content=b"%PDF-1.7\n" + b"official schedule" * 100)

    return httpx.MockTransport(handler)


def test_calendar_contract_distinguishes_partial_service_and_official_ecb_dates() -> None:
    rows = downloader._calendar_rows(
        {date(2016, 1, 4)},
        retrieved_at=datetime(2026, 7, 16, tzinfo=UTC),
    )
    keyed = {(row["event_name"], row["local_date"]): row for row in rows}

    assert len(rows) == 10_959
    assert keyed[("tokyo_fix", "2016-01-01")]["status"] == "not_published"
    assert keyed[("wmr_fix", "2016-01-04")]["status"] == "published"
    assert keyed[("ecb_fix", "2016-01-04")]["status"] == "published"
    assert keyed[("ecb_fix", "2016-01-05")]["status"] == "not_published"
    # 4pm-only Boxing Day: Tokyo is absent, London close exists.
    assert keyed[("tokyo_fix", "2017-12-26")]["status"] == "not_published"
    assert keyed[("wmr_fix", "2017-12-26")]["status"] == "published"
    # 2021 Christmas Eve half-day ends at noon: Tokyo exists, London 4pm does not.
    assert keyed[("tokyo_fix", "2021-12-24")]["status"] == "published"
    assert keyed[("wmr_fix", "2021-12-24")]["status"] == "not_published"
    assert keyed[("wmr_fix", "2025-12-27")]["status"] == "not_published"


def test_downloader_preserves_raw_evidence_and_builds_loadable_verified_manifest(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 16, 3, 45, tzinfo=UTC)
    calendar_path, manifest_path = downloader.download_calendar(
        tmp_path,
        refresh=True,
        transport=_transport(),
        now=now,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["rows"] == 10_959
    assert len(manifest["sources"]) == 6
    assert manifest["counts"]["ecb_fix"]["published"] == 2
    assert manifest["wmr_exception_contract_sha256"]
    assert all((tmp_path / item["raw_path"]).is_file() for item in manifest["sources"])

    calendar = load_publication_calendar(
        calendar_path,
        knowledge_cutoff=now,
        formal_experiment=True,
        manifest_path=manifest_path,
        require_manifest=True,
    )
    assert calendar.manifest_verified
    assert len(calendar.events) == 10_959
    assert calendar.event_on("wmr_fix", "2025-12-25").was_published is False
    assert calendar.actual_wmr_month_end(2025, 12).local_date == date(2025, 12, 31)
