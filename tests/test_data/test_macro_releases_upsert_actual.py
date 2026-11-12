"""Regression: macro_releases must UPSERT on event_id (MASTER PROMPT V4.1).

Before the 2026-11-12 fix, ``macro_releases`` was missing from
``FundamentalStore.UPSERT_KEYS`` — plain INSERT OR IGNORE silently dropped
every Actual update and Previous revision. The MT5 calendar bridge (and the
web calendar) depend on the canonical row reflecting the latest release while
``data_vintages`` keeps point-in-time history.
"""
from __future__ import annotations

import pytest

from services.nexus_data.duckdb_store import DataStore
from services.nexus_data.fundamental_store import FundamentalStore

BASE = {
    "event_id": "cal_test_macro_releases_upsert",
    "indicator_code": "TEST_CPI",
    "indicator_name_en": "Test CPI",
    "indicator_name_ar": "اختبار",
    "frequency": "monthly",
    "unit": "%",
    "actual": None,
    "forecast": "0.3",
    "previous": "0.2",
    "release_timestamp": "2026-11-12T09:00:00+00:00",
}


@pytest.mark.asyncio
async def test_macro_releases_upserts_actual_update(tmp_path, monkeypatch):
    monkeypatch.delenv("NEXUS_QUALITY_GATE", raising=False)
    ds = DataStore(db_path=str(tmp_path / "qa_upsert.duckdb"))
    await ds.init_tables()
    store = FundamentalStore(ds)
    await store.init_schema()

    # 0) parent fund_events row first (macro_releases.event_id is an FK) —
    #    the same startup-order lesson as defect D3.
    await store.insert_record("fund_events", {
        "event_id": BASE["event_id"],
        "category": "macro",
        "event_type": "economic_release",
        "event_code": "TEST_CPI",
        "title_en": "Test CPI",
        "title_ar": "اختبار",
        "received_at": "2026-11-12T09:00:00+00:00",
    })

    # 1) first write: scheduled release, no actual yet
    await store.insert_record("macro_releases", dict(BASE))
    rows = await ds._fetch(
        "SELECT actual, forecast FROM macro_releases WHERE event_id=?",
        (BASE["event_id"],),
    )
    assert rows, "first insert must create the row"
    assert rows[0][0] is None and abs(float(rows[0][1]) - 0.3) < 1e-9

    # 2) the Actual arrives later — same event_id, new value
    update = dict(BASE)
    update["actual"] = "0.4"
    await store.insert_record("macro_releases", update)

    rows = await ds._fetch(
        "SELECT actual, forecast, previous FROM macro_releases WHERE event_id=?",
        (BASE["event_id"],),
    )
    assert len(rows) == 1, "upsert must not duplicate the row"
    actual, forecast, previous = rows[0]
    assert actual is not None and abs(float(actual) - 0.4) < 1e-9,         f"Actual update was dropped (got {actual!r})"
    assert forecast is not None and abs(float(forecast) - 0.3) < 1e-9
    assert previous is not None and abs(float(previous) - 0.2) < 1e-9

    # 3) a Previous revision also overwrites
    revision = dict(BASE)
    revision["actual"] = "0.4"
    revision["previous"] = "0.25"
    await store.insert_record("macro_releases", revision)
    rows = await ds._fetch(
        "SELECT previous FROM macro_releases WHERE event_id=?",
        (BASE["event_id"],),
    )
    assert rows[0][0] is not None and abs(float(rows[0][0]) - 0.25) < 1e-9,         "Previous revision was dropped"
