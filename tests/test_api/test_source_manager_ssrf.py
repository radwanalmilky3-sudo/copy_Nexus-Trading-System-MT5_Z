from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.nexus_api.routers import fundamental


class _SourceStore:
    def get_secret(self, source_id, secret_env=None):
        return None


@pytest.mark.asyncio
async def test_source_connection_test_blocks_loopback_before_network_request(monkeypatch):
    request = AsyncMock(return_value=SimpleNamespace(
        is_success=True,
        status_code=200,
        content=b"{}",
        headers={"content-type": "application/json"},
        json=lambda: {},
    ))

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, *args, **kwargs):
            return await request(*args, **kwargs)

    monkeypatch.setattr(fundamental._httpx, "AsyncClient", FakeClient)

    result = await fundamental._connection_test(
        {
            "source_id": "custom_feed",
            "enabled": True,
            "endpoint": "http://127.0.0.1:8080/admin",
            "auth_mode": "none",
            "transport": "json",
        },
        _SourceStore(),
    )

    assert result["ok"] is False
    assert result["state"] == "invalid_config"
    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_source_connection_test_blocks_dns_names_resolving_to_private_addresses(monkeypatch):
    request = AsyncMock()
    monkeypatch.setattr(
        fundamental._socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("10.20.30.40", 80))],
    )

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, *args, **kwargs):
            return await request(*args, **kwargs)

    monkeypatch.setattr(fundamental._httpx, "AsyncClient", FakeClient)
    result = await fundamental._connection_test(
        {
            "source_id": "custom_feed",
            "enabled": True,
            "endpoint": "https://feed.example/data",
            "auth_mode": "none",
            "transport": "json",
        },
        _SourceStore(),
    )

    assert result["state"] == "invalid_config"
    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_source_connection_test_does_not_follow_redirects(monkeypatch):
    monkeypatch.setattr(
        fundamental._socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("8.8.8.8", 443))],
    )
    client_options = {}
    request = AsyncMock(return_value=SimpleNamespace(
        is_success=False,
        status_code=302,
        content=b"redirect",
        headers={"content-type": "text/plain"},
        json=lambda: {},
    ))

    class FakeClient:
        def __init__(self, **kwargs):
            client_options.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, *args, **kwargs):
            return await request(*args, **kwargs)

    monkeypatch.setattr(fundamental._httpx, "AsyncClient", FakeClient)
    result = await fundamental._connection_test(
        {
            "source_id": "custom_feed",
            "enabled": True,
            "endpoint": "https://feed.example/data",
            "auth_mode": "none",
            "transport": "json",
        },
        _SourceStore(),
    )

    assert result["ok"] is False
    assert client_options["follow_redirects"] is False
    request.assert_awaited_once()


@pytest.mark.asyncio
async def test_source_connection_test_does_not_echo_exception_or_query_secret(monkeypatch):
    secret = "credential-must-not-leak"

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, *args, **kwargs):
            raise RuntimeError(f"request failed for https://feed.example?api_key={secret}")

    monkeypatch.setattr(fundamental._socket, "getaddrinfo", lambda *a, **k: [
        (None, None, None, None, ("8.8.8.8", 443))
    ])
    monkeypatch.setattr(fundamental._httpx, "AsyncClient", FakeClient)

    result = await fundamental._connection_test(
        {
            "source_id": "custom_feed",
            "enabled": True,
            "endpoint": "https://feed.example/data",
            "auth_mode": "query",
            "secret_name": "api_key",
            "transport": "json",
        },
        type("Store", (), {"get_secret": lambda *a, **k: secret})(),
    )

    assert result["ok"] is False
    assert secret not in str(result)

