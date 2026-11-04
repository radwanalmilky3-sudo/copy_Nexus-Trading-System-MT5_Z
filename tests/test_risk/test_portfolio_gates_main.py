"""Phase 3 main.py acceptance tests (C2 side): portfolio-gate inputs, clamp,
breakers honesty, reset-day audit — all exercised through services.nexus_risk.main.

C1 owns tests/test_risk/test_portfolio_gates.py (engine gates). These tests
cover the main.py duties from NEXUS_MASTER_PLAN 3.2: equity peak (+restore),
real 7-day weekly DD, open-risk budget clamp, real correlation snapshot feed,
reset-day audit row, and honest circuit-breaker reporting.
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from services.nexus_risk import main as risk_main
from services.nexus_risk.position_sizer import PositionSizer
from services.nexus_risk.rules_engine import RulesEngine
from shared.constants import RiskDecision
from shared.models import TradeProposal, Verdict


class FakeRedis:
    """Minimal async Redis for get/set/list/ttl paths used by Phase 3 code."""

    def __init__(self) -> None:
        self.store: dict[str, object] = {}
        self.lists: dict[str, list[object]] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value, ex: int | None = None):
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex

    async def delete(self, *keys: str):
        for key in keys:
            self.store.pop(key, None)
            self.lists.pop(key, None)

    async def rpush(self, key: str, *values):
        self.lists.setdefault(key, []).extend(values)

    async def lrange(self, key: str, start: int, end: int):
        entries = self.lists.get(key, [])
        return entries[start:] if end == -1 else entries[start:end + 1]

    async def expire(self, key: str, ttl: int):
        self.ttls[key] = ttl

    async def ttl(self, key: str):
        return self.ttls.get(key, -1)

    def scan_iter(self, pattern: str):
        async def _gen():
            prefix = pattern[:-1] if pattern.endswith("*") else pattern
            for key in list(self.store) + list(self.lists):
                if str(key).startswith(prefix):
                    yield key
        return _gen()


def _patch_evaluate(monkeypatch, state: dict, engine: RulesEngine | None = None) -> None:
    """Scaffold _evaluate_proposal like test_position_sizer_risk_cap does."""

    class FakeCache:
        async def cache_get(self, key, **kwargs):
            if key == "system:auto_trade":
                return True
            if key == "fundamental:blackout":
                return {"state": "clear", "active": False}
            if key == "nexus:trade_memory:metrics":
                return None
            raise AssertionError(f"unexpected cache key: {key}")

    async def return_none(*args, **kwargs):
        return None

    async def no_cooldown(*args, **kwargs):
        return 0.0

    async def no_multiplier(*args, **kwargs):
        return 1.0, {"multiplier": 1.0}

    async def get_settings(redis):
        return {"risk_per_trade_pct": 1.0, "max_daily_trades": 0}

    # Real session-gate resolver fed by the stubbed get_settings; the patched
    # ALLOW_* module values act as the env-derived caller defaults (the stub
    # predates session_gate_policy and broke every _evaluate_proposal test).
    import shared.runtime_settings as _rs

    def _gate_policy(doc=None, *, default_off_hours=False, default_sessions=None):
        return _rs.session_gate_policy(
            doc,
            default_off_hours=ALLOW_OFF_HOURS if default_off_hours is None else default_off_hours,
            default_sessions=ALLOWED_SESSIONS if default_sessions is None else default_sessions,
        )

    monkeypatch.setattr(risk_main, "redis", SimpleNamespace(cache_get=FakeCache().cache_get))
    monkeypatch.setattr(
        risk_main, "runtime_settings",
        SimpleNamespace(get_settings=get_settings, session_gate_policy=_gate_policy),
    )
    monkeypatch.setattr(risk_main, "position_sizer", PositionSizer())
    monkeypatch.setattr(risk_main, "rules_engine", engine or RulesEngine())
    monkeypatch.setattr(risk_main, "ALLOW_OFF_HOURS", True)
    monkeypatch.setattr(risk_main, "_check_circuit_breaker", return_none)
    monkeypatch.setattr(risk_main, "_check_ergodic_circuit_breaker", return_none)
    monkeypatch.setattr(risk_main, "_get_ergodic_lot_multiplier", no_multiplier)
    monkeypatch.setattr(risk_main, "_stack_cooldown_remaining", no_cooldown)
    monkeypatch.setattr(risk_main, "_direction_block_remaining", no_cooldown)
    monkeypatch.setattr(risk_main, "_mark_stack_cooldown", return_none)
    monkeypatch.setattr(risk_main, "_persist_daily_count", return_none)
    monkeypatch.setattr(risk_main, "_daily_trade_count", 0)
    monkeypatch.setattr(risk_main, "_daily_trades_limit_observed", 0)
    monkeypatch.setattr(risk_main, "_current_state", state)


def _proposal(symbol: str = "XAUUSD") -> TradeProposal:
    return TradeProposal(
        symbol=symbol,
        direction=Verdict.BUY,
        entry=2_500,
        sl=2_490,
        tp1=2_520,
        conviction=0.9,
    )


def _base_state(**extra) -> dict:
    state = {
        "available": True,
        "balance": 10_000,
        "equity": 10_000,
        "daily_loss_pct": 0,
        "weekly_dd_pct": 0,
        "open_positions_count": 0,
        "open_positions": [],
        "current_spread": 0,
        "avg_spread": 1,
        "vol_regime": "low",
        "session": "overlap",
    }
    state.update(extra)
    return state


def _closes_from_returns(returns: list[float]) -> list[float]:
    closes = [1.0]
    for ret in returns:
        closes.append(closes[-1] * (1.0 + ret))
    return closes


# ── Equity peak: update semantics + restart survival ─────────────────────────

def test_equity_peak_new_day_rebaselines_and_computes_dd(monkeypatch) -> None:
    fake = FakeRedis()
    monkeypatch.setattr(risk_main, "redis", SimpleNamespace(r=fake))
    monkeypatch.setattr(risk_main, "_equity_peak", 5_000.0)
    monkeypatch.setattr(risk_main, "_equity_peak_day", "2026-01-01")
    monkeypatch.setattr(risk_main, "_current_state", {})

    import asyncio
    asyncio.run(risk_main._update_equity_peak(4_800.0, "2026-01-02"))

    # New day ⇒ re-baseline (mirror of _DAY_START_BALANCE), dd restarts at 0.
    assert risk_main._equity_peak == 4_800.0
    assert risk_main._current_state["equity_peak"] == 4_800.0
    assert risk_main._current_state["equity_peak_day"] == "2026-01-02"
    assert risk_main._current_state["dd_from_peak_pct"] == 0.0


def test_equity_peak_raises_on_new_high_same_day(monkeypatch) -> None:
    fake = FakeRedis()
    monkeypatch.setattr(risk_main, "redis", SimpleNamespace(r=fake))
    monkeypatch.setattr(risk_main, "_equity_peak", 5_200.0)
    monkeypatch.setattr(risk_main, "_equity_peak_day", "2026-01-01")
    monkeypatch.setattr(risk_main, "_current_state", {})

    import asyncio
    asyncio.run(risk_main._update_equity_peak(5_300.0, "2026-01-01"))
    assert risk_main._equity_peak == 5_300.0
    assert risk_main._current_state["dd_from_peak_pct"] == 0.0

    asyncio.run(risk_main._update_equity_peak(5_035.0, "2026-01-01"))
    assert risk_main._equity_peak == 5_300.0  # high-water mark untouched
    assert risk_main._current_state["dd_from_peak_pct"] == pytest.approx(5.0, abs=1e-6)


def test_equity_peak_survives_restart_via_redis(monkeypatch) -> None:
    fake = FakeRedis()
    fake.store[risk_main._EQUITY_PEAK_KEY] = "7777.5"
    fake.store[risk_main._EQUITY_PEAK_DAY_KEY] = "2026-01-05"
    monkeypatch.setattr(risk_main, "redis", SimpleNamespace(r=fake))
    monkeypatch.setattr(risk_main, "_equity_peak", 0.0)
    monkeypatch.setattr(risk_main, "_equity_peak_day", "")
    monkeypatch.setattr(risk_main, "_current_state", {"equity_peak": 0.0})

    import asyncio
    asyncio.run(risk_main._restore_equity_peak())

    assert risk_main._equity_peak == 7777.5
    assert risk_main._equity_peak_day == "2026-01-05"
    assert risk_main._current_state["equity_peak"] == 7777.5
    assert risk_main._current_state["equity_peak_day"] == "2026-01-05"


# ── Real 7-day weekly drawdown ───────────────────────────────────────────────

def test_weekly_dd_from_series_uses_seven_day_high() -> None:
    entries = [
        {"day": "2026-01-07", "equity": 10_000.0},
        {"day": "2026-01-06", "equity": 10_200.0},
        {"day": "2026-01-05", "equity": 10_500.0},
    ]
    dd = risk_main._weekly_dd_from_series(entries)
    # (10_500 − 10_000) / 10_500 = 4.7619…%
    assert dd == pytest.approx(4.7619, abs=1e-3)


def test_weekly_dd_fallback_keeps_previous_value_on_read_failure(monkeypatch) -> None:
    class BrokenRedis:
        async def lrange(self, *args, **kwargs):
            raise RuntimeError("redis down")

    monkeypatch.setattr(risk_main, "redis", SimpleNamespace(r=BrokenRedis()))
    monkeypatch.setattr(risk_main, "_current_state", {
        "weekly_dd_pct": 3.25, "weekly_dd_source": "equity_series",
    })

    import asyncio
    asyncio.run(risk_main._update_weekly_dd(9_000.0, "2026-01-07"))

    # Documented fallback: a failed read keeps the old value (old behavior).
    assert risk_main._current_state["weekly_dd_pct"] == 3.25
    assert risk_main._current_state["weekly_dd_source"] == "equity_series"


def test_weekly_dd_recorded_and_restored_from_series(monkeypatch) -> None:
    fake = FakeRedis()
    fake.lists[risk_main._EQUITY_SERIES_KEY] = [
        json.dumps({"day": "2026-01-06", "equity": 10_500}),
        json.dumps({"day": "2026-01-05", "equity": 10_300}),
    ]
    monkeypatch.setattr(risk_main, "redis", SimpleNamespace(r=fake))
    monkeypatch.setattr(risk_main, "_current_state", {})

    import asyncio
    asyncio.run(risk_main._update_weekly_dd(10_000.0, "2026-01-07"))

    assert risk_main._current_state["weekly_dd_source"] == "equity_series"
    # newest (today) first: high 10_500 vs today 10_000 ⇒ 4.7619%
    assert risk_main._current_state["weekly_dd_pct"] == pytest.approx(4.7619, abs=1e-3)

    # Restart path recomputes the same value from the persisted series.
    monkeypatch.setattr(risk_main, "_current_state", {})
    asyncio.run(risk_main._restore_weekly_dd())
    assert risk_main._current_state["weekly_dd_pct"] == pytest.approx(4.7619, abs=1e-3)


# ── Open-risk snapshot feeding the engine input alias ────────────────────────

def test_open_risk_writer_sets_engine_alias(monkeypatch) -> None:
    fake = FakeRedis()
    monkeypatch.setattr(risk_main, "redis", SimpleNamespace(r=fake))
    monkeypatch.setattr(risk_main, "rules_engine", RulesEngine())
    monkeypatch.setattr(risk_main, "_current_state", {})

    import asyncio
    asyncio.run(risk_main._update_open_risk(10_000.0, [
        {"symbol": "EURUSD", "size": 0.1, "entry_price": 1.1000, "sl": 1.0900},
    ]))

    state = risk_main._current_state
    assert isinstance(state["open_risk_usd"], float) and state["open_risk_usd"] > 0
    # Engine-facing alias (rules_engine.check_all_rules reads open_risk_amount).
    assert state["open_risk_amount"] == state["open_risk_usd"]
    assert state["open_risk_pct"] == pytest.approx(
        state["open_risk_usd"] / 10_000.0 * 100, abs=1e-6,
    )


def test_open_risk_unknown_when_stop_missing(monkeypatch) -> None:
    monkeypatch.setattr(risk_main, "redis", SimpleNamespace(r=FakeRedis()))
    monkeypatch.setattr(risk_main, "rules_engine", RulesEngine())
    monkeypatch.setattr(risk_main, "_current_state", {})

    import asyncio
    asyncio.run(risk_main._update_open_risk(10_000.0, [
        {"symbol": "EURUSD", "size": 0.1, "entry_price": 1.1000},  # no SL
    ]))

    assert risk_main._current_state["open_risk_usd"] is None
    assert risk_main._current_state["open_risk_amount"] is None
    assert risk_main._current_state["open_risk_positions_uncounted"] == 1


# ── Remaining-budget helper (clamp input) ────────────────────────────────────

def test_remaining_budget_none_when_gate_disabled(monkeypatch) -> None:
    monkeypatch.setattr(risk_main, "rules_engine", RulesEngine())
    assert risk_main._remaining_open_risk_budget_usd({"equity": 10_000}) is None


def test_remaining_budget_subtracts_open_risk(monkeypatch) -> None:
    engine = RulesEngine()
    engine._cfg.max_portfolio_open_risk_pct = 2.0
    monkeypatch.setattr(risk_main, "rules_engine", engine)

    # budget = 10_000 × 2% = 200; open 150 ⇒ 50 left (engine helper path).
    assert risk_main._remaining_open_risk_budget_usd(
        {"equity": 10_000, "open_risk_usd": 150.0},
    ) == pytest.approx(50.0)


def test_remaining_budget_fail_closed_on_unknown(monkeypatch) -> None:
    engine = RulesEngine()
    engine._cfg.max_portfolio_open_risk_pct = 2.0
    monkeypatch.setattr(risk_main, "rules_engine", engine)

    # Unknown open risk while configured ⇒ no room for new risk (0.0), never
    # the full budget.
    assert risk_main._remaining_open_risk_budget_usd(
        {"equity": 10_000, "open_risk_usd": None},
    ) == 0.0
    assert risk_main._remaining_open_risk_budget_usd({"equity": 0}) == 0.0


# ── Main-side gap-fill gates (fail-closed inputs) ────────────────────────────

def test_portfolio_gates_noop_while_cfg_unset(monkeypatch) -> None:
    monkeypatch.setattr(risk_main, "rules_engine", RulesEngine())
    state = {
        "equity": None,
        "equity_peak": 0.0,
        "open_risk_usd": None,
        "gross_leverage": None,
        "open_positions": [{"symbol": "EURUSD"}],
    }
    assert risk_main._run_portfolio_gates(state) == []


def test_portfolio_gates_reject_unknown_inputs_when_configured(monkeypatch) -> None:
    engine = RulesEngine()
    engine._cfg.max_drawdown_from_peak_pct = 10.0
    engine._cfg.max_portfolio_open_risk_pct = 2.0
    engine._cfg.max_gross_leverage = 3.0
    engine._cfg.correlation_threshold = 0.8
    monkeypatch.setattr(risk_main, "rules_engine", engine)

    violations = risk_main._run_portfolio_gates({
        "equity": 10_000.0,
        "equity_peak": 0.0,        # unknown peak ⇒ engine would skip silently
        "open_risk_usd": None,     # unknown open risk
        "gross_leverage": None,    # notional not verifiable
        "open_positions": [{"symbol": "EURUSD"}],
        "correlation_snapshot": None,
    })
    rules = [v["rule"] for v in violations]
    assert rules == [
        "dd_from_peak_unavailable",
        "open_risk_unavailable",
        "gross_leverage_unavailable",
        "correlation_data_unavailable",
    ]
    assert all(v["severity"] == "CRITICAL" for v in violations)


def test_portfolio_gates_silent_when_inputs_valid(monkeypatch) -> None:
    engine = RulesEngine()
    engine._cfg.max_drawdown_from_peak_pct = 10.0
    engine._cfg.max_portfolio_open_risk_pct = 2.0
    engine._cfg.max_gross_leverage = 3.0
    engine._cfg.correlation_threshold = 0.8
    monkeypatch.setattr(risk_main, "rules_engine", engine)

    assert risk_main._run_portfolio_gates({
        "equity": 10_000.0,
        "equity_peak": 10_500.0,
        "open_risk_usd": 50.0,
        "gross_leverage": 0.5,
        "open_positions": [{"symbol": "EURUSD"}],
        "correlation_snapshot": {"symbols": ["EURUSD", "GBPUSD"], "pairs": {}},
    }) == []


# ── Sizing clamp against the remaining budget (evaluate path) ────────────────

def _engine_with_budget(pct: float = 2.0) -> RulesEngine:
    engine = RulesEngine()
    engine._cfg.max_portfolio_open_risk_pct = pct
    return engine


@pytest.mark.asyncio
async def test_evaluate_clamps_size_to_remaining_budget(monkeypatch) -> None:
    state = _base_state(
        open_positions_count=1,
        open_positions=[{"symbol": "EURUSD"}],
        open_risk_usd=150.0,
        open_risk_amount=150.0,
    )
    _patch_evaluate(monkeypatch, state, engine=_engine_with_budget(2.0))

    result = await risk_main._evaluate_proposal(_proposal(), {})

    # Budget 200 − open 150 = 50 USD remaining ⇒ half of the 0.10-lot size
    # (1% of 10k = 100 USD ⇒ 0.10 lots for XAUUSD @ 10.0 SL distance).
    assert result["decision"] == RiskDecision.APPROVE
    assert result["approved_size"] == pytest.approx(0.05)


@pytest.mark.asyncio
async def test_evaluate_untouched_when_budget_gate_disabled(monkeypatch) -> None:
    state = _base_state(
        open_positions_count=1,
        open_positions=[{"symbol": "EURUSD"}],
        open_risk_usd=150.0,
        open_risk_amount=150.0,
    )
    _patch_evaluate(monkeypatch, state)  # fresh RulesEngine ⇒ cfg None

    result = await risk_main._evaluate_proposal(_proposal(), {})

    assert result["decision"] == RiskDecision.APPROVE
    assert result["approved_size"] == pytest.approx(0.10)


@pytest.mark.asyncio
async def test_evaluate_budget_exhausted_rejected_by_engine(monkeypatch) -> None:
    state = _base_state(
        open_positions_count=1,
        open_positions=[{"symbol": "EURUSD"}],
        open_risk_usd=200.0,       # exactly the full budget ⇒ nothing remains
        open_risk_amount=200.0,
    )
    _patch_evaluate(monkeypatch, state, engine=_engine_with_budget(2.0))

    result = await risk_main._evaluate_proposal(_proposal(), {})

    assert result["decision"] == RiskDecision.REJECT
    assert any(v["rule"] == "portfolio_open_risk" for v in result["violations"])


@pytest.mark.asyncio
async def test_evaluate_unknown_open_risk_fails_closed_when_configured(monkeypatch) -> None:
    state = _base_state(open_positions_count=0, open_positions=[])
    state["open_risk_usd"] = None
    _patch_evaluate(monkeypatch, state, engine=_engine_with_budget(2.0))

    result = await risk_main._evaluate_proposal(_proposal(), {})

    assert result["decision"] == RiskDecision.REJECT
    assert any(v["rule"] == "open_risk_unavailable" for v in result["violations"])


# ── Real correlation snapshot (proposal-time, behind cfg) ────────────────────

def _corr_engine(threshold: float) -> RulesEngine:
    engine = RulesEngine()
    engine._cfg.correlation_threshold = threshold
    return engine


@pytest.mark.asyncio
async def test_evaluate_high_correlation_rejected(monkeypatch) -> None:
    closes = _closes_from_returns([0.001 * i for i in range(1, 13)])
    provider = lambda symbols, lookback: {
        "EURUSD": closes, "XAUUSD": list(closes),  # identical ⇒ |corr| = 1.0
    }
    state = _base_state(
        open_positions_count=1,
        open_positions=[{"symbol": "EURUSD"}],
    )
    _patch_evaluate(monkeypatch, state, engine=_corr_engine(0.9))
    monkeypatch.setattr(risk_main, "_correlation_bars_provider", provider)

    result = await risk_main._evaluate_proposal(_proposal(), {})

    assert result["decision"] == RiskDecision.REJECT
    assert any(v["rule"] == "portfolio_correlation" for v in result["violations"])


@pytest.mark.asyncio
async def test_evaluate_low_correlation_allows_trade(monkeypatch) -> None:
    # Decorrelated returns (covariance ≈ −0.145) ⇒ below a 0.9 ceiling.
    good_a = _closes_from_returns([0.001 * i for i in range(1, 13)])
    good_b = _closes_from_returns([0.001 * (1 if i % 2 else -1) for i in range(1, 13)])
    provider = lambda symbols, lookback: {"EURUSD": good_a, "XAUUSD": good_b}
    state = _base_state(
        open_positions_count=1,
        open_positions=[{"symbol": "EURUSD"}],
    )
    _patch_evaluate(monkeypatch, state, engine=_corr_engine(0.9))
    monkeypatch.setattr(risk_main, "_correlation_bars_provider", provider)

    result = await risk_main._evaluate_proposal(_proposal(), {})

    assert result["decision"] == RiskDecision.APPROVE
    # Snapshot reaches the engine on the merged copy — shared state untouched.
    assert "correlation_snapshot" not in state


@pytest.mark.asyncio
async def test_evaluate_missing_correlation_bars_fails_closed(monkeypatch) -> None:
    provider = lambda symbols, lookback: {}
    state = _base_state(
        open_positions_count=1,
        open_positions=[{"symbol": "EURUSD"}],
    )
    _patch_evaluate(monkeypatch, state, engine=_corr_engine(0.9))
    monkeypatch.setattr(risk_main, "_correlation_bars_provider", provider)

    result = await risk_main._evaluate_proposal(_proposal(), {})

    assert result["decision"] == RiskDecision.REJECT
    assert any(v["rule"] == "correlation_data_unavailable" for v in result["violations"])


@pytest.mark.asyncio
async def test_evaluate_correlation_provider_untouched_when_cfg_unset(monkeypatch) -> None:
    calls: list[list[str]] = []

    def provider(symbols, lookback):
        calls.append(list(symbols))
        return {}

    state = _base_state(
        open_positions_count=1,
        open_positions=[{"symbol": "EURUSD"}],
    )
    _patch_evaluate(monkeypatch, state)  # correlation_threshold is None
    monkeypatch.setattr(risk_main, "_correlation_bars_provider", provider)

    result = await risk_main._evaluate_proposal(_proposal(), {})

    assert result["decision"] == RiskDecision.APPROVE
    assert calls == []  # default config never fetches correlation data


# ── G5 honest circuit breakers (main-side live signals) ──────────────────────

def test_breaker_session_gate_reports_actual_state(monkeypatch) -> None:
    import asyncio

    # Isolate the resolver from session-global state: an empty settings doc
    # makes session_gate_policy fall back to the caller defaults (the patched
    # ALLOW_* values), so this test asserts the BREAKER logic — not whatever a
    # previous test left in shared.runtime_settings._cache.
    import shared.runtime_settings as _rs

    async def _empty_settings(redis):
        return {}

    monkeypatch.setattr(
        risk_main, "runtime_settings",
        SimpleNamespace(get_settings=_empty_settings, session_gate_policy=_rs.session_gate_policy),
    )
    monkeypatch.setattr(risk_main, "ALLOW_OFF_HOURS", False)
    monkeypatch.setattr(risk_main, "ALLOWED_SESSIONS", {"LONDON"})
    monkeypatch.setattr(
        risk_main, "detect_session_now", lambda: SimpleNamespace(value="TOKYO"),
    )
    monkeypatch.setattr(risk_main, "redis", SimpleNamespace())  # .r missing ⇒ scans skip

    overrides = asyncio.run(risk_main._main_breaker_overrides())

    assert overrides["session_gate"]["triggered"] is True
    assert "TOKYO" in overrides["session_gate"]["reason"]

    # Off-hours allowed ⇒ no session override at all.
    monkeypatch.setattr(risk_main, "ALLOW_OFF_HOURS", True)
    overrides = asyncio.run(risk_main._main_breaker_overrides())
    assert "session_gate" not in overrides


def test_breaker_cooldowns_report_anti_stacking_and_trade_cooldown(monkeypatch) -> None:
    import asyncio
    monkeypatch.setattr(risk_main, "ALLOW_OFF_HOURS", True)
    monkeypatch.setattr(risk_main, "redis", SimpleNamespace())
    monkeypatch.setattr(
        risk_main, "_last_trade_ts_by_dir", {"EURUSD:BUY": time.monotonic()},
    )

    overrides = asyncio.run(risk_main._main_breaker_overrides())

    assert overrides["anti_stacking"]["triggered"] is True
    assert "EURUSD:BUY" in overrides["anti_stacking"]["reason"]
    assert overrides["trade_cooldown"]["triggered"] is True


@pytest.mark.asyncio
async def test_breaker_report_state_carries_fresh_counters(monkeypatch) -> None:
    monkeypatch.setattr(risk_main, "redis", SimpleNamespace())
    monkeypatch.setattr(risk_main, "_last_trade_ts_by_dir", {})
    monkeypatch.setattr(risk_main, "_current_state", {"equity": 10_000.0})
    monkeypatch.setattr(risk_main, "_daily_trade_count", 4)
    monkeypatch.setattr(risk_main, "_daily_trades_limit_observed", 5)

    report = await risk_main._breaker_report_state()

    assert report["daily_trade_count"] == 4
    assert report["max_daily_trades"] == 5
    assert isinstance(report["breaker_state"], dict)
    # The report is a copy — the shared state dict must not be mutated.
    assert "max_daily_trades" not in risk_main._current_state


def test_any_triggered_reflects_only_triggered_rows(monkeypatch) -> None:
    engine = RulesEngine()
    # Neutralize time-dependent rows so the assertion is deterministic.
    engine.check_friday_close = lambda: None          # type: ignore[method-assign]
    engine.check_news_blackout = lambda: None         # type: ignore[method-assign]

    quiet = {"equity": 10_000.0, "daily_trade_count": 1, "max_daily_trades": 5}
    rows = engine.get_active_circuit_breakers(quiet)
    # The old endpoint reported len(rows) > 0 as any_triggered — always True.
    assert len(rows) > 0
    assert any(bool(r.get("triggered")) for r in rows) is False

    breached = {"equity": 10_000.0, "daily_trade_count": 5, "max_daily_trades": 5}
    rows = engine.get_active_circuit_breakers(breached)
    assert any(bool(r.get("triggered")) for r in rows) is True


# ── Reset-day: audit row + portfolio re-baseline ─────────────────────────────

@pytest.mark.asyncio
async def test_reset_audit_writes_duckdb_row(tmp_path, monkeypatch) -> None:
    import duckdb

    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "audit.duckdb"))

    await risk_main._write_reset_audit({"daily_trade_count": 4, "equity_peak": 9_000.0})

    conn = duckdb.connect(str(tmp_path / "audit.duckdb"))
    try:
        rows = conn.execute(
            "SELECT caller, pre_clear_json FROM risk_reset_audit",
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0][0] == "api:reset-day"
    pre_clear = json.loads(rows[0][1])
    assert pre_clear["daily_trade_count"] == 4
    assert pre_clear["equity_peak"] == 9_000.0


@pytest.mark.asyncio
async def test_reset_audit_failure_never_blocks_reset(monkeypatch) -> None:
    def explode(*args, **kwargs):
        raise RuntimeError("duckdb unavailable")

    monkeypatch.setattr(risk_main, "_reset_audit_insert", explode)
    # Log-and-continue contract: no exception escapes.
    await risk_main._write_reset_audit({"equity": 1.0})


@pytest.mark.asyncio
async def test_rebaseline_portfolio_state_clears_peak_and_series(monkeypatch) -> None:
    fake = FakeRedis()
    fake.store[risk_main._EQUITY_PEAK_KEY] = "9_999"
    fake.lists[risk_main._EQUITY_SERIES_KEY] = [
        json.dumps({"day": "2026-01-01", "equity": 11_000}),
        json.dumps({"day": "2026-01-02", "equity": 10_400}),
    ]
    monkeypatch.setattr(risk_main, "redis", SimpleNamespace(r=fake))
    monkeypatch.setattr(risk_main, "_equity_peak", 11_000.0)
    monkeypatch.setattr(risk_main, "_equity_peak_day", "2026-01-01")
    monkeypatch.setattr(risk_main, "_current_state", {
        "equity_peak": 11_000.0,
        "dd_from_peak_pct": 6.0,
        "weekly_dd_pct": 5.7,
    })

    await risk_main._rebaseline_portfolio_state(10_000.0)

    assert risk_main._equity_peak == 10_000.0
    assert risk_main._current_state["equity_peak"] == 10_000.0
    assert risk_main._current_state["dd_from_peak_pct"] == 0.0
    assert risk_main._current_state["weekly_dd_pct"] == 0.0
    assert risk_main._current_state["weekly_dd_source"] == "equity_series"
    # The series restarts with a single today entry anchored at the new equity.
    assert len(fake.lists[risk_main._EQUITY_SERIES_KEY]) == 1
    only = json.loads(fake.lists[risk_main._EQUITY_SERIES_KEY][0])
    assert only["equity"] == 10_000.0
