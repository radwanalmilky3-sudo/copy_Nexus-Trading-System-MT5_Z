"""Financial-center holiday contract tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from fx_system.financial_center_calendar import (
    FinancialCenterCalendarError,
    asia_ldn_holiday_filter_status,
    deferred_central_bank_adapters,
    load_financial_center_calendar,
)


def _write_calendar(tmp_path: Path, *, with_manifest: bool) -> Path:
    csv_path = tmp_path / "tokyo_london_holidays.csv"
    body = "\n".join(
        [
            "center,session_date,session_type,source,source_url,"
            "retrieved_at_utc,notes",
            "Tokyo,2025-01-01T00:00:00Z,closed,example,"
            "https://example.invalid,2026-07-16T00:00:00Z,new year",
            "London,2025-01-01T00:00:00Z,closed,example,"
            "https://example.invalid,2026-07-16T00:00:00Z,new year",
            "London,2025-12-24T00:00:00Z,half_day,example,"
            "https://example.invalid,2026-07-16T00:00:00Z,xmas eve",
            "",
        ]
    )
    csv_path.write_text(body, encoding="utf-8")
    if with_manifest:
        digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
        manifest = {
            "schema_version": 1,
            "dataset_kind": "financial_center_calendar",
            "csv_sha256": digest,
            "centers": ["Tokyo", "London"],
        }
        csv_path.with_suffix(".manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
    return csv_path


def test_verified_calendar_enables_asia_ldn_filter(tmp_path: Path) -> None:
    calendar = load_financial_center_calendar(_write_calendar(tmp_path, with_manifest=True))
    status = asia_ldn_holiday_filter_status(calendar)
    assert status["holiday_filter_applied"] is True
    assert calendar.manifest_verified is True
    tokyo_days = calendar.closed_or_half_days("Tokyo")
    assert any(day.strftime("%Y-%m-%d") == "2025-01-01" for day in tokyo_days)


def test_missing_manifest_keeps_filter_unapplied(tmp_path: Path) -> None:
    calendar = load_financial_center_calendar(_write_calendar(tmp_path, with_manifest=False))
    status = asia_ldn_holiday_filter_status(calendar)
    assert status["holiday_filter_applied"] is False
    assert status["status"] == "unapplied_unverified_manifest"


def test_formal_mode_rejects_missing_calendar() -> None:
    with pytest.raises(FinancialCenterCalendarError, match="formal ASIA-LDN"):
        asia_ldn_holiday_filter_status(None, require_formal=True)


def test_deferred_cb_adapters_are_explicit() -> None:
    deferred = deferred_central_bank_adapters()
    assert deferred["BOE"].startswith("deferred")
    assert deferred["macro_blackout_formal_status"] == "deferred_missing_data"
