from __future__ import annotations

import pytest
from fastapi import HTTPException

from services.nexus_api.routers import backtest


class AuthorizedDataService:
    async def query(self, operation: str, params: dict | None = None):
        return [{"permission_code": "*"}]


@pytest.mark.asyncio
async def test_backtest_source_outage_returns_service_unavailable(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-data-secret")
    calls = []
    class OfflineRedis:
        async def get(self, key: str):
            raise ConnectionError("redis unavailable")

    class OfflineHttpClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            calls.append(kwargs)
            raise ConnectionError("nexus-data unavailable")

    async def get_redis():
        return OfflineRedis()

    monkeypatch.setattr(backtest, "_get_redis", get_redis)
    monkeypatch.setattr(backtest, "new_client", lambda **kwargs: OfflineHttpClient())

    with pytest.raises(HTTPException) as exc_info:
        await backtest.run_backtest(backtest.BacktestConfig(), "test-user", AuthorizedDataService())

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Historical trade data is temporarily unavailable"
    assert calls[0]["headers"] == {"X-Nexus-Internal-Secret": "test-data-secret"}


@pytest.mark.asyncio
async def test_backtest_valid_empty_history_remains_a_zero_trade_result(monkeypatch):
    async def no_trades(_symbol: str):
        return []

    monkeypatch.setattr(backtest, "_fetch_trades", no_trades)

    class EmptyRedis:
        async def get(self, key: str):
            return "[]"

        async def set(self, *args, **kwargs):
            return True

    async def get_redis():
        return EmptyRedis()

    monkeypatch.setattr(backtest, "_get_redis", get_redis)

    result = await backtest.run_backtest(backtest.BacktestConfig(), "test-user", AuthorizedDataService())

    assert result["raw_trades_fetched"] == 0
    assert result["metrics"]["total_trades"] == 0


class _FakeRedis:
    """Async dict-backed stand-in: records what run_backtest caches."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        return True


def _fake_redis(monkeypatch, fake: _FakeRedis) -> None:
    async def _get_redis():
        return fake

    monkeypatch.setattr(backtest, "_get_redis", _get_redis)


def _trade(pnl: float, ts: str, **extra) -> dict:
    trade = {
        "pnl": pnl,
        "close_time": ts,
        "session": "LONDON",
        "strategy": "trend",
        "direction": "BUY",
        "conviction": 0.8,
    }
    trade.update(extra)
    return trade


def _stub_trades(monkeypatch, trades: list[dict]) -> None:
    async def _fetch(_symbol: str) -> list[dict]:
        return list(trades)

    monkeypatch.setattr(backtest, "_fetch_trades", _fetch)


@pytest.mark.asyncio
async def test_backtest_small_sample_still_computes_metrics(monkeypatch):
    trades = [
        _trade(100.0, "2026-01-05T10:00:00+00:00"),
        _trade(-50.0, "2026-01-06T11:00:00+00:00"),
        _trade(25.0, "2026-01-07T12:00:00+00:00"),
    ]
    _stub_trades(monkeypatch, trades)
    _fake_redis(monkeypatch, _FakeRedis())

    result = await backtest.run_backtest(backtest.BacktestConfig(), "u", AuthorizedDataService())
    m = result["metrics"]

    assert m["total_trades"] == 3
    assert m["wins"] == 2
    assert m["losses"] == 1
    assert m["win_rate"] == 0.6667
    assert m["net_pnl"] == 75.0
    assert len(result["equity_curve"]) == 3


@pytest.mark.asyncio
async def test_backtest_losses_only_reports_zero_win_rate(monkeypatch):
    trades = [
        _trade(-40.0, "2026-02-01T09:00:00+00:00"),
        _trade(-10.0, "2026-02-01T10:00:00+00:00"),
    ]
    _stub_trades(monkeypatch, trades)
    _fake_redis(monkeypatch, _FakeRedis())

    result = await backtest.run_backtest(backtest.BacktestConfig(), "u", AuthorizedDataService())
    m = result["metrics"]

    assert m["wins"] == 0
    assert m["losses"] == 2
    assert m["win_rate"] == 0.0
    assert m["profit_factor"] == 0.0
    assert m["avg_win"] == 0.0
    assert m["avg_loss"] == -25.0
    assert m["net_pnl"] == -50.0


@pytest.mark.asyncio
async def test_backtest_drawdown_reflects_peak_to_trough(monkeypatch):
    trades = [
        _trade(100.0, "2026-03-01T09:00:00+00:00"),   # equity 5100 (peak)
        _trade(-300.0, "2026-03-01T10:00:00+00:00"),  # equity 4800 (dd 300)
        _trade(50.0, "2026-03-01T11:00:00+00:00"),    # equity 4850
    ]
    _stub_trades(monkeypatch, trades)
    _fake_redis(monkeypatch, _FakeRedis())

    result = await backtest.run_backtest(backtest.BacktestConfig(), "u", AuthorizedDataService())
    m = result["metrics"]

    assert m["max_drawdown"] == -300.0
    assert m["max_dd_pct"] == -5.88
    assert result["equity_curve"][1]["equity"] == 4800.0


@pytest.mark.asyncio
async def test_backtest_missing_fields_count_as_non_wins_without_crashing(monkeypatch):
    trades = [
        {"pnl": 100.0, "close_time": "2026-04-01T09:00:00+00:00"},
        {},  # no pnl, no timestamp, no session/strategy/direction
    ]
    _stub_trades(monkeypatch, trades)
    _fake_redis(monkeypatch, _FakeRedis())

    result = await backtest.run_backtest(backtest.BacktestConfig(), "u", AuthorizedDataService())
    m = result["metrics"]

    assert m["total_trades"] == 2
    assert m["wins"] == 1
    assert m["win_rate"] == 0.5
    assert "?" in result["by_hour"]
    assert "UNKNOWN" in result["by_session"]


@pytest.mark.asyncio
async def test_backtest_summary_returns_last_run_bound_to_its_own_config(monkeypatch):
    fake = _FakeRedis()
    _fake_redis(monkeypatch, fake)

    runs: dict[str, list[dict]] = {
        "A": [_trade(100.0, "2026-05-01T09:00:00+00:00", conviction=0.95)],
        "B": [_trade(-20.0, "2026-05-02T09:00:00+00:00")],
    }
    state: dict[str, list[dict]] = {"current": runs["A"]}

    async def _fetch(_symbol: str) -> list[dict]:
        return list(state["current"])

    monkeypatch.setattr(backtest, "_fetch_trades", _fetch)

    state["current"] = runs["A"]
    cfg_a = backtest.BacktestConfig(min_conviction=0.9)
    result_a = await backtest.run_backtest(cfg_a, "u", AuthorizedDataService())

    state["current"] = runs["B"]
    cfg_b = backtest.BacktestConfig(min_conviction=0.0)
    result_b = await backtest.run_backtest(cfg_b, "u", AuthorizedDataService())

    summary = await backtest.last_backtest("u", AuthorizedDataService())
    assert summary["config"] == cfg_b.model_dump()
    assert summary["run_at"] == result_b["run_at"]

    # The older report object stays bound to the config that produced it.
    assert result_a["config"] == cfg_a.model_dump()
    assert result_a["metrics"]["net_pnl"] == 100.0
    assert summary["metrics"]["net_pnl"] == -20.0


@pytest.mark.asyncio
async def test_backtest_two_identical_runs_are_reproducible(monkeypatch):
    trades = [
        _trade(100.0, "2026-06-01T09:00:00+00:00"),
        _trade(-40.0, "2026-06-01T10:00:00+00:00"),
        _trade(15.5, "2026-06-02T11:00:00+00:00"),
    ]
    _stub_trades(monkeypatch, trades)
    _fake_redis(monkeypatch, _FakeRedis())
    cfg = backtest.BacktestConfig()

    first = await backtest.run_backtest(cfg, "u", AuthorizedDataService())
    second = await backtest.run_backtest(cfg, "u", AuthorizedDataService())

    for key in ("config", "raw_trades_fetched", "trades_after_filter",
                "metrics", "equity_curve", "by_session", "by_strategy",
                "by_direction", "by_hour"):
        assert first[key] == second[key], f"field {key} differs between identical runs"
