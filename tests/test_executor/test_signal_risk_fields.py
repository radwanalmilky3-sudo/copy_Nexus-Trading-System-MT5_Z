"""Tests for Phase 5أ signal risk fields (atr/stop_atr/target_atr/...).

Covers:
(a) fields None → SL/TP identical to the pre-change pass-through path
(b) atr + stop_atr/target_atr present → SL/TP derived from ATR, correct
    direction for BUY and SELL
(c) atr = 0 / None → fallback to the caller's SL/TP
(d) shared model defaults: SignalEvent / SignalContract construct without
    the new fields; all None; reason == ""
"""
from __future__ import annotations

from datetime import datetime, timezone

from services.nexus_executor.main import _derive_sl_tp_from_signal_risk
from shared.events import SignalEvent, parse_event
from shared.research_contracts import Eligibility, SignalContract


# ── (a) fields None → byte-identical to the old pass-through path ────────────

class TestFallbackUnchanged:
    def test_all_risk_fields_none_returns_original_sl_tp(self):
        # Old code path: sl/tp from the event data are used verbatim.
        old_sl, old_tp = 2490.0, 2520.0
        sl, tp = _derive_sl_tp_from_signal_risk(
            "BUY", 2500.0, None, None, None, old_sl, old_tp,
        )
        assert sl == old_sl
        assert tp == old_tp

    def test_sell_side_none_fields_returns_original_sl_tp(self):
        old_sl, old_tp = 2510.0, 2480.0
        sl, tp = _derive_sl_tp_from_signal_risk(
            "SELL", 2500.0, None, None, None, old_sl, old_tp,
        )
        assert sl == old_sl
        assert tp == old_tp

    def test_zero_sl_tp_with_no_risk_fields_stays_zero(self):
        sl, tp = _derive_sl_tp_from_signal_risk(
            "BUY", 2500.0, None, None, None, 0.0, 0.0,
        )
        assert sl == 0.0
        assert tp == 0.0


# ── (b) atr + stop_atr/target_atr present → ATR-derived SL/TP ────────────────

class TestAtrDerivation:
    def test_buy_direction_sl_below_entry_tp_above(self):
        entry, atr, stop_mult, target_mult = 2500.0, 10.0, 2.0, 3.0
        sl, tp = _derive_sl_tp_from_signal_risk(
            "BUY", entry, atr, stop_mult, target_mult, 0.0, 0.0,
        )
        assert sl == entry - atr * stop_mult   # 2480.0
        assert tp == entry + atr * target_mult # 2530.0
        assert sl < entry < tp

    def test_sell_direction_sl_above_entry_tp_below(self):
        entry, atr, stop_mult, target_mult = 2500.0, 10.0, 2.0, 3.0
        sl, tp = _derive_sl_tp_from_signal_risk(
            "SELL", entry, atr, stop_mult, target_mult, 0.0, 0.0,
        )
        assert sl == entry + atr * stop_mult   # 2520.0
        assert tp == entry - atr * target_mult # 2470.0
        assert sl > entry > tp

    def test_derivation_overrides_existing_sl_tp(self):
        # The plan: IF risk fields non-NULL and atr > 0 → derive from ATR.
        sl, tp = _derive_sl_tp_from_signal_risk(
            "BUY", 1.1000, 0.0012, 2.5, 4.0, 1.0900, 1.1200,
        )
        assert abs(sl - (1.1000 - 0.0012 * 2.5)) < 1e-12
        assert abs(tp - (1.1000 + 0.0012 * 4.0)) < 1e-12

    def test_string_side_case_insensitive(self):
        sl, tp = _derive_sl_tp_from_signal_risk(
            "buy", 2500.0, 10.0, 2.0, 3.0, 0.0, 0.0,
        )
        assert sl == 2480.0
        assert tp == 2530.0


# ── (c) atr = 0 / None → fallback ────────────────────────────────────────────

