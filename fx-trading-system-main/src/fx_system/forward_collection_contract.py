"""Append-only market-data collection contract for a future frozen alpha."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ForwardCollectionPaths(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: Path
    immutable_generations: Path
    accepted_manifests: Path
    quarantine: Path


class ForwardCollectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    status: Literal["blocked_until_alpha_freeze", "collecting", "review_eligible"]
    provider: Literal["dukascopy"]
    symbols: list[str]
    historical_batch_end_exclusive: datetime
    market_history_previously_inspected_through: date
    alpha_freeze_time: datetime | None = None
    forward_eligibility_operator: Literal[">"] = ">"
    append_only: Literal[True] = True
    historical_database_mutation_allowed: Literal[False] = False
    generation_manifest_required: Literal[True] = True
    minimum_collecting_days: int = Field(90, ge=90)
    minimum_review_days: int = Field(180, ge=180)
    paths: ForwardCollectionPaths

    @model_validator(mode="after")
    def validate_state(self) -> ForwardCollectionConfig:
        if len(self.symbols) != len(set(self.symbols)) or not self.symbols:
            raise ValueError("forward symbols must be non-empty and unique")
        if self.alpha_freeze_time is None and self.status != "blocked_until_alpha_freeze":
            raise ValueError("forward collection cannot start before alpha_freeze_time is frozen")
        if self.alpha_freeze_time is not None and self.alpha_freeze_time.tzinfo is None:
            raise ValueError("alpha_freeze_time must be timezone-aware")
        if self.historical_batch_end_exclusive.tzinfo is None:
            raise ValueError("historical_batch_end_exclusive must be timezone-aware")
        if self.minimum_review_days < self.minimum_collecting_days:
            raise ValueError("minimum review period cannot be shorter than collecting period")
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> ForwardCollectionConfig:
        with Path(path).open("r", encoding="utf-8") as handle:
            return cls.model_validate(yaml.safe_load(handle))


class ForwardGenerationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    generation_id: str
    created_at: datetime
    observation_start: datetime
    observation_end_exclusive: datetime
    source_manifest_sha256: str
    parent_generation_sha256: str | None = None
    immutable: Literal[True] = True
    historical_database_modified: Literal[False] = False

    @model_validator(mode="after")
    def validate_times(self) -> ForwardGenerationManifest:
        times = (self.created_at, self.observation_start, self.observation_end_exclusive)
        if any(value.tzinfo is None for value in times):
            raise ValueError("forward generation times must be timezone-aware")
        if self.observation_start >= self.observation_end_exclusive:
            raise ValueError("forward generation range must be positive")
        if len(self.source_manifest_sha256) != 64:
            raise ValueError("source manifest SHA-256 must contain 64 hex characters")
        try:
            int(self.source_manifest_sha256, 16)
        except ValueError as error:
            raise ValueError("source manifest SHA-256 is not hexadecimal") from error
        return self


def assert_forward_generation_eligible(
    config: ForwardCollectionConfig,
    generation: ForwardGenerationManifest,
) -> None:
    """Fail closed unless every observation is strictly after the alpha freeze."""
    if config.alpha_freeze_time is None:
        raise ValueError("alpha_freeze_time is not frozen")
    if generation.observation_start <= config.alpha_freeze_time:
        raise ValueError("forward generation is not strictly after alpha_freeze_time")
    if generation.historical_database_modified:
        raise ValueError("forward generation modified historical data")


__all__ = [
    "ForwardCollectionConfig",
    "ForwardCollectionPaths",
    "ForwardGenerationManifest",
    "assert_forward_generation_eligible",
]
