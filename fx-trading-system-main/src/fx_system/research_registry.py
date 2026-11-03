from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{2,79}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    url: HttpUrl
    evidence_role: Literal["factor", "validation", "data", "market_microstructure"]


class SearchHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    track: Literal["slow", "intraday", "shared"]
    status: Literal["completed", "invalidated"]
    method: str
    data_source: str
    inspected_start: date
    inspected_end: date
    unique_factor_definitions: int = Field(ge=0)
    fold_level_hypothesis_tests: int = Field(ge=0)
    factor_outcome_evaluations: int = Field(ge=0)
    artifact_path: Path | None = None
    artifact_sha256: str | None = None
    inference_result: Literal[
        "rejected",
        "invalidated_but_data_inspected",
        "software_only",
    ]
    notes: str

    @model_validator(mode="after")
    def artifact_contract(self) -> SearchHistoryEntry:
        if self.inspected_end < self.inspected_start:
            raise ValueError("search-history inspected_end must not precede inspected_start")
        if (self.artifact_path is None) != (self.artifact_sha256 is None):
            raise ValueError("artifact_path and artifact_sha256 must be supplied together")
        if self.artifact_sha256 is not None and not SHA256.fullmatch(self.artifact_sha256):
            raise ValueError("artifact_sha256 must be a lowercase SHA-256 digest")
        return self


class RegisteredHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    track: Literal["slow", "intraday"]
    family: str
    directional: bool
    formula: str
    expected_sign: Literal[
        "positive",
        "negative",
        "risk_state_only",
        "execution_filter_only",
        "two_sided_interaction",
    ]
    horizons: list[str]
    data_dependencies: list[str]
    reference_ids: list[str]
    registered_at: datetime
    registration_time_quality: Literal[
        "exact_recorded", "reconstructed_from_artifact_order"
    ] = "exact_recorded"
    registration_market_data_cutoff: date
    status: Literal[
        "preregistered", "deferred_missing_data", "superseded_unevaluated"
    ]
    superseded_by: str | None = None
    inference_eligibility: Literal[
        "exploratory_reused_history_requires_new_forward",
        "strict_forward_only",
    ]
    implementation_notes: str

    @model_validator(mode="after")
    def hypothesis_contract(self) -> RegisteredHypothesis:
        if not self.horizons or len(self.horizons) != len(set(self.horizons)):
            raise ValueError("hypothesis horizons must be non-empty and unique")
        if not self.data_dependencies or len(self.data_dependencies) != len(
            set(self.data_dependencies)
        ):
            raise ValueError("data_dependencies must be non-empty and unique")
        if not self.reference_ids:
            raise ValueError("every hypothesis requires at least one evidence reference")
        if self.directional and self.expected_sign in {
            "risk_state_only",
            "execution_filter_only",
        }:
            raise ValueError("directional hypotheses require a directional expected sign")
        if not self.directional and self.expected_sign in {"positive", "negative"}:
            raise ValueError("non-directional hypotheses cannot claim a return direction")
        if self.status == "superseded_unevaluated" and not self.superseded_by:
            raise ValueError("superseded hypotheses require superseded_by")
        if self.status != "superseded_unevaluated" and self.superseded_by is not None:
            raise ValueError("only superseded hypotheses may set superseded_by")
        return self


