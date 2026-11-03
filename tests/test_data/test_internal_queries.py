from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from services.nexus_data.fundamental_store import FundamentalStore


class RecordingDataStore:
    def __init__(self) -> None:
        self.sql = ""
        self.params: tuple[object, ...] = ()

    async def _fetch_with_columns(self, sql: str, params: tuple[object, ...] = ()):
        self.sql = sql
        self.params = params
        return [("user-1",)], ["user_id"]


@pytest.mark.asyncio
async def test_named_user_lookup_binds_username_as_a_parameter():
    store = RecordingDataStore()
    queries = FundamentalStore(store)

    rows = await queries.query_named(
        "user_by_username", {"username": "x' OR TRUE --"}
    )

    assert rows == [{"user_id": "user-1"}]
    assert "x' OR TRUE --" not in store.sql
    assert store.params == ("x' OR TRUE --",)


@pytest.mark.asyncio
async def test_named_query_rejects_unregistered_operation():
    queries = FundamentalStore(RecordingDataStore())

    with pytest.raises(ValueError, match="unknown query operation"):
        await queries.query_named("SELECT * FROM app_users", {})


@pytest.mark.asyncio
async def test_named_query_rejects_unexpected_parameters():
    queries = FundamentalStore(RecordingDataStore())

    with pytest.raises(ValueError, match="parameters"):
        await queries.query_named("user_by_username", {"username": "r", "sql": "DROP TABLE"})


@pytest.mark.asyncio
async def test_named_query_allows_null_values_as_bound_sql_values():
    store = RecordingDataStore()
    queries = FundamentalStore(store)

    await queries.query_named("asset_event_outcome_by_impact", {"impact_id": None})

    assert store.params == (None,)


@pytest.mark.asyncio
async def test_user_lookup_runs_against_the_owned_duckdb_connection(tmp_path):
    from services.nexus_data.duckdb_store import DataStore

    data_store = DataStore(db_path=str(tmp_path / "auth-query.duckdb"))
    await data_store.init_tables()
    queries = FundamentalStore(data_store)
    await queries.init_schema()
    try:
        now = datetime.now(timezone.utc)
        await queries.insert_record("app_users", {
            "user_id": "user-1",
            "username": "ridwan",
            "full_name": "Ridwan",
            "password_hash": "scrypt$test",
            "active": True,
            "deleted": False,
            "created_at": now,
            "updated_at": now,
        })
        rows = await queries.query_named("user_by_username", {"username": "RIDWAN"})
        assert len(rows) == 1
        assert rows[0]["user_id"] == "user-1"
        assert rows[0]["password_hash"] == "scrypt$test"
    finally:
        data_store.close()


@pytest.mark.asyncio
async def test_fundamental_store_rejects_orphan_user_role_before_writing():
    class RelationStore:
        def __init__(self):
            self.writes = []

        async def _fetch(self, sql: str, params=()):
            if "information_schema.columns" in sql:
                return [
                    ("user_id", "NO", None),
                    ("role_id", "NO", None),
                    ("active", "YES", None),
                ]
            if "FROM app_users" in sql:
                return [("user-1",)]
            if "FROM app_roles" in sql:
                return []
            raise AssertionError(f"unexpected reference query: {sql}")

        async def _run(self, sql: str, params=()):
            self.writes.append((sql, params))

    data_store = RelationStore()
    queries = FundamentalStore(data_store)

    with pytest.raises(ValueError, match="app_roles.role_id"):
        await queries.insert_record("app_user_roles", {
            "user_id": "user-1",
            "role_id": "missing-role",
            "active": True,
        })

    assert data_store.writes == []


@pytest.mark.asyncio
async def test_data_service_owns_legacy_gateway_query_tables(tmp_path):
    from services.nexus_data.duckdb_store import DataStore

    data_store = DataStore(db_path=str(tmp_path / "gateway-tables.duckdb"))
    await data_store.init_tables()
    queries = FundamentalStore(data_store)
    await queries.init_schema()
    try:
        assert await queries.query_named("positions_by_status", {"status": "open"}) == []
        assert await queries.query_named("agent_reasoning", {"cycle_id": "c1", "cycle_pattern": "%c1%"}) == []
    finally:
        data_store.close()


@pytest.mark.asyncio
async def test_internal_query_route_requires_service_secret(monkeypatch):
    from services.nexus_data import main

    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "service-secret")
    called = False

    async def query_named(operation: str, params: dict[str, object]):
        nonlocal called
        called = True
        return [{"user_id": "u1"}]

    monkeypatch.setattr(main.fundamental_store, "query_named", query_named)
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.post("/api/data/query", json={"operation": "user_by_id", "params": {"user_id": "u1"}})

    assert response.status_code == 403
    assert not called


@pytest.mark.asyncio
async def test_internal_query_route_returns_rows_for_valid_service_secret(monkeypatch):
    from services.nexus_data import main

    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "service-secret")

    async def query_named(operation: str, params: dict[str, object]):
        assert operation == "user_by_id"
        assert params == {"user_id": "u1"}
        return [{"user_id": "u1"}]

    monkeypatch.setattr(main.fundamental_store, "query_named", query_named)
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.post(
            "/api/data/query",
            headers={"X-Nexus-Internal-Secret": "service-secret"},
            json={"operation": "user_by_id", "params": {"user_id": "u1"}},
        )

    assert response.status_code == 200
    assert response.json() == {"rows": [{"user_id": "u1"}]}