class TestAtrFallback:
    def test_atr_zero_falls_back(self):
        old_sl, old_tp = 2490.0, 2520.0
        sl, tp = _derive_sl_tp_from_signal_risk(
            "BUY", 2500.0, 0.0, 2.0, 3.0, old_sl, old_tp,
        )
        assert sl == old_sl
        assert tp == old_tp

    def test_atr_none_falls_back_even_with_multiples(self):
        old_sl, old_tp = 2490.0, 2520.0
        sl, tp = _derive_sl_tp_from_signal_risk(
            "BUY", 2500.0, None, 2.0, 3.0, old_sl, old_tp,
        )
        assert sl == old_sl
        assert tp == old_tp

    def test_stop_atr_none_keeps_sl_derives_tp(self):
        # Only target_atr present → only TP is derived; SL passes through.
        old_sl = 2490.0
        sl, tp = _derive_sl_tp_from_signal_risk(
            "BUY", 2500.0, 10.0, None, 3.0, old_sl, 0.0,
        )
        assert sl == old_sl
        assert tp == 2530.0

    def test_target_atr_none_keeps_tp_derives_sl(self):
        old_tp = 2520.0
        sl, tp = _derive_sl_tp_from_signal_risk(
            "BUY", 2500.0, 10.0, 2.0, None, 0.0, old_tp,
        )
        assert sl == 2480.0
        assert tp == old_tp

    def test_non_positive_stop_atr_ignored(self):
        old_sl = 2490.0
        sl, _ = _derive_sl_tp_from_signal_risk(
            "BUY", 2500.0, 10.0, -1.0, 3.0, old_sl, 0.0,
        )
        assert sl == old_sl

    def test_entry_zero_falls_back(self):
        old_sl, old_tp = 2490.0, 2520.0
        sl, tp = _derive_sl_tp_from_signal_risk(
            "BUY", 0.0, 10.0, 2.0, 3.0, old_sl, old_tp,
        )
        assert sl == old_sl
        assert tp == old_tp

    def test_nan_atr_falls_back(self):
        import math
        old_sl, old_tp = 2490.0, 2520.0
        sl, tp = _derive_sl_tp_from_signal_risk(
            "BUY", 2500.0, math.nan, 2.0, 3.0, old_sl, old_tp,
        )
        assert sl == old_sl
        assert tp == old_tp


# ── (d) shared model defaults ────────────────────────────────────────────────

class TestSharedModelDefaults:
    def test_signal_event_defaults(self):
        e = SignalEvent(symbol="XAUUSD", direction="BUY", confidence=0.9)
        assert e.atr is None
        assert e.stop_atr is None
        assert e.target_atr is None
        assert e.max_holding_hours is None
        assert e.group_id is None
        assert e.reason == ""

    def test_signal_event_with_risk_fields(self):
        e = SignalEvent(
            symbol="XAUUSD", direction="BUY", confidence=0.9,
            atr=25.0, stop_atr=2.0, target_atr=3.0,
            max_holding_hours=4.0, group_id="g-1", reason="breakout",
        )
        assert e.atr == 25.0
        assert e.stop_atr == 2.0
        assert e.target_atr == 3.0
        assert e.max_holding_hours == 4.0
        assert e.group_id == "g-1"
        assert e.reason == "breakout"

    def test_signal_event_stream_round_trip_none_fields(self):
        e = SignalEvent(symbol="XAUUSD", direction="BUY", confidence=0.9)
        restored = parse_event(e.to_stream_dict())
        assert isinstance(restored, SignalEvent)
        assert restored.atr is None
        assert restored.stop_atr is None
        assert restored.target_atr is None
        assert restored.max_holding_hours is None
        assert restored.group_id is None
        assert restored.reason == ""

    def test_signal_event_stream_round_trip_populated_fields(self):
        e = SignalEvent(
            symbol="XAUUSD", direction="BUY", confidence=0.9,
            atr=25.0, stop_atr=2.0, target_atr=3.0, group_id="g-1",
        )
        restored = parse_event(e.to_stream_dict())
        assert isinstance(restored, SignalEvent)
        assert restored.atr == 25.0
        assert restored.stop_atr == 2.0
        assert restored.target_atr == 3.0
        assert restored.group_id == "g-1"

    def _make_contract(self, **overrides) -> SignalContract:
        base = dict(
            run_id="run-1",
            available_at=datetime.now(timezone.utc),
            vintage_id="v-1",
            PIT=True,
            eligibility=Eligibility.ELIGIBLE,
            cost_complete=True,
            signal_id="sig-1",
            symbol="XAUUSD",
            direction="BUY",
            confidence=0.9,
        )
        base.update(overrides)
        return SignalContract(**base)

    def test_signal_contract_defaults(self):
        c = self._make_contract()
        assert c.atr is None
        assert c.stop_atr is None
        assert c.target_atr is None
        assert c.max_holding_hours is None
        assert c.group_id is None
        assert c.reason == ""

    def test_signal_contract_with_risk_fields(self):
        c = self._make_contract(
            atr=25.0, stop_atr=2.0, target_atr=3.0,
            max_holding_hours=4.0, group_id="g-1", reason="trend",
        )
        assert c.atr == 25.0
        assert c.stop_atr == 2.0
        assert c.target_atr == 3.0
        assert c.max_holding_hours == 4.0
        assert c.group_id == "g-1"
        assert c.reason == "trend"
