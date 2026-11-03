from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = (
    Path(__file__).parents[1] / "scripts" / "materialize_treasury_tic_tressect.py"
)
SPEC = importlib.util.spec_from_file_location("treasury_tic_tressect", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
materializer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = materializer
SPEC.loader.exec_module(materializer)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_csv(
    path: Path, columns: tuple[str, ...], rows: list[dict[str, object]]
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _inputs(root: Path) -> Path:
    vintage_path = root / "tressect_vintages.csv"
    revision_path = root / "tressect_revision_summary.csv"
    base = {
        "total_net_purchases_musd": 4,
        "foreign_official_institutions_musd": 1,
        "other_foreigners_musd": 2,
        "international_regional_organizations_musd": 1,
    }
    _write_csv(
        vintage_path,
        materializer.EXPECTED_COLUMNS,
        [
            {
                "release_id": "release_1",
                "available_time": "2020-01-16T00:00:00Z",
                "reference_month": "1978-01-01",
                "observation_period": "1978-01",
                **base,
            },
            {
                "release_id": "release_2",
                "available_time": "2020-02-16T00:00:00Z",
                "reference_month": "1978-02-01",
                "observation_period": "1978-01",
                **base,
            },
            {
                "release_id": "release_2",
                "available_time": "2020-02-16T00:00:00Z",
                "reference_month": "1978-02-01",
                "observation_period": "1978-02",
                **base,
            },
        ],
    )
    _write_csv(
        revision_path,
        materializer.REVISION_COLUMNS,
        [
            {
                "series_id": "tressect",
                "prior_release_id": "release_1",
                "current_release_id": "release_2",
                "prior_available_time": "2020-01-16T00:00:00Z",
                "current_available_time": "2020-02-16T00:00:00Z",
                "prior_schema_id": "tressect_txt_fixed_4_v1",
                "current_schema_id": "tressect_txt_fixed_4_v1",
                "schema_changed": False,
                "prior_latest_observation": "1978-01",
                "current_latest_observation": "1978-02",
                "overlap_observations": 1,
                "added_observations": 1,
                "dropped_observations": 0,
                "changed_observations": 0,
                "changed_cells": 0,
                "earliest_revised_period": "",
                "latest_revised_period": "",
                "max_revision_age_months": "",
            }
        ],
    )
    manifest = {
        "program_version": "treasury-tic-vintage-audit-v2",
        "strict_pit_eligible": False,
        "series_status": {
            "tressect": "parsed_revision_audited_research_only",
        },
        "tressect_observation_row_count": 3,
        "tressect_revision_transition_count": 1,
        "tressect_vintage_count": 2,
        "output_hashes": {
            vintage_path.name: _sha256(vintage_path),
            revision_path.name: _sha256(revision_path),
        },
    }
    manifest_path = root / "audit_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def test_materializer_preserves_hash_chain_and_closes_outcomes(tmp_path: Path) -> None:
    audit_manifest = _inputs(tmp_path)
    output = tmp_path / "normalized" / "tressect_vintages.csv"
    manifest_path = tmp_path / "normalized" / "tressect_manifest.json"

    manifest = materializer.materialize(audit_manifest, output, manifest_path)

    assert manifest["vintage_count"] == 2
    assert manifest["observation_row_count"] == 3
    assert manifest["strict_pit_eligible"] is True
    assert manifest["formal_factor_registered"] is False
    assert manifest["return_labels_opened"] is False
    assert manifest["factor_outcome_evaluations_added"] == 0
    assert manifest["normalized_sha256"] == _sha256(output)


def test_materializer_rejects_changed_audit_output(tmp_path: Path) -> None:
    audit_manifest = _inputs(tmp_path)
    with (tmp_path / "tressect_vintages.csv").open("a", encoding="utf-8") as handle:
        handle.write("corrupt\n")

    with pytest.raises(ValueError, match="output hash mismatch"):
        materializer.materialize(
            audit_manifest,
            tmp_path / "normalized.csv",
            tmp_path / "manifest.json",
        )
