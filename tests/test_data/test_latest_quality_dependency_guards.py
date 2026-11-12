"""Edge-case tests for latest_quality dependency-hash verification (fail-closed).

Guards introduced with the D-fix in services/nexus_data/quality/stored_audit.py:
  1. A stored dependency hash that is missing/None/empty must NEVER verify,
     even when the recomputed side is also unavailable (no None == None pass).
  2. An oversized group (combined_rows raises the bounded-audit ValueError)
     must degrade to not-current, never abort the listing.
"""
import json

import pytest

from tests.test_data.test_quality_repair import put


async def _audit_and_fetch_summary(store, now):
    from services.nexus_data.quality.stored_audit import audit_stored_ohlcv
    report = await audit_stored_ohlcv(store, 'XAUUSD', 'M5', 'mt5_poll', now=now)
    row = store._conn.execute(
        "SELECT summary_json FROM quality_runs WHERE dataset_id=? ORDER BY finished_at DESC LIMIT 1",
        ('ohlcv:XAUUSD:M5:mt5_poll',),
    ).fetchone()
    return report, json.loads(row[0])


def _rewrite_summary(store, mutate):
    row = store._conn.execute(
        "SELECT quality_run_id, summary_json FROM quality_runs WHERE dataset_id=? "
        "ORDER BY finished_at DESC LIMIT 1",
        ('ohlcv:XAUUSD:M5:mt5_poll',),
    ).fetchone()
    summary = json.loads(row[1])
    mutate(summary)
    store._conn.execute(
        "UPDATE quality_runs SET summary_json=? WHERE quality_run_id=?",
        (json.dumps(summary), row[0]),
    )


@pytest.mark.asyncio
async def test_missing_stored_series_hash_with_oversized_group_is_never_current(
    operational_store, monkeypatch
):
    """None stored hash + unverifiable recompute (oversized) => NOT current.

    Regression guard: an intermediate implementation compared
    ``report.get('series_dependency_hash') == series_dependency_hash`` where
    both could be None — certifying a report with no recorded provenance.
    """
    from datetime import datetime, timezone
    import services.nexus_data.quality.stored_audit as sa

    now = datetime.now(timezone.utc)
    await put(operational_store, now)
    _, summary = await _audit_and_fetch_summary(operational_store, now)
    assert summary.get('series_dependency_hash')  # sanity: audit records it

    def _oversized(conn, symbol, timeframe):
        raise ValueError('Combined coverage exceeds bounded audit limit')

    monkeypatch.setattr(sa, 'combined_rows', _oversized)
    _rewrite_summary(operational_store, lambda s: s.pop('series_dependency_hash', None))

    result = await sa.latest_quality(operational_store, 'XAUUSD', 'M5', 'mt5_poll')
    assert result is not None
    assert result['snapshot_current'] is False


@pytest.mark.asyncio
async def test_empty_stored_series_hash_is_never_current(operational_store):
    from datetime import datetime, timezone
    import services.nexus_data.quality.stored_audit as sa

    now = datetime.now(timezone.utc)
    await put(operational_store, now)
    await _audit_and_fetch_summary(operational_store, now)
    _rewrite_summary(operational_store, lambda s: s.update(series_dependency_hash=''))

    result = await sa.latest_quality(operational_store, 'XAUUSD', 'M5', 'mt5_poll')
    assert result['snapshot_current'] is False


@pytest.mark.asyncio
async def test_missing_stored_calendar_hash_is_never_current(operational_store):
    """A report with no recorded calendar provenance must not self-certify."""
    from datetime import datetime, timezone
    import services.nexus_data.quality.stored_audit as sa

    now = datetime.now(timezone.utc)
    await put(operational_store, now)
    await _audit_and_fetch_summary(operational_store, now)
    _rewrite_summary(operational_store, lambda s: s.pop('calendar_dependency_hash', None))

    result = await sa.latest_quality(operational_store, 'XAUUSD', 'M5', 'mt5_poll')
    assert result['snapshot_current'] is False


@pytest.mark.asyncio
async def test_valid_matching_hashes_still_verify(operational_store):
    """Control: intact provenance on both sides still verifies as current."""
    from datetime import datetime, timezone
    import services.nexus_data.quality.stored_audit as sa

    now = datetime.now(timezone.utc)
    await put(operational_store, now)
    await _audit_and_fetch_summary(operational_store, now)

    result = await sa.latest_quality(operational_store, 'XAUUSD', 'M5', 'mt5_poll')
    assert result['snapshot_current'] is True
