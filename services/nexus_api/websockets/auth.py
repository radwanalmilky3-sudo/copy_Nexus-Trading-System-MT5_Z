"""Authentication handshake shared by native dashboard WebSocket routes."""
from __future__ import annotations

import asyncio
import json

from fastapi import HTTPException, WebSocket
from starlette.websockets import WebSocketDisconnect

from ..deps import data_service, redis as default_redis
from ..middleware.auth import decode_token, denylist_is_denied, verify_token

AUTH_TIMEOUT_SECONDS = 5


async def authenticate_websocket(ws: WebSocket, required_permission: str) -> bool:
    """Require a valid JWT and current DB permission before stream registration."""
    await ws.accept()
    try:
        raw = await asyncio.wait_for(
            ws.receive_text(), timeout=AUTH_TIMEOUT_SECONDS,
        )
        message = json.loads(raw)
        if not isinstance(message, dict) or message.get("type") != "auth":
            raise ValueError("authentication frame required")
        token = message.get("token")
        if not isinstance(token, str) or not token:
            raise ValueError("token required")
        user_id = verify_token(token)
        # D15: a logged-out (denylisted) token must not open NEW websocket
        # sessions. Fail-open on Redis trouble — same availability contract
        # as the HTTP dependency.
        try:
            claims = decode_token(token)
        except HTTPException:
            claims = {}
        if await denylist_is_denied(default_redis, str(claims.get("jti") or "")):
            await ws.close(code=4401, reason="token revoked")
            return False
        permissions = await data_service.query(
            "user_permissions", {"user_id": user_id},
        )
        allowed = {str(row.get("permission_code", "")) for row in permissions}
        if "*" not in allowed and required_permission not in allowed:
            await ws.close(code=4403, reason="permission required")
            return False
        return True
    except WebSocketDisconnect:
        return False
    except (
        HTTPException,
        json.JSONDecodeError,
        ValueError,
        TypeError,
        asyncio.TimeoutError,
    ):
        try:
            await ws.close(code=4401, reason="authentication required")
        except RuntimeError:
            pass
        return False
    except Exception:
        try:
            await ws.close(code=1011, reason="authorization unavailable")
        except RuntimeError:
            pass
        return False


async def send_auth_success(ws: WebSocket) -> None:
    """Confirm authentication only after the endpoint registers the client."""
    await ws.send_json({"type": "auth", "ok": True})
