from __future__ import annotations

import pytest

from services.nexus_data import duckdb_store


@pytest.mark.asyncio
@pytest.mark.parametrize("recovery_setting", [None, "1"])
async def test_failed_checkpoint_preserves_large_wal(tmp_path, monkeypatch, recovery_setting):
    db_path = tmp_path / "recovery.duckdb"
    wal_path = tmp_path / "recovery.duckdb.wal"
    wal_contents = b"preserve-uncheckpointed-data" * (200_000)
    wal_path.write_bytes(wal_contents)
    if recovery_setting is None:
        monkeypatch.delenv("NEXUS_DUCKDB_WAL_RECOVERY", raising=False)
    else:
        monkeypatch.setenv("NEXUS_DUCKDB_WAL_RECOVERY", recovery_setting)

    def fail_to_open_database(*args, **kwargs):
        raise RuntimeError("simulated checkpoint failure")

    monkeypatch.setattr(duckdb_store.duckdb, "connect", fail_to_open_database)

    await duckdb_store.DataStore(str(db_path))._recover_stale_wal(str(db_path))

    assert wal_path.exists()
    assert wal_path.read_bytes() == wal_contents


@pytest.mark.asyncio
async def test_large_wal_recovery_does_not_open_a_second_duckdb_engine(
    tmp_path, monkeypatch,
):
    db_path = tmp_path / "single-engine-recovery.duckdb"
    wal_path = tmp_path / "single-engine-recovery.duckdb.wal"
    wal_path.write_bytes(b"pending-wal" * 500_000)

    opened_second_engine = False

    def reject_second_engine(*args, **kwargs):
        nonlocal opened_second_engine
        opened_second_engine = True
        raise RuntimeError("WAL recovery must not open a second DuckDB engine")

    monkeypatch.setattr(duckdb_store.duckdb, "connect", reject_second_engine)

    await duckdb_store.DataStore(str(db_path))._recover_stale_wal(str(db_path))

    assert not opened_second_engine
    assert wal_path.exists()


@pytest.mark.asyncio
async def test_fatal_duckdb_error_marks_store_unhealthy():
    store = duckdb_store.DataStore(":memory:")

    class InvalidatedConnection:
        def execute(self, *_args, **_kwargs):
            raise duckdb_store.duckdb.FatalException("simulated index failure")

    store._conn = InvalidatedConnection()
    try:
        with pytest.raises(duckdb_store.duckdb.FatalException):
            await store._run("SELECT 1")

        assert not store.is_open
        with pytest.raises(RuntimeError, match="DuckDB store is unavailable"):
            await store._run("SELECT 1")
    finally:
        store._conn = None


@pytest.mark.asyncio
async def test_schema_initialization_runs_through_locked_executor(tmp_path, monkeypatch):
    store = duckdb_store.DataStore(str(tmp_path / "schema-locked.duckdb"))
    calls = []

    async def execute_locked(operation):
        calls.append(operation)
        return operation()

    monkeypatch.setattr(store, "_execute_locked", execute_locked)
    async def skip_recovery(_path):
        return None

    monkeypatch.setattr(store, "_recover_stale_wal", skip_recovery)
    monkeypatch.setattr(duckdb_store.duckdb, "connect", lambda _path: object())
    monkeypatch.setattr(store, "_create_schemas", lambda: None)

    await store.init_tables()

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_schema_fatal_exception_closes_and_invalidates_connection(tmp_path, monkeypatch):
    store = duckdb_store.DataStore(str(tmp_path / "schema-fatal.duckdb"))

    class Connection:
        closed = False

        def close(self):
            self.closed = True

    connection = Connection()
    async def skip_recovery(_path):
        return None

    monkeypatch.setattr(store, "_recover_stale_wal", skip_recovery)
    monkeypatch.setattr(duckdb_store.duckdb, "connect", lambda _path: connection)

    def fail_schema():
        raise duckdb_store.duckdb.FatalException("schema fatal")

    monkeypatch.setattr(store, "_create_schemas", fail_schema)

    with pytest.raises(duckdb_store.duckdb.FatalException, match="schema fatal"):
        await store.init_tables()

    assert connection.closed
    assert store._conn is None
    assert store._invalidated
    assert not store.is_open


@pytest.mark.asyncio
async def test_checkpoint_fatal_exception_is_propagated_and_connection_closed(tmp_path, monkeypatch):
    db_path = tmp_path / "checkpoint-fatal.duckdb"
    store = duckdb_store.DataStore(str(db_path))
    store._conn = None
    connection = _CheckpointFatalConnection()

    async def skip_recovery(_path):
        return None

    async def execute_schema(operation):
        return operation()

    store._recover_stale_wal = skip_recovery
    store._execute_locked = execute_schema
    monkeypatch.setattr(duckdb_store.duckdb, "connect", lambda _path: connection)
    store._create_schemas = lambda: connection.execute("CHECKPOINT")

    with pytest.raises(duckdb_store.duckdb.FatalException, match="checkpoint fatal"):
        await store.init_tables()

    assert store._conn is None
    assert store._invalidated
    assert not store.is_open


class _CheckpointFatalConnection:
    closed = False

    def execute(self, sql):
        assert sql == "CHECKPOINT"
        raise duckdb_store.duckdb.FatalException("checkpoint fatal")

    def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_default_catalog_replay_failure_recovers_through_same_owner_connection(tmp_path, monkeypatch):
    db_path = tmp_path / "catalog's-recovery.duckdb"
    real_connect = duckdb_store.duckdb.connect
    con = real_connect(str(db_path))
    con.execute("CREATE TABLE recovery_marker(id INTEGER)")
    con.execute("INSERT INTO recovery_marker VALUES (42)")
    con.close()

    def affected_direct_open(path):
        if path != ':memory:':
            raise duckdb_store.duckdb.InternalException(
                'Failure while replaying WAL file: Calling DatabaseManager::GetDefaultDatabase with no default database set')
        return real_connect(path)

    monkeypatch.setattr(duckdb_store.duckdb, 'connect', affected_direct_open)
    store = duckdb_store.DataStore(str(db_path))
    try:
        await store.init_tables()
        assert await store._fetch('SELECT id FROM recovery_marker') == [(42,)]
        assert store.is_open
    finally:
        await store.aclose()
    con = real_connect(str(db_path))
    assert con.execute('SELECT id FROM recovery_marker').fetchall() == [(42,)]
    con.close()
