"""Phase 5B — strategy paper lifecycle tests.

Covers: the ``shadow``/``paper`` statuses in ``ALL_STATUSES``, the fail-closed
gate that blocks ``active`` when paper metrics are missing, successful paper
graduation, the researcher path routing through shadow/paper instead of
jumping straight to active, the :class:`PaperTracker` round-trip, and legacy
strategies staying readable but never auto-promoted.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.nexus_agents.research.paper_tracker import PaperTracker
from services.nexus_agents.research.registry import (
    ALL_STATUSES,
    StrategyRecord,
    StrategyRegistry,
)
from shared.redis_client import RedisClient


# ── Local fakes (registry + paper tracker need cache AND list commands) ──────

class _FakeRedis:
    """Minimal in-memory Redis: string cache + lists + no-op zadd."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def delete(self, key: str) -> int:
        gone = self.store.pop(key, None) is not None
        if self.lists.pop(key, None) is not None:
            gone = True
        return int(gone)

    async def lpush(self, key: str, value: str) -> int:
        self.lists.setdefault(key, []).insert(0, value)
        return len(self.lists[key])

    async def ltrim(self, key: str, start: int, end: int) -> None:
        self.lists[key] = self.lists.get(key, [])[start: end + 1]

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        items = self.lists.get(key, [])
        return items if end == -1 else items[start: end + 1]

    async def zadd(self, key: str, mapping: dict) -> int:
        return 1

    async def publish(self, channel: str, message: str) -> int:
        return 1

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        pass


def _redis_client(fake: _FakeRedis | None = None) -> RedisClient:
    client = RedisClient.__new__(RedisClient)
    client._url = "redis://localhost:6379/0"
    client._max_connections = 5
    client._decode_responses = True
    client._pool = None
    client._redis = fake or _FakeRedis()  # type: ignore[assignment]
    return client


# ── Helpers ──────────────────────────────────────────────────────────────────

def _record(**overrides) -> StrategyRecord:
    defaults: dict = dict(
        id="S-test0001",
        name="Test Strategy",
        short_name="Test",
        type="Trend Following",
        description="paper lifecycle test strategy",
        status="backtested",
    )
    defaults.update(overrides)
    return StrategyRecord(**defaults)


def _qualifying_backtest_metrics() -> dict:
    """Metrics that clear PromotionRules (source eligible + all thresholds)."""
    return {
        "evaluation_source": "backtester",
        "profit_factor": 2.0,
        "win_rate": 0.60,
        "sharpe": 1.2,
        "max_dd_pct": 10.0,
        "total_trades": 100,
        "net_pnl_pct": 20.0,
    }


def _with_backtest(rec: StrategyRecord) -> StrategyRecord:
    data = rec.to_dict()
    data.update(_qualifying_backtest_metrics())
    return StrategyRecord.from_dict(data)


class _StubEvaluator:
    """Deterministic evaluator: always returns qualifying backtest metrics."""

    async def evaluate(self, rec: StrategyRecord) -> SimpleNamespace:
        return SimpleNamespace(
            win_rate=0.60,
            profit_factor=2.0,
            sharpe=1.2,
            max_dd_pct=10.0,
            total_trades=100,
            avg_rr=1.5,
            net_pnl_pct=20.0,
            source="backtester",
            recent_results=[],
        )


# ── (a) statuses ─────────────────────────────────────────────────────────────

def test_all_statuses_include_shadow_and_paper():
    assert "shadow" in ALL_STATUSES
    assert "paper" in ALL_STATUSES
    # Old statuses remain reachable/readable.
    for legacy in ("active", "backtested", "investigating", "rejected", "paused"):
        assert legacy in ALL_STATUSES


# ── (b) active blocked with NULL paper fields ────────────────────────────────

@pytest.mark.asyncio
async def test_active_blocked_when_paper_fields_null():
    registry = StrategyRegistry(_redis_client())
    rec = _record()
    await registry.save(rec)

    out = await registry.set_status(rec.id, "active")

    assert out is not None
    assert out.status != "active"
    assert "paper_metrics_missing" in out.promotion_reasons
    stored = await registry.get(rec.id)
    assert stored is not None
    assert stored.status != "active"


# ── (c) active allowed when paper fields set and successful ──────────────────

@pytest.mark.asyncio
async def test_active_allowed_when_paper_metrics_successful():
    registry = StrategyRegistry(_redis_client())
    rec = _record(status="paper", paper_trades=20, paper_pf=1.5, paper_wr=0.55)
    await registry.save(rec)

    out = await registry.set_status(rec.id, "active")

    assert out is not None
    assert out.status == "active"


# ── (d) researcher path lands on shadow/paper, not active ────────────────────

@pytest.mark.asyncio
async def test_backtested_pass_routes_through_shadow_not_active():
    registry = StrategyRegistry(_redis_client())
    out = await registry.evaluate_and_promote(_with_backtest(_record()))

    assert out.status == "shadow"
    assert out.status != "active"
    assert "paper_metrics_missing" in out.promotion_reasons


