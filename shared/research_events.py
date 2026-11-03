"""Typed event envelopes for publishing research contract changes."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from .research_contracts import (
    ArtifactContract,
    DatasetContract,
    PromotionContract,
    RunContract,
    SignalContract,
    ValidationContract,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


ContractT = TypeVar(
    "ContractT",
    DatasetContract,
    RunContract,
    ArtifactContract,
    SignalContract,
    ValidationContract,
    PromotionContract,
)


class ResearchEventType(StrEnum):
    DATASET = "research.dataset"
    RUN = "research.run"
    ARTIFACT = "research.artifact"
    SIGNAL = "research.signal"
    VALIDATION = "research.validation"
    PROMOTION = "research.promotion"


class ResearchEvent(BaseModel, Generic[ContractT]):
    """Stable event envelope carrying one research contract."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    event_id: str = Field(min_length=1)
    event_type: ResearchEventType
    emitted_at: datetime = Field(default_factory=_utcnow)
    run_id: str = Field(min_length=1)
    available_at: datetime
    vintage_id: str = Field(min_length=1)
    pit: bool = Field(alias="PIT")
    eligibility: str | bool
    cost_complete: bool
    schema_version: str
    payload: ContractT
    metadata: dict[str, Any] = Field(default_factory=dict)


class DatasetEvent(ResearchEvent[DatasetContract]):
    event_type: ResearchEventType = ResearchEventType.DATASET


class RunEvent(ResearchEvent[RunContract]):
    event_type: ResearchEventType = ResearchEventType.RUN


class ArtifactEvent(ResearchEvent[ArtifactContract]):
    event_type: ResearchEventType = ResearchEventType.ARTIFACT


class SignalEvent(ResearchEvent[SignalContract]):
    event_type: ResearchEventType = ResearchEventType.SIGNAL


class ValidationEvent(ResearchEvent[ValidationContract]):
    event_type: ResearchEventType = ResearchEventType.VALIDATION


class PromotionEvent(ResearchEvent[PromotionContract]):
    event_type: ResearchEventType = ResearchEventType.PROMOTION
