"""Gateway adapter: all durable reads stay behind the nexus-data boundary."""
from __future__ import annotations

from typing import Any

from services.nexus_strategy.catalog import REFERENCE_STRATEGIES
from .data_client import DataServiceClient, DataServiceRejected, DataServiceUnavailable


class NexusResearchBackend:
    SOURCES = {'datasets': 'ohlcv', 'import_jobs': 'import_jobs', 'quality_runs': 'quality_runs',
               'news': 'news_articles', 'artifacts': 'research_artifacts'}

    def __init__(self, data_service: DataServiceClient):
        self.data_service = data_service

    async def list_research(self, resource: str, *, limit: int, offset: int, query: str | None = None) -> dict[str, Any]:
        if resource == 'strategies':
            items = [dict(strategy_id=s.strategy_id, name=s.display_name, description=s.description,
                          version=s.version, status='draft', tags=[str(s.family)])
                     for s in REFERENCE_STRATEGIES]
            if query:
                items = [s for s in items if query.casefold() in (s['strategy_id'] + s['name']).casefold()]
            return dict(status='available', source='nexus-strategy:reference-catalog',
                        items=items[offset:offset + limit], total=len(items))
        source = f"nexus-data:{self.SOURCES.get(resource, resource)}"
        unavailable = dict(status='unavailable', source=source, items=[], total=0)
        if resource not in self.SOURCES:
            # There is no durable research-run backend attached for this resource.
            return unavailable
        try:
            rows = await self.data_service.query('research_collection', dict(
                resource=resource, limit=limit, offset=offset, query=query))
        except (DataServiceUnavailable, DataServiceRejected):
            return unavailable
        if len(rows) != 1 or rows[0].get('status') not in {'available', 'degraded', 'unavailable'} or not isinstance(rows[0].get('items'), list):
            return {**unavailable, 'status': 'degraded'}
        return rows[0]

    async def get_research(self, resource: str, item_id: str) -> dict:
        if resource in self.SOURCES:
            try:
                rows = await self.data_service.query('research_item', dict(resource=resource, item_id=item_id))
            except (DataServiceUnavailable, DataServiceRejected):
                return dict(status='unavailable', source=f'nexus-data:{self.SOURCES[resource]}', item=None)
            if len(rows) != 1 or not isinstance(rows[0].get('items'), list):
                return dict(status='degraded', source=f'nexus-data:{self.SOURCES[resource]}', item=None)
            result = rows[0]
        else:
            result = await self.list_research(resource, limit=100, offset=0, query=item_id)
        key = {'datasets': 'dataset_id', 'import_jobs': 'import_job_id', 'quality_runs': 'quality_run_id',
               'strategies': 'strategy_id', 'backtests': 'backtest_id', 'news': 'news_id',
               'artifacts': 'artifact_id'}.get(resource)
        item = next((row for row in result['items'] if row.get(key) == item_id), None)
        return dict(status=result['status'], source=result['source'], item=item)
