"""Regression: snapshot retries never rewrite indexed outcome parents."""
import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pytest

from services.nexus_data.duckdb_store import DataStore
from services.nexus_data.fundamental_store import FundamentalStore


@pytest.mark.parametrize("mode", ["full", "score_only", "score_time"])
@pytest.mark.parametrize("with_outcome", [False, True])
def test_impact_update_repro(tmp_path, monkeypatch, mode, with_outcome):
    async def run():
        store = DataStore(str(tmp_path / "impact-repro.duckdb"))
        store._conn = duckdb.connect(store._db_path)
        fundamental = FundamentalStore(store)
        schema = (Path(__file__).resolve().parents[2] / "services/nexus_data/fundamental_schema.sql").read_text(encoding="utf-8")
        statements = []
        for table in ("fund_sources", "fund_events", "fundamental_fusion_results",
                      "gold_impact_predictions", "asset_registry", "event_asset_impacts",
                      "asset_event_outcomes"):
            statements.append(re.search(rf"CREATE TABLE IF NOT EXISTS {table} \(.*?\n\);", schema, re.S).group())
        for index in ("idx_asset_impact_asset_time", "idx_asset_impact_event", "idx_asset_outcome_impact"):
            statements.append(re.search(rf"CREATE INDEX IF NOT EXISTS {index} .*?;", schema).group())
        now = datetime(2026, 10, 19, tzinfo=timezone.utc)
        impact = dict(impact_id="impact-repro", event_id="event-repro", asset_id="BTCUSD",
                      prediction_id=None, event_stage="at_release", direction="neutral",
                      impact_score=1.0, horizon="5m", engine_version="repro",
                      feature_schema_version="fundamental-v6.1", known_at=now, calculated_at=now)
        try:
            await store._run_script("\n".join(statements))
            await store._run("INSERT INTO asset_registry(asset_id,symbol,asset_class) VALUES ('BTCUSD','BTCUSD','crypto')")
            await store._run("INSERT INTO fund_events(event_id,category,event_type,event_code,received_at) VALUES ('event-repro','macro','repro','repro',?)", (now,))
            await fundamental.insert_record("event_asset_impacts", impact)
            if with_outcome:
                await fundamental.insert_record("asset_event_outcomes", dict(
                    outcome_id="outcome-repro", impact_id="impact-repro", asset_id="BTCUSD",
                    event_id="event-repro", market_timestamp=now, captured_at=now))
            captured = []
            real_run = store._run

            async def traced(sql, params=()):
                captured.append(sql)
                return await real_run(sql, params)

            monkeypatch.setattr(store, "_run", traced)
            update = {**impact, "impact_score": 2.0, "calculated_at": now + timedelta(minutes=1)}
            if mode != "full":
                # Required fields stay present; omitted identities stay untouched.
                update = {k: update[k] for k in ("impact_id", "asset_id", "direction", "impact_score", "horizon", "engine_version", "feature_schema_version", "known_at", "calculated_at")}
                if mode == "score_only":
                    update["calculated_at"] = now
            error = None
            try:
                await fundamental.insert_record("event_asset_impacts", update)
            except Exception as exc:
                error = exc
            chain = []
            cause = error
            while cause is not None:
                chain.append({"type": type(cause).__name__, "message": str(cause)})
                cause = cause.__cause__
            readable = await store._fetch("SELECT impact_score,calculated_at FROM event_asset_impacts WHERE impact_id='impact-repro'", ()) if store.is_open else None
            print(json.dumps(dict(mode=mode, with_outcome=with_outcome, duckdb=duckdb.__version__,
                                  statements=captured, errors=chain, is_open=store.is_open,
                                  row=readable), default=str))
            assert not any(sql.startswith("UPDATE event_asset_impacts SET ") for sql in captured)
            assert error is None
            assert store.is_open
            assert readable == [(1.0, now)]
        finally:
            store.close()
    asyncio.run(run())
