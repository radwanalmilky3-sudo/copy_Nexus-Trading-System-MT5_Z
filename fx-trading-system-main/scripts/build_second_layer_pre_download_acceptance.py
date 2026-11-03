#!/usr/bin/env python3
"""Close the seven pre-download second-layer tasks with machine evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fx_system.financial_center_calendar import deferred_central_bank_adapters
from fx_system.forward_collection_contract import ForwardCollectionConfig

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            f"verification failed ({completed.returncode}): {' '.join(command)}\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
    return {
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def main() -> None:
    output = PROJECT_ROOT / "outputs/second_layer_pre_download_acceptance_20260723"
    output.mkdir(parents=True, exist_ok=True)
    package_acceptance_path = (
        PROJECT_ROOT
        / "outputs/structured_external_package_acceptance_20260723/acceptance_manifest.json"
    )
    interaction_path = (
        PROJECT_ROOT
        / "outputs/structured_external_interaction_preregistration_20260723/manifest.json"
    )
    registry_path = PROJECT_ROOT / "outputs/research_registry_audit.json"
    package = json.loads(package_acceptance_path.read_text(encoding="utf-8"))
    interaction = json.loads(interaction_path.read_text(encoding="utf-8"))
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    forward = ForwardCollectionConfig.from_yaml(
        PROJECT_ROOT / "configs/dukascopy_forward_collection.yaml"
    )
    deferred = deferred_central_bank_adapters()
    if package.get("verdict") != ("accepted_outcome_blind_package_current_registry_hash_closed"):
        raise ValueError("external package acceptance is not closed")
    if interaction.get("hypotheses_per_fold") != 8:
        raise ValueError("interaction family is not exactly 4 formal + 4 shadow")
    if interaction.get("return_labels_opened") is not False:
        raise ValueError("interaction preregistration opened return labels")
    if registry.get("search_rounds") != 8 or registry.get("registered_hypotheses") != 20:
        raise ValueError("research registry audit is stale")
    if registry.get("disclosed_factor_outcome_evaluations") != 3504:
        raise ValueError("outcome exposure count changed during outcome-blind preparation")
    if forward.status != "blocked_until_alpha_freeze" or forward.alpha_freeze_time is not None:
        raise ValueError("forward contract must wait for a real alpha freeze")
    for authority in ("BOE", "SNB", "BOC", "RBNZ"):
        if deferred.get(authority) != "deferred_missing_official_adapter":
            raise ValueError(f"{authority} is neither implemented nor explicitly deferred")

    verification = {
        "pytest": _run(
            [
                "uv",
                "run",
                "pytest",
                "-q",
                "tests/test_structured_external_package.py",
                "tests/test_external_interaction.py",
                "tests/test_forward_collection_contract.py",
                "tests/test_research_registry.py",
                "tests/test_long_horizon_execution.py",
                "tests/test_long_horizon_portfolio_bridge.py",
                "tests/test_financial_center_calendar.py",
                "tests/test_central_bank_calendar.py",
            ]
        ),
        "ruff": _run(
            [
                "uv",
                "run",
                "ruff",
                "check",
                "src/fx_system/external_interaction.py",
                "src/fx_system/forward_collection_contract.py",
                "src/fx_system/long_horizon_portfolio_bridge.py",
                "src/fx_system/financial_center_calendar.py",
                "src/fx_system/research_registry.py",
                "scripts/audit_structured_external_package.py",
                "scripts/build_external_interaction_preregistration.py",
                "tests/test_external_interaction.py",
                "tests/test_forward_collection_contract.py",
                "tests/test_long_horizon_portfolio_bridge.py",
                "tests/test_research_registry.py",
            ]
        ),
    }
    tracked = [
        package_acceptance_path,
        interaction_path,
        registry_path,
        PROJECT_ROOT / "configs/structured_external_interaction.yaml",
        PROJECT_ROOT / "configs/dukascopy_forward_collection.yaml",
        PROJECT_ROOT / "src/fx_system/external_interaction.py",
        PROJECT_ROOT / "src/fx_system/forward_collection_contract.py",
        PROJECT_ROOT / "src/fx_system/long_horizon_portfolio_bridge.py",
        PROJECT_ROOT / "src/fx_system/financial_center_calendar.py",
    ]
    manifest = {
        "schema_version": 1,
        "stage": "second_layer_pre_download_tasks_acceptance",
        "created_at": datetime.now(UTC).isoformat(),
        "tasks": {
            "external_package_freeze": "complete",
            "price_external_interaction_engine": "complete_software_waiting_price_data",
            "anti_leakage_tests": "complete",
            "synthetic_long_horizon_ledger": "complete_software_cost_incomplete",
            "central_bank_calendars": "complete_via_explicit_deferred_branch",
            "research_registry_and_exposure_ledger": "complete",
            "post_freeze_forward_pipeline_design": "complete_blocked_until_real_alpha_freeze",
        },
        "tracked_artifacts": {
            path.relative_to(PROJECT_ROOT).as_posix(): {
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in tracked
        },
        "verification": verification,
        "package_verdict": package["verdict"],
        "interaction_verdict": interaction["verdict"],
        "registry_counts": {
            "search_rounds": registry["search_rounds"],
            "registered_hypotheses": registry["registered_hypotheses"],
            "outcome_evaluations": registry["disclosed_factor_outcome_evaluations"],
        },
        "deferred_central_bank_adapters": deferred,
        "return_labels_opened": False,
        "factor_outcome_evaluations_added": 0,
        "formal_net_returns_ready": False,
        "trading_approval": False,
        "verdict": "pre_download_tasks_complete_software_and_contract_only",
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (output / "manifest.json.sha256").write_text(
        f"{_sha256(manifest_path)}  manifest.json\n", encoding="utf-8"
    )
    (output / "pytest_relevant.txt").write_text(
        verification["pytest"]["stdout"] + verification["pytest"]["stderr"],
        encoding="utf-8",
    )
    (output / "ruff_relevant.txt").write_text(
        verification["ruff"]["stdout"] + verification["ruff"]["stderr"],
        encoding="utf-8",
    )
    (output / "REPORT_ZH.md").write_text(
        "# 第二层数据等待期任务验收\n\n"
        "目标列出的七项任务已完成软件和合同交付。五因子包 hash 闭合，交互器和反泄漏门可用，"
        "合成两阶段账本已接收冻结 schedule，registry 与 forward 合同已同步。\n\n"
        "四个缺失央行适配器按任务允许的 deferred 分支关闭，正式 macro blackout 仍不可用。"
        "真实收益、成本和交易批准没有打开；新价格数据到齐后仍须通过 intake/G0。\n\n"
        "```text\nreturn_labels_opened=false\n"
        "factor_outcome_evaluations_added=0\n"
        "formal_net_returns_ready=false\ntrading_approval=false\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
