from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_unconfigured_calendar_is_explicit_in_health(monkeypatch):
    from services.nexus_data import main
    monkeypatch.setattr(main.redis_client,'health_check',AsyncMock(return_value=True))
    result=await main.health_check()
    assert result['quality_automation']['calendar']['state'] == 'not_configured'
    assert 'path' not in result['quality_automation']['calendar']