class RegistryAmendment(BaseModel):
    """A pre-result correction to a registered hypothesis.

    Amendments remain separate from the hypothesis so the original registration
    time is not silently rewritten.  The contract is deliberately limited to
    changes made without inspecting any additional market outcomes.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    hypothesis_id: str
    amended_at: datetime
    market_data_cutoff: date
    market_outcomes_inspected_since_registration: Literal[False] = False
    reason: str
    changes: list[str]
    evidence_reference_ids: list[str]

    @model_validator(mode="after")
    def amendment_contract(self) -> RegistryAmendment:
        if not self.changes or len(self.changes) != len(set(self.changes)):
            raise ValueError("amendment changes must be non-empty and unique")
        if not self.evidence_reference_ids or len(self.evidence_reference_ids) != len(
            set(self.evidence_reference_ids)
        ):
            raise ValueError(
                "amendment evidence_reference_ids must be non-empty and unique"
            )
        return self


class ResearchRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    registry_date: date
    market_history_previously_inspected_through: date
    fresh_forward_required: Literal[True] = True
    references: list[EvidenceReference]
    search_history: list[SearchHistoryEntry]
    amendments: list[RegistryAmendment] = Field(default_factory=list)
    hypotheses: list[RegisteredHypothesis]

    @model_validator(mode="after")
    def registry_contract(self) -> ResearchRegistry:
        groups = {
            "reference": [item.id for item in self.references],
            "search-history": [item.id for item in self.search_history],
            "amendment": [item.id for item in self.amendments],
            "hypothesis": [item.id for item in self.hypotheses],
        }
        for label, identifiers in groups.items():
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"duplicate {label} identifier")
            invalid = [item for item in identifiers if not IDENTIFIER.fullmatch(item)]
            if invalid:
                raise ValueError(f"invalid {label} identifiers: {invalid}")
        reference_ids = set(groups["reference"])
        hypothesis_ids = set(groups["hypothesis"])
        hypothesis_by_id = {item.id: item for item in self.hypotheses}
        formulas: set[tuple[str, tuple[str, ...]]] = set()
        for hypothesis in self.hypotheses:
            missing = set(hypothesis.reference_ids) - reference_ids
            if missing:
                raise ValueError(
                    f"{hypothesis.id}: unknown evidence references {sorted(missing)}"
                )
            if (
                hypothesis.registration_market_data_cutoff
                != self.market_history_previously_inspected_through
            ):
                raise ValueError(
                    f"{hypothesis.id}: registration cutoff must disclose all inspected history"
                )
            signature = (hypothesis.formula, tuple(hypothesis.horizons))
            if signature in formulas:
                raise ValueError("duplicate hypothesis formula and horizon set")
            formulas.add(signature)
            if hypothesis.superseded_by is not None:
                if hypothesis.superseded_by == hypothesis.id:
                    raise ValueError("a hypothesis cannot supersede itself")
                if hypothesis.superseded_by not in hypothesis_ids:
                    raise ValueError(
                        f"{hypothesis.id}: unknown superseding hypothesis "
                        f"{hypothesis.superseded_by!r}"
                    )
        amended_hypotheses: set[str] = set()
        for amendment in self.amendments:
            if amendment.hypothesis_id not in hypothesis_ids:
                raise ValueError(
                    f"{amendment.id}: unknown amended hypothesis "
                    f"{amendment.hypothesis_id!r}"
                )
            if amendment.hypothesis_id in amended_hypotheses:
                raise ValueError(
                    "only one outcome-free amendment is currently allowed per hypothesis"
                )
            amended_hypotheses.add(amendment.hypothesis_id)
            missing = set(amendment.evidence_reference_ids) - reference_ids
            if missing:
                raise ValueError(
                    f"{amendment.id}: unknown amendment evidence references "
                    f"{sorted(missing)}"
                )
            hypothesis = hypothesis_by_id[amendment.hypothesis_id]
            if amendment.amended_at < hypothesis.registered_at:
                raise ValueError("amendment time cannot precede hypothesis registration")
            if amendment.market_data_cutoff != self.market_history_previously_inspected_through:
                raise ValueError(
                    "amendment cutoff must disclose all previously inspected history"
                )
        if not self.search_history or not self.hypotheses or not self.references:
            raise ValueError("registry requires references, prior search history, and hypotheses")
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> ResearchRegistry:
        with Path(path).open("r", encoding="utf-8") as handle:
            return cls.model_validate(yaml.safe_load(handle))


def _file_sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def audit_research_registry(path: str | Path) -> dict[str, object]:
    registry_path = Path(path).resolve()
    registry = ResearchRegistry.from_yaml(registry_path)
    project_root = registry_path.parent.parent
    artifacts: list[dict[str, object]] = []
    for entry in registry.search_history:
        if entry.artifact_path is None:
            artifacts.append(
                {"round": entry.id, "path": None, "status": "declared_without_artifact"}
            )
            continue
        artifact = (
            entry.artifact_path
            if entry.artifact_path.is_absolute()
            else project_root / entry.artifact_path
        )
        if not artifact.exists():
            raise FileNotFoundError(f"{entry.id}: missing registered artifact {artifact}")
        actual = _file_sha256(artifact)
        if actual != entry.artifact_sha256:
            raise ValueError(f"{entry.id}: registered artifact SHA-256 mismatch")
        artifacts.append(
            {
                "round": entry.id,
                "path": str(artifact),
                "status": "verified",
                "sha256": actual,
            }
        )
    hypothesis_status = {
        status: sum(item.status == status for item in registry.hypotheses)
        for status in (
            "preregistered",
            "deferred_missing_data",
            "superseded_unevaluated",
        )
    }
    return {
        "schema_version": 1,
        "registry_path": str(registry_path),
        "registry_sha256": _file_sha256(registry_path),
        "registry_date": registry.registry_date.isoformat(),
        "market_history_previously_inspected_through": (
            registry.market_history_previously_inspected_through.isoformat()
        ),
        "fresh_forward_required": registry.fresh_forward_required,
        "references": len(registry.references),
        "search_rounds": len(registry.search_history),
        "outcome_free_amendments": len(registry.amendments),
        "amendments": [
            {
                "id": item.id,
                "hypothesis_id": item.hypothesis_id,
                "amended_at": item.amended_at.isoformat(),
                "market_data_cutoff": item.market_data_cutoff.isoformat(),
                "market_outcomes_inspected_since_registration": (
                    item.market_outcomes_inspected_since_registration
                ),
            }
            for item in registry.amendments
        ],
        "disclosed_unique_factor_definitions_sum": sum(
            item.unique_factor_definitions for item in registry.search_history
        ),
        "disclosed_fold_level_hypothesis_tests": sum(
            item.fold_level_hypothesis_tests for item in registry.search_history
        ),
        "disclosed_factor_outcome_evaluations": sum(
            item.factor_outcome_evaluations for item in registry.search_history
        ),
        "registered_hypotheses": len(registry.hypotheses),
        "active_hypotheses": sum(
            item.status != "superseded_unevaluated" for item in registry.hypotheses
        ),
        "hypothesis_status": hypothesis_status,
        "directional_hypotheses": sum(item.directional for item in registry.hypotheses),
        "active_directional_hypotheses": sum(
            item.directional and item.status != "superseded_unevaluated"
            for item in registry.hypotheses
        ),
        "risk_or_execution_hypotheses": sum(
            not item.directional for item in registry.hypotheses
        ),
        "artifacts": artifacts,
        "all_supplied_artifacts_verified": all(
            item["status"] == "verified"
            for item in artifacts
            if item["path"] is not None
        ),
        "interpretation": (
            "Counts disclose prior research exposure; they are not pooled independent tests. "
            "All new hypotheses evaluated on previously viewed market history remain exploratory "
            "until a frozen forward period is available."
        ),
    }


def write_registry_audit(audit: dict[str, object], output: str | Path) -> Path:
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(audit, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        temporary.write_bytes(encoded)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
