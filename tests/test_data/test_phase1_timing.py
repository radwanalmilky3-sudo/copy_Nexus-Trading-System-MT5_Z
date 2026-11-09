"""Phase 1 (development plan): timing ledgers, identity, tz rejection.

Covers the plan's verification points:
- imported timestamps must carry an explicit timezone (CSV/JSON rejection),
- ohlcv rows stamp bar_open_server_time / utc_offset_seconds / bar_open_utc
  with the identity bar_open_utc = server - offset,
- broker_server_time_offsets is a change-only validity-interval ledger,
- value corrections land append-only in ohlcv_revisions (v1.1),
- broker_symbols maps every captured instrument to its broker symbol,
- the delta-logic in main._accept_utc_offset keeps the last shift against
  stale quote times and follows genuine ±1h clock changes.
"""
from __future__ import annotations

import importlib.util
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from shared.models import OHLCV
from services.nexus_data.duckdb_store import DataStore

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "import_historical_data.py"


def _load_import_script():
    spec = importlib.util.spec_from_file_location("import_historical_data_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── tz rejection (plan item 5) ───────────────────────────────────────────────

def test_naive_timestamp_rejected_with_explicit_error():
    mod = _load_import_script()
    with pytest.raises(ValueError, match="refusing to assume UTC"):
        mod.parse_datetime("2026-11-09 20:00:00")


def test_date_only_timestamp_rejected_too():
    mod = _load_import_script()
    with pytest.raises(ValueError, match="no timezone"):
        mod.parse_datetime("2026-11-09")


def test_aware_timestamp_accepted_and_normalized_to_utc():
    mod = _load_import_script()
    dt = mod.parse_datetime("2026-11-09 20:00:00+02:00")
    assert dt.tzinfo is not None
    assert dt.utcoffset() == timedelta(0)
    assert dt.hour == 18  # 20:00+02:00 == 18:00 UTC


def test_epoch_timestamp_accepted_as_utc_by_definition():
    mod = _load_import_script()
    dt = mod.parse_datetime("1794182400")  # 2026-11-09 00:00:00 UTC
    assert dt.tzinfo is not None
    assert dt.utcoffset() == timedelta(0)
    assert dt == datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc)


# ── timing columns + identity ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_insert_stamps_timing_and_identity_holds(tmp_path):
    store = DataStore(db_path=str(tmp_path / "phase1-timing.duckdb"))
    await store.init_tables()
    ts = datetime(2026, 11, 9, 10, 0, tzinfo=timezone.utc)
    try:
        await store.insert_ohlcv_batch(
            [OHLCV(symbol="XAUUSD", timeframe="H1", open=100, high=105,
                   low=99, close=102, volume=10, timestamp=ts)],
            utc_offset_seconds=7200,
        )
        rows = await store._fetch(
            "SELECT timestamp, bar_open_server_time, utc_offset_seconds, bar_open_utc "
            "FROM ohlcv WHERE symbol='XAUUSD'"
        )
        assert len(rows) == 1
        server_t, stamped_server, offset, open_utc = rows[0]
        assert offset == 7200
        assert stamped_server is not None and open_utc is not None
        # identity: epoch(bar_open_utc) = epoch(bar_open_server_time) - offset
        bad = await store._fetch(
            "SELECT COUNT(*) FROM ohlcv WHERE bar_open_utc IS NOT NULL "
            "AND epoch(bar_open_utc) <> epoch(bar_open_server_time) - utc_offset_seconds"
        )
        assert bad[0][0] == 0
        # the raw broker clock in `timestamp` is unchanged (additive design)
        assert server_t == stamped_server
        assert open_utc == ts - timedelta(seconds=7200)
    finally:
        store.close()


@pytest.mark.asyncio
async def test_unknown_offset_stays_null_then_next_sample_completes_it(tmp_path):
    store = DataStore(db_path=str(tmp_path / "phase1-legacy.duckdb"))
    await store.init_tables()
    ts = datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc)
    try:
        # writer without a measured shift → NULL (never guessed)
        await store.insert_ohlcv_batch(
            [OHLCV(symbol="XAUUSD", timeframe="H1", open=100, high=105,
                   low=99, close=102, volume=10, timestamp=ts)],
        )
        rows = await store._fetch(
            "SELECT utc_offset_seconds, bar_open_utc FROM ohlcv WHERE symbol='XAUUSD'"
        )
        assert rows == [(None, None)]

        # first successful sample completes every legacy row in one operation
        opened = await store.record_server_utc_offset(
            "OneRoyal-Demo", 7200, method="test",
        )
        assert opened is True
        rows = await store._fetch(
            "SELECT utc_offset_seconds, bar_open_utc FROM ohlcv WHERE symbol='XAUUSD'"
        )
        assert rows[0][0] == 7200
        assert rows[0][1] == ts - timedelta(seconds=7200)
    finally:
        store.close()


# ── offset ledger: filled on change only ─────────────────────────────────────

