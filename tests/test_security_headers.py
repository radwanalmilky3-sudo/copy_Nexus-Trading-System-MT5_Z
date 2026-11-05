"""Security response headers tests (T-012, 2026-11-06).

Pins the T-012 contract on two levels:

* Unit level — a minimal FastAPI app wrapped with
  ``shared.security_headers.SecurityHeadersMiddleware``: the five
  hardening headers plus the ``Cache-Control: no-store`` default are
  injected, handler-set ``Cache-Control`` and handler-set security
  headers are respected (never duplicated/overridden), and non-HTTP
  scopes pass through untouched.
* Integration level — the real ``services.nexus_api.main`` app (the
  internet-facing gateway) serves the same set on an unauthenticated
  route, proving the wiring survives the full middleware stack
  (CORS outermost, security headers innermost).
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from services.nexus_api.main import app as gateway_app
from shared.security_headers import (
    DEFAULT_CACHE_CONTROL,
    SECURITY_HEADERS,
    SecurityHeadersMiddleware,
)

EXPECTED_NAMES = {name for name, _ in SECURITY_HEADERS} | {"cache-control"}


def make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/plain")
    async def plain() -> dict:
        return {"ok": True}

    @app.get("/cached")
    async def cached(response: Response) -> dict:
        response.headers["Cache-Control"] = "max-age=60"
        return {"ok": True}

    @app.get("/custom-csp")
    async def custom_csp(response: Response) -> dict:
        response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
        return {"ok": True}

    return app


def test_all_hardening_headers_injected() -> None:
    client = TestClient(make_app())
    r = client.get("/plain")
    assert r.status_code == 200
    lower = {k.lower() for k in r.headers}
    assert EXPECTED_NAMES <= lower
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert r.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert r.headers["content-security-policy"] == "frame-ancestors 'none'"
    assert r.headers["cache-control"] == DEFAULT_CACHE_CONTROL


def test_handler_cache_control_wins() -> None:
    client = TestClient(make_app())
    r = client.get("/cached")
    assert r.headers["cache-control"] == "max-age=60"
    # exactly one Cache-Control header, the handler's own
    assert r.headers.get_list("cache-control") == ["max-age=60"]


def test_handler_security_header_not_duplicated() -> None:
    client = TestClient(make_app())
    r = client.get("/custom-csp")
    assert r.headers.get_list("content-security-policy") == ["frame-ancestors 'self'"]
    # the rest of the set is still applied
    assert r.headers["x-frame-options"] == "DENY"


def test_non_http_scope_passes_through() -> None:
    """WebSocket/lifespan scopes must reach the inner app untouched."""
    received: list[dict] = []

    async def inner_app(scope, receive, send) -> None:
        received.append(scope)

    middleware = SecurityHeadersMiddleware(inner_app)
    scope = {"type": "lifespan"}

    import anyio

    async def drive() -> None:
        await middleware(scope, None, None)

    anyio.run(drive)
    assert received == [scope]


@pytest.mark.asyncio
async def test_gateway_health_carries_hardening_set() -> None:
    """Real gateway app (full middleware stack) serves the headers."""
    transport = ASGITransport(app=gateway_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    lower = {k.lower() for k in response.headers}
    assert EXPECTED_NAMES <= lower
    assert response.headers["x-frame-options"] == "DENY"
