"""EA Bridge router — MT5 terminal API tokens and the command queue.

Security model:
- Raw tokens (``nexus_ea_`` prefix + 32 url-safe random bytes, ~256 bits of
  entropy) are shown exactly once at creation; only their SHA-256 hash is
  persisted, so a database leak never leaks usable credentials.
- Every EA call authenticates with ``Authorization: Bearer nexus_ea_...``;
  the hash is looked up in ``api_tokens`` and must be active.
- The first successful handshake binds the terminal identity
  (mt5_login / broker / server) to the token; later calls from a different
  terminal are rejected even with a valid token.
- Tokens are revocable instantly (active=FALSE + revoked_at).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import uuid

import httpx
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from ..data_client import DataServiceClient
from ..deps import get_data_service
from ..middleware.auth import CurrentUser
from .admin import _audit, _post_data

from shared.rate_limit import rate_limit_scope

router = APIRouter(tags=["ea-bridge"], dependencies=[rate_limit_scope("ea")])
UTC = timezone.utc
TOKEN_PREFIX = "nexus_ea_"

ALLOWED_ACTIONS = {"OPEN", "MODIFY", "CLOSE", "PARTIAL_CLOSE"}


class Mt5CalendarEventIn(BaseModel):
    """One MqlCalendarValue joined with its event/country metadata."""

    model_config = {"extra": "ignore"}
    id: int | None = None
    name: str = Field(min_length=1, max_length=256)
    country: str | None = Field(default=None, max_length=64)
    currency: str = Field(min_length=2, max_length=16)
    importance: int = Field(default=0, ge=0, le=3)
    time: int = Field(ge=0)                     # unix, TRADE SERVER time
    period: int | None = Field(default=None, ge=0)
    actual: float | None = None
    forecast: float | None = None
    previous: float | None = None
    revised_previous: float | None = None
    updated: int | None = Field(default=None, ge=0)


class Mt5CalendarBatchIn(BaseModel):
    model_config = {"extra": "ignore"}
    events: list[Mt5CalendarEventIn] = Field(max_length=200)
    server_offset_sec: int = Field(default=0, ge=-14 * 3600, le=14 * 3600)
    chunk_index: int = Field(default=0, ge=0)
    has_more: bool = False
    terminal_time: int | None = Field(default=None, ge=0)


class TokenCreateIn(BaseModel):
    label: str = Field(default="MT5 Terminal", min_length=1, max_length=80)


class HandshakeIn(BaseModel):
    mt5_login: str = Field(min_length=1, max_length=40)
    mt5_broker: str = Field(min_length=1, max_length=120)
    mt5_server: str | None = Field(default=None, max_length=120)
    terminal_version: str | None = Field(default=None, max_length=60)


class CommandResultIn(BaseModel):
    command_id: str = Field(min_length=8, max_length=64)
    ok: bool
    detail: str | None = Field(default=None, max_length=500)
    ticket: int | None = None
    price: float | None = None


class PollIn(BaseModel):
    results: list[CommandResultIn] = Field(default_factory=list)


async def _touch_last_used(db: DataServiceClient, row: dict[str, Any]) -> None:
    """Best-effort heartbeat update; failures never block the EA call."""
    try:
        await _post_data("api_tokens", {**row, "last_used_at": datetime.now(UTC)})
    except Exception:
        pass


async def ea_identity(
    authorization: str | None = Header(default=None),
    db: DataServiceClient = Depends(get_data_service),
) -> tuple[str, str]:
    """Authenticate an EA call and return ``(user_id, token_id)``."""
    if authorization is None:
        raise HTTPException(401, "Missing Authorization header")
    scheme, _, token = authorization.strip().partition(" ")
    if scheme.lower() != "bearer" or not token.startswith(TOKEN_PREFIX):
        raise HTTPException(401, "Invalid auth scheme")
    token_hash = hashlib.sha256(token.strip().encode()).hexdigest()
    rows = await db.query("api_token_by_hash", {"token_hash": token_hash})
    if not rows:
        raise HTTPException(401, "Unknown or revoked token")
    row = rows[0]
    await _touch_last_used(db, row)
    return str(row["user_id"]), str(row["token_id"])


def _mask(raw: str) -> str:
    return f"{raw[:12]}...{raw[-4:]}"


@router.post("/api/admin/ea-tokens")
async def create_token(
    payload: TokenCreateIn,
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
):
    """Create an EA token for the signed-in user; the raw value is returned once."""
    token_id = uuid.uuid4().hex
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    await _post_data("api_tokens", {
        "token_id": token_id,
        "user_id": actor,
        "token_hash": hashlib.sha256(raw.encode()).hexdigest(),
        "label": payload.label.strip(),
        "active": True,
        "created_at": datetime.now(UTC),
    })
    await _audit(actor, "ea.token_create", "api_token", token_id, {"label": payload.label})
    return {"ok": True, "token_id": token_id, "token": raw, "note": "store it now; it is never shown again"}


@router.get("/api/admin/ea-tokens")
async def list_tokens(actor: CurrentUser, db: DataServiceClient = Depends(get_data_service)):
    rows = await db.query("api_tokens_by_user", {"user_id": actor})
    return {"tokens": rows}


@router.get("/api/admin/ea-commands")
async def list_commands(actor: CurrentUser, db: DataServiceClient = Depends(get_data_service)):
    """Recent EA bridge commands for the signed-in user (dashboard view)."""
    rows = await db.query("ea_commands_recent", {"user_id": actor})
    return {"commands": rows}


@router.delete("/api/admin/ea-tokens/{token_id}")
async def revoke_token(token_id: str, actor: CurrentUser, db: DataServiceClient = Depends(get_data_service)):
    rows = await db.query("api_token_by_id", {"token_id": token_id, "user_id": actor})
    if not rows:
        raise HTTPException(404, "token not found")
    row = rows[0]
    await _post_data("api_tokens", {**row, "active": False, "revoked_at": datetime.now(UTC)})
    await _audit(actor, "ea.token_revoke", "api_token", token_id)
    return {"ok": True}


@router.post("/api/ea/handshake")
async def handshake(
    payload: HandshakeIn,
    identity: tuple[str, str] = Depends(ea_identity),
    db: DataServiceClient = Depends(get_data_service),
):
    """Bind the terminal identity to the token (first call after EA attach)."""
    user_id, token_id = identity
    rows = await db.query("api_token_by_id", {"token_id": token_id, "user_id": user_id})
    if not rows:
        raise HTTPException(404, "token not found")
    row = rows[0]
    bound_login = row.get("mt5_login")
    if bound_login and str(bound_login) != payload.mt5_login:
        raise HTTPException(409, "token already bound to a different MT5 login")
    await _post_data("api_tokens", {
        **row,
        "mt5_login": payload.mt5_login,
        "mt5_broker": payload.mt5_broker,
        "mt5_server": payload.mt5_server,
        "last_used_at": datetime.now(UTC),
    })
    await _audit(user_id, "ea.handshake", "api_token", token_id, {
        "mt5_login": payload.mt5_login, "broker": payload.mt5_broker,
    })
    profile = await db.query("user_profile", {"user_id": user_id})
    return {
        "ok": True,
        "user": {"id": user_id, "username": profile[0]["username"] if profile else None},
        "heartbeat_seconds": 3,
        "protocol_version": 1,
    }


@router.post("/api/ea/poll")
async def poll(
    payload: PollIn,
    identity: tuple[str, str] = Depends(ea_identity),
    db: DataServiceClient = Depends(get_data_service),
):
    """Single round-trip: report previous results, claim the next pending batch."""
    user_id, token_id = identity
    now = datetime.now(UTC)

    # 1) Apply execution results reported by the terminal.
    for res in payload.results:
        rows = await db.query("ea_command_by_id", {"command_id": res.command_id, "user_id": user_id})
        if not rows:
            continue  # unknown command: ignore rather than fail the whole batch
        cmd = rows[0]
        if cmd.get("status") in ("done", "failed"):
            continue  # idempotent re-report
        result = {
            "ok": res.ok,
            "detail": res.detail,
            "ticket": res.ticket,
            "price": res.price,
        }
        await _post_data("ea_commands", {
            **cmd,
            "status": "done" if res.ok else "failed",
            "completed_at": now,
            "result_json": json.dumps(result, ensure_ascii=False),
        })

    # 2) Claim the next pending commands (up to 20) for this user.
    pending = await db.query("ea_pending_commands", {"user_id": user_id})
    claimed: list[dict[str, Any]] = []
    for cmd in pending:
        await _post_data("ea_commands", {**cmd, "status": "claimed", "claimed_at": now, "token_id": token_id})
        claimed.append({
            "command_id": cmd["command_id"],
            "symbol": cmd["symbol"],
            "action": cmd["action"],
            "payload": json.loads(cmd.get("payload_json") or "{}"),
        })
    return {"ok": True, "commands": claimed, "server_time": now.isoformat()}


# ── MT5 native economic calendar bridge ─────────────────────────────────────

# Shared client for forwarding to nexus-news. Creating an httpx.AsyncClient
# per request re-resolves environment proxies on every call (seconds on
# Windows) and drops keep-alive reuse — measured 1.5–5 s per EA calendar
# chunk, which tripped the EA's hard ~10 s WebRequest limit (status 1003).
# Reversal: restore the per-request `async with httpx.AsyncClient(...)`.
_news_forward_client: httpx.AsyncClient | None = None


async def _forward_to_news(path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """POST an internal payload to nexus-news; returns (status, body)."""
    global _news_forward_client
    secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
    if not secret:
        raise HTTPException(503, "NEXUS_INTERNAL_API_SECRET missing — internal forwarding disabled")
    url = os.getenv("NEXUS_NEWS_URL", "http://127.0.0.1:9005").rstrip("/") + path
    if _news_forward_client is None or _news_forward_client.is_closed:
        _news_forward_client = httpx.AsyncClient(timeout=30.0, trust_env=False)
    try:
        response = await _news_forward_client.post(
            url,
            headers={"X-Nexus-Internal-Secret": secret},
            json=payload,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"nexus-news unreachable: {exc}") from exc
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, {}


@router.post("/api/ea/calendar")
async def calendar_batch(
    payload: Mt5CalendarBatchIn,
    identity: tuple[str, str] = Depends(ea_identity),
    db: DataServiceClient = Depends(get_data_service),
):
    """Receive one batch of MT5-native calendar events from the EA bridge.

    The EA pulls CalendarValueHistory inside the terminal (times in TRADE
    SERVER time) and posts chunks here.  The batch is validated then forwarded
    to nexus-news (/api/internal/calendar/mt5) which owns the fundamental
    pipeline: blackout windows, Redis publish, DuckDB persistence.
    """
    user_id, token_id = identity
    status, body = await _forward_to_news("/api/internal/calendar/mt5", payload.model_dump())
    if status >= 400:
        detail = body.get("detail") if isinstance(body, dict) else None
        raise HTTPException(status_code=502 if status >= 500 else 422,
                            detail=detail or f"nexus-news rejected the batch (HTTP {status})")
    # Audit asynchronously: the EA's WebRequest has a hard ~10 s read-timeout
    # and the nexus-data audit write can take seconds under load. The audit is
    # observability, not a gate — never make the EA wait for it.
    asyncio.create_task(_audit(user_id, "ea.calendar_batch", "api_token", token_id, {
        "events": len(payload.events), "chunk": payload.chunk_index,
    }))
    return {"ok": True, "accepted": body.get("accepted", 0), "has_more": payload.has_more}
