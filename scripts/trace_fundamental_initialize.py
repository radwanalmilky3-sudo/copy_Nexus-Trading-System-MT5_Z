"""Run the complete runtime.initialize against a disposable backup DB+WAL.

No real Redis, sockets, credentials, source-manager files or service processes.
Records HTTP400 failures and continues; stops at the first operational failure.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import traceback
from unittest.mock import patch
from fastapi import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FirstFailure(BaseException):
    pass


class FakeRedis:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, **kwargs):
        self.values[key] = value


def emit(event, **fields):
    print(json.dumps({"event": event, **fields}, ensure_ascii=False, default=str), flush=True)


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


async def reproduce(db):
    import httpx
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from services.nexus_data.duckdb_store import DataStore
    from services.nexus_data.fundamental_store import FundamentalStore
    from services.nexus_news.fundamental import runtime as module

    state = {"phase": "schema", "table": None, "sql": None}
    failures = []
    store = DataStore(str(db))
    fundamental = FundamentalStore(store)
    original_run = store._run

    async def traced_run(sql, params=()):
        state["sql"] = sql
        emit("SQL", **state)
        try:
            return await original_run(sql, params)
        except Exception as exc:
            emit("SQL_FAILURE", **state, exception=type(exc).__name__, message=str(exc))
            raise

    store._run = traced_run
    app = FastAPI()

    async def persist(request, source=False):
        payload = await request.json()
        state["table"] = "fund_sources" if source else payload["table"]
        state["sql"] = None
        emit("WRITE", phase=state["phase"], table=state["table"])
        try:
            if source:
                await fundamental.upsert_source(payload["source"])
            else:
                await fundamental.insert_record(payload["table"], payload["record"])
        except Exception as exc:
            chain = []
            root = exc
            while root is not None:
                chain.append({"type": type(root).__name__, "message": str(root)})
                root = root.__cause__
            failure = dict(state, chain=chain, store_invalidated=store._invalidated)
            failures.append(failure)
            emit("FIRST_FAILURE" if len(failures) == 1 else "NEXT_FAILURE", **failure)
            traceback.print_exception(exc)
            if isinstance(exc, ValueError):
                return JSONResponse({"detail": str(exc)}, status_code=400)
            raise FirstFailure("first persistence failure; stopped before HTTP swallowing") from exc
        return {"ok": True}

    @app.post("/api/data/fundamental/source")
    async def source(request: Request):
        return await persist(request, source=True)

    @app.post("/api/data/fundamental/record")
    async def record(request: Request):
        return await persist(request)

    # All HTTP clients, including adapter constructors, get only this ASGI app.
    original_client = httpx.AsyncClient
    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.ASGITransport(app=app)
        kwargs["trust_env"] = False
        return original_client(*args, **kwargs)

    class EmptySources:
        def list_sources(self):
            return []

    def no_network(*args, **kwargs):
        raise AssertionError("external socket access prohibited")

    runtime = None
    with patch.object(httpx, "AsyncClient", client_factory), \
         patch.object(module, "source_manager_store", lambda: EmptySources()), \
         patch.object(module, "managed_source_config", lambda sid: None), \
         patch.object(module, "managed_enabled", lambda sid, default=True: default), \
         patch.object(socket.socket, "connect", no_network), \
         patch.object(socket.socket, "connect_ex", no_network):
        try:
            await store.init_tables()
            await fundamental.init_schema()
            runtime = module.FundamentalRuntime(FakeRedis())
            original_seed = runtime._seed_v5_governance
            original_recompute = runtime.recompute

            async def seed():
                state["phase"] = "governance_seed"
                await original_seed()
                emit("SEED_PASSED")

            async def recompute(**kwargs):
                state["phase"] = "recompute:" + kwargs["reason"]
                return await original_recompute(**kwargs)

            runtime._seed_v5_governance = seed
            runtime.recompute = recompute
            state["phase"] = "official_and_custom_sources"
            await runtime.initialize()
            emit("INITIALIZE_COMPLETED", redis_keys=len(runtime.redis.values), failures=len(failures))
        finally:
            if runtime is not None:
                await runtime.close()
            await store.aclose()


def main():
    emit("REPRO_STARTED")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", type=Path, required=True)
    args = parser.parse_args()
    backup = args.backup.resolve(strict=True)
    expected = Path(__file__).resolve().parents[1] / "data/backups/before_restore_20261019_012430"
    if backup != expected.resolve():
        parser.error("only the explicitly authorized before_restore backup is accepted")
    files = [backup / "nexus.duckdb", backup / "nexus.duckdb.wal"]
    emit("HASHING_BACKUP")
    before = {str(p): digest(p) for p in files}
    workspace = Path(tempfile.mkdtemp(prefix="nexus-initialize-trace-"))
    for path in files:
        emit("COPYING", name=path.name)
        shutil.copy2(path, workspace / path.name)
    emit("DISPOSABLE_COPY", directory=workspace, backup_sha256=before)
    # Clear inherited credentials/configuration before loading runtime modules.
    environment = {
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", "C:/Windows"),
        "TEMP": str(workspace), "TMP": str(workspace),
        "NEXUS_INTERNAL_API_SECRET": "isolated-trace-only",
        "NEXUS_DATA_URL": "http://isolated.test",
        "DUCKDB_PATH": str(workspace / "nexus.duckdb"),
    }
    code = 0
    try:
        with patch.dict(os.environ, environment, clear=True):
            asyncio.run(reproduce(workspace / "nexus.duckdb"))
    except FirstFailure:
        code = 1
    except Exception:
        traceback.print_exc()
        code = 2
    finally:
        after = {str(p): digest(p) for p in files}
        emit("BACKUP_UNCHANGED", unchanged=before == after, directory=workspace)
        if before != after:
            code = 3
    return code


if __name__ == "__main__":
    raise SystemExit(main())
