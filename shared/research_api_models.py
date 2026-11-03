"""Read-only API contracts for the Research Lab surface.

These models deliberately describe the gateway contract only.  They do not
know how research data is stored or fetched; the router can therefore expose a
stable shape while the backing research service is optional.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field


API_SCHEMA_VERSION = "1.0"


class ResearchStatus(StrEnum):
    """Availability of the optional research backend."""

    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ResearchModel(BaseModel):
    """Common strict configuration for public research contracts."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    schema_version: str = API_SCHEMA_VERSION


class DatasetContract(ResearchModel):
    dataset_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str | None = None
    source: str | None = None
    version: str | None = None
    status: str = "unknown"
    row_count: int | None = Field(default=None, ge=0)
    columns: list[str] = Field(default_factory=list)
    content_hash: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    quality_summary: dict[str, Any] | None = None


class ImportJobContract(ResearchModel):
    import_job_id: str = Field(min_length=1)
    dataset_id: str | None = None
    status: str = "unknown"
    source: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    rows_imported: int | None = Field(default=None, ge=0)
    error: str | None = None


class QualityRunContract(ResearchModel):
    quality_run_id: str = Field(min_length=1)
    dataset_id: str | None = None
    status: str = "unknown"
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    checks: dict[str, bool] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    content_hash: str | None = None
    rows_checked: int | None = Field(default=None, ge=0)
    scope: str | None = None


class StrategyContract(ResearchModel):
    strategy_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str | None = None
    version: str | None = None
    status: str = "unknown"
    symbols: list[str] = Field(default_factory=list)
    timeframes: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class BacktestMetrics(ResearchModel):
    total_trades: int | None = Field(default=None, ge=0)
    net_pnl: float | None = None
    win_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    max_drawdown: float | None = Field(default=None, ge=0.0)
    sharpe: float | None = None


class BacktestContract(ResearchModel):
    backtest_id: str = Field(min_length=1)
    strategy_id: str | None = None
    dataset_id: str | None = None
    status: str = "unknown"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metrics: BacktestMetrics = Field(default_factory=BacktestMetrics)
    parameters: dict[str, Any] = Field(default_factory=dict)


class NewsContract(ResearchModel):
    news_id: str = Field(min_length=1)
    headline: str = Field(min_length=1)
    source: str | None = None
    published_at: datetime | None = None
    symbols: list[str] = Field(default_factory=list)
    impact: str | None = None
    sentiment: float | None = Field(default=None, ge=-1.0, le=1.0)
    url: str | None = None


class ArtifactContract(ResearchModel):
    artifact_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    artifact_type: str = Field(min_length=1)
    strategy_id: str | None = None
    backtest_id: str | None = None
    status: str = "unknown"
    uri: str | None = None
    media_type: str | None = None
    content_hash: str | None = None
    created_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


ContractT = TypeVar("ContractT", bound=ResearchModel)


class ResearchCollection(BaseModel, Generic[ContractT]):
    """List response shared by all Research Lab read endpoints."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = API_SCHEMA_VERSION
    status: ResearchStatus
    source: str = "research-backend"
    items: list[ContractT] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class ResearchItem(BaseModel, Generic[ContractT]):
    """Single-resource response shared by optional detail endpoints."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = API_SCHEMA_VERSION
    status: ResearchStatus
    source: str = "research-backend"
    item: ContractT | None = None


DatasetList = ResearchCollection[DatasetContract]
ImportJobList = ResearchCollection[ImportJobContract]
QualityRunList = ResearchCollection[QualityRunContract]
StrategyList = ResearchCollection[StrategyContract]
BacktestList = ResearchCollection[BacktestContract]
NewsList = ResearchCollection[NewsContract]
ArtifactList = ResearchCollection[ArtifactContract]


__all__ = [
    "API_SCHEMA_VERSION",
    "ArtifactContract",
    "ArtifactList",
    "BacktestContract",
    "BacktestList",
    "BacktestMetrics",
    "DatasetContract",
    "DatasetList",
    "ImportJobContract",
    "ImportJobList",
    "NewsContract",
    "NewsList",
    "QualityRunContract",
    "QualityRunList",
    "ResearchCollection",
    "ResearchItem",
    "ResearchModel",
    "ResearchStatus",
    "StrategyContract",
    "StrategyList",
]
