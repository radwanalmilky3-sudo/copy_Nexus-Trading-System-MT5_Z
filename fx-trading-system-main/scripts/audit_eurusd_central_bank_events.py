#!/usr/bin/env python3
"""Extract the strict FED/ECB event-control candidate without using outcomes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from fx_system.central_bank_calendar import load_central_bank_calendar

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARENT_SOURCE_ID = "central_bank_policy_calendar_partial"
SOURCE_VIEW_ID = "central_bank_policy_calendar_eurusd_strict_rows"
TARGET_AUTHORITIES = frozenset({"FED", "ECB"})
TARGET_QUALITIES = frozenset({"verified_actual_publication", "official_rule_derived"})
OUTPUT_COLUMNS = (
    "event_id",
    "currency",
    "authority",
    "event_type",
    "decision_date_local",
    "release_at_utc",
    "available_time",
    "timestamp_quality",
    "source_url",
    "source_document_type",
    "source_sha256",
    "retrieved_at_utc",
    "event_control_role",
)


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--calendar",
        type=Path,
        default=Path("data/central_bank_calendars/central_bank_policy_events_2016_2025.csv"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(
            "data/central_bank_calendars/central_bank_policy_events_2016_2025.manifest.json"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/eurusd_central_bank_event_candidate_20260719"),
    )
    args = parser.parse_args()
    calendar_path = (PROJECT_ROOT / args.calendar).resolve()
    manifest_path = (PROJECT_ROOT / args.manifest).resolve()
    calendar = load_central_bank_calendar(
        calendar_path,
        manifest_path=manifest_path,
        knowledge_cutoff=datetime(2026, 7, 19, 23, 59, 59, tzinfo=UTC),
        require_complete=False,
        formal_experiment=True,
    )
    selected = [
        event
        for event in calendar.events
        if event.authority in TARGET_AUTHORITIES
        and event.timestamp_quality in TARGET_QUALITIES
        and not event.cancelled
        and event.release_at_utc is not None
    ]
    if not selected:
        raise ValueError("strict EURUSD central-bank event candidate is empty")
    rows = [
        {
            "event_id": event.event_id,
            "currency": event.currency,
            "authority": event.authority,
            "event_type": event.event_type,
            "decision_date_local": event.decision_date_local.isoformat(),
            "release_at_utc": event.release_at_utc.isoformat(),
            "available_time": event.release_at_utc.isoformat(),
            "timestamp_quality": event.timestamp_quality,
            "source_url": event.source_url,
            "source_document_type": event.source_document_type,
            "source_sha256": event.source_sha256,
            "retrieved_at_utc": event.retrieved_at_utc.isoformat(),
            "event_control_role": "announcement_risk_blackout_not_directional_alpha",
        }
        for event in selected
    ]
    rows.sort(key=lambda row: (row["available_time"], row["authority"], row["event_id"]))
    output_dir = (PROJECT_ROOT / args.output_dir).resolve()
    data_path = output_dir / "eurusd_central_bank_strict_events.csv"
    _write_csv(data_path, rows)
    counts = {}
    for row in rows:
        counts[row["authority"]] = counts.get(row["authority"], 0) + 1
    manifest = {
        "schema_version": 1,
        "stage_date": "2026-07-19",
        "stage": "eurusd_central_bank_strict_event_candidate_outcome_blind",
        "parent_source_id": PARENT_SOURCE_ID,
        "registered_source_view_id": SOURCE_VIEW_ID,
        "parent_calendar_path": args.calendar.as_posix(),
        "parent_calendar_sha256": _sha256(calendar_path),
        "parent_manifest_path": args.manifest.as_posix(),
        "parent_manifest_sha256": _sha256(manifest_path),
        "parent_complete": False,
        "filter": {
            "authorities": sorted(TARGET_AUTHORITIES),
            "timestamp_qualities": sorted(TARGET_QUALITIES),
            "cancelled": False,
            "release_at_utc_required": True,
        },
        "coverage_start": min(row["decision_date_local"] for row in rows),
        "coverage_end": max(row["decision_date_local"] for row in rows),
        "rows": len(rows),
        "authority_counts": counts,
        "timestamp_quality_counts": {
            quality: sum(row["timestamp_quality"] == quality for row in rows)
            for quality in sorted(TARGET_QUALITIES)
        },
        "data_path": data_path.relative_to(PROJECT_ROOT).as_posix(),
        "data_sha256": _sha256(data_path),
        "registry_path": "configs/external_factor_source_registry.yaml",
        "registry_sha256": _sha256(
            PROJECT_ROOT / "configs/external_factor_source_registry.yaml"
        ),
        "runner_path": "scripts/audit_eurusd_central_bank_events.py",
        "runner_sha256": _sha256(Path(__file__).resolve()),
        "available_time_policy": "official release_at_utc; no date-only ECB rows",
        "research_role": "EURUSD announcement-risk blackout control; not directional alpha",
        "boe_status": "missing_for_gbpusd",
        "price_inputs_read": [],
        "return_labels_opened": False,
        "factor_outcome_evaluations_added": 0,
        "trading_approval": False,
        "verdict": "eurusd_event_control_candidate_not_in_current_five_feature_package",
    }
    manifest_output = output_dir / "manifest.json"
    _write_text(
        manifest_output,
        json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
    )
    _write_text(
        output_dir / "REPORT_ZH.md",
        "\n".join(
            [
                "# EURUSD 央行事件控制候选审计",
                "",
                "该候选只保留 FED/ECB 中有正式 UTC 发布时间的行，用于公告风险 blackout；"
                "不读取利率决定内容，也不是方向 alpha。",
                "",
                f"- 严格事件：{len(rows)}；FED {counts.get('FED', 0)}；"
                f"ECB {counts.get('ECB', 0)}；",
                "- 排除 ECB date-only 非例行事件 2 行；",
                "- 父八央行日历仍 `complete=false`；BOE 缺失，因此 GBPUSD 不能使用对称"
                " FED/BOE 控制；",
                "- 本候选未加入现有五因子包或任何 FDR 家族。",
                "",
                "```text",
                "return_labels_opened=false",
                "factor_outcome_evaluations_added=0",
                "trading_approval=false",
                "```",
                "",
            ]
        ),
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
