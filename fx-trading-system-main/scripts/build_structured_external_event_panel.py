#!/usr/bin/env python3
"""Build and audit the two formal strict-PIT structured event controls."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from fx_system.external_factor_eligibility import (
    ExternalFactorDefinitionCatalog,
    ExternalFactorSourceRegistry,
    audit_external_factor_definitions,
    audit_external_factor_sources,
)
from fx_system.publication_calendar import PublicationCalendar, load_publication_calendar
from fx_system.structured_event_controls import (
    EVENT_CONTROL_FEATURES,
    EVENT_CONTROL_SOURCE_IDS,
    build_structured_external_event_panel,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_SOURCE_ID = "benchmark_publication_calendar"
SPF_SOURCE_ID = "phillyfed_spf_release_calendar"


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _write_csv_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(
        temporary,
        index=False,
        lineterminator="\n",
        date_format="%Y-%m-%dT%H:%M:%S.%f%z",
        float_format="%.17g",
    )
    temporary.replace(path)


def _source_by_id(registry: ExternalFactorSourceRegistry, source_id: str):
    matches = [source for source in registry.sources if source.source_id == source_id]
    if len(matches) != 1:
        raise ValueError(f"registry must contain exactly one {source_id!r} source")
    return matches[0]


def _changed_future_calendar(
    calendar: PublicationCalendar,
    decision: pd.Timestamp,
) -> PublicationCalendar:
    events = []
    for event in calendar.events:
        if pd.Timestamp(event.scheduled_time_utc) > decision:
            status = "not_published" if event.was_published else "published"
            events.append(replace(event, status=status))
        else:
            events.append(event)
    return replace(calendar, events=tuple(events))


def _changed_future_spf(spf: pd.DataFrame, decision: pd.Timestamp) -> pd.DataFrame:
    changed = spf.copy()
    available = pd.to_datetime(changed["available_time"], utc=True)
    future = available > decision
    one_day = pd.Timedelta(24, unit="h")
    changed.loc[future, "news_release_date"] = (
        pd.to_datetime(changed.loc[future, "news_release_date"]) + one_day
    ).dt.strftime("%Y-%m-%d")
    changed.loc[future, "available_time"] = (
        available.loc[future] + one_day
    ).map(lambda value: value.isoformat())
    return changed


def _future_prefix_checks(
    benchmark: PublicationCalendar,
    spf: pd.DataFrame,
    values: pd.DataFrame,
    lineage: pd.DataFrame,
    components: pd.DataFrame,
) -> list[dict[str, object]]:
    activation = values.loc[values["phillyfed_spf_release_state"].eq(1)].reset_index(
        drop=True
    )
    if activation.empty:
        raise ValueError("event interval contains no SPF activation for prefix audit")
    positions = sorted({0, len(activation) // 2, max(0, len(activation) - 2)})
    checks: list[dict[str, object]] = []
    for position in positions:
        decision = pd.Timestamp(activation.iloc[position]["decision_time"])
        changed = build_structured_external_event_panel(
            _changed_future_calendar(benchmark, decision),
            _changed_future_spf(spf, decision),
            [decision],
        )
        expected_values = values.loc[values["decision_time"].eq(decision)].reset_index(
            drop=True
        )
        expected_lineage = lineage.loc[
            lineage["decision_time"].eq(decision)
        ].reset_index(drop=True)
        expected_components = components.loc[
            components["decision_time"].eq(decision)
        ].reset_index(drop=True)
        pd.testing.assert_frame_equal(expected_values, changed.values)
        pd.testing.assert_frame_equal(expected_lineage, changed.lineage)
        pd.testing.assert_frame_equal(expected_components, changed.components)
        future_benchmark = sum(
            pd.Timestamp(event.scheduled_time_utc) > decision
            for event in benchmark.events
        )
        future_spf = int((pd.to_datetime(spf["available_time"], utc=True) > decision).sum())
        checks.append(
            {
                "decision_time": decision.isoformat(),
                "future_benchmark_rows_mutated": future_benchmark,
                "future_spf_rows_shifted": future_spf,
                "historical_prefix_invariant": True,
                "future_information_canary_passed": True,
            }
        )
    return checks


def _report(manifest: dict[str, object]) -> str:
    coverage = manifest["coverage"]
    return "\n".join(
        [
            "# 严格 PIT 结构化事件控制面板",
            "",
            f"生成日期：{manifest['stage_date']}。本产物不读取价格或收益标签。",
            "",
            "## 结果",
            "",
            f"- 覆盖 `{manifest['decision_start']}` 至排他边界 "
            f"`{manifest['decision_end_exclusive']}`，共 {manifest['decision_rows']} 个日度 UTC "
            "决策边界。",
            "- `benchmark_publication_state` 是过去 24 小时内已完成 benchmark 事件的三位"
            " bitmask：Tokyo=1、ECB=2、WMR=4；不是方向信号。",
            "- `phillyfed_spf_release_state` 只在官方 date-only 发布经过保守 next-New-York-day "
            "available_time 后产生一次脉冲；不加载 forecast values。",
            f"- Benchmark ready {coverage['benchmark_publication_state']['ready']}/"
            f"{manifest['decision_rows']}；SPF ready "
            f"{coverage['phillyfed_spf_release_state']['ready']}/"
            f"{manifest['decision_rows']}，release impulses="
            f"{coverage['phillyfed_spf_release_state']['ones']}。",
            "- 40 个 SPF 脉冲中 32 个落在周日 00:00 UTC。当前面板不会把它们擅自移动到"
            "周一；若下游只保留工作日，必须在预注册中选择保留周日决策或明确滚到下一可用"
            "决策边界。",
            f"- 三个真实历史检查点 future-row/prefix canary "
            f"{len(manifest['prefix_invariance_checks'])}/"
            f"{len(manifest['prefix_invariance_checks'])} 通过；未来时间违规 0。",
            "",
            "## 研究边界",
            "",
            "两个事件变量只能作为 nuisance/blackout control。若未来要解释它们的收益系数或"
            "与价格因子交互，必须另行预注册并计入新的多重检验家族。",
            "",
            "```text",
            "return_labels_opened=false",
            "factor_outcome_evaluations_added=0",
            "trading_approval=false",
            "```",
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("configs/external_factor_source_registry.yaml"),
    )
    parser.add_argument(
        "--factor-catalog",
        type=Path,
        default=Path("configs/external_factor_definitions.yaml"),
    )
    parser.add_argument("--start", default="2016-01-01T00:00:00Z")
    parser.add_argument("--end", default="2026-01-01T00:00:00Z")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/structured_external_event_panel_20260717"),
    )
    args = parser.parse_args()

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware")
    start = start.tz_convert("UTC")
    end = end.tz_convert("UTC")
    if start >= end:
        raise ValueError("start must precede exclusive end")
    if start != pd.Timestamp("2016-01-01T00:00:00Z") or end != pd.Timestamp(
        "2026-01-01T00:00:00Z"
    ):
        raise ValueError(
            "the frozen event-control runner range is [2016-01-01, 2026-01-01)"
        )
    decisions = pd.date_range(start, end, freq="D", inclusive="left", tz="UTC")

    registry_path = (PROJECT_ROOT / args.registry).resolve()
    catalog_path = (PROJECT_ROOT / args.factor_catalog).resolve()
    registry = ExternalFactorSourceRegistry.from_yaml(registry_path)
    source_audit = audit_external_factor_sources(registry, project_root=PROJECT_ROOT)
    if source_audit["integrity_verified_count"] != source_audit["source_count"]:
        raise ValueError("external source registry integrity audit failed")
    catalog = ExternalFactorDefinitionCatalog.from_yaml(catalog_path)
    factor_audit = audit_external_factor_definitions(catalog, source_audit)
    if not set(EVENT_CONTROL_FEATURES).issubset(factor_audit["formal_factor_ids"]):
        raise ValueError("one or more event controls are not formal eligible")

    benchmark_source = _source_by_id(registry, BENCHMARK_SOURCE_ID)
    spf_source = _source_by_id(registry, SPF_SOURCE_ID)
    if not (
        benchmark_source.formal_event_control_eligible
        and spf_source.formal_event_control_eligible
    ):
        raise ValueError("event-control source is not formally eligible")
    benchmark_path = (PROJECT_ROOT / benchmark_source.data_path).resolve()
    benchmark_manifest_path = (PROJECT_ROOT / benchmark_source.manifest_path).resolve()
    spf_path = (PROJECT_ROOT / spf_source.data_path).resolve()
    benchmark = load_publication_calendar(
        benchmark_path,
        knowledge_cutoff=datetime(2026, 7, 17, 23, 59, 59, tzinfo=UTC),
        manifest_path=benchmark_manifest_path,
        require_manifest=True,
    )
    spf = pd.read_csv(spf_path)
    panel = build_structured_external_event_panel(benchmark, spf, decisions)
    prefix_checks = _future_prefix_checks(
        benchmark, spf, panel.values, panel.lineage, panel.components
    )

    source_hashes = {
        BENCHMARK_SOURCE_ID: benchmark_source.data_sha256,
        SPF_SOURCE_ID: spf_source.data_sha256,
    }
    manifest_hashes = {
        BENCHMARK_SOURCE_ID: benchmark_source.manifest_sha256,
        SPF_SOURCE_ID: spf_source.manifest_sha256,
    }
    lineage = panel.lineage.copy()
    lineage["source_data_sha256"] = lineage["source_id"].map(source_hashes)
    lineage["source_manifest_sha256"] = lineage["source_id"].map(manifest_hashes)
    components = panel.components.copy()
    component_source = components["feature_name"].map(EVENT_CONTROL_SOURCE_IDS)
    components["source_id"] = component_source
    components["source_data_sha256"] = component_source.map(source_hashes)
    components["source_manifest_sha256"] = component_source.map(manifest_hashes)

    available = lineage["source_available_time"].notna()
    future_violations = int(
        (
            lineage.loc[available, "source_available_time"]
            > lineage.loc[available, "decision_time"]
        ).sum()
    )
    non_strict_ready = int(
        (~lineage.loc[lineage["feature_status"].eq("ready"), "source_eligibility"].eq(
            "verified_strict_pit"
        )).sum()
    )
    if future_violations or non_strict_ready:
        raise RuntimeError("event-control panel violated strict-PIT contract")

    output_dir = (PROJECT_ROOT / args.output_dir).resolve()
    values_path = output_dir / "feature_values.csv"
    lineage_path = output_dir / "feature_lineage.csv"
    components_path = output_dir / "event_component_lineage.csv"
    _write_csv_atomic(panel.values, values_path)
    _write_csv_atomic(lineage, lineage_path)
    _write_csv_atomic(components, components_path)
    coverage = {
        feature: {
            "ready": int(
                lineage.loc[lineage["feature_name"].eq(feature), "feature_status"]
                .eq("ready")
                .sum()
            ),
            "ones": int(panel.values[feature].eq(1).sum()),
            "missing": int(panel.values[feature].isna().sum()),
            "maximum_source_age_days": float(
                lineage.loc[
                    lineage["feature_name"].eq(feature), "source_staleness_days"
                ].max()
            ),
        }
        for feature in EVENT_CONTROL_FEATURES
    }
    spf_impulses = panel.values.loc[
        panel.values["phillyfed_spf_release_state"].eq(1), "decision_time"
    ]
    coverage["phillyfed_spf_release_state"]["impulse_decision_weekday_counts"] = {
        str(key): int(value)
        for key, value in spf_impulses.dt.day_name().value_counts().sort_index().items()
    }
    manifest = {
        "schema_version": 1,
        "stage_date": "2026-07-17",
        "stage": "structured_external_event_panel_outcome_blind",
        "decision_start": start.isoformat(),
        "decision_end_exclusive": end.isoformat(),
        "decision_frequency": "1D_UTC_trailing_24h_event_window",
        "decision_rows": len(panel.values),
        "feature_ids": list(EVENT_CONTROL_FEATURES),
        "feature_count": len(EVENT_CONTROL_FEATURES),
        "lineage_rows": len(lineage),
        "component_lineage_rows": len(components),
        "coverage": coverage,
        "prefix_invariance_checks": prefix_checks,
        "future_information_violations": future_violations,
        "non_strict_ready_rows": non_strict_ready,
        "source_data_sha256": source_hashes,
        "source_manifest_sha256": manifest_hashes,
        "registry_path": args.registry.as_posix(),
        "registry_sha256": _sha256(registry_path),
        "factor_catalog_path": args.factor_catalog.as_posix(),
        "factor_catalog_sha256": _sha256(catalog_path),
        "builder_path": "src/fx_system/structured_event_controls.py",
        "builder_sha256": _sha256(
            PROJECT_ROOT / "src/fx_system/structured_event_controls.py"
        ),
        "runner_path": "scripts/build_structured_external_event_panel.py",
        "runner_sha256": _sha256(Path(__file__).resolve()),
        "outputs": {},
        "price_inputs_read": [],
        "return_labels_opened": False,
        "factor_outcome_evaluations_added": 0,
        "formal_net_returns_ready": False,
        "trading_approval": False,
        "verdict": "outcome_blind_event_controls_ready_not_alpha",
    }
    for name, path, rows in (
        ("feature_values", values_path, len(panel.values)),
        ("feature_lineage", lineage_path, len(lineage)),
        ("event_component_lineage", components_path, len(components)),
    ):
        manifest["outputs"][name] = {
            "path": path.relative_to(PROJECT_ROOT).as_posix(),
            "sha256": _sha256(path),
            "rows": rows,
        }
    manifest_path = output_dir / "manifest.json"
    report_path = output_dir / "REPORT_ZH.md"
    _write_text_atomic(
        manifest_path,
        json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
    )
    _write_text_atomic(report_path, _report(manifest))
    print(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
