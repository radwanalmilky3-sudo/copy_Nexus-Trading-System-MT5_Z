"""Declared-state reconciliation for ohlcv_manifests (Task 7).

Synthetic fixtures on ISOLATED temp databases only — never the production file.
A manifest row is declared state (row_count / content_hash / available_through);
if it disagrees with the stored ohlcv series the declaration is a lie and must
be recomputed honestly (including manifests whose series vanished entirely).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from shared.models import OHLCV
from services.nexus_data.duckdb_store import DataStore

UTC = timezone.utc
T0 = datetime(2026, 10, 12, 16, 30, tzinfo=UTC)
STEP = timedelta(minutes=15)


def _bar(offset: int) -> OHLCV:
    """SYNTHETIC test bar — not market data."""
    close = 2650.0 + offset * 0.5
    return OHLCV(
        symbol="XAUUSD", timeframe="M15", timestamp=T0 + STEP * offset,
        open=close - 0.4, high=close + 0.8, low=close - 0.9, close=close,
        volume=12.0,
    )


@pytest_asyncio.fixture
async def store(tmp_path):
    s = DataStore(db_path=str(tmp_path / "manifest-reconcile.duckdb"))
    await s.init_tables()
    try:
        yield s
    finally:
        await s.aclose()


async def _manifest(store, symbol="XAUUSD", timeframe="M15"):
    rows = await store._fetch(
        "SELECT row_count, content_hash, available_through FROM ohlcv_manifests "
        "WHERE symbol=? AND timeframe=?", (symbol, timeframe),
    )
    return rows[0] if rows else None


@pytest.mark.asyncio
async def test_reconcile_repairs_stale_manifest_declaration(store):
    await store.insert_ohlcv_batch([_bar(0), _bar(1), _bar(2)], source="mt5_backfill")
    assert (await _manifest(store))[0] == 3
    await store._run(
        "UPDATE ohlcv_manifests SET row_count=999, content_hash='stale' "
        "WHERE symbol='XAUUSD' AND timeframe='M15'"
    )
    assert (await _manifest(store))[0] == 999

    result = await store.reconcile_ohlcv_manifests()
    assert result["stale"] == 1 and result["refreshed"] == 1
    row_count, content_hash, available_through = await _manifest(store)
    assert row_count == 3, "declared count must be recomputed from stored rows"
    assert content_hash and content_hash != "stale"
    assert available_through is not None

    again = await store.reconcile_ohlcv_manifests()
    assert again["stale"] == 0 and again["refreshed"] == 0, "reconcile must be idempotent"


@pytest.mark.asyncio
async def test_reconcile_zeroes_manifest_whose_series_vanished(store):
    await store.insert_ohlcv_batch([_bar(0), _bar(1), _bar(2)], source="mt5_poll")
    await store._run("DELETE FROM ohlcv WHERE symbol='XAUUSD' AND timeframe='M15'")

    result = await store.reconcile_ohlcv_manifests()
    assert result["stale"] == 1
    row_count, content_hash, available_through = await _manifest(store)
    assert row_count == 0, "an emptied series must be declared 0, not its former count"
    assert content_hash, "honest empty-series fingerprint still recorded"
    assert available_through is None


@pytest.mark.asyncio
async def test_reconcile_creates_manifest_missing_for_live_pair(store):
    await store.insert_ohlcv_batch([_bar(0), _bar(1)], source="mt5_backfill")
    await store._run(
        "DELETE FROM ohlcv_manifests WHERE symbol='XAUUSD' AND timeframe='M15'"
    )
    assert await _manifest(store) is None

    result = await store.reconcile_ohlcv_manifests()
    assert result["stale"] == 1
    row_count, content_hash, _ = await _manifest(store)
    assert row_count == 2 and content_hash


@pytest.mark.asyncio
async def test_reconcile_handles_multiple_pairs_including_declared_only(store):
    await store.insert_ohlcv_batch([_bar(0)], source="mt5_poll")
    await store.insert_ohlcv_batch(
        [OHLCV(
            symbol="EURUSD", timeframe="M15", timestamp=T0 + STEP,
            open=1.1, high=1.2, low=1.0, close=1.15, volume=7.0,
        )], source="mt5_poll",
    )
    await store._run("DELETE FROM ohlcv WHERE symbol='EURUSD'")
    await store._run(
        "UPDATE ohlcv_manifests SET row_count=500 WHERE symbol='EURUSD'"
    )
    await store._run("DELETE FROM ohlcv_manifests WHERE symbol='XAUUSD'")

    result = await store.reconcile_ohlcv_manifests()
    assert result["stale"] == 2, "one vanished-pair lie and one missing manifest"
    assert (await _manifest(store, "XAUUSD"))[0] == 1
    assert (await _manifest(store, "EURUSD"))[0] == 0


@pytest.mark.asyncio
async def test_automation_cycle_reconciles_manifests_every_cycle(store):
    from services.nexus_data.quality.automation import QualityAutomation

    await store.insert_ohlcv_batch([_bar(0), _bar(1)], source="mt5_poll")
    await store._run(
        "UPDATE ohlcv_manifests SET row_count=42 WHERE symbol='XAUUSD' AND timeframe='M15'"
    )
    worker = QualityAutomation(store, interval=30)
    await worker.cycle()
    assert worker.state["manifests_stale"] == 1, (
        "the periodic certification cycle must surface stale manifests")
    assert (await _manifest(store))[0] == 2
    assert worker.state["last_cycle"]
