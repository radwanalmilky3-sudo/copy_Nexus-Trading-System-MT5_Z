"""
WebSocket endpoint:  ws://host/ws/broadcast

Generic relay for service pub/sub broadcasts. Internal services publish JSON
messages to the Redis pub/sub channel ``nexus:ws:broadcast`` (e.g.
``nexus_features`` pushes ``{"type": "institutional_features", ...}`` after
each computed cycle).  The gateway subscribes once and fans every message out
to all authenticated dashboard clients on this channel.

Auth model is identical to the other native dashboard sockets: the client must
send ``{"type": "auth", "token": <JWT>}`` as its first frame within 5 seconds,
and the token must carry the required permission.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from shared.constants import RedisStream, WSChannel  # noqa: F401 (RedisStream kept for symmetry)
from shared.redis_client import RedisClient

from .manager import ConnectionManager
from .auth import authenticate_websocket, send_auth_success

logger = structlog.get_logger(__name__)

router = APIRouter()

CHANNEL = WSChannel.BROADCAST
_SERVICE_PUBSUB = "nexus:ws:broadcast"


@router.websocket("/ws/broadcast")
async def broadcast_ws(ws: WebSocket) -> None:
    if not await authenticate_websocket(ws, "trading.view"):
        return
    manager: ConnectionManager = ws.app.state.ws_manager  # type: ignore[union-attr]
    await manager.connect(ws, CHANNEL, accepted=True)
    await send_auth_success(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        await logger.aexception("ws.broadcast.error")
    finally:
        await manager.disconnect(ws, CHANNEL)


async def broadcast_relay(redis: RedisClient, manager: ConnectionManager) -> None:
    """Relay every service pub/sub message to the broadcast WS channel."""
    async for message in redis.subscribe_channel(_SERVICE_PUBSUB):
        try:
            await manager.broadcast(CHANNEL, message)
        except Exception:  # noqa: BLE001 — one bad payload must not kill the relay
            await logger.aexception("ws.broadcast.relay_error")
