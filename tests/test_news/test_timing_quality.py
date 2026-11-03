"""Phase 4 timing-quality rules for the canonical news blackout engine.

Covers: legacy-literal gate, date-only full-civil-day blackout, unverified
timing block, cancelled/superseded append-only blocking, and reason codes.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from services.nexus_news.fundamental.blackout import (
    DATE_ONLY_TIMING_QUALITIES,
    REASON_DATE_ONLY_DAY_BLACKOUT,
    REASON_EVENT_CANCELLED,
    REASON_TIMING_UNVERIFIED,
    UNVERIFIED_TIMING_QUALITIES,
    VERIFIED_TIMING_QUALITIES,
    BlackoutEngine,
    civil_day_window,
    event_carries_timing_fields,
)

UTC = timezone.utc

LEGACY_KEYS = {
    "blackout_id", "event_id", "active", "state", "starts_at", "ends_at",
    "impact", "reason_code", "reason", "reason_ar", "policy_version", "checked_at",
}
CLEAR_KEYS = {
    "blackout_id", "active", "state", "reason_code", "reason", "reason_ar",
    "policy_version", "checked_at",
}

NOW = datetime(2026, 3, 12, 12, 0, tzinfo=UTC)


def _legacy_event(**overrides):
    event = {
        "event_id": "nfp-legacy",
        "event_name": "Non-Farm Payrolls",
        "impact": "high",
        "timestamp": NOW + timedelta(minutes=5),
    }
    event.update(overrides)
    return event


class TestLegacyPayloadGate:
    """(a)+(d) Payloads without new fields keep the pre-Phase-4 decisions."""

    def test_legacy_high_impact_active_window_is_unchanged(self):
        state = BlackoutEngine().evaluate([_legacy_event()], now=NOW)
        assert state["active"] is True
        assert state["state"] == "active"
        assert state["reason_code"] == "NEWS_BLACKOUT"
        assert state["starts_at"] == "2026-03-12T11:35:00+00:00"
        assert state["ends_at"] == "2026-03-12T12:35:00+00:00"
        assert set(state) == LEGACY_KEYS

    def test_legacy_empty_calendar_is_clear_with_legacy_shape(self):
        state = BlackoutEngine().evaluate([], now=NOW)
        assert state["active"] is False
        assert state["state"] == "clear"
        assert state["reason_code"] == "CLEAR"
        assert set(state) == CLEAR_KEYS

    def test_legacy_missing_time_is_degraded_not_clear(self):
        state = BlackoutEngine().evaluate([_legacy_event(timestamp=None)], now=NOW)
        assert state["state"] == "degraded"
        assert state["reason_code"] == "CALENDAR_DEGRADED"
        assert state["active"] is False

    def test_legacy_bare_date_keeps_midnight_utc_minute_window(self):
        # Pre-Phase-4 behavior: a bare date is parsed as naive UTC midnight and
        # gets a small window — Phase 4 must not change that for legacy rows.
        state = BlackoutEngine().evaluate(
            [_legacy_event(timestamp="2026-03-12")], now=datetime(2026, 3, 12, 0, 10, tzinfo=UTC)
        )
        assert state["active"] is True
        assert state["reason_code"] == "NEWS_BLACKOUT"
        assert state["starts_at"] == "2026-03-11T23:30:00+00:00"
        assert state["ends_at"] == "2026-03-12T00:30:00+00:00"

    def test_default_negative_new_fields_behave_like_legacy(self):
        legacy = BlackoutEngine().evaluate([_legacy_event()], now=NOW)
        passthrough = BlackoutEngine().evaluate(
            [_legacy_event(timing_quality=None, cancelled=0, release_tzid=None, authority=None)],
            now=NOW,
        )
        assert passthrough == legacy

    def test_activation_gate_ignores_empty_and_default_negative(self):
        assert event_carries_timing_fields(_legacy_event()) is False
        assert event_carries_timing_fields(_legacy_event(cancelled=0)) is False
        assert event_carries_timing_fields(_legacy_event(timing_quality="")) is False
        assert event_carries_timing_fields(_legacy_event(timing_quality="exact")) is True


class TestDateOnlyFullDayBlackout:
    """(b) rule a — full civil day in the event zone, no invented minute."""

    def test_date_only_high_impact_blocks_full_new_york_civil_day(self):
        # 2026-03-12 in America/New_York is EDT (UTC-4): day = 04:00Z -> 04:00Z.
        event = {
            "event_id": "cpi-day",
            "event_name": "CPI",
            "impact": "high",
            "timing_quality": "date_only",
            "decision_date_local": "2026-03-12",
            "release_tzid": "America/New_York",
        }
        state = BlackoutEngine().evaluate([event], now=NOW)
        assert state["active"] is True
        assert state["state"] == "active"
        assert state["reason_code"] == REASON_DATE_ONLY_DAY_BLACKOUT
        assert state["starts_at"] == "2026-03-12T04:00:00+00:00"
        assert state["ends_at"] == "2026-03-13T04:00:00+00:00"
        assert state["window_kind"] == "civil_day"
        assert REASON_DATE_ONLY_DAY_BLACKOUT in state["reason_codes"]

    def test_date_only_window_is_exactly_local_midnight_to_midnight(self):
        from datetime import date
        from zoneinfo import ZoneInfo
        start, end = civil_day_window(date(2026, 3, 12), ZoneInfo("America/New_York"))
        assert start == datetime(2026, 3, 12, 4, 0, tzinfo=UTC)
        assert end - start == timedelta(hours=24)

    def test_date_only_block_persists_until_local_midnight(self):
        event = {
            "event_id": "cpi-day",
            "event_name": "CPI",
            "impact": "high",
            "timing_quality": "date_only",
            "decision_date_local": "2026-03-12",
            "release_tzid": "America/New_York",
        }
        engine = BlackoutEngine()
        just_before = engine.evaluate([event], now=datetime(2026, 3, 13, 3, 59, 59, tzinfo=UTC))
        assert just_before["active"] is True
        just_after = engine.evaluate([event], now=datetime(2026, 3, 13, 4, 0, 1, tzinfo=UTC))
        assert just_after["state"] == "clear"

    def test_date_only_without_tz_falls_back_to_utc_day(self):
        event = {
            "event_id": "ppi-day",
            "event_name": "PPI",
            "impact": "high",
            "timing_quality": "date_only",
            "decision_date_local": "2026-03-12",
        }
        state = BlackoutEngine().evaluate([event], now=NOW)
        assert state["starts_at"] == "2026-03-12T00:00:00+00:00"
        assert state["ends_at"] == "2026-03-13T00:00:00+00:00"
        assert state["release_tzid"] == "UTC"

    def test_missing_time_component_with_civil_date_is_date_only(self):
        # timing_quality absent but decision_date_local without any clock time.
        event = {
            "event_id": "gdp-day",
            "event_name": "GDP",
            "impact": "high",
            "decision_date_local": "2026-03-12",
            "release_tzid": "America/New_York",
            "authority": "BEA",
        }
        state = BlackoutEngine().evaluate([event], now=NOW)
        assert state["reason_code"] == REASON_DATE_ONLY_DAY_BLACKOUT
        assert state["starts_at"] == "2026-03-12T04:00:00+00:00"

    def test_medium_impact_date_only_blocks_full_civil_day(self):
        event = {
            "event_id": "retail-day",
            "event_name": "Retail Sales",
            "impact": "medium",
            "timing_quality": "date_only",
            "decision_date_local": "2026-03-12",
            "release_tzid": "Europe/Berlin",
        }
        # Berlin is CET (UTC+1) on 2026-03-12 (DST starts 2026-03-29).
        state = BlackoutEngine().evaluate([event], now=datetime(2026, 3, 12, 10, 0, tzinfo=UTC))
        assert state["active"] is True
        assert state["reason_code"] == REASON_DATE_ONLY_DAY_BLACKOUT
        assert state["starts_at"] == "2026-03-11T23:00:00+00:00"
        assert state["ends_at"] == "2026-03-12T23:00:00+00:00"

    def test_low_impact_date_only_stays_clear(self):
        event = {
            "event_id": "low-day",
            "event_name": "Inventory Data",
            "impact": "low",
            "timing_quality": "date_only",
            "decision_date_local": "2026-03-12",
        }
        state = BlackoutEngine().evaluate([event], now=NOW)
        assert state["state"] == "clear"
        assert state["active"] is False


class TestUnverifiedTimingBlocks:
    """(b) rule — unverified timing is not clear; trading is blocked."""

    def test_explicit_unverified_quality_blocks_high_impact(self):
        event = _legacy_event(timing_quality="unknown")
        state = BlackoutEngine().evaluate([event], now=NOW)
        assert state["active"] is True
        assert state["state"] == "unverified_timing"
        assert state["state"] != "clear"
        assert state["reason_code"] == REASON_TIMING_UNVERIFIED
        assert REASON_TIMING_UNVERIFIED in state["reason_codes"]

    def test_enriched_payload_with_null_quality_blocks(self):
        # New fields present (authority set) but timing_quality NULL -> fail closed.
        event = _legacy_event(authority="BLS")
        state = BlackoutEngine().evaluate([event], now=NOW)
        assert state["state"] == "unverified_timing"
        assert state["active"] is True
        assert state["reason_code"] == REASON_TIMING_UNVERIFIED

    def test_unverified_block_is_time_scoped_not_permanent(self):
        event = _legacy_event(
            timing_quality="unknown",
            timestamp=NOW - timedelta(hours=3),
        )
        state = BlackoutEngine().evaluate([event], now=NOW)
        assert state["state"] == "clear"

    def test_verified_quality_keeps_normal_news_blackout(self):
        event = _legacy_event(timing_quality="exact", authority="BLS")
        state = BlackoutEngine().evaluate([event], now=NOW)
        assert state["state"] == "active"
        assert state["reason_code"] == "NEWS_BLACKOUT"
        assert state["starts_at"] == "2026-03-12T11:35:00+00:00"

    def test_c1_verified_tokens_keep_normal_window(self):
        for token in ("verified_actual_publication", "official_event_scheduled_time", "official_rule_derived"):
            state = BlackoutEngine().evaluate([_legacy_event(timing_quality=token)], now=NOW)
            assert state["reason_code"] == "NEWS_BLACKOUT", token
            assert state["state"] == "active", token

    def test_c1_official_date_only_blocks_full_civil_day(self):
        event = _legacy_event(
            timing_quality="official_date_only",
            decision_date_local="2026-03-12",
            release_tzid="America/New_York",
        )
        state = BlackoutEngine().evaluate([event], now=NOW)
        assert state["reason_code"] == REASON_DATE_ONLY_DAY_BLACKOUT
        assert state["starts_at"] == "2026-03-12T04:00:00+00:00"
        assert state["ends_at"] == "2026-03-13T04:00:00+00:00"

    def test_c1_unverified_external_blocks(self):
        state = BlackoutEngine().evaluate([_legacy_event(timing_quality="unverified_external")], now=NOW)
        assert state["state"] == "unverified_timing"
        assert state["reason_code"] == REASON_TIMING_UNVERIFIED

    def test_token_sets_do_not_overlap(self):
        assert DATE_ONLY_TIMING_QUALITIES.isdisjoint(VERIFIED_TIMING_QUALITIES)
        assert DATE_ONLY_TIMING_QUALITIES.isdisjoint(UNVERIFIED_TIMING_QUALITIES)
        assert VERIFIED_TIMING_QUALITIES.isdisjoint(UNVERIFIED_TIMING_QUALITIES)


class TestCancelledAndSuperseded:
    """(c) cancelled/superseded rows block; the view stays append-only."""

    def test_cancelled_flag_blocks_with_event_cancelled(self):
        event = _legacy_event(cancelled=1)
        state = BlackoutEngine().evaluate([event], now=NOW)
        assert state["active"] is True
        assert state["state"] == "active"
        assert state["reason_code"] == REASON_EVENT_CANCELLED
        assert REASON_EVENT_CANCELLED in state["reason_codes"]

    def test_scheduled_status_cancelled_blocks(self):
        event = _legacy_event(scheduled_status="cancelled")
        state = BlackoutEngine().evaluate([event], now=NOW)
        assert state["reason_code"] == REASON_EVENT_CANCELLED
        assert state["active"] is True

    def test_scheduled_status_superseded_blocks(self):
        event = _legacy_event(scheduled_status="superseded")
        state = BlackoutEngine().evaluate([event], now=NOW)
        assert state["reason_code"] == REASON_EVENT_CANCELLED
        assert state["active"] is True

    def test_superseded_row_stays_blocking_next_to_replacement(self):
        old = _legacy_event(event_id="cpi-old", timing_quality="exact")
        replacement = _legacy_event(
            event_id="cpi-new",
            supersedes_event_id="cpi-old",
            timing_quality="exact",
        )
        state = BlackoutEngine().evaluate([old, replacement], now=NOW)
        # Append-only: never a silent "net of cancelled" pass.
        assert state["active"] is True
        assert state["state"] != "clear"
        assert state["reason_code"] == REASON_EVENT_CANCELLED
        assert state["event_id"] == "cpi-old"

    def test_c1_cancellation_marker_row_shape_stays_blocking(self):
        # C1 mark_event_cancelled(): new row with cancelled=TRUE,
        # scheduled_status='cancelled', supersedes_event_id -> original.
        original = _legacy_event(event_id="cpi-orig", timing_quality="official_event_scheduled_time")
        marker = _legacy_event(
            event_id="cpi-orig-cancel",
            supersedes_event_id="cpi-orig",
            cancelled=True,
            scheduled_status="cancelled",
            timing_quality="unverified_external",
        )
        engine = BlackoutEngine()
        for probe in (NOW, NOW + timedelta(minutes=20)):
            state = engine.evaluate([original, marker], now=probe)
            assert state["active"] is True
            assert state["state"] != "clear"
            assert state["reason_code"] == REASON_EVENT_CANCELLED

    def test_cancelled_is_not_active_outside_its_window(self):
        event = _legacy_event(cancelled=1, timestamp=NOW - timedelta(hours=3))
        state = BlackoutEngine().evaluate([event], now=NOW)
        assert state["state"] == "clear"


class TestReasonCodesAndSerialization:
    """(e) reason codes on new paths; payloads stay JSON-serializable."""

    def test_new_reason_codes_are_additive_not_replacements(self):
        assert "NEWS_BLACKOUT" not in {
            REASON_DATE_ONLY_DAY_BLACKOUT, REASON_EVENT_CANCELLED, REASON_TIMING_UNVERIFIED,
        }
        assert "CLEAR" not in {
            REASON_DATE_ONLY_DAY_BLACKOUT, REASON_EVENT_CANCELLED, REASON_TIMING_UNVERIFIED,
        }

    def test_blackout_payload_with_none_fields_serializes(self):
        event = {
            "event_id": "cpi-day",
            "event_name": "CPI",
            "impact": "high",
            "timing_quality": "date_only",
            "decision_date_local": "2026-03-12",
            "release_tzid": "America/New_York",
            "authority": None,
        }
        state = BlackoutEngine().evaluate([event], now=NOW)
        assert state["authority"] is None
        assert json.loads(json.dumps(state))["reason_code"] == REASON_DATE_ONLY_DAY_BLACKOUT

    def test_annotated_paths_carry_additive_keys_only(self):
        state = BlackoutEngine().evaluate(
            [_legacy_event(timing_quality="date_only", decision_date_local="2026-03-12")],
            now=NOW,
        )
        assert {"reason_codes", "window_kind", "timing_quality", "release_tzid", "authority"} <= set(state)
        assert set(state) - LEGACY_KEYS == {"reason_codes", "window_kind", "timing_quality", "release_tzid", "authority"}


class TestRuntimePassThrough:
    """runtime.py forwards the new fields additively; absent -> unchanged."""

    def test_calendar_event_without_new_fields_forwards_nothing(self):
        from shared.models import CalendarEvent
        from services.nexus_news.fundamental.runtime import _calendar_timing_fields

        event = CalendarEvent(event_name="CPI", currency="USD", impact="high", timestamp=NOW)
        assert _calendar_timing_fields(event) == {}

    def test_object_with_new_fields_is_forwarded_verbatim(self):
        from types import SimpleNamespace
        from services.nexus_news.fundamental.runtime import _calendar_timing_fields

        event = SimpleNamespace(
            timing_quality="date_only", release_tzid="America/New_York",
            cancelled=0, authority="BLS", decision_date_local="2026-03-12",
        )
        passed = _calendar_timing_fields(event)
        assert passed["timing_quality"] == "date_only"
        assert passed["release_tzid"] == "America/New_York"
        assert passed["authority"] == "BLS"

    def test_timing_fields_tuple_matches_blackout_contract(self):
        from services.nexus_news.fundamental.blackout import TIMING_FIELDS
        expected = {
            "timing_quality", "authority", "release_tzid", "decision_date_local",
            "scheduled_status", "supersedes_event_id", "cancelled", "source_sha256",
            "retrieved_at_utc",
        }
        assert set(TIMING_FIELDS) == expected
