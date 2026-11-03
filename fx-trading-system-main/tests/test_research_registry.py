from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from fx_system.research_registry import (
    ResearchRegistry,
    audit_research_registry,
    write_registry_audit,
)

REGISTRY = Path(__file__).parents[1] / "configs" / "factor_research_registry.yaml"


def test_project_registry_discloses_prior_searches_and_verifies_artifacts(tmp_path) -> None:
    audit = audit_research_registry(REGISTRY)

    assert audit["fresh_forward_required"] is True
    assert audit["search_rounds"] == 8
    assert audit["outcome_free_amendments"] == 1
    assert audit["amendments"][0]["hypothesis_id"] == "intraday_local_session_exact"
    assert audit["amendments"][0]["market_outcomes_inspected_since_registration"] is False
    assert audit["disclosed_fold_level_hypothesis_tests"] == 3249
    assert audit["disclosed_factor_outcome_evaluations"] == 3504
    assert audit["registered_hypotheses"] == 20
    assert audit["active_hypotheses"] == 17
    assert audit["hypothesis_status"] == {
        "preregistered": 15,
        "deferred_missing_data": 2,
        "superseded_unevaluated": 3,
    }
    assert audit["all_supplied_artifacts_verified"] is True

    destination = write_registry_audit(audit, tmp_path / "audit.json")
    written = json.loads(destination.read_text())
    assert written["registry_sha256"] == audit["registry_sha256"]


def test_registry_rejects_unknown_evidence_reference() -> None:
    payload = yaml.safe_load(REGISTRY.read_text())
    payload["hypotheses"][0]["reference_ids"] = ["missing_reference"]

    with pytest.raises(ValueError, match="unknown evidence references"):
        ResearchRegistry.model_validate(payload)


def test_registry_audit_rejects_artifact_digest_drift(tmp_path) -> None:
    payload = yaml.safe_load(REGISTRY.read_text())
    project_root = REGISTRY.parent.parent
    for item in payload["search_history"]:
        if item.get("artifact_path"):
            item["artifact_path"] = str(project_root / item["artifact_path"])
    payload["search_history"][0]["artifact_sha256"] = "0" * 64
    registry = tmp_path / "factor_research_registry.yaml"
    registry.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="artifact SHA-256 mismatch"):
        audit_research_registry(registry)


def test_registry_rejects_unknown_superseding_hypothesis() -> None:
    payload = yaml.safe_load(REGISTRY.read_text())
    hypothesis = next(
        item
        for item in payload["hypotheses"]
        if item["status"] == "superseded_unevaluated"
    )
    hypothesis["superseded_by"] = "missing_replacement"

    with pytest.raises(ValueError, match="unknown superseding hypothesis"):
        ResearchRegistry.model_validate(payload)


def test_registry_rejects_amendment_that_claims_a_newer_market_cutoff() -> None:
    payload = yaml.safe_load(REGISTRY.read_text())
    payload["amendments"][0]["market_data_cutoff"] = "2026-07-14"

    with pytest.raises(ValueError, match="amendment cutoff"):
        ResearchRegistry.model_validate(payload)
