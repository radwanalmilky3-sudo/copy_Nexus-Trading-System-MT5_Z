"""CORS allowlist tests — N3 closure (T-011).

The dashboard is browsed from :3100 (next-server) or from :3000
(scripts/port3000_forward.py, a raw TCP forwarder onto :3100, so the browser
Origin is then http://localhost:3000). In the primary flow CORS is never
evaluated: next.config.js rewrites keep every API call same-origin, and
same-origin fetches are exempt. The allowlist only matters for the degraded
case of a stale browser bundle calling nexus-api (:9000) cross-origin — the
same contract documented in the next.config.js rewrites comment.

These tests pin the contract: :3000/:3100 preflights pass, DASHBOARD_ORIGIN
stays first with duplicates collapsed, and a foreign origin gets a 400
preflight (Starlette ≥0.40 behaviour) with no allow-origin header.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from services.nexus_api.main import DASHBOARD_ORIGIN, app, build_cors_origins


async def _preflight(origin: str) -> tuple[int, dict[str, str]]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.options(
            "/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
    return response.status_code, dict(response.headers)


@pytest.mark.asyncio
async def test_preflight_allowed_for_forwarder_origin_3000() -> None:
    status, headers = await _preflight("http://localhost:3000")
    assert status == 200
    assert headers["access-control-allow-origin"] == "http://localhost:3000"
    assert headers["access-control-allow-credentials"] == "true"


@pytest.mark.asyncio
async def test_preflight_allowed_for_loopback_forwarder_origin_3000() -> None:
    status, headers = await _preflight("http://127.0.0.1:3000")
    assert status == 200
    assert headers["access-control-allow-origin"] == "http://127.0.0.1:3000"


@pytest.mark.asyncio
async def test_preflight_allowed_for_next_server_origin_3100() -> None:
    status, headers = await _preflight("http://localhost:3100")
    assert status == 200
    assert headers["access-control-allow-origin"] == "http://localhost:3100"


@pytest.mark.asyncio
async def test_preflight_allowed_for_dashboard_env_origin() -> None:
    status, headers = await _preflight(DASHBOARD_ORIGIN)
    assert status == 200
    assert headers["access-control-allow-origin"] == DASHBOARD_ORIGIN


@pytest.mark.asyncio
async def test_preflight_rejected_for_foreign_origin() -> None:
    status, headers = await _preflight("https://evil.example.com")
    assert status == 400
    assert "access-control-allow-origin" not in headers


def test_build_cors_origins_env_default_first_no_duplicates() -> None:
    origins = build_cors_origins("http://localhost:3100")
    assert origins[0] == "http://localhost:3100"
    assert len(origins) == len(set(origins))
    for required in (
        "http://localhost:3100",
        "http://127.0.0.1:3100",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ):
        assert required in origins


def test_build_cors_origins_env_override_extends_not_replaces() -> None:
    origins = build_cors_origins("https://nexus.example.com")
    assert origins[0] == "https://nexus.example.com"
    assert "http://localhost:3000" in origins
    assert "http://localhost:3100" in origins


def test_build_cors_origins_normalizes_trailing_slash_and_whitespace() -> None:
    origins = build_cors_origins(" http://localhost:3100/ ")
    assert origins[0] == "http://localhost:3100"
    assert origins.count("http://localhost:3100") == 1
