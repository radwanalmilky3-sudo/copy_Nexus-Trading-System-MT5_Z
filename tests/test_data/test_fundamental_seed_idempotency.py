from __future__ import annotations

import pytest

from services.nexus_data.duckdb_store import DataStore
from services.nexus_data.fundamental_store import FundamentalStore
from services.nexus_news.fundamental.bootstrap_v5 import knowledge_seed


@pytest.mark.asyncio
async def test_reseeding_versioned_knowledge_claim_does_not_update_existing_row(tmp_path):
    store = DataStore(db_path=str(tmp_path / "fundamental-seed.duckdb"))
    await store.init_tables()
    fundamental = FundamentalStore(store)
    await fundamental.init_schema()
    sources, claims = knowledge_seed()
    claim = claims[0]
    assert claim["claim_id"] == "claim_cycle_rates_v4"
    assert len(claim) == 17

    try:
        await fundamental.insert_record("fundamental_knowledge_sources", sources[0])
        await fundamental.insert_record("fundamental_knowledge_claims", claim)
        original_row = await store._fetch(
            "SELECT statement_ar, version, updated_at FROM fundamental_knowledge_claims "
            "WHERE claim_id = ?",
            (claim["claim_id"],),
        )

        changed_claim = {**claim, "statement_ar": "محتوى تجريبي لإصدار جديد"}
        await fundamental.insert_record("fundamental_knowledge_claims", changed_claim)

        rows = await store._fetch(
            "SELECT statement_ar, version, updated_at FROM fundamental_knowledge_claims "
            "WHERE claim_id = ?",
            (claim["claim_id"],),
        )
        assert rows == original_row
        assert rows[0][:2] == (claim["statement_ar"], claim["version"])
    finally:
        store.close()
