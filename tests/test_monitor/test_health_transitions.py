from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from services.nexus_monitor import main as monitor


@pytest.mark.asyncio
async def test_outage_alerts_once_and_alerts_again_after_recovery(monkeypatch):
    monkeypatch.setattr(monitor, "_SERVICES_TO_CHECK", [("test-service", 9001)])
    monkeypatch.setattr(monitor, "_service_statuses", {})
    monkeypatch.setattr(monitor, "redis", SimpleNamespace(cache_set=AsyncMock()))
    monkeypatch.setattr(monitor, "metrics", SimpleNamespace(update_service_metrics=Mock()))
    alert = AsyncMock()
    monkeypatch.setattr(monitor, "telegram", SimpleNamespace(alert_error=alert))
    probe = AsyncMock(side_effect=[
        {"status": "unhealthy", "error": "offline"},
        {"status": "unhealthy", "error": "offline"},
        {"status": "healthy"},
        {"status": "unhealthy", "error": "offline again"},
    ])
    monkeypatch.setattr(monitor, "_check_service", probe)

    await monitor._check_all_services()
    alert.assert_awaited_once_with("test-service", "offline")
    await monitor._check_all_services()
    assert alert.await_count == 1
    await monitor._check_all_services()
    await monitor._check_all_services()
    assert alert.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, [], {"status": "unknown"}])
async def test_http_200_without_valid_health_state_is_not_healthy(monkeypatch, payload):
    response = SimpleNamespace(status_code=200, json=lambda: payload)
    monkeypatch.setattr(monitor, "_http_client", SimpleNamespace(get=AsyncMock(return_value=response)))

    result = await monitor._check_service("test-service", 9001)

    assert result["status"] == "unhealthy"
