from __future__ import annotations

import json

import httpx
import pytest
from conftest import make_bars

from fx_system.brokers.oanda import OandaPracticeBroker
from fx_system.config import SystemConfig
from fx_system.data import SyntheticFXProvider
from fx_system.engine import BacktestEngine
from fx_system.models import Side, Signal
from fx_system.planner import create_paper_plan
from fx_system.reporting import write_backtest_artifacts


def test_oanda_adapter_hard_blocks_live_endpoint_and_unconfirmed_orders() -> None:
    with pytest.raises(ValueError, match="live trading is disabled"):
        OandaPracticeBroker("acct", "token", base_url="https://api-fxtrade.oanda.com")
    broker = OandaPracticeBroker(
        "acct", "token", transport=httpx.MockTransport(lambda request: None)
    )
    with pytest.raises(PermissionError):
        broker.submit_market_order("EURUSD", 1000, 1.0, 1.1, "test")
    broker.close()


def test_oanda_practice_payload_uses_attached_protection() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(201, json={"orderCreateTransaction": {"id": "42"}})

    with OandaPracticeBroker("acct", "token", transport=httpx.MockTransport(handler)) as broker:
        response = broker.submit_market_order(
            "USDJPY", -1000, 151.2, 150.2, "pytest", confirm_practice=True
        )
    assert response["orderCreateTransaction"]["id"] == "42"
    order = captured["order"]
    assert order["instrument"] == "USD_JPY"
    assert order["stopLossOnFill"]["price"] == "151.200"
    assert order["takeProfitOnFill"]["price"] == "150.200"
    assert order["clientExtensions"]["id"] == "pytest"


def test_reporting_writes_reproducible_manifest(tmp_path) -> None:
    config = SystemConfig.from_yaml("configs/demo.yaml")
    data = SyntheticFXProvider(seed=1).generate(config.data.symbols, bars=100, interval="4h")
    result = BacktestEngine(config.risk, config.costs).run(data, [])
    output = write_backtest_artifacts(result, [], data, config, tmp_path)
    manifest = json.loads((output / "run_manifest.json").read_text())
    metrics = json.loads((output / "metrics.json").read_text())
    assert len(manifest["data_fingerprint_sha256"]) == 64
    assert manifest["symbols"] == sorted(config.data.symbols)
    assert metrics["trades"] == 0


def test_paper_plan_requires_strategy_approval_and_has_idempotency_key(monkeypatch) -> None:
    config = SystemConfig.from_yaml("configs/demo.yaml")
    bars = make_bars([(1, 1.01, 0.99, 1)] * 3)
    signal = Signal(bars.index[-1], "EURUSD", Side.LONG, 0.8, "trend_pullback", 0.01, 1.2, 0.8, 24)
    monkeypatch.setattr(
        "fx_system.planner.generate_ensemble_signals",
        lambda data, config, selected: ([signal], [signal]),
    )
    assert create_paper_plan({"EURUSD": bars}, config) == []
    plan = create_paper_plan({"EURUSD": bars}, config, include_unapproved=True)
    assert len(plan) == 1
    assert len(plan[0].proposal_id) == 32
    assert plan[0].expires_at > plan[0].signal_timestamp
