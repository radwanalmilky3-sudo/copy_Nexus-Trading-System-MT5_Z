"""Read-only Research Lab API contracts.

The gateway owns the HTTP contract, not the research data store.  A backend
may be attached by the application through ``app.state.research_backend``;
until then every endpoint returns a typed ``unavailable`` response without
performing storage, network, or service I/O.
"""
from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from typing import Any, Protocol, TypeVar

from fastapi import APIRouter, Depends, Query, Request

from shared.research_api_models import (
    ArtifactContract,
    ArtifactList,
    BacktestContract,
    BacktestList,
    DatasetContract,
    DatasetList,
    ImportJobContract,
    ImportJobList,
    NewsContract,
    NewsList,
    QualityRunContract,
    QualityRunList,
    ResearchCollection,
    ResearchItem,
    ResearchModel,
    ResearchStatus,
    StrategyContract,
    StrategyList,
)

from .admin import require_permission


router = APIRouter(prefix="/api/research-lab", tags=["research-lab"])
_trading_view = require_permission("trading.view")


class ResearchBackend(Protocol):
    """Optional backend protocol; implementations must be read-only here."""

    async def list_research(self, resource: str, *, limit: int, offset: int, query: str | None = None) -> Any:
        ...

    async def get_research(self, resource: str, item_id: str) -> Any:
        ...


ContractT = TypeVar("ContractT", bound=ResearchModel)


def _status(value: Any, default: ResearchStatus = ResearchStatus.AVAILABLE) -> ResearchStatus:
    try:
        return ResearchStatus(str(value))
    except ValueError:
        return ResearchStatus.DEGRADED if value is not None else default


def _backend(request: Request) -> ResearchBackend | None:
    """Return an explicitly registered backend, if the app has one."""

    value = getattr(request.app.state, "research_backend", None)
    return value if value is not None else None


def _unavailable(
    model: type[ContractT],
    *,
    limit: int,
    offset: int,
) -> ResearchCollection[ContractT]:
    del model  # Keeps the helper's type contract explicit without instantiation.
    return ResearchCollection(
        status=ResearchStatus.UNAVAILABLE,
        items=[],
        total=0,
        limit=limit,
        offset=offset,
    )


async def _list(
    request: Request,
    resource: str,
    model: type[ContractT],
    *,
    limit: int,
    offset: int,
    query: str | None,
) -> ResearchCollection[ContractT]:
    backend = _backend(request)
    if backend is None:
        return _unavailable(model, limit=limit, offset=offset)

    result = backend.list_research(resource, limit=limit, offset=offset, query=query)
    raw = await result if inspect.isawaitable(result) else result
    status = ResearchStatus.AVAILABLE
    source = "research-backend"
    raw_items: Sequence[Any] = []
    total = 0

    if isinstance(raw, Mapping):
        status = _status(raw.get("status"), ResearchStatus.AVAILABLE)
        source = str(raw.get("source") or source)
        candidate = raw.get("items", [])
        raw_items = candidate if isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes)) else []
        total = int(raw.get("total", len(raw_items)))
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        raw_items = raw
        total = len(raw_items)
    else:
        status = ResearchStatus.DEGRADED

    items = [model.model_validate(item) for item in raw_items]
    return ResearchCollection(
        status=status,
        source=source,
        items=items,
        total=max(total, len(items)),
        limit=limit,
        offset=offset,
    )


async def _item(
    request: Request,
    resource: str,
    item_id: str,
    model: type[ContractT],
) -> ResearchItem[ContractT]:
    backend = _backend(request)
    if backend is None:
        return ResearchItem(status=ResearchStatus.UNAVAILABLE)

    getter = getattr(backend, "get_research", None)
    if getter is None:
        return ResearchItem(status=ResearchStatus.UNAVAILABLE)
    result = getter(resource, item_id)
    raw = await result if inspect.isawaitable(result) else result
    if raw is None:
        return ResearchItem(status=ResearchStatus.AVAILABLE, item=None)
    if isinstance(raw, Mapping) and "item" in raw:
        status = _status(raw.get("status"), ResearchStatus.AVAILABLE)
        source = str(raw.get("source") or "research-backend")
        value = raw.get("item")
    else:
        status = ResearchStatus.AVAILABLE
        source = "research-backend"
        value = raw
    return ResearchItem(status=status, source=source, item=model.model_validate(value) if value is not None else None)