@pytest.mark.asyncio
async def test_shadow_candidate_advances_to_paper_on_reeval():
    registry = StrategyRegistry(_redis_client())
    out = await registry.evaluate_and_promote(
        _with_backtest(_record(status="shadow"))
    )

    assert out.status == "paper"


@pytest.mark.asyncio
async def test_paper_stage_stays_paper_when_paper_run_unsuccessful():
    registry = StrategyRegistry(_redis_client())
    rec = _with_backtest(
        _record(status="paper", paper_trades=10, paper_pf=0.6, paper_wr=0.30)
    )
    out = await registry.evaluate_and_promote(rec)

    assert out.status == "paper"


@pytest.mark.asyncio
async def test_paper_stage_graduates_to_active_when_paper_run_succeeds():
    registry = StrategyRegistry(_redis_client())
    rec = _with_backtest(
        _record(status="paper", paper_trades=20, paper_pf=1.5, paper_wr=0.55)
    )
    out = await registry.evaluate_and_promote(rec)

    assert out.status == "active"


@pytest.mark.asyncio
async def test_researcher_evaluate_and_save_lands_on_shadow_not_active():
    from services.nexus_agents.research.researcher import StrategyResearcher

    researcher = StrategyResearcher(_redis_client(), evaluator=_StubEvaluator())
    rec = _record()

    saved = await researcher._evaluate_and_save(rec)

    assert saved is not None
    assert saved.status in ("shadow", "paper")
    assert saved.status != "active"


# ── (e) paper_tracker round-trip ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_paper_tracker_record_and_metrics_round_trip():
    tracker = PaperTracker(_redis_client())

    await tracker.record_fill(
        strategy_id="S-1", symbol="XAUUSD", side="buy",
        entry_price=2000.0, exit_price=2010.0, qty=0.1, pnl=10.0,
    )
    await tracker.record_fill(
        strategy_id="S-1", symbol="XAUUSD", side="buy",
        entry_price=2000.0, exit_price=1990.0, qty=0.1, pnl=-10.0,
    )
    await tracker.record_fill(
        strategy_id="S-1", symbol="XAUUSD", side="sell",
        entry_price=2000.0, exit_price=1995.0, qty=0.1, pnl=5.0,
    )

    metrics = await tracker.get_metrics("S-1")

    assert metrics["trades"] == 3
    assert metrics["wins"] == 2
    assert metrics["losses"] == 1
    assert metrics["win_rate"] == pytest.approx(2 / 3)
    assert metrics["profit_factor"] == pytest.approx(15.0 / 10.0)
    assert metrics["net_pnl"] == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_paper_tracker_reset_clears_metrics():
    tracker = PaperTracker(_redis_client())
    await tracker.record_fill(
        strategy_id="S-2", symbol="XAUUSD", side="buy",
        entry_price=2000.0, exit_price=2010.0, pnl=10.0,
    )

    await tracker.reset("S-2")
    metrics = await tracker.get_metrics("S-2")

    assert metrics["trades"] == 0
    assert metrics["win_rate"] is None
    assert metrics["profit_factor"] is None


@pytest.mark.asyncio
async def test_paper_tracker_open_fill_counted_separately():
    tracker = PaperTracker(_redis_client())
    await tracker.record_fill(
        strategy_id="S-3", symbol="XAUUSD", side="buy", entry_price=2000.0,
    )

    metrics = await tracker.get_metrics("S-3")

    assert metrics["trades"] == 0
    assert metrics["open_trades"] == 1


# ── (f) legacy strategies: readable, never auto-promoted ─────────────────────

@pytest.mark.asyncio
async def test_legacy_strategy_readable_and_never_auto_promoted():
    registry = StrategyRegistry(_redis_client())
    legacy_dict = _record(status="backtested").to_dict()
    for key in ("paper_trades", "paper_pf", "paper_wr"):
        legacy_dict.pop(key, None)

    # Readable: missing paper keys default to None.
    rec = StrategyRecord.from_dict(legacy_dict)
    assert rec.paper_trades is None
    assert rec.paper_pf is None
    assert rec.paper_wr is None
    await registry.save(rec)

    # Auto-promotion path: clears backtest thresholds but must not reach active.
    out = await registry.evaluate_and_promote(_with_backtest(rec))
    assert out.status != "active"
    assert out.status in ("shadow", "paper")

    # Manual active attempt is also blocked with the documented reason code.
    out2 = await registry.set_status(rec.id, "active")
    assert out2 is not None
    assert out2.status != "active"
    assert "paper_metrics_missing" in out2.promotion_reasons


@pytest.mark.asyncio
async def test_existing_active_legacy_not_demoted_on_reeval():
    """Grandfathering: an already-active strategy with NULL paper fields keeps
    ``active`` on re-evaluation (the gate blocks new transitions only)."""
    registry = StrategyRegistry(_redis_client())
    rec = _with_backtest(_record(status="active"))
    await registry.save(rec)

    out = await registry.evaluate_and_promote(rec)

    assert out.status == "active"
