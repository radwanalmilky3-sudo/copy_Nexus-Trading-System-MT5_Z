from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from services.nexus_data.duckdb_store import DataStore
from services.nexus_data.fundamental_store import FundamentalStore

NEW_COLUMNS = (
    "timing_quality",
    "authority",
    "release_tzid",
    "decision_date_local",
    "scheduled_status",
    "supersedes_event_id",
    "cancelled",
    "source_sha256",
    "retrieved_at_utc",
)

RECEIVED_AT = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)


def _legacy_record(event_id: str = "evt-legacy-1", event_code: str = "US_CPI") -> dict:
    """Pre-Phase-4 style insert: none of the new timing fields are supplied."""
    return {
        "event_id": event_id,
        "category": "macro",
        "event_type": "economic_release",
        "event_code": event_code,
        "title_en": "US CPI",
        "received_at": RECEIVED_AT,
    }


async def _open(tmp_path, name: str, monkeypatch) -> tuple[DataStore, FundamentalStore]:
    monkeypatch.delenv("NEXUS_QUALITY_GATE", raising=False)
    store = DataStore(db_path=str(tmp_path / name))
    await store.init_tables()
    fundamental = FundamentalStore(store)
    await fundamental.init_schema()
    return store, fundamental


async def _timing_columns(store: DataStore, event_id: str) -> dict:
    marks = ",".join(NEW_COLUMNS)
    rows = await store._fetch(
        f"SELECT {marks} FROM fund_events WHERE event_id=? LIMIT 1", (event_id,)
    )
    assert rows, f"missing event: {event_id}"
    return dict(zip(NEW_COLUMNS, rows[0]))


@pytest.mark.asyncio
async def test_timing_columns_exist_and_legacy_insert_stores_null(tmp_path, monkeypatch):
    store, fundamental = await _open(tmp_path, "timing-cols.duckdb", monkeypatch)
    try:
        info = await store._fetch("PRAGMA table_info('fund_events')")
        columns = {row[1]: row for row in info}
        for name in NEW_COLUMNS:
            assert name in columns, f"missing column: {name}"
            row = columns[name]
            assert row[2].upper() in {"VARCHAR", "DATE", "BOOLEAN", "TIMESTAMP WITH TIME ZONE"}
            assert row[3] == 0, f"{name} must be nullable"
            assert row[4] is None, f"{name} must default to NULL"

        await fundamental.insert_record("fund_events", _legacy_record())
        values = await _timing_columns(store, "evt-legacy-1")
        assert values == dict.fromkeys(NEW_COLUMNS)
    finally:
        store.close()


@pytest.mark.asyncio
async def test_insert_with_new_timing_fields_round_trips(tmp_path, monkeypatch):
    store, fundamental = await _open(tmp_path, "timing-rt.duckdb", monkeypatch)
    try:
        retrieved_at = datetime(2026, 1, 5, 12, 5, 30, tzinfo=timezone.utc)
        record = _legacy_record(event_id="evt-new-1")
        record.update(
            timing_quality="official_event_scheduled_time",
            authority="FED",
            release_tzid="America/New_York",
            decision_date_local=date(2026, 1, 7),
            scheduled_status="scheduled",
            cancelled=False,
            source_sha256="a" * 64,
            retrieved_at_utc=retrieved_at,
        )
        await fundamental.insert_record("fund_events", record)

        values = await _timing_columns(store, "evt-new-1")
        assert values["timing_quality"] == "official_event_scheduled_time"
        assert values["authority"] == "FED"
        assert values["release_tzid"] == "America/New_York"
        assert values["decision_date_local"] == date(2026, 1, 7)
        assert values["scheduled_status"] == "scheduled"
        assert values["cancelled"] is False
        assert values["supersedes_event_id"] is None
        assert values["source_sha256"] == "a" * 64
        assert values["retrieved_at_utc"] == retrieved_at
    finally:
        store.close()