@router.get("/datasets", response_model=DatasetList, dependencies=[Depends(_trading_view)])
async def list_datasets(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    query: str | None = Query(None, max_length=200),
) -> DatasetList:
    return await _list(request, "datasets", DatasetContract, limit=limit, offset=offset, query=query)


@router.get("/import-jobs", response_model=ImportJobList, dependencies=[Depends(_trading_view)])
async def list_import_jobs(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    query: str | None = Query(None, max_length=200),
) -> ImportJobList:
    return await _list(request, "import_jobs", ImportJobContract, limit=limit, offset=offset, query=query)


@router.get("/quality-runs", response_model=QualityRunList, dependencies=[Depends(_trading_view)])
async def list_quality_runs(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    query: str | None = Query(None, max_length=200),
) -> QualityRunList:
    return await _list(request, "quality_runs", QualityRunContract, limit=limit, offset=offset, query=query)


@router.get("/strategies", response_model=StrategyList, dependencies=[Depends(_trading_view)])
async def list_research_strategies(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    query: str | None = Query(None, max_length=200),
) -> StrategyList:
    return await _list(request, "strategies", StrategyContract, limit=limit, offset=offset, query=query)


@router.get("/backtests", response_model=BacktestList, dependencies=[Depends(_trading_view)])
async def list_research_backtests(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    query: str | None = Query(None, max_length=200),
) -> BacktestList:
    return await _list(request, "backtests", BacktestContract, limit=limit, offset=offset, query=query)


@router.get("/news", response_model=NewsList, dependencies=[Depends(_trading_view)])
async def list_research_news(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    query: str | None = Query(None, max_length=200),
) -> NewsList:
    return await _list(request, "news", NewsContract, limit=limit, offset=offset, query=query)


@router.get("/artifacts", response_model=ArtifactList, dependencies=[Depends(_trading_view)])
async def list_research_artifacts(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    query: str | None = Query(None, max_length=200),
) -> ArtifactList:
    return await _list(request, "artifacts", ArtifactContract, limit=limit, offset=offset, query=query)


@router.get("/datasets/{dataset_id}", response_model=ResearchItem[DatasetContract], dependencies=[Depends(_trading_view)])
async def get_dataset(request: Request, dataset_id: str) -> ResearchItem[DatasetContract]:
    return await _item(request, "datasets", dataset_id, DatasetContract)


@router.get("/import-jobs/{import_job_id}", response_model=ResearchItem[ImportJobContract], dependencies=[Depends(_trading_view)])
async def get_import_job(request: Request, import_job_id: str) -> ResearchItem[ImportJobContract]:
    return await _item(request, "import_jobs", import_job_id, ImportJobContract)


@router.get("/quality-runs/{quality_run_id}", response_model=ResearchItem[QualityRunContract], dependencies=[Depends(_trading_view)])
async def get_quality_run(request: Request, quality_run_id: str) -> ResearchItem[QualityRunContract]:
    return await _item(request, "quality_runs", quality_run_id, QualityRunContract)


@router.get("/strategies/{strategy_id}", response_model=ResearchItem[StrategyContract], dependencies=[Depends(_trading_view)])
async def get_research_strategy(request: Request, strategy_id: str) -> ResearchItem[StrategyContract]:
    return await _item(request, "strategies", strategy_id, StrategyContract)


@router.get("/backtests/{backtest_id}", response_model=ResearchItem[BacktestContract], dependencies=[Depends(_trading_view)])
async def get_research_backtest(request: Request, backtest_id: str) -> ResearchItem[BacktestContract]:
    return await _item(request, "backtests", backtest_id, BacktestContract)


@router.get("/news/{news_id}", response_model=ResearchItem[NewsContract], dependencies=[Depends(_trading_view)])
async def get_research_news(request: Request, news_id: str) -> ResearchItem[NewsContract]:
    return await _item(request, "news", news_id, NewsContract)


@router.get("/artifacts/{artifact_id}", response_model=ResearchItem[ArtifactContract], dependencies=[Depends(_trading_view)])
async def get_research_artifact(request: Request, artifact_id: str) -> ResearchItem[ArtifactContract]:
    return await _item(request, "artifacts", artifact_id, ArtifactContract)


__all__ = ["ResearchBackend", "router"]
