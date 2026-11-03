#!/usr/bin/env python3
"""Assemble the five formal strict-PIT external features into one package."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from fx_system.external_factor_eligibility import (
    ExternalFactorDefinitionCatalog,
    ExternalFactorSourceRegistry,
    audit_external_factor_definitions,
    audit_external_factor_sources,
)
from fx_system.structured_event_controls import EVENT_CONTROL_FEATURES
from fx_system.structured_external_features import FORMAL_REGIME_FEATURES
from fx_system.structured_external_package import (
    FORMAL_STRUCTURED_FEATURES,
    combine_structured_external_panels,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


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


def _load_manifest(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid child manifest: {path}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"child manifest must be an object: {path}")
    if (
        payload.get("return_labels_opened") is not False
        or payload.get("factor_outcome_evaluations_added") != 0
        or payload.get("trading_approval") is not False
    ):
        raise ValueError(f"child manifest is not outcome-blind: {path}")
    return payload


def _load_child(
    manifest_path: Path,
    *,
    expected_features: tuple[str, ...],
    expected_stage: str,
) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    manifest = _load_manifest(manifest_path)
    if manifest.get("stage") != expected_stage:
        raise ValueError(f"unexpected child stage in {manifest_path}")
    if tuple(manifest.get("feature_ids", ())) != expected_features:
        raise ValueError(f"child feature IDs disagree with the formal catalog: {manifest_path}")
    output_records = manifest.get("outputs")
    if not isinstance(output_records, dict):
        raise ValueError(f"child outputs are missing: {manifest_path}")
    frames: dict[str, pd.DataFrame] = {}
    for name, record in output_records.items():
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise ValueError(f"child output record is malformed: {manifest_path}")
        path = PROJECT_ROOT / str(record["path"])
        if not path.is_file() or _sha256(path) != record.get("sha256"):
            raise ValueError(f"child output hash failed: {path}")
        frame = pd.read_csv(path)
        if len(frame) != record.get("rows"):
            raise ValueError(f"child output row count failed: {path}")
        frames[str(name)] = frame
    values = frames.get("feature_values")
    lineage = frames.get("feature_lineage")
    if values is None or lineage is None:
        raise ValueError(f"child values/lineage outputs are incomplete: {manifest_path}")
    for column in (
        "decision_time",
        "source_observation_time",
        "baseline_observation_time",
        "source_available_time",
        "event_window_start",
        "event_window_end",
        "source_retrieved_at",
    ):
        if column in lineage:
            lineage[column] = pd.to_datetime(
                lineage[column], utc=True, errors="coerce", format="mixed"
            )
    values["decision_time"] = pd.to_datetime(
        values["decision_time"], utc=True, errors="coerce", format="mixed"
    )
    return manifest, values, lineage, frames


def _coverage(values: pd.DataFrame, lineage: pd.DataFrame) -> dict[str, object]:
    result: dict[str, object] = {}
    for feature in FORMAL_STRUCTURED_FEATURES:
        value_series = values[feature]
        status = lineage.loc[lineage["feature_name"].eq(feature), "feature_status"]
        result[feature] = {
            "rows": len(value_series),
            "non_missing": int(value_series.notna().sum()),
            "missing": int(value_series.isna().sum()),
            "status_counts": {
                str(key): int(value)
                for key, value in status.value_counts().items()
            },
        }
    return result


def _report(manifest: dict[str, object]) -> str:
    coverage = manifest["coverage"]
    lines = [
        "# 五因子严格 PIT 外部特征包",
        "",
        f"生成日期：{manifest['stage_date']}。包内没有读取价格或收益标签。",
        "",
        "## 组成",
        "",
        "统一包合并 3 个结构化 regime 状态和 2 个事件控制：",
        "",
        "```text",
        *[f"{feature}" for feature in FORMAL_STRUCTURED_FEATURES],
        "```",
        "",
        f"区间 `{manifest['decision_start']}` 至 `{manifest['decision_end_exclusive']}`，"
        f"共 {manifest['decision_rows']} 个严格相同的日度 UTC 决策键，"
        f"{manifest['lineage_rows']} 行统一谱系。",
        "",
        "## 覆盖",
        "",
    ]
    for feature in FORMAL_STRUCTURED_FEATURES:
        item = coverage[feature]
        lines.append(
            f"- `{feature}`：{item['non_missing']}/{item['rows']} 非空；"
            f"状态 `{json.dumps(item['status_counts'], ensure_ascii=False, sort_keys=True)}`。"
        )
    lines.extend(
        [
            "",
            "GSCPI 的 2022-07-08 前缺失和 IP 的 2025-12-02 至 2025-12-24 stale 日均保留；"
            "SPF 与 benchmark 事件控制不使用 forecast values，也不把事件变量当方向 alpha。"
            "事件控制的首个日度边界因过去 24 小时窗口缺少完整前缀而 unavailable；SPF 的 "
            "32 个周日脉冲不会在此层移动到周一。",
            "",
            "## 下一轮限制",
            "",
            "价格因子与外部状态的交互尚未打开收益标签。正式研究必须使用独立预注册、统一"
            "complete-date mask、训练期 ECDF 变换、共同 BH 家族和新的 forward 数据；事件控制"
            "默认只作 nuisance/blackout control。",
            "",
            "```text",
            "return_labels_opened=false",
            "factor_outcome_evaluations_added=0",
            "trading_approval=false",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--regime-manifest",
        type=Path,
        default=Path("outputs/structured_external_regime_panel_20260717/manifest.json"),
    )
    parser.add_argument(
        "--event-manifest",
        type=Path,
        default=Path("outputs/structured_external_event_panel_20260717/manifest.json"),
    )
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
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/structured_external_feature_package_20260719"),
    )
    args = parser.parse_args()

    regime_manifest_path = (PROJECT_ROOT / args.regime_manifest).resolve()
    event_manifest_path = (PROJECT_ROOT / args.event_manifest).resolve()
    regime_manifest, regime_values, regime_lineage, _ = _load_child(
        regime_manifest_path,
        expected_features=FORMAL_REGIME_FEATURES,
        expected_stage="structured_external_regime_panel_outcome_blind",
    )
    event_manifest, event_values, event_lineage, event_frames = _load_child(
        event_manifest_path,
        expected_features=EVENT_CONTROL_FEATURES,
        expected_stage="structured_external_event_panel_outcome_blind",
    )
    package = combine_structured_external_panels(
        regime_values,
        regime_lineage,
        event_values,
        event_lineage,
    )
    decisions = package.values["decision_time"]
    if decisions.empty:
        raise ValueError("combined external package has no decisions")
    if package.values[list(FORMAL_STRUCTURED_FEATURES)].isna().all(axis=1).any():
        raise ValueError("combined external package contains an all-missing decision")
    available = package.lineage["source_available_time"].notna()
    future_information_violations = int(
        (
            package.lineage.loc[available, "source_available_time"]
            > package.lineage.loc[available, "decision_time"]
        ).sum()
    )
    ready = package.lineage["feature_status"].eq("ready")
    non_strict_ready_rows = int(
        (~package.lineage.loc[ready, "source_eligibility"].eq("verified_strict_pit")).sum()
    )
    if future_information_violations or non_strict_ready_rows:
        raise RuntimeError("combined external package violated strict-PIT lineage")

    registry_path = (PROJECT_ROOT / args.registry).resolve()
    catalog_path = (PROJECT_ROOT / args.factor_catalog).resolve()
    registry = ExternalFactorSourceRegistry.from_yaml(registry_path)
    source_audit = audit_external_factor_sources(registry, project_root=PROJECT_ROOT)
    catalog = ExternalFactorDefinitionCatalog.from_yaml(catalog_path)
    factor_audit = audit_external_factor_definitions(catalog, source_audit)
    if set(factor_audit["formal_factor_ids"]) != set(FORMAL_STRUCTURED_FEATURES):
        raise ValueError("formal catalog is not exactly the five structured package features")
    if source_audit["integrity_verified_count"] != source_audit["source_count"]:
        raise ValueError("source integrity audit failed")

    output_dir = (PROJECT_ROOT / args.output_dir).resolve()
    values_path = output_dir / "feature_values.csv"
    lineage_path = output_dir / "feature_lineage.csv"
    component_path = output_dir / "event_component_lineage.csv"
    event_components = event_frames.get("event_component_lineage")
    if event_components is None:
        raise ValueError("event component lineage is missing from child package")
    _write_csv_atomic(package.values, values_path)
    _write_csv_atomic(package.lineage, lineage_path)
    _write_csv_atomic(event_components, component_path)

    child_manifests = {
        "regime": {
            "path": args.regime_manifest.as_posix(),
            "sha256": _sha256(regime_manifest_path),
            "manifest": regime_manifest,
        },
        "event_control": {
            "path": args.event_manifest.as_posix(),
            "sha256": _sha256(event_manifest_path),
            "manifest": event_manifest,
        },
    }
    manifest = {
        "schema_version": 1,
        "stage_date": "2026-07-19",
        "stage": "structured_external_feature_package_outcome_blind",
        "decision_start": pd.Timestamp(decisions.min()).isoformat(),
        "decision_end_exclusive": (
            pd.Timestamp(decisions.max()) + pd.Timedelta(24, unit="h")
        ).isoformat(),
        "decision_frequency": "1D_UTC",
        "decision_rows": len(package.values),
        "feature_ids": list(FORMAL_STRUCTURED_FEATURES),
        "feature_count": len(FORMAL_STRUCTURED_FEATURES),
        "lineage_rows": len(package.lineage),
        "event_component_lineage_rows": len(event_components),
        "coverage": _coverage(package.values, package.lineage),
        "future_information_violations": future_information_violations,
        "non_strict_ready_rows": non_strict_ready_rows,
        "child_manifests": child_manifests,
        "registry_path": args.registry.as_posix(),
        "registry_sha256": _sha256(registry_path),
        "factor_catalog_path": args.factor_catalog.as_posix(),
        "factor_catalog_sha256": _sha256(catalog_path),
        "builder_path": "src/fx_system/structured_external_package.py",
        "builder_sha256": _sha256(
            PROJECT_ROOT / "src/fx_system/structured_external_package.py"
        ),
        "runner_path": "scripts/build_structured_external_feature_package.py",
        "runner_sha256": _sha256(Path(__file__).resolve()),
        "outputs": {},
        "price_inputs_read": [],
        "return_labels_opened": False,
        "factor_outcome_evaluations_added": 0,
        "formal_net_returns_ready": False,
        "trading_approval": False,
        "verdict": "outcome_blind_five_feature_package_ready_not_alpha",
    }
    for name, path, rows in (
        ("feature_values", values_path, len(package.values)),
        ("feature_lineage", lineage_path, len(package.lineage)),
        ("event_component_lineage", component_path, len(event_components)),
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