@pytest.mark.asyncio
async def test_cancellation_is_append_only(tmp_path, monkeypatch):
    store, fundamental = await _open(tmp_path, "timing-cancel.duckdb", monkeypatch)
    try:
        original = _legacy_record(event_id="evt-fed-1", event_code="FED_RATE")
        original.update(
            timing_quality="official_date_only",
            authority="FED",
            release_tzid="America/New_York",
            decision_date_local=date(2026, 1, 28),
            scheduled_status="scheduled",
        )
        await fundamental.insert_record("fund_events", original)

        new_id = await fundamental.mark_event_cancelled(
            "evt-fed-1", reason="meeting postponed",
        )
        assert new_id == "evt-fed-1:cancelled"

        legacy = await _timing_columns(store, "evt-fed-1")
        assert legacy["cancelled"] is None
        assert legacy["scheduled_status"] == "scheduled"
        assert legacy["supersedes_event_id"] is None

        cancellation = await _timing_columns(store, new_id)
        assert cancellation["cancelled"] is True
        assert cancellation["scheduled_status"] == "cancelled"
        assert cancellation["supersedes_event_id"] == "evt-fed-1"
        assert cancellation["timing_quality"] == "official_date_only"
        assert cancellation["release_tzid"] == "America/New_York"

        audit = await store._fetch(
            "SELECT action,entity_id,reason FROM fundamental_audit_log"
        )
        assert audit == [("fund_event_cancelled", new_id, "meeting postponed")]

        timeline = await fundamental.get_event_timeline(event_code="FED_RATE")
        assert [row["event_id"] for row in timeline] == ["evt-fed-1", new_id]
        active = await fundamental.get_event_timeline(
            event_code="FED_RATE", include_cancelled=False,
        )
        assert [row["event_id"] for row in active] == ["evt-fed-1"]

        second = await fundamental.mark_event_cancelled("evt-fed-1", reason="again")
        assert second == "evt-fed-1:cancelled:2"
    finally:
        store.close()


@pytest.mark.asyncio
async def test_migration_is_idempotent_across_reruns_and_reopen(tmp_path, monkeypatch):
    store, fundamental = await _open(tmp_path, "timing-idem.duckdb", monkeypatch)
    db_path = str(tmp_path / "timing-idem.duckdb")
    try:
        record = _legacy_record()
        record.update(
            timing_quality="official_rule_derived",
            scheduled_status="scheduled",
            cancelled=False,
        )
        await fundamental.insert_record("fund_events", record)

        await fundamental.init_schema()
        await fundamental.init_schema()
        values = await _timing_columns(store, "evt-legacy-1")
        assert values["timing_quality"] == "official_rule_derived"
        assert values["cancelled"] is False
    finally:
        store.close()

    reopened = DataStore(db_path=db_path)
    await reopened.init_tables()
    reopened_fundamental = FundamentalStore(reopened)
    await reopened_fundamental.init_schema()
    try:
        values = await _timing_columns(reopened, "evt-legacy-1")
        assert values["timing_quality"] == "official_rule_derived"
        assert values["scheduled_status"] == "scheduled"
    finally:
        reopened.close()


@pytest.mark.asyncio
async def test_legacy_query_helpers_unchanged_with_null_timing_fields(tmp_path, monkeypatch):
    store, fundamental = await _open(tmp_path, "timing-legacy-q.duckdb", monkeypatch)
    try:
        await fundamental.insert_record("fund_events", _legacy_record())
        await fundamental.insert_record(
            "fund_events", _legacy_record(event_id="evt-legacy-2", event_code="ECB_RATE"),
        )

        rows = await fundamental.latest_rows("fund_events", "created_at", limit=10)
        assert {row["event_id"] for row in rows} == {"evt-legacy-1", "evt-legacy-2"}
        for row in rows:
            for column in NEW_COLUMNS:
                assert row[column] is None

        timeline = await fundamental.get_event_timeline(event_code="US_CPI")
        assert [row["event_id"] for row in timeline] == ["evt-legacy-1"]

        with pytest.raises(ValueError):
            await fundamental.get_event_timeline()
    finally:
        store.close()
