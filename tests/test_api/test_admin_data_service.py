from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from services.nexus_api.data_client import DataServiceUnavailable
from services.nexus_api.deps import get_data_service
from services.nexus_api.main import app


@pytest.mark.asyncio
async def test_login_reports_data_service_outage_as_503_not_invalid_credentials():
    class OfflineDataService:
        async def query(self, operation: str, params=None):
            raise DataServiceUnavailable("nexus-data is unreachable")

    previous = app.dependency_overrides.get(get_data_service)
    app.dependency_overrides[get_data_service] = lambda: OfflineDataService()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v2/auth/login",
                json={"username": "ridwan", "password": "not-a-real-password"},
            )
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_data_service, None)
        else:
            app.dependency_overrides[get_data_service] = previous

    assert response.status_code == 503
    # D10-a contract: detail is surfaced but must never read as bad-credentials.
    assert "Invalid credentials" not in response.json()["detail"]
