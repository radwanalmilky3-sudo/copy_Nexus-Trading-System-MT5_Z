"""Task 9 Phase-2 prep — ML surface honesty contracts (Agent 4).

Every test here passes TODAY with no trained models, no nexus-ml service
running, and no historical data. They pin honesty contracts only:

1. The gateway ML proxy surfaces the REAL failure (unreachable service,
   missing secret, upstream error body) — it never fabricates a prediction.
2. Untrained traders answer NO_TRADE with explicit reasoning at confidence
   0.0 — never a canned BUY/SELL.
3. The trading-mode module is a SCALPING/SWING strategy profile switch — it
   has no paper/live/auto-trade surface.
4. The rule-based fallback is honest NO_TRADE on empty evidence.

NOT CLAIMED here: trained-model accuracy, real-data performance, or any
walk-forward/backtest result (blocked until approved historical data / Task 7).
"""
from __future__ import annotations

import asyncio
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest
from fastapi import HTTPException

from services.nexus_api.routers import ml as ml_router


# ── Gateway proxy honesty ────────────────────────────────────────────────────

def test_proxy_unreachable_service_returns_honest_502(monkeypatch):
    """nexus-ml down → 502 'nexus-ml unreachable', never a fabricated payload."""
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "contract-test-secret")
    monkeypatch.setattr(ml_router, "ML_BASE", "http://127.0.0.1:9")  # closed port

    with pytest.raises(HTTPException) as exc:
        asyncio.run(ml_router._proxy("GET", "/api/ml/models/status"))

    assert exc.value.status_code == 502
    detail = json.dumps(exc.value.detail) if not isinstance(exc.value.detail, str) else exc.value.detail
    assert "nexus-ml unreachable" in detail
    # No prediction-shaped fields may leak through on failure.
    for token in ("direction", "BUY", "SELL", "confidence"):
        assert token not in detail


def test_proxy_missing_internal_secret_returns_honest_503(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(ml_router._proxy("GET", "/api/ml/models/status"))

    assert exc.value.status_code == 503
    assert "NEXUS_INTERNAL_API_SECRET is not configured" in str(exc.value.detail)


class _UpstreamErrorHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = json.dumps({"detail": "no models fitted — directory empty"}).encode()
        self.send_response(503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence test server
        pass


def test_proxy_passes_upstream_error_status_and_body_unchanged(monkeypatch):
    """Honesty is not masked: an upstream 503 + explanation reaches the caller."""
    server = HTTPServer(("127.0.0.1", 0), _UpstreamErrorHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "contract-test-secret")
        monkeypatch.setattr(ml_router, "ML_BASE", f"http://127.0.0.1:{server.server_port}")

        with pytest.raises(HTTPException) as exc:
            asyncio.run(ml_router._proxy("GET", "/api/ml/models/status"))
    finally:
        server.shutdown()

    assert exc.value.status_code == 503
    assert "no models fitted" in str(exc.value.detail)


# ── Untrained trader honesty (no model artifacts touched) ────────────────────

def test_ml_trader_untrained_predict_is_no_trade_with_explicit_reason():
    from services.nexus_ml.traders.ml_trader import MLTrader

    trader = MLTrader()  # __init__ is path/threshold only — no fitting, no IO
    sig = trader.predict({"rsi": 50.0, "ema_9": 1.0}, symbol="XAUUSD")

    assert sig.direction == "NO_TRADE"
    assert sig.confidence == 0.0
    assert "not trained" in sig.reasoning.lower()


def test_dl_trader_untrained_predict_is_honest_no_trade():
    from services.nexus_ml.traders.dl_trader import DLTrader

    # Bypass __init__ (may touch torch/session state); pin the untrained
    # contract branch exactly as shipped: unfitted ⇒ honest NO_TRADE.
    trader = object.__new__(DLTrader)
    trader._is_fitted = False
    trader._model = None
    trader.model_name = "CONTRACT_PROBE"

    sig = trader.predict({"rsi": 50.0}, symbol="XAUUSD")

    assert sig.direction == "NO_TRADE"
    assert sig.confidence == 0.0
    assert "not trained" in sig.reasoning.lower()


def test_rl_trader_untrained_predict_is_honest_no_trade():
    from services.nexus_ml.traders.rl_trader import RLTrader

    trader = object.__new__(RLTrader)
    trader._is_fitted = False
    trader._model = None
    trader.model_name = "CONTRACT_PROBE"

    sig = trader.predict({"rsi": 50.0}, symbol="XAUUSD")

    assert sig.direction == "NO_TRADE"
    assert sig.confidence == 0.0
    assert "not trained" in sig.reasoning.lower()


# ── Rule-based fallback honesty ──────────────────────────────────────────────

def test_rule_based_fallback_empty_evidence_is_no_trade():
    from services.nexus_ml.rule_based_signal import RuleBasedSignalGenerator

    sig = RuleBasedSignalGenerator().predict({})

    assert sig.direction == "NO_TRADE"
    assert sig.confidence == 0.0


# ── Trading-mode surface safety inventory ────────────────────────────────────

def test_trading_mode_is_scalping_or_swing_only_with_no_live_surface():
    """trading_mode.py is a strategy-profile switch. It must never expose a
    paper/live or auto-trade toggle, and its enum cannot hold 'live'."""
    from services.nexus_ml.traders import trading_mode as tm

    assert tm.get_current_mode() in (tm.TradingMode.SCALPING, tm.TradingMode.SWING)
    with pytest.raises(ValueError):
        tm.TradingMode("live")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        tm.TradingMode("paper")  # type: ignore[arg-type]

    # Source-level safety inventory: no paper/live execution-mode concept.
    source = (tm.__file__ or "").strip()
    assert source
    from pathlib import Path

    text = Path(source).read_text(encoding="utf-8", errors="ignore").lower()
    for banned in ("auto_trade", "live_mode", "paper_mode", "real_money"):
        assert banned not in text, f"trading_mode.py must not contain {banned!r}"

    # Round-trip switch stays inside the two strategy profiles.
    original = tm.get_current_mode()
    try:
        tm.switch_mode(tm.TradingMode.SWING)
        assert tm.get_current_mode() == tm.TradingMode.SWING
        cfg = tm.get_current_config()
        assert 0.0 < cfg.risk_per_trade <= 0.05
    finally:
        tm.switch_mode(original)
    assert tm.get_current_mode() == original
