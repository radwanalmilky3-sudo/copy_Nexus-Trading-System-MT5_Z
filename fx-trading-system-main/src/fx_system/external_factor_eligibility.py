"""Outcome-blind integrity and eligibility contract for structured external factor data."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

ExternalQuality = Literal[
    "verified_strict_pit",
    "verified_vintage_conservative_availability",
    "conservative_pit_current_archive",
    "exploratory_current_vintage",
    "research_only_retrieved_later",
    "ineligible",
]
ExternalRole = Literal[
    "directional_factor",
    "regime_factor",
    "event_control",
    "cost_stress",
    "research_context",
]
ExternalFactorStatus = Literal["formal_eligible", "exploratory_only", "blocked"]

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{2,79}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


class ExternalFactorSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    family: str
    manifest_path: Path
    manifest_sha256: str
    data_path: Path
    data_sha256: str
    row_filter: str | None = None
    quality: ExternalQuality
    roles: list[ExternalRole]
    formal_directional_eligible: bool = False
    formal_regime_eligible: bool = False
    formal_event_control_eligible: bool = False
    available_time_policy: str
    revision_policy: str
    license_status: str
    blockers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def eligibility_contract(self) -> ExternalFactorSource:
        if not _IDENTIFIER.fullmatch(self.source_id):
            raise ValueError(f"invalid source_id {self.source_id!r}")
        if not _SHA256.fullmatch(self.manifest_sha256) or not _SHA256.fullmatch(
            self.data_sha256
        ):
            raise ValueError(f"{self.source_id}: hashes must be lowercase SHA-256")
        if not self.roles or len(self.roles) != len(set(self.roles)):
            raise ValueError(f"{self.source_id}: roles must be non-empty and unique")
        any_formal = (
            self.formal_directional_eligible
            or self.formal_regime_eligible
            or self.formal_event_control_eligible
        )
        if any_formal and self.quality != "verified_strict_pit":
            raise ValueError(
                f"{self.source_id}: formal eligibility requires verified_strict_pit"
            )
        if any_formal and self.blockers:
            raise ValueError(f"{self.source_id}: blocked source cannot be formal eligible")
        if self.formal_directional_eligible and "directional_factor" not in self.roles:
            raise ValueError(f"{self.source_id}: directional role is missing")
        if self.formal_regime_eligible and "regime_factor" not in self.roles:
            raise ValueError(f"{self.source_id}: regime role is missing")
        if self.formal_event_control_eligible and "event_control" not in self.roles:
            raise ValueError(f"{self.source_id}: event-control role is missing")
        return self


class ExternalFactorSourceRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    registry_date: date
    sources: list[ExternalFactorSource]

    @model_validator(mode="after")
    def unique_sources(self) -> ExternalFactorSourceRegistry:
        identifiers = [source.source_id for source in self.sources]
        if not identifiers or len(identifiers) != len(set(identifiers)):
            raise ValueError("external source IDs must be non-empty and unique")
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> ExternalFactorSourceRegistry:
        with Path(path).open("r", encoding="utf-8") as handle:
            return cls.model_validate(yaml.safe_load(handle))


class ExternalFactorDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    factor_id: str
    family: str
    directional: bool
    intended_role: Literal["directional_factor", "regime_factor", "event_control"]
    source_ids: list[str]
    horizons_days: list[int]
    formula: str
    expected_sign: Literal["positive", "negative", "risk_state_only", "event_control_only"]
    maximum_staleness_days: int = Field(ge=0, le=730)

    @model_validator(mode="after")
    def factor_contract(self) -> ExternalFactorDefinition:
        if not _IDENTIFIER.fullmatch(self.factor_id):
            raise ValueError(f"invalid factor_id {self.factor_id!r}")
        if not self.source_ids or len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError(f"{self.factor_id}: source_ids must be non-empty and unique")
        if not self.horizons_days or len(self.horizons_days) != len(set(self.horizons_days)):
            raise ValueError(f"{self.factor_id}: horizons_days must be non-empty and unique")
        if self.directional and self.intended_role != "directional_factor":
            raise ValueError(f"{self.factor_id}: directional factor requires directional role")
        if self.directional and self.expected_sign not in {"positive", "negative"}:
            raise ValueError(f"{self.factor_id}: directional factor requires directional sign")
        if not self.directional and self.expected_sign in {"positive", "negative"}:
            raise ValueError(f"{self.factor_id}: non-directional factor cannot claim a sign")
        return self


class ExternalFactorDefinitionCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    catalog_date: date
    factors: list[ExternalFactorDefinition]

    @model_validator(mode="after")
    def unique_factors(self) -> ExternalFactorDefinitionCatalog:
        identifiers = [factor.factor_id for factor in self.factors]
        if not identifiers or len(identifiers) != len(set(identifiers)):
            raise ValueError("external factor IDs must be non-empty and unique")
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> ExternalFactorDefinitionCatalog:
        with Path(path).open("r", encoding="utf-8") as handle:
            return cls.model_validate(yaml.safe_load(handle))


def audit_external_factor_sources(
    registry: ExternalFactorSourceRegistry,
    *,
    project_root: str | Path,
) -> dict[str, object]:
    root = Path(project_root).resolve()
    rows: list[dict[str, object]] = []
    for source in registry.sources:
        manifest = root / source.manifest_path
        data = root / source.data_path
        issues: list[str] = []
        manifest_actual = _sha256(manifest) if manifest.is_file() else None
        data_actual = _sha256(data) if data.is_file() else None
        if manifest_actual != source.manifest_sha256:
            issues.append("manifest_missing_or_sha256_mismatch")
        if data_actual != source.data_sha256:
            issues.append("data_missing_or_sha256_mismatch")
        integrity_verified = not issues
        rows.append(
            {
                "source_id": source.source_id,
                "family": source.family,
                "quality": source.quality,
                "roles": list(source.roles),
                "manifest_path": source.manifest_path.as_posix(),
                "data_path": source.data_path.as_posix(),
                "row_filter": source.row_filter,
                "integrity_verified": integrity_verified,
                "formal_directional_eligible": bool(
                    integrity_verified and source.formal_directional_eligible
                ),
                "formal_regime_eligible": bool(
                    integrity_verified and source.formal_regime_eligible
                ),
                "formal_event_control_eligible": bool(
                    integrity_verified and source.formal_event_control_eligible
                ),
                "license_status": source.license_status,
                "blockers": list(source.blockers),
                "issues": issues,
            }
        )
    counts_by_quality = {
        quality: sum(row["quality"] == quality for row in rows)
        for quality in sorted({str(row["quality"]) for row in rows})
    }
    return {
        "schema_version": 1,
        "registry_date": registry.registry_date.isoformat(),
        "sources": rows,
        "source_count": len(rows),
        "integrity_verified_count": sum(bool(row["integrity_verified"]) for row in rows),
        "counts_by_quality": counts_by_quality,
        "formal_directional_sources": [
            row["source_id"] for row in rows if row["formal_directional_eligible"]
        ],
        "formal_regime_sources": [
            row["source_id"] for row in rows if row["formal_regime_eligible"]
        ],
        "formal_event_control_sources": [
            row["source_id"] for row in rows if row["formal_event_control_eligible"]
        ],
        "return_labels_opened": False,
        "factor_outcome_evaluations_added": 0,
        "trading_approval": False,
    }


def audit_external_factor_definitions(
    catalog: ExternalFactorDefinitionCatalog,
    source_audit: dict[str, object],
) -> dict[str, object]:
    source_rows = source_audit.get("sources")
    if not isinstance(source_rows, list):
        raise ValueError("source audit does not contain a source list")
    by_id = {str(row["source_id"]): row for row in source_rows}
    rows: list[dict[str, object]] = []
    formal_flag = {
        "directional_factor": "formal_directional_eligible",
        "regime_factor": "formal_regime_eligible",
        "event_control": "formal_event_control_eligible",
    }
    for factor in catalog.factors:
        missing = [source_id for source_id in factor.source_ids if source_id not in by_id]
        dependencies = [by_id[source_id] for source_id in factor.source_ids if source_id in by_id]
        blockers: list[str] = []
        if missing:
            blockers.append(f"missing source IDs: {missing}")
        integrity_ok = bool(dependencies) and all(
            bool(source["integrity_verified"]) for source in dependencies
        )
        if dependencies and not integrity_ok:
            blockers.append("one or more source byte-integrity checks failed")
        incompatible = [
            str(source["source_id"])
            for source in dependencies
            if factor.intended_role not in set(source["roles"])
        ]
        if incompatible:
            blockers.append(f"sources do not declare intended role: {incompatible}")
        ineligible = [
            str(source["source_id"])
            for source in dependencies
            if source["quality"] == "ineligible"
        ]
        if ineligible:
            blockers.append(f"ineligible sources: {ineligible}")
        eligible_flag = formal_flag[factor.intended_role]
        formal = bool(
            not blockers
            and dependencies
            and all(bool(source[eligible_flag]) for source in dependencies)
        )
        status: ExternalFactorStatus = (
            "formal_eligible"
            if formal
            else "blocked"
            if blockers
            else "exploratory_only"
        )
        rows.append(
            {
                **factor.model_dump(mode="json"),
                "status": status,
                "dependency_qualities": {
                    str(source["source_id"]): source["quality"] for source in dependencies
                },
                "blockers": blockers,
            }
        )
    return {
        "schema_version": 1,
        "catalog_date": catalog.catalog_date.isoformat(),
        "factors": rows,
        "factor_count": len(rows),
        "counts_by_status": {
            status: sum(row["status"] == status for row in rows)
            for status in ("formal_eligible", "exploratory_only", "blocked")
        },
        "formal_factor_ids": [
            row["factor_id"] for row in rows if row["status"] == "formal_eligible"
        ],
        "return_labels_opened": False,
        "factor_outcome_evaluations_added": 0,
        "trading_approval": False,
    }
def write_external_factor_source_audit(audit: dict[str, object], path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(audit, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return destination.resolve()


__all__ = [
    "ExternalFactorSource",
    "ExternalFactorSourceRegistry",
    "ExternalFactorDefinition",
    "ExternalFactorDefinitionCatalog",
    "audit_external_factor_definitions",
    "audit_external_factor_sources",
    "write_external_factor_source_audit",
]
