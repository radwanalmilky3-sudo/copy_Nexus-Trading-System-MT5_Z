"""Versioned contracts for research data, runs, artifacts, signals, and gates."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


SCHEMA_VERSION = "1.0"


class Eligibility(StrEnum):
    """Eligibility state for a research object or decision."""

    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    PENDING = "pending"


class ContractBase(BaseModel):
    """Fields required to make a research object point-in-time auditable."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    run_id: str = Field(min_length=1)
    available_at: datetime
    vintage_id: str = Field(min_length=1)
    pit: bool = Field(alias="PIT")
    eligibility: Eligibility | bool
    cost_complete: bool
    schema_version: str = SCHEMA_VERSION


class DatasetContract(ContractBase):
    """Description of a versioned dataset available to research."""

    dataset_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    source: str = ""
    row_count: int | None = Field(default=None, ge=0)
    columns: list[str] = Field(default_factory=list)
    content_hash: str = ""


class RunContract(ContractBase):
    """Inputs and execution metadata for one reproducible research run."""

    run_name: str = Field(min_length=1)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    code_version: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class ArtifactContract(ContractBase):
    """A materialized output of a research run."""

    artifact_id: str = Field(min_length=1)
    artifact_type: str = Field(min_length=1)
    uri: str = ""
    content_hash: str = ""
    media_type: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class SignalContract(ContractBase):
    """A research signal with explicit temporal and eligibility context."""

    signal_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    direction: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    signal_at: datetime | None = None
    features: dict[str, float | int | str] = Field(default_factory=dict)
    # Optional signal risk fields — None/"" means "not provided" (backward compatible).
    atr: float | None = None
    stop_atr: float | None = None
    target_atr: float | None = None
    max_holding_hours: float | None = None
    group_id: str | None = None
    reason: str = ""


class ValidationContract(ContractBase):
    """Validation evidence attached to a dataset, run, artifact, or signal."""

    validation_id: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    valid: bool
    validator: str = ""
    checks: dict[str, bool] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)
    validated_at: datetime | None = None


class PromotionContract(ContractBase):
    """Decision record for promoting a research artifact or signal."""

    promotion_id: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    from_stage: str = Field(min_length=1)
    to_stage: str = Field(min_length=1)
    approved: bool
    approver: str = ""
    reason: str = ""
    promoted_at: datetime | None = None
