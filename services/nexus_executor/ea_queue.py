"""EA bridge queue — mirror executor orders to the owner's MT5 terminals.

Item 4 of the agreed plan: when the executor successfully places, closes or
modifies an order, the same instruction is ALSO written to the ``ea_commands``
queue for every user owning an active EA token. The MQL5 Expert Advisor
(NexusBridgeEA) claims those commands via ``POST /api/ea/poll`` and reports
execution results back on the next cycle; ``command_id`` is the idempotency
key on both sides.

Strictly best-effort: every failure here is logged and never affects the
broker execution path itself. Disable entirely with NEXUS_EA_QUEUE_DISABLED=1.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

import httpx
import structlog

log = structlog.get_logger(__name__)
UTC = timezone.utc


def _data_url() -> str:
    return os.getenv("NEXUS_DATA_URL", "http://127.0.0.1:9001").rstrip("/")


def _secret() -> str:
    return os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()


def _enabled() -> bool:
    return os.getenv("NEXUS_EA_QUEUE_DISABLED", "").strip().lower() not in {"1", "true", "yes"}


async def _query(operation: str, params: dict) -> list[dict]:
    secret = _secret()
    if not secret:
        return []
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{_data_url()}/api/data/query",
                headers={"X-Nexus-Internal-Secret": secret},
                json={"operation": operation, "params": params},
            )
        if resp.status_code != 200:
            return []
        rows = resp.json().get("rows")
        return rows if isinstance(rows, list) else []
    except Exception as exc:
        log.warning("ea_queue.query_failed", operation=operation, error=str(exc))
        return []


async def _record(table: str, record: dict) -> bool:
    secret = _secret()
    if not secret:
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{_data_url()}/api/data/fundamental/record",
                headers={"X-Nexus-Internal-Secret": secret},
                json={"table": table, "record": record},
            )
        return resp.status_code < 300
    except Exception as exc:
        log.warning("ea_queue.record_failed", table=table, error=str(exc))
        return False


async def _enqueue(symbol: str, action: str, payload: dict) -> None:
    """Write one pending command per active-token user. Never raises."""
    if not _enabled():
        return
    try:
        rows = await _query("api_tokens_active_users", {})
        users = sorted({str(r["user_id"]) for r in rows if r.get("user_id")})
        if not users:
            return
        now = datetime.now(UTC)
        for user_id in users:
            command_id = uuid.uuid4().hex
            ok = await _record("ea_commands", {
                "command_id": command_id,
                "user_id": user_id,
                "symbol": symbol.upper(),
                "action": action,
                "payload_json": json.dumps(payload, ensure_ascii=False),
                "status": "pending",
                "created_at": now,
                "updated_at": now,
            })
            (log.info if ok else log.warning)(
                "ea_queue.enqueued" if ok else "ea_queue.enqueue_failed",
                action=action, symbol=symbol, user_id=user_id, command_id=command_id,
            )
    except Exception as exc:
        log.warning("ea_queue.enqueue_error", action=action, symbol=symbol, error=str(exc))


async def mirror_open(
    symbol: str,
    side: str,
    order_type: str,
    size: float,
    price: float,
    sl: float,
    tp: float,
    slippage: int,
    comment: str,
) -> None:
    await _enqueue(symbol, "OPEN", {
        "side": str(side).upper(),
        "order_type": str(order_type).upper(),
        "size": float(size),
        "price": float(price or 0),
        "sl": float(sl or 0),
        "tp": float(tp or 0),
        "slippage": int(slippage or 0),
        "comment": str(comment or ""),
    })


async def mirror_close(symbol: str, side: str, volume: float, comment: str) -> None:
    await _enqueue(symbol, "CLOSE", {
        "side": str(side or "").upper(),
        "volume": float(volume or 0),  # 0 => close all matching positions
        "comment": str(comment or ""),
    })


async def mirror_modify(
    symbol: str,
    sl: float,
    tp: float,
    comment: str,
    position_id: str = "",
) -> None:
    await _enqueue(symbol, "MODIFY", {
        "sl": float(sl or 0),
        "tp": float(tp or 0),
        "comment": str(comment or ""),
        "position_id": str(position_id or ""),
    })
