from __future__ import annotations

import httpx
import numpy as np
import pytest
import warnings
from fastapi import HTTPException


class _UnusedDatabaseClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def init_db(self) -> None:
        pass

    async def get_trades(self, *, limit: int):
        return []

    async def close(self) -> None:
        pass


def test_sortino_is_finite_with_only_one_downside_observation():
    from services.nexus_monitor.performance import PerformanceAnalyzer

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        result = PerformanceAnalyzer.calculate_sortino(np.array([10.0, -4.0]))

    assert result == 0.0


@pytest.mark.asyncio
async def test_monitor_performance_reads_trades_through_data_owner(monkeypatch):
    from services.nexus_monitor import main
    from shared import duckdb_client

    requests: list[httpx.Request] = []
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-data-secret")

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={
            "trades": [
                {"pnl_usd": 10.0, "rr_ratio": 1.0},
                {"pnl_usd": -4.0, "rr_ratio": -0.5},
            ],
            "total": 2,
            "page": 1,
            "page_size": 2,
        })

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(duckdb_client, "DuckDBClient", _UnusedDatabaseClient)
    monkeypatch.setattr(main, "new_client", lambda **kwargs: client)
    monkeypatch.setattr(main, "DATA_SERVICE_URL", "http://nexus-data.test", raising=False)

    try:
        result = await main.get_performance(
            limit=2,
            x_nexus_internal_secret="test-data-secret",
        )
    finally:
        await client.aclose()

    assert len(requests) == 1
    assert str(requests[0].url) == "http://nexus-data.test/api/data/trades?page=1&page_size=2"
    assert requests[0].headers["X-Nexus-Internal-Secret"] == "test-data-secret"
    assert result["total_trades"] == 2
    assert result["total_pnl"] == 6.0


@pytest.mark.asyncio
async def test_monitor_performance_reports_data_owner_outage(monkeypatch):
    from services.nexus_monitor import main
    from shared import duckdb_client

    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-data-secret")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503))
    )
    monkeypatch.setattr(duckdb_client, "DuckDBClient", _UnusedDatabaseClient)
    monkeypatch.setattr(main, "new_client", lambda **kwargs: client)
    monkeypatch.setattr(main, "DATA_SERVICE_URL", "http://nexus-data.test", raising=False)

    try:
        with pytest.raises(HTTPException) as exc:
            await main.get_performance(
                limit=2,
                x_nexus_internal_secret="test-data-secret",
            )
    finally:
        await client.aclose()

    assert exc.value.status_code == 503
