import pytest

from services.nexus_api.data_client import DataServiceUnavailable


@pytest.mark.asyncio
async def test_default_backend_projects_reference_catalog_as_unvalidated():
    from services.nexus_api.research_backend import NexusResearchBackend
    result = await NexusResearchBackend(None).list_research('strategies', limit=1, offset=0)
    assert result['status'] == 'available'
    assert result['total'] == 6
    assert result['items'][0]['status'] == 'draft'
    assert len(result['items']) == 1


@pytest.mark.asyncio
async def test_gateway_preserves_source_outage_and_does_not_claim_empty_success():
    from services.nexus_api.research_backend import NexusResearchBackend
    class Offline:
        async def query(self, operation, params):
            raise DataServiceUnavailable('offline')
    result = await NexusResearchBackend(Offline()).list_research('datasets', limit=50, offset=0)
    assert result['status'] == 'unavailable'
    assert result['source'] == 'nexus-data:ohlcv'


@pytest.mark.asyncio
async def test_item_missing_or_unavailable_does_not_validate_none():
    from fastapi import FastAPI
    from starlette.requests import Request
    from services.nexus_api.routers.research_lab import _item
    from shared.research_api_models import DatasetContract
    class Backend:
        async def get_research(self, resource, item_id):
            return {'status': 'unavailable', 'source': 'nexus-data:ohlcv', 'item': None}
    app = FastAPI()
    app.state.research_backend = Backend()
    result = await _item(Request({'type': 'http', 'app': app}), 'datasets', 'missing', DatasetContract)
    assert result.status == 'unavailable' and result.item is None


@pytest.mark.asyncio
async def test_detail_uses_exact_owner_lookup_not_first_page_of_substring_matches():
    from services.nexus_api.research_backend import NexusResearchBackend
    class Owner:
        async def query(self, operation, params):
            if operation == 'research_item' and params == {'resource': 'quality_runs', 'item_id': 'run-1'}:
                return [dict(status='available', source='nexus-data:quality_runs', items=[dict(quality_run_id='run-1')], total=1)]
            return [dict(status='available', source='nexus-data:quality_runs', items=[dict(quality_run_id=f'other-{i}') for i in range(100)], total=101)]
    result = await NexusResearchBackend(Owner()).get_research('quality_runs', 'run-1')
    assert result['item']['quality_run_id'] == 'run-1'
