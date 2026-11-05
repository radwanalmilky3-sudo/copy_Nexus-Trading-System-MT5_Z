"""Boot-race retry tests for FundamentalRuntime._post_data (T-012 companion fix).

On 2026-11-06 a fast fleet restart raced nexus-news against nexus-data:
the first bootstrap persist hit "All connection attempts failed" while
:9001 was still binding, news raised RuntimeError and run.py tore the
whole fleet down. The fix: connection errors retry a bounded 5 times
(2s apart); HTTP >=400 rejections stay fail-fast.

These tests use ``object.__new__`` to build a bare runtime (no redis,
no fetchers, no lifespan) and drive ``_post_data`` against fake httpx
clients.
"""
from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from services.nexus_news.fundamental.runtime import FundamentalRuntime


class FakeResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class FlakyClient:
    """post() raises ConnectError for the first `failures` calls, then 200s."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def post(self, url: str, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise httpx.ConnectError("All connection attempts failed")
        return FakeResponse(200)


class Always400Client:
    def __init__(self) -> None:
        self.calls = 0

    async def post(self, url: str, **kwargs):
        self.calls += 1
        return FakeResponse(422, text="validation error")


def make_runtime(client) -> FundamentalRuntime:
    rt = object.__new__(FundamentalRuntime)
    rt._client = client
    rt.internal_secret = "test-secret"
    rt.data_url = "http://127.0.0.1:9001"
    return rt


@pytest.mark.parametrize("failures", [0, 1, 3, 4])
def test_connection_errors_retry_then_succeed(failures):
    """Bounded retry bridges the boot race: up to 4 failed connects recover."""
    client = FlakyClient(failures)
    rt = make_runtime(client)
    started = time.monotonic()
    ok = asyncio.run(rt._post_data("/api/data/fundamental/record", {"a": 1}))
    elapsed = time.monotonic() - started
    assert ok is True
    assert client.calls == failures + 1
    # each retried connect costs one 2s backoff; succeed-on-first-call is instant
    assert elapsed >= failures * 2.0 - 0.1
    assert elapsed < failures * 2.0 + 5.0


def test_http_4xx_not_retried():
    """Real rejections fail fast — no retry, single call, False."""
    client = Always400Client()
    rt = make_runtime(client)
    started = time.monotonic()
    ok = asyncio.run(rt._post_data("/api/data/fundamental/record", {"a": 1}))
    elapsed = time.monotonic() - started
    assert ok is False
    assert client.calls == 1
    assert elapsed < 1.0


def test_persistent_connect_failure_returns_false():
    """Data genuinely down: 5 attempts, ~8s of backoff, graceful False."""
    client = FlakyClient(999)
    rt = make_runtime(client)
    started = time.monotonic()
    ok = asyncio.run(rt._post_data("/api/data/fundamental/record", {"a": 1}))
    elapsed = time.monotonic() - started
    assert ok is False
    assert client.calls == 5
    assert 8.0 <= elapsed < 8.0 + 5.0


def test_missing_secret_disables_persistence():
    rt = object.__new__(FundamentalRuntime)
    rt._client = FlakyClient(0)
    rt.internal_secret = ""
    rt.data_url = "http://127.0.0.1:9001"
    ok = asyncio.run(rt._post_data("/api/data/fundamental/record", {"a": 1}))
    assert ok is False
