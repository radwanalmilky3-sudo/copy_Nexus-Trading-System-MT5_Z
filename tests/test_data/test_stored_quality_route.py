import pytest
import httpx


@pytest.mark.asyncio
async def test_quality_run_requires_internal_credential_before_any_write(monkeypatch):
    from services.nexus_data.main import app
    monkeypatch.setenv('NEXUS_INTERNAL_API_SECRET', 'test-only-secret')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/api/data/research/quality', json={'symbol': 'XAUUSD', 'timeframe': 'M5', 'source': 'mt5_poll'})
    assert response.status_code == 403
