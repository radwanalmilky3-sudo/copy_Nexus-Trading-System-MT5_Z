"""Internal registry operations on the data service's sole DuckDB connection."""
from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from . import trial_registry as registry


class Family(BaseModel):
    family_id: str = Field(min_length=1)
    p_values: list[float] = Field(min_length=1)
    method: str = "bh"
    meta: dict[str, Any] | None = None


class Trial(BaseModel):
    family_id: str = Field(min_length=1)
    p_value: float
    trial_id: str | None = None
    q_value: float | None = None
    method: str = "bh"
    total_trials: int | None = None
    min_resamples: int | None = None
    meta: dict[str, Any] | None = None


class Lookup(BaseModel):
    family_id: str = Field(min_length=1)


def _authorize(x_nexus_internal_secret: str | None = Header(default=None)) -> None:
    secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
    if not secret:
        raise HTTPException(503, "internal credential unavailable")
    if not x_nexus_internal_secret or not hmac.compare_digest(
        secret.encode(), x_nexus_internal_secret.encode()
    ):
        raise HTTPException(403, "invalid internal service credential")


def create_router(store: Any) -> APIRouter:
    router = APIRouter(prefix="/internal/trials", dependencies=[Depends(_authorize)])

    async def execute(operation: Any) -> dict[str, Any]:
        try:
            result = await store._execute_locked(lambda: operation(store._conn))
            return {"ok": True, "result": result}
        except ValueError:
            raise HTTPException(409, "invalid or conflicting disclosure") from None
        except Exception:
            raise HTTPException(503, "trial registry unavailable") from None

    @router.post("/family")
    async def family(payload: Family) -> dict[str, Any]:
        def operation(conn: Any) -> list[float]:
            qs, rows = registry._make_rows(**payload.model_dump())
            registry._insert_rows(conn, rows)
            return qs
        return await execute(operation)

    @router.post("/record")
    async def record(payload: Trial) -> dict[str, Any]:
        def operation(conn: Any) -> str:
            row = registry._single_row(**payload.model_dump())
            registry._insert_rows(conn, [row], single=True)
            return row[0]
        return await execute(operation)

    @router.post("/get")
    async def get(payload: Lookup) -> dict[str, Any]:
        return await execute(lambda conn: registry._read_rows(conn, payload.family_id))

    return router
