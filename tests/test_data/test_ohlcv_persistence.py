from __future__ import annotations

from datetime import datetime, timezone

import pytest
import duckdb

from shared.models import OHLCV
from services.nexus_data.duckdb_store import DataStore


@pytest.mark.asyncio
async def test_reopening_legacy_database_backfills_before_recreating_indexes(tmp_path):
    """Exercise the startup backfill/index ordering on an isolated legacy DB."""
    db_path = tmp_path / "legacy-startup.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE ohlcv (
            symbol VARCHAR NOT NULL,
            timeframe VARCHAR NOT NULL,
            open DOUBLE NOT NULL,
            high DOUBLE NOT NULL,
            low DOUBLE NOT NULL,
            close DOUBLE NOT NULL,
            volume DOUBLE NOT NULL,
            timestamp TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (symbol, timeframe, timestamp)
        )
    """)
    conn.execute("""
        CREATE TABLE ticks (
            symbol VARCHAR NOT NULL,
            bid DOUBLE NOT NULL,
            ask DOUBLE NOT NULL,
            volume DOUBLE NOT NULL,
            timestamp TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (symbol, timestamp)
        )
    """)
    conn.execute(
        "INSERT INTO ohlcv VALUES ('XAUUSD', 'M15', 100, 105, 99, 102, 10, ?)",
        [datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)],
    )
    conn.execute(
        "INSERT INTO ticks VALUES ('XAUUSD', 100, 101, 1, ?)",
        [datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)],
    )
    conn.close()

    store = DataStore(db_path=str(db_path))
    await store.init_tables()
    try:
        rows = await store._fetch(
            "SELECT source, fetched_at FROM ohlcv WHERE symbol='XAUUSD'"
        )
        tick_rows = await store._fetch(
            "SELECT fetched_at FROM ticks WHERE symbol='XAUUSD'"
        )
        assert len(rows) == 1
        assert rows[0][0] == "mt5"
        assert rows[0][1] is not None
        assert len(tick_rows) == 1
        assert tick_rows[0][0] is not None
    finally:
        store.close()


@pytest.mark.asyncio
async def test_ohlcv_batch_persists_history_without_duplicate_bars(tmp_path):
    store = DataStore(db_path=str(tmp_path / "ohlcv.duckdb"))
    await store.init_tables()
    first_ts = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
    current_ts = datetime(2026, 10, 14, 10, 15, tzinfo=timezone.utc)

    try:
        await store.insert_ohlcv_batch([
            OHLCV(symbol="XAUUSD", timeframe="M15", open=100, high=105, low=99, close=102,
                  volume=10, timestamp=first_ts),
            OHLCV(symbol="XAUUSD", timeframe="M15", open=102, high=106, low=101, close=103,
                  volume=12, timestamp=current_ts),
        ])
        await store.insert_ohlcv_batch([
            OHLCV(symbol="XAUUSD", timeframe="M15", open=100, high=105, low=99, close=102,
                  volume=10, timestamp=first_ts),
            OHLCV(symbol="XAUUSD", timeframe="M15", open=102, high=106, low=101, close=103,
                  volume=12, timestamp=current_ts),
        ])

        rows = await store.query_ohlcv("XAUUSD", "M15", limit=10)

        assert len(rows) == 2
        assert rows[0].timestamp == current_ts
        assert rows[0].close == 103
        assert rows[0].volume == 12
    finally:
        store.close()


@pytest.mark.asyncio
async def test_publisher_persists_closed_bars_but_not_the_forming_bar(tmp_path, monkeypatch):
    from datetime import timedelta

    from services.nexus_data import main

    store = DataStore(db_path=str(tmp_path / "publisher-ohlcv.duckdb"))
    await store.init_tables()
    monkeypatch.setattr(main, "data_store", store)
    now = datetime.now(timezone.utc)
    # Align to M15 boundaries so the newest bar is still forming right now.
    current_boundary = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    bars = [
        OHLCV(symbol="XAUUSD", timeframe="M15", open=100, high=105, low=99, close=102,
              volume=10, timestamp=current_boundary - timedelta(minutes=30)),
        OHLCV(symbol="XAUUSD", timeframe="M15", open=102, high=106, low=101, close=103,
              volume=12, timestamp=current_boundary - timedelta(minutes=15)),
        OHLCV(symbol="XAUUSD", timeframe="M15", open=103, high=107, low=102, close=104,
              volume=5, timestamp=current_boundary),
    ]

    try:
        await main._persist_closed_ohlcv(bars)
        rows = await store.query_ohlcv("XAUUSD", "M15", limit=10)

        assert len(rows) == 2
        assert [row.timestamp for row in rows] == [bars[1].timestamp, bars[0].timestamp]
    finally:
        store.close()
