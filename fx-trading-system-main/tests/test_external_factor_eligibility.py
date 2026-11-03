from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from fx_system.external_factor_eligibility import (
    ExternalFactorDefinitionCatalog,
    ExternalFactorSource,
    ExternalFactorSourceRegistry,
    audit_external_factor_definitions,
    audit_external_factor_sources,
)

ROOT = Path(__file__).parents[1]
REGISTRY = ROOT / "configs" / "external_factor_source_registry.yaml"
FACTOR_CATALOG = ROOT / "configs" / "external_factor_definitions.yaml"


def test_real_external_source_registry_has_verified_bytes_and_closed_outcomes() -> None:
    registry = ExternalFactorSourceRegistry.from_yaml(REGISTRY)
    audit = audit_external_factor_sources(registry, project_root=ROOT)

    assert audit["source_count"] == 13
    assert audit["integrity_verified_count"] == 13
    assert audit["formal_directional_sources"] == []
    assert set(audit["formal_regime_sources"]) == {
        "nyfed_gscpi_preserved_vintages",
        "phillyfed_rtdsm_verified_rows",
        "treasury_tic_tressect_vintages",
    }
    assert set(audit["formal_event_control_sources"]) == {
        "phillyfed_spf_release_calendar",
        "benchmark_publication_calendar",
        "central_bank_policy_calendar_eurusd_strict_rows",
    }
    assert audit["return_labels_opened"] is False
    assert audit["factor_outcome_evaluations_added"] == 0
    assert audit["trading_approval"] is False


def test_non_strict_or_blocked_source_cannot_self_promote() -> None:
    base = {
        "source_id": "example_source",
        "family": "example",
        "manifest_path": "manifest.json",
        "manifest_sha256": "0" * 64,
        "data_path": "data.csv",
        "data_sha256": "1" * 64,
        "roles": ["directional_factor"],
        "formal_directional_eligible": True,
        "available_time_policy": "known",
        "revision_policy": "fixed",
        "license_status": "internal",
        "blockers": [],
    }
    with pytest.raises(ValidationError, match="verified_strict_pit"):
        ExternalFactorSource.model_validate(
            {**base, "quality": "exploratory_current_vintage"}
        )
    with pytest.raises(ValidationError, match="blocked source"):
        ExternalFactorSource.model_validate(
            {**base, "quality": "verified_strict_pit", "blockers": ["unresolved"]}
        )


def test_integrity_failure_closes_all_formal_roles(tmp_path: Path) -> None:
    registry = ExternalFactorSourceRegistry.model_validate(
        {
            "schema_version": 1,
            "registry_date": "2026-07-17",
            "sources": [
                {
                    "source_id": "strict_but_missing",
                    "family": "event",
                    "manifest_path": "missing.manifest.json",
                    "manifest_sha256": "0" * 64,
                    "data_path": "missing.csv",
                    "data_sha256": "1" * 64,
                    "quality": "verified_strict_pit",
                    "roles": ["event_control"],
                    "formal_event_control_eligible": True,
                    "available_time_policy": "known",
                    "revision_policy": "fixed",
                    "license_status": "internal",
                    "blockers": [],
                }
            ],
        }
    )
    audit = audit_external_factor_sources(registry, project_root=tmp_path)
    row = audit["sources"][0]
    assert row["integrity_verified"] is False
    assert row["formal_event_control_eligible"] is False
    assert set(row["issues"]) == {
        "manifest_missing_or_sha256_mismatch",
        "data_missing_or_sha256_mismatch",
    }


def test_external_factor_dependencies_resolve_without_opening_outcomes() -> None:
    registry = ExternalFactorSourceRegistry.from_yaml(REGISTRY)
    source_audit = audit_external_factor_sources(registry, project_root=ROOT)
    catalog = ExternalFactorDefinitionCatalog.from_yaml(FACTOR_CATALOG)
    audit = audit_external_factor_definitions(catalog, source_audit)

    assert audit["factor_count"] == 12
    assert audit["counts_by_status"] == {
        "formal_eligible": 5,
        "exploratory_only": 7,
        "blocked": 0,
    }
    assert set(audit["formal_factor_ids"]) == {
        "gscpi_risk_state_pit",
        "us_cpi_12m_log_inflation",
        "us_ip_6m_log_growth",
        "benchmark_publication_state",
        "phillyfed_spf_release_state",
    }
    assert audit["return_labels_opened"] is False
    assert audit["factor_outcome_evaluations_added"] == 0
