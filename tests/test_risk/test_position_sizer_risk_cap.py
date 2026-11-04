from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.nexus_risk import main as risk_main
from services.nexus_risk.position_sizer import PositionSizer
from services.nexus_risk.rules_engine import RulesEngine
from shared.constants import RiskDecision
from shared.models import TradeProposal, Verdict


def test_minimum_lot_does_not_override_risk_budget() -> None:
    sizing = PositionSizer().calculate_size(
        balance=1_000,
        risk_pct=1.0,
        entry=2_500,
        sl=2_400,
        symbol="XAUUSD",
        vol_regime="low",
        session="london",
    )

    assert sizing.lots == 0
    assert sizing.risk_pct_used == 0
    assert "minimum" in sizing.reason.lower()


@pytest.mark.parametrize(
    ("symbol", "balance", "entry", "sl", "lots", "expected_pct"),
    [
        ("XAUUSD", 10_000, 2_500, 2_490, 0.10, 1.0),
        ("EURUSD", 10_000, 1.1000, 1.0990, 0.10, 0.1),
    ],
)
def test_rules_engine_risk_check_uses_symbol_contract_value(
    symbol: str,
    balance: float,
    entry: float,
    sl: float,
    lots: float,
    expected_pct: float,
) -> None:
    violation = RulesEngine().check_max_risk_per_trade(
        lots, entry, sl, balance, symbol=symbol
    )

    assert violation is None
    assert RulesEngine().risk_pct_for_size(lots, entry, sl, balance, symbol) == pytest.approx(expected_pct)


def test_rules_engine_rejects_actual_lots_over_limit() -> None:
    violation = RulesEngine().check_max_risk_per_trade(
        size=0.21,
        entry=2_500,
        sl=2_490,
        balance=10_000,
        symbol="XAUUSD",
    )

    assert violation is not None
    assert violation.current_value == 2.1


def test_risk_budget_lot_cap_is_rounded_down_and_asset_aware() -> None:
    sizing = PositionSizer()

    assert sizing.max_lots_for_risk(10_000, 2_500, 2_490, "XAUUSD", 1.0) == pytest.approx(0.10)
    assert sizing.max_lots_for_risk(10_000, 1.1000, 1.0990, "EURUSD", 1.0) == pytest.approx(1.0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("metrics", "expected_size", "expected_risk_pct"),
    [
        ({"win_rate": 0.9, "net_pnl_usd": 100}, 0.10, 1.0),
    ],
)
async def test_final_risk_approval_cannot_exceed_budget_after_multipliers(
    monkeypatch, metrics, expected_size, expected_risk_pct
) -> None:
    class FakeRedis:
        async def cache_get(self, key, **kwargs):
            if key == "system:auto_trade":
                return True
            if key == "fundamental:blackout":
                return {"state": "clear", "active": False}
            if key == "nexus:trade_memory:metrics":
                return {"overall": metrics}
            raise AssertionError(f"unexpected cache key: {key}")

    async def return_none(*args, **kwargs):
        return None

    async def no_cooldown(*args, **kwargs):
        return 0.0

    async def no_multiplier(*args, **kwargs):
        return 1.0, {"multiplier": 1.0}

    async def get_settings(redis):
        return {"risk_per_trade_pct": 1.0, "max_daily_trades": 0}

    monkeypatch.setattr(risk_main, "redis", SimpleNamespace(cache_get=FakeRedis().cache_get))
    # Real session-gate resolver (stub predates session_gate_policy); the
    # patched ALLOW_* values act as the caller's env-derived defaults.
    import shared.runtime_settings as _rs

    monkeypatch.setattr(
        risk_main, "runtime_settings",
        SimpleNamespace(get_settings=get_settings, session_gate_policy=_rs.session_gate_policy),
    )
    monkeypatch.setattr(risk_main, "position_sizer", PositionSizer())
    monkeypatch.setattr(risk_main, "rules_engine", RulesEngine())
    monkeypatch.setattr(risk_main, "ALLOW_OFF_HOURS", True)
    monkeypatch.setattr(risk_main, "_check_circuit_breaker", return_none)
    monkeypatch.setattr(risk_main, "_check_ergodic_circuit_breaker", return_none)
    monkeypatch.setattr(risk_main, "_get_ergodic_lot_multiplier", no_multiplier)
    monkeypatch.setattr(risk_main, "_stack_cooldown_remaining", no_cooldown)
    monkeypatch.setattr(risk_main, "_direction_block_remaining", no_cooldown)
    monkeypatch.setattr(risk_main, "_mark_stack_cooldown", return_none)
    monkeypatch.setattr(risk_main, "_persist_daily_count", return_none)
    monkeypatch.setattr(risk_main, "_daily_trade_count", 0)
    monkeypatch.setattr(
        risk_main,
        "_current_state",
        {
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
        },
    )

    proposal = TradeProposal(
        symbol="XAUUSD",
        direction=Verdict.BUY,
        entry=2_500,
        sl=2_490,
        tp1=2_520,
        conviction=0.9,
    )

    result = await risk_main._evaluate_proposal(proposal, {})

    assert result["decision"] == RiskDecision.APPROVE
    assert result["approved_size"] == pytest.approx(expected_size)
    assert result["sizing"]["risk_pct_used"] == pytest.approx(expected_risk_pct)
