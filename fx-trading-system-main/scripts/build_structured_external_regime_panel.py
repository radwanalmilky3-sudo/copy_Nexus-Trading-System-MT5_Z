#!/usr/bin/env python3
"""Build and audit the outcome-blind strict-PIT external regime panel."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from fx_system.external_factor_eligibility import (
    ExternalFactorDefinitionCatalog,
    ExternalFactorSourceRegistry,
    audit_external_factor_definitions,
    audit_external_factor_sources,
)
from fx_system.macro_vintages import rtdsm_eligibility_audit
from fx_system.structured_external_features import (
    FORMAL_REGIME_FEATURES,
    build_structured_external_regime_panel,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GSCPI_SOURCE_ID = "nyfed_gscpi_preserved_vintages"
RTDSM_SOURCE_ID = "phillyfed_rtdsm_verified_rows"


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


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


def _utc_timestamp(raw: str, *, name: str) -> pd.Timestamp:
    value = pd.to_datetime(raw, utc=True, errors="coerce")
    if pd.isna(value):
        raise ValueError(f"{name} is not a valid timestamp")
    return pd.Timestamp(value)


def _source_by_id(registry: ExternalFactorSourceRegistry, source_id: str):
    matches = [source for source in registry.sources if source.source_id == source_id]
    if len(matches) != 1:
        raise ValueError(f"registry must contain exactly one {source_id!r} source")
    return matches[0]


def _records_for_hash(frame: pd.DataFrame) -> list[dict[str, object]]:
    normalized = frame.copy()
    for column in normalized.select_dtypes(include=["datetime", "datetimetz"]).columns:
        normalized[column] = normalized[column].map(
            lambda value: value.isoformat() if pd.notna(value) else None
        )
    normalized = normalized.astype(object).where(pd.notna(normalized), None)
    return normalized.to_dict(orient="records")


def _prefix_invariance_audit(
    gscpi: pd.DataFrame,
    rtdsm: pd.DataFrame,
    values: pd.DataFrame,
    lineage: pd.DataFrame,
) -> list[dict[str, object]]:
    complete = values.dropna(subset=list(FORMAL_REGIME_FEATURES))
    if complete.empty:
        raise ValueError("no complete decision exists for prefix-invariance audit")
    locations = sorted({0, len(complete) // 2, len(complete) - 1})
    gscpi_available = pd.to_datetime(gscpi["available_time"], utc=True)
    rtdsm_available = pd.to_datetime(rtdsm["available_time"], utc=True)
    rows: list[dict[str, object]] = []

    for location in locations:
        decision = pd.Timestamp(complete.iloc[location]["decision_time"])
        expected_values = values.loc[values["decision_time"].eq(decision)].reset_index(
            drop=True
        )
        expected_lineage = lineage.loc[
            lineage["decision_time"].eq(decision)
        ].reset_index(drop=True)

        prefix = build_structured_external_regime_panel(
            gscpi.loc[gscpi_available <= decision],
            rtdsm.loc[rtdsm_available <= decision],
            [decision],
            require_complete=True,
        )
        comparable_lineage = [
            column
            for column in prefix.lineage.columns
            if column not in {"source_data_sha256", "source_manifest_sha256"}
        ]
        pd.testing.assert_frame_equal(expected_values, prefix.values)
        pd.testing.assert_frame_equal(
            expected_lineage[comparable_lineage],
            prefix.lineage[comparable_lineage],
        )

        changed_gscpi = gscpi.copy()
        future_gscpi = gscpi_available > decision
        changed_gscpi.loc[future_gscpi, "value"] += 1000.0
        changed_rtdsm = rtdsm.copy()
        future_rtdsm = rtdsm_available > decision
        multipliers = 1.0 + (np.arange(int(future_rtdsm.sum())) % 17 + 1) / 100.0
        changed_rtdsm.loc[future_rtdsm, "value"] *= multipliers
        changed = build_structured_external_regime_panel(
            changed_gscpi,
            changed_rtdsm,
            [decision],
            require_complete=True,
        )
        pd.testing.assert_frame_equal(expected_values, changed.values)
        pd.testing.assert_frame_equal(
            expected_lineage[comparable_lineage],
            changed.lineage[comparable_lineage],
        )

        rows.append(
            {
                "decision_time": decision.isoformat(),
                "prefix_rows": {
                    GSCPI_SOURCE_ID: int((gscpi_available <= decision).sum()),
                    RTDSM_SOURCE_ID: int((rtdsm_available <= decision).sum()),
                },
                "future_rows_mutated": {
                    GSCPI_SOURCE_ID: int(future_gscpi.sum()),
                    RTDSM_SOURCE_ID: int(future_rtdsm.sum()),
                },
                "prefix_invariant": True,
                "future_information_canary_passed": True,
                "selected_feature_and_lineage_sha256": _canonical_sha256(
                    {
                        "values": _records_for_hash(expected_values),
                        "lineage": _records_for_hash(
                            expected_lineage[comparable_lineage]
                        ),
                    }
                ),
            }
        )
    return rows


def _coverage_summary(lineage: pd.DataFrame) -> dict[str, object]:
    output: dict[str, object] = {}
    for feature_name, group in lineage.groupby("feature_name", sort=True):
        group = group.sort_values("decision_time").copy()
        ready = group.loc[group["feature_status"].eq("ready")]
        not_ready = group.loc[~group["feature_status"].eq("ready")].copy()
        intervals: list[dict[str, object]] = []
        if not not_ready.empty:
            new_interval = (
                not_ready["decision_time"]
                .diff()
                .dt.total_seconds()
                .ne(86400.0)
                | not_ready["feature_status"].ne(not_ready["feature_status"].shift())
            )
            not_ready["_interval"] = new_interval.cumsum()
            intervals = [
                {
                    "status": str(interval["feature_status"].iloc[0]),
                    "start": interval["decision_time"].min().isoformat(),
                    "end": interval["decision_time"].max().isoformat(),
                    "days": len(interval),
                    "first_source_vintage": (
                        str(interval["source_vintage_label"].dropna().iloc[0])
                        if interval["source_vintage_label"].notna().any()
                        else None
                    ),
                    "last_source_vintage": (
                        str(interval["source_vintage_label"].dropna().iloc[-1])
                        if interval["source_vintage_label"].notna().any()
                        else None
                    ),
                }
                for _, interval in not_ready.groupby("_interval", sort=True)
            ]
        output[str(feature_name)] = {
            "rows": len(group),
            "status_counts": {
                str(key): int(value)
                for key, value in group["feature_status"].value_counts().items()
            },
            "ready_fraction": float(len(ready) / len(group)),
            "first_ready_decision": (
                ready["decision_time"].min().isoformat() if not ready.empty else None
            ),
            "last_ready_decision": (
                ready["decision_time"].max().isoformat() if not ready.empty else None
            ),
            "maximum_ready_staleness_days": (
                float(ready["source_staleness_days"].max())
                if not ready.empty
                else None
            ),
            "non_ready_intervals": intervals,
        }
    return output


def _report(manifest: dict[str, object]) -> str:
    coverage = manifest["coverage"]
    lines = [
        "# 严格 PIT 结构化外部 regime 特征面板",
        "",
        f"生成日期：{manifest['stage_date']}。本产物没有读取价格或收益标签。",
        "",
        "## 交付结果",
        "",
        f"- 决策区间：`[{manifest['decision_start']}, {manifest['decision_end_exclusive']})`；"
        f"共 {manifest['decision_rows']} 个日度 UTC 决策时点。",
        f"- 特征值：{manifest['feature_count']} 个正式 regime 特征；谱系："
        f"{manifest['lineage_rows']} 行，每行保留 source vintage、available time、"
        "observation、staleness、eligibility 与源文件哈希。",
        f"- 三个真实历史检查点均通过 prefix invariance 和未来版本篡改 canary："
        f"{len(manifest['prefix_invariance_checks'])}/{len(manifest['prefix_invariance_checks'])}。",
        "- 所有非空来源时间均不晚于决策时间；ready 行全部为 `verified_strict_pit`。",
        "",
        "## 可用性",
        "",
    ]
    for feature_name in FORMAL_REGIME_FEATURES:
        item = coverage[feature_name]
        lines.append(
            f"- `{feature_name}`：ready {item['status_counts'].get('ready', 0)}/"
            f"{item['rows']}；首次 ready `{item['first_ready_decision']}`；状态分布 "
            f"`{json.dumps(item['status_counts'], ensure_ascii=False, sort_keys=True)}`。"
        )
        for interval in item["non_ready_intervals"]:
            lines.append(
                f"  - `{interval['status']}`：`{interval['start']}` 至 "
                f"`{interval['end']}`（{interval['days']} 天）。"
            )
    lines.extend(
        [
            "",
            "GSCPI 在 2022 年才开始保存逐期 vintage，且六版本变化需要热身，因此此前缺失是"
            "合同要求，不会用当前修订值回填。IP 的 stale 行同样保持缺失，不会放宽 75 天上限。",
            "",
            "## 当前含义",
            "",
            "这是一套可接到未来价格决策时点的外部状态输入，不是方向 alpha，也没有做任何"
            "factor/outcome 筛选。它不会修改第一层的 16 因子或每折 48 个假设。后续若要测试"
            "“价格因子在某种宏观状态下是否更有效”，必须另行预注册交互形式和多重检验家族。",
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
        default=Path("outputs/structured_external_regime_panel_20260717"),
    )
    args = parser.parse_args()

    start = _utc_timestamp(args.start, name="start")
    end = _utc_timestamp(args.end, name="end")
    if start >= end:
        raise ValueError("start must precede the exclusive end")
    decisions = pd.date_range(start, end, freq="D", inclusive="left", tz="UTC")
    if decisions.empty:
        raise ValueError("decision range is empty")

    registry_path = (PROJECT_ROOT / args.registry).resolve()
    catalog_path = (PROJECT_ROOT / args.factor_catalog).resolve()
    registry = ExternalFactorSourceRegistry.from_yaml(registry_path)
    source_audit = audit_external_factor_sources(registry, project_root=PROJECT_ROOT)
    if source_audit["integrity_verified_count"] != source_audit["source_count"]:
        raise ValueError("external source registry integrity audit failed")
    catalog = ExternalFactorDefinitionCatalog.from_yaml(catalog_path)
    factor_audit = audit_external_factor_definitions(catalog, source_audit)
    formal = set(factor_audit["formal_factor_ids"])
    if not set(FORMAL_REGIME_FEATURES).issubset(formal):
        raise ValueError("one or more structured regime features are not formal eligible")

    gscpi_source = _source_by_id(registry, GSCPI_SOURCE_ID)
    rtdsm_source = _source_by_id(registry, RTDSM_SOURCE_ID)
    if not gscpi_source.formal_regime_eligible or not rtdsm_source.formal_regime_eligible:
        raise ValueError("structured regime source is not formally eligible")
    gscpi_path = (PROJECT_ROOT / gscpi_source.data_path).resolve()
    rtdsm_path = (PROJECT_ROOT / rtdsm_source.data_path).resolve()
    gscpi = pd.read_csv(gscpi_path)
    rtdsm = pd.read_csv(rtdsm_path, low_memory=False)

    panel = build_structured_external_regime_panel(gscpi, rtdsm, decisions)
    source_hashes = {
        GSCPI_SOURCE_ID: gscpi_source.data_sha256,
        RTDSM_SOURCE_ID: rtdsm_source.data_sha256,
    }
    manifest_hashes = {
        GSCPI_SOURCE_ID: gscpi_source.manifest_sha256,
        RTDSM_SOURCE_ID: rtdsm_source.manifest_sha256,
    }
    lineage = panel.lineage.copy()
    lineage["source_data_sha256"] = lineage["source_id"].map(source_hashes)
    lineage["source_manifest_sha256"] = lineage["source_id"].map(manifest_hashes)
    if lineage[["source_data_sha256", "source_manifest_sha256"]].isna().any(axis=None):
        raise RuntimeError("lineage source hashes are incomplete")

    prefix_checks = _prefix_invariance_audit(
        gscpi, rtdsm, panel.values, lineage
    )
    available = lineage["source_available_time"].notna()
    future_information_violations = int(
        (
            lineage.loc[available, "source_available_time"]
            > lineage.loc[available, "decision_time"]
        ).sum()
    )
    non_strict_ready_rows = int(
        (~lineage.loc[lineage["feature_status"].eq("ready"), "source_eligibility"].eq(
            "verified_strict_pit"
        )).sum()
    )
    if future_information_violations or non_strict_ready_rows:
        raise RuntimeError("structured external panel violated its strict-PIT contract")

    output_dir = (PROJECT_ROOT / args.output_dir).resolve()
    values_path = output_dir / "feature_values.csv"
    lineage_path = output_dir / "feature_lineage.csv"
    _write_csv_atomic(panel.values, values_path)
    _write_csv_atomic(lineage, lineage_path)
    manifest = {
        "schema_version": 1,
        "stage_date": "2026-07-17",
        "stage": "structured_external_regime_panel_outcome_blind",
        "decision_start": start.isoformat(),
        "decision_end_exclusive": end.isoformat(),
        "decision_frequency": "1D_UTC",
        "decision_rows": len(panel.values),
        "feature_ids": list(FORMAL_REGIME_FEATURES),
        "feature_count": len(FORMAL_REGIME_FEATURES),
        "lineage_rows": len(lineage),
        "input_physical_rows": {
            GSCPI_SOURCE_ID: len(gscpi),
            RTDSM_SOURCE_ID: len(rtdsm),
        },
        "input_eligible_rows": {
            GSCPI_SOURCE_ID: len(gscpi),
            RTDSM_SOURCE_ID: rtdsm_eligibility_audit(rtdsm)[
                "counts_by_eligibility"
            ].get("verified_strict_pit", 0),
        },
        "source_data_sha256": source_hashes,
        "source_manifest_sha256": manifest_hashes,
        "registry_path": args.registry.as_posix(),
        "registry_sha256": _sha256(registry_path),
        "factor_catalog_path": args.factor_catalog.as_posix(),
        "factor_catalog_sha256": _sha256(catalog_path),
        "builder_path": "src/fx_system/structured_external_features.py",
        "builder_sha256": _sha256(
            PROJECT_ROOT / "src/fx_system/structured_external_features.py"
        ),
        "runner_path": "scripts/build_structured_external_regime_panel.py",
        "runner_sha256": _sha256(Path(__file__).resolve()),
        "outputs": {
            "feature_values": {
                "path": values_path.relative_to(PROJECT_ROOT).as_posix(),
                "sha256": _sha256(values_path),
                "rows": len(panel.values),
            },
            "feature_lineage": {
                "path": lineage_path.relative_to(PROJECT_ROOT).as_posix(),
                "sha256": _sha256(lineage_path),
                "rows": len(lineage),
            },
        },
        "coverage": _coverage_summary(lineage),
        "prefix_invariance_checks": prefix_checks,
        "future_information_violations": future_information_violations,
        "non_strict_ready_rows": non_strict_ready_rows,
        "price_inputs_read": [],
        "return_labels_opened": False,
        "factor_outcome_evaluations_added": 0,
        "formal_net_returns_ready": False,
        "trading_approval": False,
        "verdict": "outcome_blind_external_regime_panel_ready_not_alpha",
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
