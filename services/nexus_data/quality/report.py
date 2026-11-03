"""Validation reports and projections into shared research contracts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from shared.research_contracts import ArtifactContract, DatasetContract, Eligibility, ValidationContract

from .validators import ValidationFindings


class ReportStatus(StrEnum):
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ResearchContext:
    """Fields required by shared.research_contracts.ContractBase."""

    run_id: str
    available_at: datetime
    vintage_id: str
    pit: bool
    eligibility: Eligibility | bool
    cost_complete: bool

    def __post_init__(self) -> None:
        if self.available_at.tzinfo is None:
            raise ValueError("available_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ValidationReport:
    report_id: str
    dataset_id: str
    dataset_name: str
    source: str
    columns: tuple[str, ...]
    row_count: int
    findings: ValidationFindings
    context: ResearchContext
    validated_at: datetime
    validator: str = "nexus_data.import_quality"
    content_hash: str = ""
    artifact_uri: str = ""

    @property
    def status(self) -> ReportStatus:
        return ReportStatus(self.findings.status)

    @property
    def valid(self) -> bool:
        return self.findings.valid

    def to_validation_contract(self) -> ValidationContract:
        """Map quality fields to shared ValidationContract without mutation."""
        checks = {check.name: check.passed for check in self.findings.checks}
        issues = [f"{issue.code}: {issue.message}" for issue in self.findings.issues]
        return ValidationContract(
            run_id=self.context.run_id,
            available_at=self.context.available_at,
            vintage_id=self.context.vintage_id,
            PIT=self.context.pit,
            eligibility=self.context.eligibility,
            cost_complete=self.context.cost_complete,
            validation_id=self.report_id,
            subject_id=self.dataset_id,
            valid=self.valid,
            validator=self.validator,
            checks=checks,
            issues=issues,
            validated_at=self.validated_at,
        )

    def to_dataset_contract(self) -> DatasetContract:
        """Map dataset identity, columns, count, and hash to shared contract."""
        return DatasetContract(
            run_id=self.context.run_id,
            available_at=self.context.available_at,
            vintage_id=self.context.vintage_id,
            PIT=self.context.pit,
            eligibility=self.context.eligibility,
            cost_complete=self.context.cost_complete,
            dataset_id=self.dataset_id,
            name=self.dataset_name,
            source=self.source,
            row_count=self.row_count,
            columns=list(self.columns),
            content_hash=self.content_hash,
        )

    def to_artifact_contract(self) -> ArtifactContract:
        """Expose the report as a research artifact contract."""
        return ArtifactContract(
            run_id=self.context.run_id,
            available_at=self.context.available_at,
            vintage_id=self.context.vintage_id,
            PIT=self.context.pit,
            eligibility=self.context.eligibility,
            cost_complete=self.context.cost_complete,
            artifact_id=f"{self.report_id}:validation",
            artifact_type="validation_report",
            uri=self.artifact_uri,
            content_hash=self.content_hash,
            media_type="application/json",
            metadata={
                "dataset_id": self.dataset_id,
                "status": self.status.value,
                "rows_checked": self.findings.rows_checked,
                "quarantine_count": len(self.findings.quarantined),
                "validated_at": self.validated_at.astimezone(timezone.utc).isoformat(),
            },
        )
