from datetime import datetime, timezone

import pytest

from services.nexus_data.duckdb_store import DataStore
from services.nexus_data.fundamental_store import FundamentalStore


@pytest.mark.asyncio
async def test_impact_snapshot_retry_preserves_outcome_reference(tmp_path):
    store = DataStore(str(tmp_path / "impact-history.duckdb"))
    await store.init_tables()
    fundamental = FundamentalStore(store)
    await fundamental.init_schema()
    at = datetime(2026, 10, 19, tzinfo=timezone.utc)
    impact = dict(
        impact_id="snapshot-1", asset_id="BTCUSD", direction="neutral",
        impact_score=10.0, horizon="5m", engine_version="test",
        feature_schema_version="test", known_at=at, calculated_at=at,
    )
    try:
        await fundamental.insert_record("asset_registry", {
            "asset_id": "BTCUSD", "symbol": "BTCUSD", "asset_class": "crypto",
        })
        await fundamental.insert_record("event_asset_impacts", impact)
        await fundamental.insert_record("asset_event_outcomes", {
            "outcome_id": "outcome-1", "impact_id": "snapshot-1", "asset_id": "BTCUSD",
            "market_timestamp": at, "captured_at": at,
        })
        await fundamental.insert_record("event_asset_impacts", {**impact, "impact_score": 99.0})
        await fundamental.insert_record("event_asset_impacts", {**impact, "impact_id": "snapshot-2", "impact_score": 20.0})
        assert await store._fetch(
            "SELECT impact_score FROM event_asset_impacts ORDER BY impact_id"
        ) == [(10.0,), (20.0,)]
        assert await store._fetch("SELECT impact_id FROM asset_event_outcomes") == [("snapshot-1",)]
        assert store.is_open
    finally:
        await store.aclose()
