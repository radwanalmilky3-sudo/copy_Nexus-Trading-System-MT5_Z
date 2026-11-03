"""Read-only projections of owner-held evidence; never fetch or manufacture data."""
from __future__ import annotations

import json
from typing import Any


class ResearchReader:
    RESOURCES = frozenset({'datasets', 'import_jobs', 'quality_runs', 'news', 'artifacts'})
    TABLES = {'datasets': 'ohlcv', 'import_jobs': 'import_jobs',
              'quality_runs': 'quality_runs', 'news': 'news_articles',
              'artifacts': 'research_artifacts'}
    SEARCH = {'import_jobs': ('import_job_id', 'dataset_id'),
              'quality_runs': ('quality_run_id', 'dataset_id'),
              'news': ('article_id', 'headline', 'source_id'),
              'artifacts': ('artifact_id', 'artifact_name', 'artifact_type')}
    ORDER = {'import_jobs': 'created_at', 'quality_runs': 'started_at',
             'news': 'received_at', 'artifacts': 'created_at'}
    IDS = {'import_jobs': 'import_job_id', 'quality_runs': 'quality_run_id',
           'news': 'article_id', 'artifacts': 'artifact_id'}

    def __init__(self, store: Any):
        self.store = store

    async def collection(self, resource: str, limit: int, offset: int, query: str | None, *, item_id: str | None = None) -> dict:
        if resource not in self.RESOURCES:
            raise ValueError('unsupported research resource')
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('limit must be between 1 and 100')
        if type(offset) is not int or offset < 0:
            raise ValueError('offset must be non-negative')
        if query is not None and (not isinstance(query, str) or len(query) > 200):
            raise ValueError('query must be a short string')
        if item_id is not None and (not isinstance(item_id, str) or not item_id or len(item_id) > 512):
            raise ValueError('item_id must be a short nonempty string')
        table = self.TABLES[resource]
        result = dict(status='available', source=f'nexus-data:{table}', items=[], total=0,
                      limit=limit, offset=offset)
        exists = await self.store._fetch(
            "SELECT 1 FROM information_schema.tables WHERE table_schema='main' AND table_name=?", (table,))
        if not exists:
            return {**result, 'status': 'unavailable'}
        if resource == 'datasets':
            return await self._datasets(result, limit, offset, query, item_id)

        # Identifiers come only from the fixed maps above; values stay parameterized.
        conditions = ''
        values: tuple = ()
        if item_id is not None:
            conditions = f' WHERE {self.IDS[resource]}=?'
            values = (item_id,)
        elif query:
            conditions = ' WHERE ' + ' OR '.join(f'contains(lower({c}), lower(?))' for c in self.SEARCH[resource])
            values = (query,) * len(self.SEARCH[resource])
        count = await self.store._fetch(f'SELECT COUNT(*) FROM {table}{conditions}', values)
        rows, columns = await self.store._fetch_with_columns(
            f'SELECT * FROM {table}{conditions} ORDER BY {self.ORDER[resource]} DESC LIMIT ? OFFSET ?',
            (*values, limit, offset))
        result['total'] = count[0][0]
        result['items'] = [self._project(resource, dict(zip(columns, row))) for row in rows]
        return result

    async def _datasets(self, result: dict, limit: int, offset: int, query: str | None, item_id: str | None) -> dict:
        where = (" WHERE contains(lower(symbol || '/' || timeframe || '/' || source), lower(?))"
                 " OR contains(lower('ohlcv:' || symbol || ':' || timeframe || ':' || source), lower(?))") if query else ''
        values = (query, query) if query else ()
        if item_id is not None:
            where = " WHERE ('ohlcv:' || symbol || ':' || timeframe || ':' || source)=?"
            values = (item_id,)
        base = (
            'SELECT symbol,timeframe,source,COUNT(*) AS row_count,MIN(timestamp) AS first_bar,'
            'MAX(timestamp) AS last_bar,MAX(fetched_at) AS fetched_at FROM ohlcv'
            + where + ' GROUP BY symbol,timeframe,source'
        )
        count = await self.store._fetch(f'SELECT COUNT(*) FROM ({base})', values)
        rows, columns = await self.store._fetch_with_columns(
            f'SELECT * FROM ({base}) ORDER BY symbol,timeframe,source LIMIT ? OFFSET ?', (*values, limit, offset))
        items = []
        for row in rows:
            item = dict(zip(columns, row))
            from .quality.stored_audit import latest_quality
            quality_summary = await latest_quality(self.store, item['symbol'], item['timeframe'], item['source'])
            # The manifest hashes the whole symbol/timeframe, not one provider.
            # Expose it only when this group is the entire manifest's row set.
            hashes = await self.store._fetch(
                'SELECT content_hash FROM ohlcv_manifests WHERE symbol=? AND timeframe=? AND row_count=? '
                'AND row_count=(SELECT COUNT(*) FROM ohlcv WHERE symbol=? AND timeframe=?)',
                (item['symbol'], item['timeframe'], item['row_count'], item['symbol'], item['timeframe']))
            items.append(dict(
                dataset_id=f"ohlcv:{item['symbol']}:{item['timeframe']}:{item['source']}",
                name=f"{item['symbol']}/{item['timeframe']}", source=item['source'],
                description=f"Stored bars: {item['first_bar']} → {item['last_bar']}; not a coverage or freshness certification",
                status='stored', row_count=item['row_count'],
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'],
                content_hash=hashes[0][0] if hashes else None,
                created_at=item['first_bar'], updated_at=item['last_bar'],
                quality_summary=quality_summary,
            ))
        return {**result, 'items': items, 'total': count[0][0]}

    @staticmethod
    def _project(resource: str, row: dict) -> dict:
        if resource == 'import_jobs':
            return dict(import_job_id=row['import_job_id'], dataset_id=row['dataset_id'],
                        status=row['status'], source=row['source_uri'], started_at=row['started_at'],
                        completed_at=row['finished_at'], rows_imported=row['rows_loaded'], error=row['error_message'])
        if resource == 'quality_runs':
            try:
                summary = json.loads(row.get('summary_json') or '{}')
            except (TypeError, ValueError):
                summary = {}
            if isinstance(summary, dict) and summary.get('scope') == 'stored_ohlcv_basic_v1':
                return dict(quality_run_id=row['quality_run_id'], dataset_id=row['dataset_id'], status=row['status'],
                            score=row['score'], checks=summary['checks'], issues=summary['issues'], warnings=summary['warnings'],
                            content_hash=summary['content_hash'], rows_checked=summary['rows_checked'], scope=summary['scope'],
                            started_at=row['started_at'], completed_at=row['finished_at'])
            finished = row['finished_at'] is not None or row['status'] in {'complete', 'completed', 'failed', 'passed', 'warning'}
            checks = ({'all_checks_passed': row['checks_failed'] == 0 and row['checks_passed'] == row['checks_total']}
                      if finished and row['checks_total'] > 0 else {})
            return dict(quality_run_id=row['quality_run_id'], dataset_id=row['dataset_id'],
                        status=row['status'], score=row['score'], checks=checks,
                        started_at=row['started_at'], completed_at=row['finished_at'],
                        issues=[f"{row['checks_failed']} failed checks"] if row['checks_failed'] else [])
        if resource == 'news':
            return dict(news_id=row['article_id'], headline=row['headline'], source=row['source_id'],
                        published_at=row['published_at'], url=row['url'])
        if resource == 'artifacts':
            try:
                metadata = json.loads(row['metadata_json'] or '{}')
            except (TypeError, ValueError):
                metadata = {}
            return dict(artifact_id=row['artifact_id'], name=row['artifact_name'],
                        artifact_type=row['artifact_type'], status=row['status'],
                        content_hash=row['content_checksum'], created_at=row['created_at'],
                        metadata={**(metadata if isinstance(metadata, dict) else {}), 'version': row['version']})
        raise ValueError('unsupported resource')
