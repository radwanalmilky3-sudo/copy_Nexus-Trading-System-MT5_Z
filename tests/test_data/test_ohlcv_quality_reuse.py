"""Reuse assessment tests for OHLCV cleaning, dedup, inspection, and repair.

All fixtures are synthetic, labeled test data on isolated temp databases.
Nothing here reads or writes the production DuckDB file.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from services.nexus_data.duckdb_store import DataStore
from services.nexus_data.imports.contracts import CanonicalOHLCV
from services.nexus_data.imports.deduplicate import deduplicate, ohlcv_key
from services.nexus_data.quality.validators import OutlierPolicy, Severity, validate_ohlcv
from services.nexus_data.research_market import inspect_bars, session_gap_review

UTC = timezone.utc
T0 = datetime(2026, 10, 12, 16, 30, tzinfo=UTC)
STEP = timedelta(minutes=15)


def _bar(offset: int, *, close: float = 100.0, symbol: str = "XAUUSD") -> CanonicalOHLCV:
    stamp = T0 + STEP * offset
    return CanonicalOHLCV(
        symbol=symbol, timeframe="M15", timestamp=stamp,
        open=close - 0.5, high=close + 1.0, low=close - 1.0, close=close,
        volume=10.0,
    )


@pytest_asyncio.fixture
async def temp_store(tmp_path):
    store = DataStore(db_path=str(tmp_path / "reuse.duckdb"))
    await store.init_tables()
    try:
        yield store
    finally:
        store.close()


def test_validate_ohlcv_flags_duplicate_as_error_and_gap_as_warning():
    records = [
        _bar(0),
        _bar(1, close=101.0),
        _bar(1, close=101.0),
        _bar(6, close=102.0),
    ]
    findings = validate_ohlcv(
        records, dataset_id="test:ohlcv:XAUUSD:M15:synthetic",
        expected_interval=STEP,
    )
    codes = {issue.code for issue in findings.issues}
    assert "duplicate_key" in codes
    assert "time_gap" in codes
    assert findings.status == "failed"
    assert not findings.valid
    assert findings.quarantined
    assert findings.quarantined[0].reason_code == "duplicate"


def test_validate_ohlcv_passes_clean_series():
    findings = validate_ohlcv(
        [_bar(i, close=100.0 + i) for i in range(5)],
        dataset_id="test:ohlcv:clean", expected_interval=STEP,
    )
    assert findings.valid
    assert findings.status == "passed"
    assert findings.issues == ()


def test_validate_ohlcv_outlier_policy_is_configurable():
    records = [_bar(0, close=100.0), _bar(1, close=130.0)]
    strict = validate_ohlcv(
        records, dataset_id="outlier", expected_interval=STEP,
        outlier_policy=OutlierPolicy(max_abs_return=0.20),
    )
    relaxed = validate_ohlcv(
        records, dataset_id="outlier", expected_interval=STEP,
        outlier_policy=OutlierPolicy(max_abs_return=0.50),
    )
    assert any(i.code == "price_outlier" and i.severity == Severity.ERROR for i in strict.issues)
    assert not any(i.code == "price_outlier" for i in relaxed.issues)


def test_deduplicate_keeps_first_and_counts_duplicates():
    a = _bar(0)
    b = _bar(1, close=101.0)
    result = deduplicate([a, b, a])
    assert result.records == (a, b)
    assert result.duplicate_count == 1
    assert ohlcv_key(a) == ("XAUUSD", "M15", T0)


def test_inspect_bars_rejects_invalid_and_hashes_stable_fingerprint():
    bars = [
        {"time": T0.timestamp(), "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 10.0},
        {"time": (T0 + STEP).timestamp(), "open": 100.0, "high": 99.0, "low": 101.0, "close": 100.5, "volume": 10.0},
        {"time": (T0 + STEP * 2).timestamp(), "open": 100.5, "high": 101.5, "low": 99.5, "close": 101.0, "volume": 10.0},
        {"time": (T0 + STEP * 8).timestamp(), "open": 101.0, "high": 102.0, "low": 100.0, "close": 101.5, "volume": 10.0},
    ]
    clean, quality = inspect_bars(bars, "M15")
    assert quality["rejected"] == 1
    assert quality["unclassified_gaps"] >= 1
    assert quality["status"] == "needs_review"
    clean_again, quality_again = inspect_bars(bars, "M15")
    assert quality["fingerprint"] == quality_again["fingerprint"]
    assert clean == clean_again


def test_session_gap_review_is_missing_without_evidence():
    bars = [
        {"time": T0.timestamp(), "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1},
        {"time": (T0 + STEP * 4).timestamp(), "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1},
    ]
    account = {"version": "v1", "server": "Demo", "settings": {}}
    result = session_gap_review(bars, "M15", account, "XAUUSD")
    assert result["state"] == "missing"
    assert result["unclassified_gaps"] == 1
    assert result["confirmed_closed"] == 0


def test_session_gap_review_marks_weekly_reference_only_with_evidence():
    bars = [
        {"time": T0.timestamp(), "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1},
        {"time": (T0 + STEP * 4).timestamp(), "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1},
    ]
    account = {
        "version": "v1", "server": "Demo",
        "settings": {"session_observation": {
            "server": "Demo", "broker_symbol": "XAUUSD",
            "captured_at_utc": "2026-10-12T00:00:00+00:00",
            "windows": [{"day": d, "start_seconds": 0, "end_seconds": 86400} for d in range(7)],
        }},
    }
    result = session_gap_review(bars, "M15", account, "XAUUSD")
    assert result["state"] == "weekly_reference_only"
    assert result["confirmed_closed"] == 0


@pytest.mark.asyncio
async def test_insert_ohlcv_batch_is_idempotent_and_refreshes_manifest(temp_store):
    from shared.models import OHLCV

    bars = [
        OHLCV(symbol="XAUUSD", timeframe="M15", open=100, high=105, low=99, close=102,
              volume=10, timestamp=T0),
        OHLCV(symbol="XAUUSD", timeframe="M15", open=102, high=106, low=101, close=103,
              volume=12, timestamp=T0 + STEP),
    ]
    await temp_store.insert_ohlcv_batch(bars)
    await temp_store.insert_ohlcv_batch(bars)

    rows = await temp_store._fetch("SELECT COUNT(*) FROM ohlcv")
    assert rows[0][0] == 2
    manifests = await temp_store._fetch(
        "SELECT symbol, timeframe, row_count, content_hash, available_through FROM ohlcv_manifests"
    )
    assert manifests == [("XAUUSD", "M15", 2, manifests[0][3], manifests[0][4])]
    assert manifests[0][3]


@pytest.mark.asyncio
async def test_repair_pair_on_clean_synthetic_series_touches_nothing(temp_store):
    from services.nexus_data.quality.repair import repair_pair
    from shared.models import OHLCV

    now = datetime(2026, 10, 12, 18, 0, tzinfo=UTC)
    bars = [
        OHLCV(symbol="XAUUSD", timeframe="M15", open=100, high=105, low=99, close=102,
              volume=10, timestamp=T0, source="mt5_poll"),
        OHLCV(symbol="XAUUSD", timeframe="M15", open=102, high=106, low=101, close=103,
              volume=12, timestamp=T0 + STEP, source="mt5_poll"),
    ]
    await temp_store.insert_ohlcv_batch(bars, source="mt5_poll")
    before = await temp_store._fetch(
        "SELECT open, high, low, close, volume, revision FROM ohlcv ORDER BY timestamp"
    )

    result = await repair_pair(temp_store, None, "XAUUSD", "M15", now=now)

    assert result["quarantined"] == 0
    assert result["replaced"] == 0
    assert result["inserted"] == 0
    after = await temp_store._fetch(
        "SELECT open, high, low, close, volume, revision FROM ohlcv ORDER BY timestamp"
    )
    assert after == before
    attempts = await temp_store._fetch("SELECT COUNT(*) FROM quality_repair_attempts")
    assert attempts[0][0] == 0


@pytest.mark.asyncio
async def test_repair_pair_quarantines_conflicting_sources_without_arbitrary_pick(temp_store):
    from services.nexus_data.quality.repair import repair_pair
    from shared.models import OHLCV

    now = datetime(2026, 10, 12, 18, 0, tzinfo=UTC)
    insert = (
        "INSERT INTO ohlcv(symbol,timeframe,open,high,low,close,volume,timestamp,"
        "source,quality,fetched_at,available_at,revision) VALUES "
        "('XAUUSD','M15',?,?,?,?,?,?,?, 'ok', ?, ?, 0)"
    )
    await temp_store._run(insert, (100, 105, 99, 102, 10, T0, "mt5_poll", now, now))
    await temp_store._run(insert, (100, 108, 99, 102, 10, T0, "mt5_backfill", now, now))

    result = await repair_pair(temp_store, None, "XAUUSD", "M15", now=now)

    assert result["quarantined"] >= 1
    remaining = await temp_store._fetch("SELECT COUNT(*) FROM ohlcv")
    assert remaining[0][0] == 0
    reasons = await temp_store._fetch(
        "SELECT DISTINCT reason_code FROM quarantine WHERE resolution_status='open'"
    )
    assert ("auto_conflict",) in reasons
