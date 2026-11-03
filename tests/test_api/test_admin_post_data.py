from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import FastAPI

from services.nexus_api.data_client import DataServiceUnavailable
from services.nexus_api.main import data_service_unavailable_handler
from services.nexus_api.routers import admin


@pytest.fixture
def mocked_data_http(monkeypatch):
    original_client = httpx.AsyncClient
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-only-internal-secret")
    monkeypatch.setenv("NEXUS_DATA_URL", "http://data.test")

    def install(handler):
        def client_factory(**kwargs):
            kwargs.setdefault("transport", httpx.MockTransport(handler))
            return original_client(**kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", client_factory)

    return install


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        301, 302, 307, 400, 401, 403, 408, 429, 500, 503,
        httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError,
        httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout,
    ],
)
async def test_post_data_failure_uses_generic_503(mocked_data_http, failure):
    def upstream(request):
        if isinstance(failure, int):
            return httpx.Response(
                failure,
                text="private upstream body: test-only-internal-secret",
                headers={"Location": "http://must-not-follow.test"},
            )
        raise failure("private transport diagnostics", request=request)

    mocked_data_http(upstream)
    app = FastAPI()
    app.add_exception_handler(DataServiceUnavailable, data_service_unavailable_handler)

    @app.post("/write")
    async def write():
        await admin._post_data("app_users", {"user_id": "test-user"})
        return {"ok": True}

    # ASGITransport does not run lifespan or start services/database connections.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://gateway.test",
    ) as client:
        response = await client.post("/write")

    assert response.status_code == 503
    assert response.json() == {"detail": "Data service unavailable"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 201, 204, 299])
async def test_post_data_accepts_2xx_and_preserves_request(mocked_data_http, status):
    requests = []

    def upstream(request):
        requests.append(request)
        return httpx.Response(status)

    mocked_data_http(upstream)
    result = await admin._post_data(
        "app_users",
        {"user_id": "test-user", "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc)},
    )

    assert result is None
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "http://data.test/api/data/fundamental/record"
    assert request.headers["X-Nexus-Internal-Secret"] == "test-only-internal-secret"
    assert json.loads(request.content) == {
        "table": "app_users",
        "record": {"user_id": "test-user", "updated_at": "2026-01-01 00:00:00+00:00"},
    }
    assert request.extensions["timeout"] == {
        "connect": 10.0, "read": 10.0, "write": 10.0, "pool": 10.0,
    }
