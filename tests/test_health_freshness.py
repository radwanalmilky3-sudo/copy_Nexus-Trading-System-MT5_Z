from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services.nexus_api import main as api_main


@pytest.mark.asyncio
async def test_health_reflects_data_service_outage_after_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_main.redis, "health_check", AsyncMock(return_value=True))
    monkeypatch.setattr(api_main.data_service, "health", AsyncMock(side_effect=[True, False]))
    monkeypatch.setattr(api_main.app.state, "data_service_available", True, raising=False)

    initial = await api_main.health_check()
    after_outage = await api_main.health_check()

    assert initial["duckdb"] == "connected"
    assert after_outage["duckdb"] == "unavailable"
    assert after_outage["status"] == "degraded"
