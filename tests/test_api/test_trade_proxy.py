"""Regression tests for trade-history gateway failure semantics."""
from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from services.nexus_api.routers import performance, trades


class _ClientContext:
    def __init__(self, client: AsyncMock) -> None:
        self.client = client

    async def __aenter__(self) -> AsyncMock:
        return self.client

    async def __aexit__(self, *_: object) -> None:
        return None


@pytest.mark.asyncio
async def test_list_trades_reports_unavailable_source_instead_of_empty_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-data-secret")
    client = AsyncMock()
    client.get.side_effect = httpx.ConnectError("source offline")
    monkeypatch.setattr(trades, "new_client", lambda **_: _ClientContext(client))
    monkeypatch.setattr(trades, "_require", AsyncMock(return_value=None))

    with pytest.raises(HTTPException) as error:
        await trades.list_trades(actor="user", db=object())

    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_list_trades_keeps_a_valid_empty_history_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-data-secret")
    client = AsyncMock()
    client.get.return_value = httpx.Response(
        200,
        request=httpx.Request("GET", "http://nexus-data/api/data/trades"),
        json={"trades": [], "total": 0, "page": 1, "page_size": 50},
    )
    monkeypatch.setattr(trades, "new_client", lambda **_: _ClientContext(client))
    monkeypatch.setattr(trades, "_require", AsyncMock(return_value=None))

    result = await trades.list_trades(
        actor="user", db=object(), symbol=None, session=None, side=None,
        since=None, page=1, page_size=50,
    )

    assert result["trades"] == []
    assert result["total"] == 0
    assert client.get.await_args.kwargs["headers"] == {
        "X-Nexus-Internal-Secret": "test-data-secret"
    }


@pytest.mark.asyncio
async def test_trade_stats_aggregates_more_than_one_source_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    all_trades = [
        {"pnl_usd": 1.0, "rr_ratio": 1.0, "duration_s": 10}
        for _ in range(5001)
    ]
    requested_pages: list[int] = []

    async def proxy(params: dict[str, object]) -> dict[str, object]:
        page = int(params["page"])
        page_size = int(params["page_size"])
        requested_pages.append(page)
        start = (page - 1) * page_size
        return {
            "trades": all_trades[start : start + page_size],
            "total": len(all_trades),
        }

    monkeypatch.setattr(trades, "_proxy_trades", proxy)
    monkeypatch.setattr(trades, "_require", AsyncMock(return_value=None))

    stats = await trades.trade_stats(
        actor="user", db=object(), symbol=None, session=None, since=None,
    )

    assert requested_pages == [1, 2]
    assert stats["total_trades"] == 5001
    assert stats["total_pnl"] == 5001.0


@pytest.mark.asyncio
async def test_performance_proxy_passes_internal_data_credential(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-data-secret")
    client = AsyncMock()
    client.get.return_value = httpx.Response(
        200,
        json={"total_trades": 3},
        request=httpx.Request("GET", "http://nexus-data/api/data/performance"),
    )
    monkeypatch.setattr(performance, "new_client", lambda **_: _ClientContext(client))

    result = await performance._get("/api/data/performance")

    assert result == {"total_trades": 3}
    assert client.get.await_args.kwargs["headers"] == {
        "X-Nexus-Internal-Secret": "test-data-secret"
    }
