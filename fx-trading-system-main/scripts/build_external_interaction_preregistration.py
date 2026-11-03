#!/usr/bin/env python3
"""Freeze the outcome-blind external-interaction implementation contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from fx_system.external_interaction import (
    ALL_HYPOTHESIS_COUNT,
    FORMAL_INTERACTION_SPECS,
    SHADOW_IDS,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/structured_external_interaction.yaml"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/structured_external_interaction_preregistration_20260723"),
    )
    args = parser.parse_args()
    config_path = (PROJECT_ROOT / args.config).resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config.get("hypotheses_per_fold") != ALL_HYPOTHESIS_COUNT:
        raise ValueError("config must freeze exactly eight hypotheses per fold")
    if config.get("formal_hypotheses") != [spec["id"] for spec in FORMAL_INTERACTION_SPECS]:
        raise ValueError("config formal interaction family drifted")
    if config.get("matched_shadow_hypotheses") != list(SHADOW_IDS):
        raise ValueError("config matched shadow family drifted")
    if config.get("outcome_authorization_required") is not True:
        raise ValueError("outcome authorization cannot be disabled")

    acceptance_path = (PROJECT_ROOT / config["external_acceptance_manifest"]).resolve()
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    if acceptance.get("verdict") != ("accepted_outcome_blind_package_current_registry_hash_closed"):
        raise ValueError("external package is not accepted")
    if acceptance.get("return_labels_opened") is not False:
        raise ValueError("external package acceptance is not outcome-blind")

    tracked_paths = {
        "config": config_path,
        "external_acceptance_manifest": acceptance_path,
        "external_package_manifest": PROJECT_ROOT
        / config["external_package_dir"]
        / "manifest.json",
        "implementation": PROJECT_ROOT / "src/fx_system/external_interaction.py",
        "implementation_tests": PROJECT_ROOT / "tests/test_external_interaction.py",
        "preregistration_draft": PROJECT_ROOT
        / "docs/STRUCTURED_EXTERNAL_INTERACTION_PREREGISTRATION_DRAFT_ZH.md",
        "research_registry": PROJECT_ROOT / "configs/factor_research_registry.yaml",
        "research_registry_audit": PROJECT_ROOT / "outputs/research_registry_audit.json",
    }
    inputs = {
        name: {
            "path": path.relative_to(PROJECT_ROOT).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for name, path in tracked_paths.items()
    }
    manifest = {
        "schema_version": 1,
        "stage": "structured_external_interaction_preregistration_outcome_blind",
        "created_at": datetime.now(UTC).isoformat(),
        "status": config["status"],
        "symbols": config["symbols"],
        "specifications": [dict(spec) for spec in FORMAL_INTERACTION_SPECS],
        "matched_shadow_ids": list(SHADOW_IDS),
        "hypotheses_per_fold": ALL_HYPOTHESIS_COUNT,
        "statistical_contract": {
            key: config[key]
            for key in (
                "train_years",
                "test_years",
                "step_years",
                "maximum_purge_horizon_days",
                "rebalance_common_trading_days",
                "bootstrap_block_days",
                "bootstrap_samples",
                "fdr_method",
                "fdr_level",
                "by_sensitivity_only",
                "minimum_complete_date_coverage",
                "ecdf_policy",
                "missing_policy",
                "oos_policy",
            )
        },
        "inputs": inputs,
        "price_panel_status": config["price_panel_status"],
        "price_panel_rows": None,
        "return_labels_opened": False,
        "factor_outcome_evaluations_added": 0,
        "formal_net_returns_ready": False,
        "trading_approval": False,
        "maximum_success_state": config["maximum_success_state"],
        "verdict": "interaction_implementation_ready_waiting_for_verified_price_panel",
    }
    output = (PROJECT_ROOT / args.output_dir).resolve()
    manifest_path = output / "manifest.json"
    _atomic_text(
        manifest_path,
        json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
    )
    _atomic_text(
        manifest_path.with_name("manifest.json.sha256"),
        f"{_sha256(manifest_path)}  manifest.json\n",
    )
    _atomic_text(
        output / "REPORT_ZH.md",
        "# 结构化外部交互预注册冻结\n\n"
        "四个正式交互和四个 matched shadow 已冻结，软件实现与外部包 SHA 已登记。"
        "当前等待新 Dukascopy 日线价格面板，没有读取收益标签。\n\n"
        "```text\nreturn_labels_opened=false\n"
        "factor_outcome_evaluations_added=0\n"
        "formal_net_returns_ready=false\ntrading_approval=false\n```\n",
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
