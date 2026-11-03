from datetime import datetime, timezone

import pytest

from services.nexus_data.duckdb_store import DataStore
from services.nexus_data.fundamental_store import FundamentalStore
from shared.models import OHLCV


@pytest.mark.asyncio
async def test_research_datasets_expose_persisted_series_and_hash(tmp_path):
    store = DataStore(str(tmp_path / 'research.duckdb'))
    await store.init_tables()
    try:
        await store.insert_ohlcv_batch([
            OHLCV(symbol='XAUUSD', timeframe='M5', open=10, high=12,
                  low=9, close=11, volume=5,
                  timestamp=datetime(2026, 10, 18, 10, tzinfo=timezone.utc)),
        ], source='mt5_backfill')
        result, = await FundamentalStore(store).query_named('research_collection', {
            'resource': 'datasets', 'limit': 50, 'offset': 0, 'query': None,
        })
        assert result['status'] == 'available'
        assert result['total'] == 1
        item, = result['items']
        assert item['dataset_id'] == 'ohlcv:XAUUSD:M5:mt5_backfill'
        assert item['source'] == 'mt5_backfill'
        assert item['row_count'] == 1
        assert len(item['content_hash']) == 64
        assert item['updated_at'] is not None
        missing, = await FundamentalStore(store).query_named('research_collection', {
            'resource': 'datasets', 'limit': 1, 'offset': 0, 'query': 'EURUSD',
        })
        assert missing['status'] == 'available'
        assert missing['items'] == [] and missing['total'] == 0
        page, = await FundamentalStore(store).query_named('research_collection', {
            'resource': 'datasets', 'limit': 1, 'offset': 1, 'query': None,
        })
        assert page['items'] == [] and page['total'] == 1
        by_id, = await FundamentalStore(store).query_named('research_collection', {
            'resource': 'datasets', 'limit': 50, 'offset': 0, 'query': 'ohlcv:XAUUSD:M5:mt5_backfill',
        })
        assert by_id['total'] == 1
        # A combined series fingerprint must not be attributed to one provider.
        await store.insert_ohlcv_batch([
            OHLCV(symbol='XAUUSD', timeframe='M5', open=10, high=12, low=9,
                  close=11, volume=5, timestamp=datetime(2026, 10, 18, 10, 5, tzinfo=timezone.utc)),
        ], source='external-test')
        mixed, = await FundamentalStore(store).query_named('research_collection', {
            'resource': 'datasets', 'limit': 50, 'offset': 0, 'query': None,
        })
        assert len(mixed['items']) == 2
        assert all(item['content_hash'] is None for item in mixed['items'])
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_missing_research_table_is_unavailable_not_empty(tmp_path):
    store = DataStore(str(tmp_path / 'missing.duckdb'))
    await store.init_tables()
    try:
        result, = await FundamentalStore(store).query_named('research_collection', {
            'resource': 'quality_runs', 'limit': 50, 'offset': 0, 'query': None,
        })
        assert result['status'] == 'unavailable'
        assert result['items'] == []
        # Do not create schemas or seed successes during a read.
        assert await store._fetch("SELECT table_name FROM information_schema.tables WHERE table_name='quality_runs'") == []
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_registered_empty_quality_table_is_available_and_reads_real_runs(tmp_path):
    store = DataStore(str(tmp_path / 'quality.duckdb'))
    await store.init_tables()
    try:
        from pathlib import Path
        await store._run_script(Path('services/nexus_data/migrations/research_lineage_001.sql').read_text())
        params = dict(resource='quality_runs', limit=50, offset=0, query=None)
        result, = await FundamentalStore(store).query_named('research_collection', params)
        assert result['status'] == 'available' and result['total'] == 0
        await store._run("INSERT INTO datasets(dataset_id,dataset_name) VALUES ('d1','Gold')")
        await store._run("INSERT INTO quality_runs(quality_run_id,dataset_id,contract_version,status,score,checks_total,checks_passed,checks_failed) VALUES ('q1','d1','1','failed',0.5,2,1,1)")
        result, = await FundamentalStore(store).query_named('research_collection', params)
        item, = result['items']
        assert item['quality_run_id'] == 'q1'
        assert item['status'] == 'failed' and item['score'] == 0.5
        assert item['checks']['all_checks_passed'] is False
        await store._run("INSERT INTO quality_runs(quality_run_id,dataset_id,contract_version,status,score,checks_total,checks_passed) VALUES ('q2','d1','1','passed',1.0,1,1)")
        exact, = await FundamentalStore(store).query_named('research_item', {'resource': 'quality_runs', 'item_id': 'q2'})
        assert len(exact['items']) == 1
        assert exact['items'][0]['checks']['all_checks_passed'] is True
    finally:
        await store.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [dict(resource='app_users'), dict(limit=0), dict(limit=101), dict(offset=-1), dict(query=123)])
async def test_research_reader_rejects_unbounded_or_unknown_inputs(changes):
    params = dict(resource='datasets', limit=50, offset=0, query=None)
    params.update(changes)
    with pytest.raises(ValueError):
        await FundamentalStore(None).query_named('research_collection', params)


@pytest.mark.asyncio
async def test_import_artifact_and_news_projections_satisfy_public_contracts(tmp_path):
    from pathlib import Path
    from shared.research_api_models import ArtifactContract, ImportJobContract, NewsContract
    store = DataStore(str(tmp_path / 'projections.duckdb'))
    await store.init_tables()
    fundamental = FundamentalStore(store)
    try:
        await fundamental.init_schema()
        await store._run_script(Path('services/nexus_data/migrations/research_lineage_001.sql').read_text())
        await store._run("INSERT INTO datasets(dataset_id,dataset_name) VALUES ('d1','Gold')")
        await store._run("INSERT INTO import_jobs(import_job_id,dataset_id,source_uri,status,rows_loaded) VALUES ('i1','d1','mt5','complete',42)")
        await store._run("INSERT INTO research_artifacts(artifact_id,artifact_type,artifact_name,content_checksum,status) VALUES ('a1','report','Quality report','abc','available')")
        await fundamental.upsert_source(dict(source_id='official', name_ar='مصدر', name_en='Official', category='macro', transport='rss'))
        await fundamental.insert_record('news_articles', dict(article_id='n1', source_id='official', headline='Release', received_at=datetime.now(timezone.utc)))
        for resource, model, expected_id, field in [
            ('import_jobs', ImportJobContract, 'i1', 'import_job_id'),
            ('artifacts', ArtifactContract, 'a1', 'artifact_id'),
            ('news', NewsContract, 'n1', 'news_id'),
        ]:
            result, = await fundamental.query_named('research_collection', dict(resource=resource, limit=50, offset=0, query=None))
            row, = result['items']
            parsed = model.model_validate(row)
            assert getattr(parsed, field) == expected_id
        assert row.get('sentiment') is None
    finally:
        await store.aclose()
