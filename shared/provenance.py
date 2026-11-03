"""Point-in-time provenance records for research contracts and artifacts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProvenanceRecord(BaseModel):
    """Evidence describing where and when a value came from."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    provenance_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    available_at: datetime
    vintage_id: str = Field(min_length=1)
    pit: bool = Field(alias="PIT")
    eligibility: str | bool
    cost_complete: bool
    schema_version: str
    source_name: str = Field(min_length=1)
    source_uri: str = ""
    source_version: str = ""
    retrieved_at: datetime | None = None
    as_of: datetime | None = None
    content_hash: str = ""
    parent_ids: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
