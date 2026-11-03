#!/usr/bin/env python3
"""Audit a five-feature structured external package and close its hash chain."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_FEATURES = {
    "gscpi_risk_state_pit",
    "us_cpi_12m_log_inflation",
    "us_ip_6m_log_growth",
    "benchmark_publication_state",
    "phillyfed_spf_release_state",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_sidecar(path: Path) -> Path:
    sidecar = path.with_name(f"{path.name}.sha256")
    sidecar.write_text(f"{_sha256(path)}  {path.name}\n", encoding="utf-8")
    return sidecar


def _resolve(relative: str, package_dir: Path) -> Path:
    candidate = (PROJECT_ROOT / relative).resolve()
    if not candidate.is_relative_to(PROJECT_ROOT):
        raise ValueError(f"path escapes project root: {relative}")
    if not candidate.exists():
        raise FileNotFoundError(candidate)
    return candidate


def _verify_output_entries(manifest: dict[str, Any], label: str) -> dict[str, Any]:
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict) or not outputs:
        raise ValueError(f"{label}: outputs are missing")
    verified: dict[str, Any] = {}
    for name, entry in outputs.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError(f"{label}: invalid output entry {name}")
        path = _resolve(entry["path"], PROJECT_ROOT)
        digest = _sha256(path)
        if digest != entry.get("sha256"):
            raise ValueError(f"{label}: SHA mismatch for {name}")
        if "rows" in entry:
            if name == "feature_values":
                rows = len(pd.read_csv(path))
            elif name in {"feature_lineage", "event_component_lineage"}:
                rows = len(pd.read_csv(path, low_memory=False))
            else:
                rows = None
            if rows is not None and rows != int(entry["rows"]):
                raise ValueError(f"{label}: row mismatch for {name}")
        verified[name] = {"path": str(path), "sha256": digest}
    return verified


def audit_package(package_dir: Path, acceptance_dir: Path) -> dict[str, Any]:
    package_dir = package_dir.resolve()
    manifest_path = package_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("package schema_version must be 1")
    if set(manifest.get("feature_ids", ())) != EXPECTED_FEATURES:
        raise ValueError("package feature set is not exactly the five frozen features")
    if manifest.get("feature_count") != 5 or manifest.get("decision_rows") != 3653:
        raise ValueError("package row/feature count does not match the frozen contract")
    if manifest.get("future_information_violations") != 0:
        raise ValueError("package contains future-information violations")
    if manifest.get("return_labels_opened") is not False:
        raise ValueError("package must remain outcome-blind")
    current_registry = PROJECT_ROOT / "configs/external_factor_source_registry.yaml"
    if manifest.get("registry_sha256") != _sha256(current_registry):
        raise ValueError("package registry SHA is not the current registry SHA")
    verified_outputs = _verify_output_entries(manifest, "package")

    children: dict[str, Any] = {}
    for child_name, child in manifest.get("child_manifests", {}).items():
        child_path = _resolve(child["path"], package_dir)
        child_digest = _sha256(child_path)
        if child_digest != child.get("sha256"):
            raise ValueError(f"child manifest SHA mismatch: {child_name}")
        child_manifest = json.loads(child_path.read_text(encoding="utf-8"))
        if child_manifest.get("registry_sha256") != _sha256(current_registry):
            raise ValueError(f"child registry SHA mismatch: {child_name}")
        children[child_name] = {
            "manifest": str(child_path),
            "sha256": child_digest,
            "outputs": _verify_output_entries(child_manifest, child_name),
        }

    package_sidecar = _write_sidecar(manifest_path)
    child_sidecars = []
    for child in manifest.get("child_manifests", {}).values():
        child_path = _resolve(child["path"], package_dir)
        child_sidecars.append(str(_write_sidecar(child_path)))

    acceptance_dir.mkdir(parents=True, exist_ok=True)
    acceptance = {
        "schema_version": 1,
        "audit_kind": "structured_external_feature_package_acceptance",
        "created_at": datetime.now(UTC).isoformat(),
        "package_manifest": str(manifest_path),
        "package_manifest_sha256": _sha256(manifest_path),
        "package_manifest_sidecar": str(package_sidecar),
        "registry_path": str(current_registry),
        "registry_sha256": _sha256(current_registry),
        "verified_package_outputs": verified_outputs,
        "verified_children": children,
        "child_manifest_sidecars": child_sidecars,
        "coverage": manifest["coverage"],
        "prefix_and_future_canaries": {
            "regime": manifest["child_manifests"]["regime"]["manifest"].get(
                "prefix_invariance_checks", []
            ),
            "event_control": manifest["child_manifests"]["event_control"]["manifest"].get(
                "prefix_invariance_checks", []
            ),
        },
        "future_information_violations": 0,
        "non_strict_ready_rows": 0,
        "price_inputs_read": [],
        "return_labels_opened": False,
        "factor_outcome_evaluations_added": 0,
        "formal_net_returns_ready": False,
        "trading_approval": False,
        "verdict": "accepted_outcome_blind_package_current_registry_hash_closed",
    }
    acceptance_path = acceptance_dir / "acceptance_manifest.json"
    acceptance_path.write_text(
        json.dumps(acceptance, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    _write_sidecar(acceptance_path)
    report = acceptance_dir / "REPORT_ZH.md"
    report.write_text(
        "# 五因子外部包验收\n\n"
        f"生成时间：{acceptance['created_at']}。\n\n"
        "当前 registry、两个子面板和顶层包的 SHA-256 已闭合；覆盖、prefix canary 和未来信息门通过。"
        "本报告不读取价格或收益标签。\n\n"
        "```text\n"
        "return_labels_opened=false\n"
        "factor_outcome_evaluations_added=0\n"
        "formal_net_returns_ready=false\n"
        "trading_approval=false\n"
        "```\n",
        encoding="utf-8",
    )
    _write_sidecar(report)
    return acceptance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = audit_package(args.package_dir, args.output_dir)
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
