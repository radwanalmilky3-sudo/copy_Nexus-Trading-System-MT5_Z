"""Phase 2 (development plan v1.1): raw ticks, per-bar aggregates, ask enrichment.

Covers the plan's verification points:
- raw tick import is idempotent via the (symbol, time_msc, flags) key and
  stamps source_time_utc = broker clock - measured offset (NULL when none),
- SUM(tick_count) over the window's bars reconciles with the raw tick rows,
- buy + sell <= tick_count always (a both/neither-flagged tick counts only
  in tick_count),
- ohlcv.ask_* comes only from stored ticks (ask_source='ticks'); bars without
  a usable ask keep NULL ask AND NULL ask_source — an ask is never guessed,
- re-running the same aggregation window changes nothing (raw ticks are the
  audit trail) and windows are scoped to their own bars,
- apply_rate_enrichment: real_volume 0 means "not provided" → NULL,
  volume_type='tick' records what the legacy `volume` column holds.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from shared.models import OHLCV

# Grid-aligned M1 bars (2026-11-09, broker clock == epoch grid, live proof):
# 10:00, 10:01, 10:02, 10:03 UTC.
BAR_TIMES = [datetime(2026, 11, 9, 10, i, tzinfo=timezone.utc) for i in range(4)]


def _msc(h: int, m: int, s: int) -> int:
    """Epoch milliseconds of one 2026-11-09 wall-clock instant (UTC)."""
    return int(datetime(2026, 11, 9, h, m, s, tzinfo=timezone.utc).timestamp() * 1000)


# (time_msc, bid, ask, last, volume, volume_real, flags, spread_points)
# MT5 flags: 1=buy, 2=sell, 3=both, 0=neither.
TICKS = [
    (_msc(10, 0, 10), 2400.8, 2401.0, 2400.9, 1.0, 0.0, 1, 10.0),  # bar1 buy
    (_msc(10, 0, 20), 2401.8, 2402.0, 2401.9, 2.0, 0.0, 2, 12.0),  # bar1 sell
    (_msc(10, 0, 30), 2400.3, 2400.5, 2400.4, 1.0, 0.0, 3, 8.0),   # bar1 both
    (_msc(10, 1, 5), 2402.8, 2403.0, 2402.9, 1.0, 0.0, 0, 9.0),    # bar2 neither
    (_msc(10, 1, 15), 2403.8, 2404.0, 2403.9, 3.0, 0.0, 1, 11.0),  # bar2 buy
    (_msc(10, 2, 50), 2404.0, 0.0, 2404.1, 1.0, 0.0, 2, 0.0),      # bar3 ask=0 (unusable)
    (_msc(10, 4, 30), 2404.8, 2405.0, 2404.9, 1.0, 0.0, 1, 10.0),  # no bar in this bucket
]

WINDOW_START = datetime(2026, 11, 9, 10, 0, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 11, 9, 10, 4, tzinfo=timezone.utc)


async def _insert_bars(store, offset: int | None = 7200) -> None:
    await store.insert_ohlcv_batch(
        [
            OHLCV(symbol="XAUUSD", timeframe="M1", open=2400.0, high=2405.0,
                  low=2399.0, close=2404.0, volume=100, timestamp=ts)
            for ts in BAR_TIMES
        ],
        utc_offset_seconds=offset,
    )


# ── raw tick import: idempotence + provenance ────────────────────────────────

@pytest.mark.asyncio
async def test_tick_import_is_idempotent_and_stamps_provenance(operational_store):
    store = operational_store
    inserted = await store.insert_ticks_batch(
        "XAUUSD", TICKS[:4], utc_offset_seconds=7200,
    )
    assert inserted == 4

    # re-import of the same window must insert nothing (unique key)
    again = await store.insert_ticks_batch(
        "XAUUSD", TICKS[:4], utc_offset_seconds=7200,
    )
    assert again == 0
    rows = await store._fetch(
        "SELECT COUNT(*) FROM ticks WHERE symbol='XAUUSD'"
    )
    assert rows[0][0] == 4

    # provenance identity: source_time_utc = timestamp - measured offset
    bad = await store._fetch(
        "SELECT COUNT(*) FROM ticks WHERE source_time_utc IS NOT NULL "
        "AND epoch(source_time_utc) <> epoch(timestamp) - 7200"
    )
    assert bad[0][0] == 0
    one = await store._fetch(
        "SELECT time_msc, CAST(epoch(timestamp) AS BIGINT) AS ts_sec, "
        "       CAST(epoch(source_time_utc) AS BIGINT) AS src_sec, "
        "       flags, last, volume, volume_real, spread "
        "FROM ticks WHERE symbol='XAUUSD' AND time_msc = ?",
        (TICKS[0][0],),
    )
    assert one, "inserted tick missing"
    ts_sec, src_sec, flags, last, vol, vol_real, spread = one[0][1], one[0][2], one[0][3], one[0][4], one[0][5], one[0][6], one[0][7]
    assert ts_sec == TICKS[0][0] // 1000            # timestamp = broker clock
    assert src_sec == ts_sec - 7200                 # source = broker - offset
    assert flags == 1 and last == 2400.9
    assert vol == 1.0 and vol_real == 0.0            # broker values kept as sent
    assert spread == 10.0

    # no measured offset → source_time_utc stays NULL (never guessed)
    fresh = await store.insert_ticks_batch("XAGUSD", [TICKS[0]])
    assert fresh == 1
    nulls = await store._fetch(
        "SELECT source_time_utc FROM ticks WHERE symbol='XAGUSD'"
    )
    assert nulls == [(None,)]


# ── aggregation: reconciliation + direction invariant ────────────────────────

@pytest.mark.asyncio
async def test_aggregation_reconciles_and_direction_invariant_holds(operational_store):
    store = operational_store
    await _insert_bars(store)
    await store.insert_ticks_batch("XAUUSD", TICKS, utc_offset_seconds=7200)

    stats = await store.aggregate_ticks_for_window(
        "XAUUSD", "M1", WINDOW_START, WINDOW_END,
    )
    # 7 raw ticks read; 6 fall in buckets that have a bar (10:04 has none);
    # 3 bars carry ticks; 2 of those have a usable ask (bar3's ask is 0).
    assert stats == {
        "ticks": 7, "sum_tick_count": 6, "bars": 3, "bars_with_ask": 2,
    }

    # plan invariant: buy + sell <= tick_count on every aggregate row
    violations = await store._fetch(
        "SELECT COUNT(*) FROM bar_tick_aggregates "
        "WHERE buy_tick_count + sell_tick_count > tick_count"
    )
    assert violations[0][0] == 0

    # exact direction split per bar (both/neither flags count only in tick_count)
    rows = await store._fetch(
        "SELECT tick_count, buy_tick_count, sell_tick_count, "
        "       spread_min, spread_max, spread_avg "
        "FROM bar_tick_aggregates WHERE symbol='XAUUSD' AND timeframe='M1' "
        "ORDER BY bar_open_utc"
    )
    assert rows == [
        (3, 1, 1, 8.0, 12.0, 10.0),   # bar1: buy + sell + both
        (2, 1, 0, 9.0, 11.0, 10.0),   # bar2: neither + buy
        (1, 0, 1, 0.0, 0.0, 0.0),     # bar3: sell only
    ]


# ── ask semantics: only from ticks, never guessed ────────────────────────────

@pytest.mark.asyncio
async def test_ask_comes_only_from_usable_ticks(operational_store):
    store = operational_store
    await _insert_bars(store)
    await store.insert_ticks_batch("XAUUSD", TICKS, utc_offset_seconds=7200)
    await store.aggregate_ticks_for_window("XAUUSD", "M1", WINDOW_START, WINDOW_END)

    rows = await store._fetch(
        "SELECT ask_open, ask_high, ask_low, ask_close, ask_source "
        "FROM ohlcv WHERE symbol='XAUUSD' AND timeframe='M1' ORDER BY timestamp"
    )
    assert len(rows) == 4
    # bar1: ask_open = ask at first tick, close = ask at last tick
    assert rows[0] == (2401.0, 2402.0, 2400.5, 2400.5, "ticks")
    # bar2: two usable asks
    assert rows[1] == (2403.0, 2404.0, 2403.0, 2404.0, "ticks")
    # bar3: ticks exist but ask=0 is unusable → NULL ask AND NULL source
    assert rows[2] == (None, None, None, None, None)
    # bar4: no ticks at all → untouched
    assert rows[3] == (None, None, None, None, None)

    # structural invariant: ask_source='ticks' exactly when ask_close exists
    bad = await store._fetch(
        "SELECT COUNT(*) FROM ohlcv WHERE (ask_source = 'ticks') "
        "<> (ask_close IS NOT NULL)"
    )
    assert bad[0][0] == 0

    # bar3 has an aggregate row (ticks counted) but carries no ask
    agg = await store._fetch(
        "SELECT COUNT(*) FROM bar_tick_aggregates WHERE symbol='XAUUSD' "
        "AND timeframe='M1'"
    )
    assert agg[0][0] == 3


# ── re-aggregation: idempotent + window-scoped ───────────────────────────────

@pytest.mark.asyncio
async def test_reaggregation_is_idempotent_and_window_scoped(operational_store):
    store = operational_store
    await _insert_bars(store)
    await store.insert_ticks_batch("XAUUSD", TICKS, utc_offset_seconds=7200)

    # narrow window covers only bars 10:00–10:01 (read range reaches 10:03,
    # so the raw count includes bar3's tick, but no bar outside the window
    # is joined or touched)
    narrow = await store.aggregate_ticks_for_window(
        "XAUUSD", "M1", WINDOW_START, datetime(2026, 11, 9, 10, 2, tzinfo=timezone.utc),
    )
    assert narrow == {
        "ticks": 6, "sum_tick_count": 5, "bars": 2, "bars_with_ask": 2,
    }
    untouched = await store._fetch(
        "SELECT COUNT(*), COUNT(ask_close) FROM ohlcv "
        "WHERE symbol='XAUUSD' AND timeframe='M1' AND timestamp >= ?",
        (BAR_TIMES[2],),
    )
    assert untouched == [(2, 0)]  # bars 10:02/10:03: no aggregates, no ask
    scope = await store._fetch(
        "SELECT COUNT(*) FROM bar_tick_aggregates WHERE symbol='XAUUSD' "
        "AND timeframe='M1'"
    )
    assert scope[0][0] == 2

    # full window, run twice → identical content both times
    first = await store.aggregate_ticks_for_window(
        "XAUUSD", "M1", WINDOW_START, WINDOW_END,
    )
    snapshot_sql = (
        "SELECT tick_count, buy_tick_count, sell_tick_count, first_time_msc, "
        "       last_time_msc, max_gap_ms, spread_min, spread_max, "
        "       round(spread_avg, 6) "
        "FROM bar_tick_aggregates WHERE symbol='XAUUSD' AND timeframe='M1' "
        "ORDER BY bar_open_utc"
    )
    before = await store._fetch(snapshot_sql)
    second = await store.aggregate_ticks_for_window(
        "XAUUSD", "M1", WINDOW_START, WINDOW_END,
    )
    after = await store._fetch(snapshot_sql)
    assert first == second == {
        "ticks": 7, "sum_tick_count": 6, "bars": 3, "bars_with_ask": 2,
    }
    assert before == after
    assert len(after) == 3  # no duplicate rows accumulated


# ── rate enrichment: copy_rates extras without fake zeros ────────────────────

@pytest.mark.asyncio
async def test_apply_rate_enrichment_stores_real_volume_and_marks_type(operational_store):
    store = operational_store
    await _insert_bars(store)

    stored, other, missing = BAR_TIMES[0], BAR_TIMES[1], datetime(
        2026, 11, 9, 10, 5, tzinfo=timezone.utc,
    )
    counted = await store.apply_rate_enrichment("XAUUSD", "M1", [
        {"timestamp": stored, "spread_points": 15.0, "real_volume": 0,
         "tick_volume": 90},
        {"timestamp": other, "spread_points": 12.0, "real_volume": 500,
         "tick_volume": 80},
        # bar not in the store → skipped, never faked
        {"timestamp": missing, "spread_points": 7.0, "real_volume": 10,
         "tick_volume": 5},
    ])
    assert counted == 2  # stored bars carrying spread_points in the range

    rows = await store._fetch(
        "SELECT spread_points, real_volume, tick_volume, volume_type "
        "FROM ohlcv WHERE symbol='XAUUSD' AND timeframe='M1' ORDER BY timestamp"
    )
    assert rows == [
        (15.0, None, 90.0, "tick"),   # real_volume 0 → NULL ("not provided")
        (12.0, 500.0, 80.0, "tick"),
        (None, None, None, None),     # untouched bar
        (None, None, None, None),
    ]
    stored_count = await store._fetch(
        "SELECT COUNT(*) FROM ohlcv WHERE symbol='XAUUSD' AND timeframe='M1' "
        "AND timestamp = ? AND spread_points IS NULL",
        (missing,),
    )
    assert stored_count[0][0] == 0  # no phantom bar was created for `missing`


# ── bulk chunking regression (2026-11-10 lock-wedge evidence) ────────────────

@pytest.mark.asyncio
async def test_bulk_tick_insert_spans_chunks_and_stays_idempotent(operational_store):
    """Rows > _BULK_CHUNK must split into multi-row statements, not per-row
    commits (per-row executemany wedged the store lock at ~60 rows/s)."""
    from services.nexus_data import duckdb_store as ds

    store = operational_store
    big = ds._BULK_CHUNK + 500  # spans 3 chunks (2000 + 2000 + 500)
    base = _msc(12, 0, 0)
    rows = [
        (base + i * 10, 1.0, 2.0, 1.5, 1.0, 0.0, 1, 5.0) for i in range(big)
    ]
    first = await store.insert_ticks_batch("BTCUSD", rows, utc_offset_seconds=7200)
    assert first == big
    again = await store.insert_ticks_batch("BTCUSD", rows, utc_offset_seconds=7200)
    assert again == 0
    total = await store._fetch(
        "SELECT COUNT(*), MIN(time_msc), MAX(time_msc) FROM ticks "
        "WHERE symbol='BTCUSD'"
    )
    assert total == [(big, base, base + (big - 1) * 10)]


# ── point metadata for spread conversion ─────────────────────────────────────

@pytest.mark.asyncio
async def test_latest_symbol_point_reads_metadata_snapshot(operational_store):
    store = operational_store
    await store.insert_symbol_snapshot({
        "logical_symbol": "XAUUSD", "broker_symbol": "XAUUSD",
        "time": 1794218400, "is_available": True,
        "server_code": "OneRoyal-Demo", "digits": 2, "point": 0.01,
    })
    assert await store.latest_symbol_point("XAUUSD") == 0.01
    assert await store.latest_symbol_point("NOSUCH") is None
