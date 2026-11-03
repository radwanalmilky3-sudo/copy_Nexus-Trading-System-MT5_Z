import pytest
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import duckdb
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.nexus_data import trial_registry as registry


@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.delenv("NEXUS_DATA_URL", raising=False)
    monkeypatch.setenv("TRIAL_REGISTRY_DB", str(tmp_path / "trials.duckdb"))
    return registry


def test_partial_family_is_not_disclosed(local):
    assert local.record_trial(family_id="partial", p_value=0.01, total_trials=2)
    assert not local.has_disclosed_family("partial")
    assert local.best_family_q_value("partial") is None


def test_remote_failure_never_opens_local(local, monkeypatch):
    monkeypatch.setenv("NEXUS_DATA_URL", "http://unused.invalid")
    monkeypatch.delenv("NEXUS_INTERNAL_API_SECRET", raising=False)
    def forbidden():
        pytest.fail("remote mode opened local DuckDB")
    monkeypatch.setattr(registry, "_connect", forbidden)
    assert local.record_family("remote", [0.01]) is None
    assert local.get_family("remote") == []
    assert not local.has_disclosed_family("remote")


def test_family_failure_rolls_back(local, monkeypatch):
    original = registry._connect
    class Broken:
        def __init__(self):
            self.conn = original()
        def execute(self, sql, *args):
            return self.conn.execute(sql, *args)
        def executemany(self, sql, rows):
            self.conn.execute(sql, rows[0])
            raise RuntimeError("injected failure after first insert")
        def close(self):
            self.conn.close()
    monkeypatch.setattr(registry, "_connect", Broken)
    assert local.record_family("atomic", [0.01, 0.02]) is None
    monkeypatch.setattr(registry, "_connect", original)
    assert local.get_family("atomic") == []


@pytest.fixture
def service(tmp_path, monkeypatch):
    from services.nexus_data.duckdb_store import DataStore
    from services.nexus_data.trial_registry_router import create_router
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "unit-test-only-credential")
    store = DataStore.__new__(DataStore)
    store._conn = duckdb.connect(str(tmp_path / "service.duckdb"))
    store._connection_lock = asyncio.Lock()
    store._invalidated = False
    app = FastAPI()
    app.include_router(create_router(store))
    try:
        with TestClient(app) as client:
            yield store, client
    finally:
        store._conn.close()


def test_secret_checked_before_store(service, monkeypatch):
    store, client = service
    async def forbidden(*args):
        pytest.fail("unauthorized request touched store")
    monkeypatch.setattr(store, "_execute_locked", forbidden)
    payload = {"family_id": "x"}
    assert client.post("/internal/trials/get", json=payload).status_code == 403
    assert client.post("/internal/trials/get", json=payload,
                       headers={"X-Nexus-Internal-Secret": "wrong"}).status_code == 403
    monkeypatch.delenv("NEXUS_INTERNAL_API_SECRET")
    assert client.post("/internal/trials/get", json=payload).status_code == 503


def test_remote_roundtrip_uses_existing_connection_and_lock(service, monkeypatch):
    import httpx
    store, client = service
    monkeypatch.setenv("NEXUS_DATA_URL", "http://testserver")
    original = store._execute_locked
    calls = []
    async def checked(operation):
        def guarded():
            assert store._connection_lock.locked()
            calls.append(threading.get_ident())
            return operation()
        return await original(guarded)
    monkeypatch.setattr(store, "_execute_locked", checked)
    def forbidden():
        pytest.fail("HTTP registry opened local connection")
    monkeypatch.setattr(registry, "_connect", forbidden)
    class Transport:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, url, **kwargs):
            return client.post(url, **kwargs)
    monkeypatch.setattr(httpx, "Client", Transport)
    assert registry.record_family("remote-ok", [0.01, 0.2]) == pytest.approx([0.02, 0.2])
    assert registry.has_disclosed_family("remote-ok")
    assert registry.best_family_q_value("remote-ok") == pytest.approx(0.02)
    assert registry.record_trial(family_id="one", p_value=0.04)
    assert registry.record_family("remote-ok", [0.01, 0.2]) == pytest.approx([0.02, 0.2])
    assert registry.record_family("remote-ok", [0.001]) is None
    assert len(registry.get_family("remote-ok")) == 2
    assert len(calls) >= 6


def test_concurrent_requests_serialize_on_store(service, monkeypatch):
    store, client = service
    headers = {"X-Nexus-Internal-Secret": "unit-test-only-credential"}
    original = registry._insert_rows
    active = 0
    maximum = 0
    guard = threading.Lock()
    def insert(conn, rows):
        nonlocal active, maximum
        with guard:
            active += 1
            maximum = max(maximum, active)
        try:
            assert store._connection_lock.locked()
            assert conn is store._conn
            original(conn, rows)
        finally:
            with guard:
                active -= 1
    monkeypatch.setattr(registry, "_insert_rows", insert)
    def send(i):
        return client.post("/internal/trials/family", headers=headers,
                           json={"family_id": f"parallel-{i}", "p_values": [0.01, 0.02]})
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(send, range(8)))
    assert all(r.status_code == 200 for r in responses)
    assert maximum == 1
    assert store._conn.execute("SELECT count(*) FROM research_trials").fetchone()[0] == 16


def test_service_transaction_failure_is_closed(service, monkeypatch):
    store, client = service
    original = store._conn
    class FailingConnection:
        def execute(self, *args):
            return original.execute(*args)
        def executemany(self, sql, rows):
            original.execute(sql, rows[0])
            raise RuntimeError("injected failure")
    store._conn = FailingConnection()
    try:
        response = client.post("/internal/trials/family",
                               headers={"X-Nexus-Internal-Secret": "unit-test-only-credential"},
                               json={"family_id": "rollback", "p_values": [0.01, 0.02]})
        assert response.status_code == 503
        assert registry._read_rows(original, "rollback") == []
    finally:
        store._conn = original