@pytest.mark.asyncio
async def test_offset_ledger_opens_interval_on_change_only(tmp_path):
    store = DataStore(db_path=str(tmp_path / "phase1-offsets.duckdb"))
    await store.init_tables()
    try:
        assert await store.record_server_utc_offset("srv", 7200, method="a") is True
        # identical measurement → no new interval, only refresh
        assert await store.record_server_utc_offset("srv", 7200, method="a") is False
        # quote-age jitter (< 30 min materiality gate) → refreshed in place,
        # still one row, open row carries the freshest estimate
        # (regression: evidence showed 7170→7171 opening two rows)
        assert await store.record_server_utc_offset("srv", 7300, method="a") is False
        rows = await store._fetch(
            "SELECT utc_offset_seconds, valid_to FROM broker_server_time_offsets "
            "WHERE server_code='srv'"
        )
        assert len(rows) == 1 and rows[0][0] == 7300 and rows[0][1] is None

        # clock change (e.g. DST, >= 30 min) → old interval closed, new opened
        assert await store.record_server_utc_offset("srv", 10800, method="a") is True
        rows = await store._fetch(
            "SELECT utc_offset_seconds, valid_to IS NULL AS is_open "
            "FROM broker_server_time_offsets WHERE server_code='srv' "
            "ORDER BY valid_from"
        )
        assert rows == [(7300, False), (10800, True)]
    finally:
        store.close()


# ── append-only correction history (v1.1) ────────────────────────────────────

@pytest.mark.asyncio
async def test_value_correction_writes_append_only_revision(tmp_path):
    store = DataStore(db_path=str(tmp_path / "phase1-revisions.duckdb"))
    await store.init_tables()
    ts = datetime(2026, 11, 9, 8, 0, tzinfo=timezone.utc)
    bar_v1 = OHLCV(symbol="XAUUSD", timeframe="H1", open=100, high=105,
                   low=99, close=102, volume=10, timestamp=ts)
    bar_v2 = OHLCV(symbol="XAUUSD", timeframe="H1", open=100, high=106,
                   low=99, close=105, volume=12, timestamp=ts)
    try:
        await store.insert_ohlcv_batch([bar_v1], utc_offset_seconds=7200)
        await store.insert_ohlcv_batch(
            [bar_v2], utc_offset_seconds=7200, fetch_run_id=None,
        )

        rows = await store._fetch(
            "SELECT close, volume, revision FROM ohlcv WHERE symbol='XAUUSD'"
        )
        assert rows == [(105.0, 12.0, 1)]

        revs = await store._fetch(
            "SELECT revision_no, old_close, old_volume, new_close, new_volume, reason "
            "FROM ohlcv_revisions WHERE symbol='XAUUSD'"
        )
        assert revs == [(1, 102.0, 10.0, 105.0, 12.0, "value_change")]

        # re-inserting identical values is still a no-op (no new revision)
        await store.insert_ohlcv_batch([bar_v2], utc_offset_seconds=7200)
        revs = await store._fetch(
            "SELECT COUNT(*) FROM ohlcv_revisions WHERE symbol='XAUUSD'"
        )
        assert revs[0][0] == 1
    finally:
        store.close()


# ── broker_symbols mapping ledger ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_symbol_snapshot_upserts_broker_mapping(tmp_path):
    store = DataStore(db_path=str(tmp_path / "phase1-mapping.duckdb"))
    await store.init_tables()
    info = {
        "logical_symbol": "XAUUSD", "broker_symbol": "XAUUSD",
        "time": int(time.time()), "is_available": True,
        "server_code": "OneRoyal-Demo", "digits": 2,
    }
    try:
        await store.insert_symbol_snapshot(info)
        rows = await store._fetch(
            "SELECT instrument_code, broker_symbol, server_code, is_tradable, valid_to "
            "FROM broker_symbols"
        )
        assert rows == [("XAUUSD", "XAUUSD", "OneRoyal-Demo", True, None)]

        # identical capture → still one open row (idempotent)
        await store.insert_symbol_snapshot(info)
        rows = await store._fetch(
            "SELECT COUNT(*), COUNT(valid_to IS NULL) FROM broker_symbols"
        )
        assert rows[0][0] == 1 and rows[0][1] == 1

        # tradability flip → history preserved: old row closed, new opened
        flipped = dict(info, is_available=False)
        await store.insert_symbol_snapshot(flipped)
        rows = await store._fetch(
            "SELECT is_tradable, valid_to IS NULL FROM broker_symbols "
            "ORDER BY valid_from"
        )
        assert rows == [(True, False), (False, True)]
    finally:
        store.close()


# ── delta-logic for measured shifts (plan: stale samples ignored) ────────────

@pytest.mark.asyncio
async def test_accept_utc_offset_delta_logic(monkeypatch):
    from services.nexus_data import main

    class _Recorder:
        def __init__(self):
            self.calls: list[tuple[str, int, str]] = []

        async def record_server_utc_offset(self, server_code, offset, *, method):
            self.calls.append((server_code, offset, method))
            return True

    recorder = _Recorder()
    monkeypatch.setattr(main, "data_store", recorder)
    saved = dict(main._offset_state)
    try:
        main._offset_state["value"] = None
        main._offset_state["sampled_at"] = 0.0

        # first sample always accepted
        assert await main._accept_utc_offset(7200, method="t") == 7200
        # fresher-or-equal within jitter → accepted
        assert await main._accept_utc_offset(7150, method="t") == 7150
        # stale quote (well below last, not an hour shift) → rejected
        assert await main._accept_utc_offset(6500, method="t") == 7150
        # large positive jump (self-heal: stored value was stale-low) → accepted
        assert await main._accept_utc_offset(10800, method="t") == 10800
        # genuine -1h clock change (DST fall-back) → accepted
        main._offset_state["value"] = 7200
        assert await main._accept_utc_offset(3600, method="t") == 3600

        assert [c[1] for c in recorder.calls] == [7200, 7150, 10800, 3600]
        assert all(c[0] == main.OFFSET_SERVER_CODE for c in recorder.calls)
    finally:
        main._offset_state.clear()
        main._offset_state.update(saved)
