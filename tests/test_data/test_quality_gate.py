from __future__ import annotations

from datetime import datetime, timezone

import pytest

from shared.models import OHLCV, Tick
from services.nexus_data.duckdb_store import (
    DataStore,
    _ohlcv_invariant_issue,
    quality_gate_enabled,
)

BAR_TS_1 = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
BAR_TS_2 = datetime(2026, 1, 5, 10, 15, tzinfo=timezone.utc)


def _base_bar() -> OHLCV:
    return OHLCV(
        symbol="XAUUSD", timeframe="M15", open=100, high=105,
        low=99, close=100, volume=10, timestamp=BAR_TS_1,
    )


def _outlier_bar() -> OHLCV:
    # +50% return and a 37% bar range: exceeds the default OutlierPolicy.
    return OHLCV(
        symbol="XAUUSD", timeframe="M15", open=100, high=155,
        low=99, close=150, volume=10, timestamp=BAR_TS_2,
    )


def test_quality_gate_flag_defaults_on_with_explicit_optout(monkeypatch):
    """Task 7 plan requires raw→clean→verify→trace: gating is the default.

    Opt out only with an explicit falsy NEXUS_QUALITY_GATE value.
    """
    monkeypatch.delenv("NEXUS_QUALITY_GATE", raising=False)
    assert quality_gate_enabled() is True, "gate must default ON per Task 7 plan"
    monkeypatch.setenv("NEXUS_QUALITY_GATE", "")
    assert quality_gate_enabled() is True, "empty value behaves like unset"
    for optout in ("0", "false", "FALSE", "off"):
        monkeypatch.setenv("NEXUS_QUALITY_GATE", optout)
        assert quality_gate_enabled() is False, optout
    monkeypatch.setenv("NEXUS_QUALITY_GATE", "1")
    assert quality_gate_enabled() is True


@pytest.mark.asyncio
async def test_gate_default_quarantines_outlier_without_explicit_env(tmp_path, monkeypatch):
    """With no env set, writes validate + quarantine: raw kept, outlier skipped."""
    monkeypatch.delenv("NEXUS_QUALITY_GATE", raising=False)
    store = DataStore(db_path=str(tmp_path / "gate-default.duckdb"))
    await store.init_tables()

    try:
        submitted = await store.insert_ohlcv_batch([_base_bar(), _outlier_bar()])

        assert submitted == 1
        rows = await store.query_ohlcv("XAUUSD", "M15", limit=10)
        assert [row.timestamp for row in rows] == [BAR_TS_1]
        quarantine = await store._fetch(
            "SELECT reason_code, payload_json FROM quarantine"
        )
        assert len(quarantine) == 1
        assert quarantine[0][0] == "outlier"
        import json as _json
        assert _json.loads(quarantine[0][1])["high"] == 155.0, (
            "raw rejected values must be preserved verbatim by the default path")
    finally:
        store.close()


@pytest.mark.asyncio
async def test_gate_off_inserts_outlier_bar_with_quality_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_QUALITY_GATE", "0")
    store = DataStore(db_path=str(tmp_path / "gate-off.duckdb"))
    await store.init_tables()

    try:
        submitted = await store.insert_ohlcv_batch([_base_bar(), _outlier_bar()])

        assert submitted == 2
        rows = await store.query_ohlcv("XAUUSD", "M15", limit=10)
        assert len(rows) == 2
        coverage = await store.get_ohlcv_coverage("XAUUSD", "M15")
        assert coverage["qualities"] == {"ok": 2}
    finally:
        store.close()


@pytest.mark.asyncio
async def test_gate_on_quarantines_outlier_bar_and_skips_insert(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_QUALITY_GATE", "1")
    store = DataStore(db_path=str(tmp_path / "gate-on.duckdb"))
    await store.init_tables()

    try:
        submitted = await store.insert_ohlcv_batch([_base_bar(), _outlier_bar()])

        assert submitted == 1
        rows = await store.query_ohlcv("XAUUSD", "M15", limit=10)
        assert len(rows) == 1
        assert rows[0].timestamp == BAR_TS_1

        quarantine = await store._fetch(
            "SELECT dataset_id, reason_code FROM quarantine ORDER BY created_at"
        )
        assert quarantine == [("market_ohlcv", "outlier")]
        datasets = await store._fetch("SELECT dataset_id FROM datasets")
        assert ("market_ohlcv",) in datasets
    finally:
        store.close()


@pytest.mark.asyncio
async def test_ticks_table_has_provenance_columns_after_init(tmp_path, monkeypatch):
    monkeypatch.delenv("NEXUS_QUALITY_GATE", raising=False)
    store = DataStore(db_path=str(tmp_path / "ticks-columns.duckdb"))
    await store.init_tables()

    try:
        rows = await store._fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'ticks'"
        )
        columns = {row[0] for row in rows}
        assert {"source", "quality", "fetched_at"} <= columns
    finally:
        store.close()


def test_ohlcv_invariant_helper_flags_broken_bars():
    assert _ohlcv_invariant_issue(_base_bar()) is None

    envelope_broken = OHLCV(
        symbol="XAUUSD", timeframe="M15", open=100, high=110,
        low=105, close=102, volume=1, timestamp=BAR_TS_1,
    )
    assert "envelope" in (_ohlcv_invariant_issue(envelope_broken) or "")

    non_positive = OHLCV(
        symbol="XAUUSD", timeframe="M15", open=0, high=1,
        low=0, close=1, volume=1, timestamp=BAR_TS_1,
    )
    assert "non-positive" in (_ohlcv_invariant_issue(non_positive) or "")


@pytest.mark.asyncio
async def test_gate_on_rejects_invariant_broken_bar_on_single_insert(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_QUALITY_GATE", "1")
    store = DataStore(db_path=str(tmp_path / "invariant.duckdb"))
    await store.init_tables()

    envelope_broken = OHLCV(
        symbol="XAUUSD", timeframe="M15", open=100, high=110,
        low=105, close=102, volume=1, timestamp=BAR_TS_1,
    )
    try:
        await store.insert_ohlcv(envelope_broken)

        rows = await store.query_ohlcv("XAUUSD", "M15", limit=10)
        assert rows == []
        quarantine = await store._fetch(
            "SELECT dataset_id, reason_code, reason_detail FROM quarantine"
        )
        assert len(quarantine) == 1
        assert quarantine[0][0] == "market_ohlcv"
        assert quarantine[0][1] == "invalid_record"
        assert "invalid_record" in quarantine[0][2]
    finally:
        store.close()


@pytest.mark.asyncio
async def test_gate_on_dedupes_in_batch_ticks_and_quarantines_duplicates(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_QUALITY_GATE", "1")
    store = DataStore(db_path=str(tmp_path / "tick-dup.duckdb"))
    await store.init_tables()

    ts = datetime(2026, 1, 5, 10, 0, 0, 100, tzinfo=timezone.utc)
    first = Tick(symbol="XAUUSD", bid=2600.1, ask=2600.3, timestamp=ts)
    duplicate = Tick(symbol="XAUUSD", bid=2600.1, ask=2600.3, timestamp=ts)
    other = Tick(symbol="XAUUSD", bid=2600.2, ask=2600.4, timestamp=ts)
    try:
        await store.insert_batch([first, duplicate, other])

        rows = await store._fetch("SELECT COUNT(*) FROM ticks")
        assert rows[0][0] == 2
        quarantine = await store._fetch(
            "SELECT dataset_id, reason_code FROM quarantine"
        )
        assert quarantine == [("market_ticks", "duplicate")]
    finally:
        store.close()