def test_promotion_caller_rejects_failed_storage(local, monkeypatch):
    from services.nexus_ml.model_promotion import disclose_promotion_family
    from tests.test_ml.test_statistical_gates import fold_metrics
    monkeypatch.setattr(registry, "_connect", lambda: (_ for _ in ()).throw(OSError("offline")))
    assert disclose_promotion_family(fold_metrics(log_loss=0.4),
                                     fold_metrics(log_loss=0.5), "failed") is None


@pytest.mark.parametrize("failure", ["timeout", "invalid_json", "partial_ack"])
def test_http_errors_fail_closed_without_local_fallback(local, monkeypatch, failure):
    import httpx
    monkeypatch.setenv("NEXUS_DATA_URL", "http://unused.invalid")
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "unit-test-only-credential")
    def forbidden():
        pytest.fail("remote failure fell back to local")
    monkeypatch.setattr(registry, "_connect", forbidden)
    class Transport:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, url, **kwargs):
            request = httpx.Request("POST", url)
            if failure == "timeout":
                raise httpx.ReadTimeout("offline", request=request)
            if failure == "invalid_json":
                return httpx.Response(200, text="invalid", request=request)
            return httpx.Response(200, json={"ok": True, "result": [0.01]}, request=request)
    monkeypatch.setattr(httpx, "Client", Transport)
    assert registry.record_family("failed", [0.01, 0.02]) is None
    assert not registry.has_disclosed_family("failed")
    assert registry.best_family_q_value("failed") is None


def test_unavailable_store_returns_503(service):
    store, client = service
    store._invalidated = True
    response = client.post("/internal/trials/get", json={"family_id": "none"},
                           headers={"X-Nexus-Internal-Secret": "unit-test-only-credential"})
    assert response.status_code == 503


def test_family_retry_is_idempotent_and_conflicts_rejected(local):
    assert local.record_family("retry", [0.01, 0.02], meta={"a": 1}) == [0.02, 0.02]
    assert local.record_family("retry", [0.01, 0.02], meta={"a": 1}) == [0.02, 0.02]
    assert len(local.get_family("retry")) == 2
    for ps, method, meta in [
        ([0.01], "bh", {"a": 1}), ([0.01, 0.03], "bh", {"a": 1}),
        ([0.01, 0.02], "by", {"a": 1}), ([0.01, 0.02], "bh", {"a": 2}),
    ]:
        assert local.record_family("retry", ps, method=method, meta=meta) is None
    assert len(local.get_family("retry")) == 2


def test_record_trial_can_complete_family_and_retry_by_id(local):
    first = dict(family_id="sequence", p_value=0.01, q_value=0.02,
                 total_trials=2, trial_id="first", meta={"source": "test"})
    assert local.record_trial(**first) == "first"
    assert not local.has_disclosed_family("sequence")
    assert local.record_trial(**first) == "first"
    assert len(local.get_family("sequence")) == 1
    assert local.record_trial(**{**first, "p_value": 0.02}) is None
    assert local.record_trial(**{**first, "trial_id": "second", "p_value": 0.02}) == "second"
    assert local.has_disclosed_family("sequence")
    assert local.best_family_q_value("sequence") == 0.02
    assert local.record_trial(**{**first, "trial_id": "overflow"}) is None
    assert len(local.get_family("sequence")) == 2


def test_rollback_failure_preserves_original_fatal(local):
    fatal = duckdb.FatalException("injected fatal")
    class Broken:
        def execute(self, sql, *args):
            if sql == "BEGIN TRANSACTION":
                return self
            if sql == "ROLLBACK":
                raise RuntimeError("rollback also failed")
            raise fatal
    _, rows = registry._make_rows("fatal", [0.01], "bh")
    with pytest.raises(duckdb.FatalException) as caught:
        registry._insert_rows(Broken(), rows)
    assert caught.value is fatal


def test_retry_after_committed_response_is_lost(service, monkeypatch):
    import httpx
    _, client = service
    monkeypatch.setenv("NEXUS_DATA_URL", "http://testserver")
    lost = False
    class Transport:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, url, **kwargs):
            nonlocal lost
            response = client.post(url, **kwargs)
            if not lost:
                assert response.status_code == 200
                lost = True
                raise httpx.ReadTimeout("response lost after commit")
            return response
    monkeypatch.setattr(httpx, "Client", Transport)
    assert registry.record_family("lost-ack", [0.01, 0.02], meta={"a": 1}) is None
    assert registry.record_family("lost-ack", [0.01, 0.02], meta={"a": 1}) == [0.02, 0.02]
    assert len(registry.get_family("lost-ack")) == 2


def test_fatal_reaches_datastore_invalidation(service, monkeypatch):
    store, client = service
    connection = store._conn
    def fatal_insert(*args, **kwargs):
        raise duckdb.FatalException("injected fatal")
    monkeypatch.setattr(registry, "_insert_rows", fatal_insert)
    try:
        response = client.post("/internal/trials/family",
                               headers={"X-Nexus-Internal-Secret": "unit-test-only-credential"},
                               json={"family_id": "fatal", "p_values": [0.01]})
        assert response.status_code == 503
        assert store._invalidated is True
        assert store._conn is None
    finally:
        # DataStore closed it already; restore only for fixture cleanup.
        store._conn = connection
