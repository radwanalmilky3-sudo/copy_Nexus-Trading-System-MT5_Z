from __future__ import annotations

import httpx
import pytest
import ssl

from shared import http_client  # Initialize the shared SSL context before spying.

from services.nexus_api.data_client import DataServiceClient, DataServiceUnavailable


@pytest.mark.asyncio
async def test_named_query_posts_operation_and_internal_secret():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["secret"] = request.headers.get("X-Nexus-Internal-Secret")
        seen["json"] = request.read().decode()
        return httpx.Response(200, json={"rows": [{"user_id": "u1"}]})

    client = DataServiceClient(base_url="http://nexus-data", secret="internal", transport=httpx.MockTransport(handler))
    assert await client.query("user_by_id", {"user_id": "u1"}) == [{"user_id": "u1"}]
    assert seen["path"] == "/api/data/query"
    assert seen["secret"] == "internal"
    assert '"operation":"user_by_id"' in str(seen["json"])


@pytest.mark.asyncio
async def test_query_reports_data_service_server_failure_as_unavailable():
    transport = httpx.MockTransport(lambda request: httpx.Response(500))
    client = DataServiceClient(base_url="http://nexus-data", secret="internal", transport=transport)

    with pytest.raises(DataServiceUnavailable):
        await client.query("user_by_id", {"user_id": "u1"})


@pytest.mark.asyncio
async def test_query_fails_closed_when_internal_secret_is_missing():
    client = DataServiceClient(base_url="http://nexus-data", secret="", transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"rows": []})))

    with pytest.raises(DataServiceUnavailable):
        await client.query("user_by_id", {"user_id": "u1"})


@pytest.mark.asyncio
async def test_repeated_queries_and_health_reuse_ssl_context(monkeypatch):
    seen = []

    def unexpected_ssl_creation(*args, **kwargs):
        pytest.fail("each request must reuse the shared SSL context")

    async def respond(transport, request):
        seen.append(request)
        if request.url.path == "/health":
            return httpx.Response(200, json={"ready": True, "duckdb": True})
        return httpx.Response(200, json={"rows": [{"user_id": "u1"}]})

    # Keep real HTTPX client/transport construction; intercept only network I/O.
    monkeypatch.setattr(ssl, "create_default_context", unexpected_ssl_creation)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", respond)
    client = DataServiceClient(base_url="http://127.0.0.1:9001", secret="internal")

    for _ in range(2):
        assert await client.query("user_by_id", {"user_id": "u1"}) == [{"user_id": "u1"}]
        assert await client.health() is True

    assert [r.url.path for r in seen] == ["/api/data/query", "/health"] * 2
    for request in seen:
        timeout = 2.0 if request.url.path == "/health" else 10.0
        assert request.extensions["timeout"] == {
            "connect": timeout, "read": timeout, "write": timeout, "pool": timeout,
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("ready,duckdb,expected", [(True, True, True), (False, True, False), (True, False, False)])
async def test_health_preserves_injected_transport_and_readiness(ready, duckdb, expected):
    def handler(request):
        assert request.url.path == "/health"
        return httpx.Response(200, json={"ready": ready, "duckdb": duckdb})

    client = DataServiceClient(
        base_url="http://data.test", secret="internal", transport=httpx.MockTransport(handler),
    )
    assert await client.health() is expected
