"""Typed contracts for research-data ingestion and quality reporting.

Declarative only: no DuckDB connection, migration, import, or service startup.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping
JsonObject = Mapping[str, Any]
DatasetStatus = Literal['active', 'deprecated', 'quarantined']
ImportStatus = Literal['queued', 'running', 'succeeded', 'failed', 'cancelled']
QualityStatus = Literal['running', 'passed', 'failed', 'warning']
ResolutionStatus = Literal['open', 'reviewed', 'accepted', 'rejected', 'reprocessed']
ArtifactStatus = Literal['draft', 'published', 'superseded', 'archived']
@dataclass(frozen=True, slots=True)
class DatasetContract:
    dataset_id: str
    dataset_name: str
    description: str | None = None
    owner: str | None = None
    source_system: str | None = None
    storage_uri: str | None = None
    schema_version: int = 1
    grain: str | None = None
    sensitivity: str = 'internal'
    status: DatasetStatus = 'active'
    metadata: JsonObject = field(default_factory=dict)
@dataclass(frozen=True, slots=True)
class ImportJobContract:
    import_job_id: str
    dataset_id: str
    source_uri: str | None = None
    source_checksum: str | None = None
    requested_by: str | None = None
    status: ImportStatus = 'queued'
    started_at: datetime | None = None
    finished_at: datetime | None = None
    rows_seen: int = 0
    rows_loaded: int = 0
    rows_rejected: int = 0
    error_message: str | None = None
    parameters: JsonObject = field(default_factory=dict)
@dataclass(frozen=True, slots=True)
class QualityRunContract:
    quality_run_id: str
    dataset_id: str
    contract_version: str
    import_job_id: str | None = None
    status: QualityStatus = 'running'
    score: float | None = None
    checks_total: int = 0
    checks_passed: int = 0
    checks_failed: int = 0
    summary: JsonObject = field(default_factory=dict)
@dataclass(frozen=True, slots=True)
class QuarantineRecordContract:
    quarantine_id: str
    dataset_id: str
    reason_code: str
    payload: JsonObject
    import_job_id: str | None = None
    quality_run_id: str | None = None
    record_key: str | None = None
    reason_detail: str | None = None
    resolution_status: ResolutionStatus = 'open'
    resolved_by: str | None = None
    resolved_at: datetime | None = None
@dataclass(frozen=True, slots=True)
class LineageContract:
    lineage_id: str
    upstream_dataset_id: str
    downstream_dataset_id: str
    transformation_name: str
    import_job_id: str | None = None
    transformation_version: str | None = None
    column_mapping: JsonObject = field(default_factory=dict)
    run_started_at: datetime | None = None
    run_finished_at: datetime | None = None
    metadata: JsonObject = field(default_factory=dict)
@dataclass(frozen=True, slots=True)
class ResearchArtifactContract:
    artifact_id: str
    artifact_type: str
    artifact_name: str
    dataset_id: str | None = None
    quality_run_id: str | None = None
    artifact_uri: str | None = None
    content_checksum: str | None = None
    version: str | None = None
    status: ArtifactStatus = 'draft'
    produced_by: str | None = None
    parameters: JsonObject = field(default_factory=dict)
    metadata: JsonObject = field(default_factory=dict)