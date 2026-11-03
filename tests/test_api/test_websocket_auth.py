"""WebSocket streams must authenticate before joining a broadcast channel."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from services.nexus_api.websockets import auth as websocket_auth
from services.nexus_api.websockets import agents, news, orders, positions, risk, ticks
from services.nexus_api.websockets.manager import ConnectionManager


WS_ROUTES = [
    ("/ws/agents", agents.router, agents.CHANNEL, "trading.view"),
    ("/ws/news", news.router, news.CHANNEL, "fundamental.view"),
    ("/ws/orders", orders.router, orders.CHANNEL, "trading.view"),
    ("/ws/positions", positions.router, positions.CHANNEL, "trading.view"),
    ("/ws/risk", risk.router, risk.CHANNEL, "risk.view"),
    ("/ws/ticks", ticks.router, ticks.CHANNEL, "trading.view"),
    ("/ws/stream", ticks.router, ticks.CHANNEL, "trading.view"),
]


@pytest.fixture
def websocket_app(monkeypatch):
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-only-websocket-secret-32-bytes-minimum")
    app = FastAPI()
    manager = ConnectionManager()
    app.state.ws_manager = manager
    for _path, router, _channel, _permission in WS_ROUTES:
        app.include_router(router)
    return app, manager


@pytest.mark.parametrize("path,router,channel,_permission", WS_ROUTES)
def test_invalid_token_is_rejected_before_broadcast_registration(
    websocket_app, path, router, channel, _permission
):
    app, manager = websocket_app
    with TestClient(app) as client:
        with client.websocket_connect(path) as websocket:
            websocket.send_json({"type": "auth", "token": "invalid-token"})
            assert manager.active_count(channel) == 0


@pytest.mark.parametrize("path,router,channel,permission", WS_ROUTES)
def test_valid_token_without_channel_permission_is_rejected(
    websocket_app, monkeypatch, path, router, channel, permission
):
    from services.nexus_api.middleware.auth import create_token

    app, manager = websocket_app

    async def no_permissions(*_args, **_kwargs):
        return []

    monkeypatch.setattr(
        websocket_auth,
        "data_service",
        SimpleNamespace(query=no_permissions),
        raising=False,
    )
    token = create_token("test-user")
    with TestClient(app) as client:
        with client.websocket_connect(path) as websocket:
            websocket.send_json({"type": "auth", "token": token})
            assert manager.active_count(channel) == 0


@pytest.mark.parametrize("path,router,channel,permission", WS_ROUTES)
def test_user_with_channel_permission_can_join_and_disconnect_cleanly(
    websocket_app, monkeypatch, path, router, channel, permission
):
    from services.nexus_api.middleware.auth import create_token

    app, manager = websocket_app

    async def channel_permissions(*_args, **_kwargs):
        return [{"permission_code": permission}]

    monkeypatch.setattr(
        websocket_auth,
        "data_service",
        SimpleNamespace(query=channel_permissions),
        raising=False,
    )
    token = create_token("test-user")
    with TestClient(app) as client:
        with client.websocket_connect(path) as websocket:
            websocket.send_json({"type": "auth", "token": token})
            assert websocket.receive_json() == {"type": "auth", "ok": True}
            assert manager.active_count(channel) == 1
            websocket.send_text("keepalive")

    assert manager.active_count(channel) == 0


def test_authentication_handshake_times_out_without_registering(websocket_app, monkeypatch):
    app, manager = websocket_app
    monkeypatch.setattr(websocket_auth, "AUTH_TIMEOUT_SECONDS", 0.01)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/orders") as websocket:
            with pytest.raises(WebSocketDisconnect) as disconnected:
                websocket.receive_text()
            assert disconnected.value.code == 4401
            assert manager.active_count(orders.CHANNEL) == 0


def test_permission_store_failure_fails_closed(websocket_app, monkeypatch):
    from services.nexus_api.middleware.auth import create_token

    app, manager = websocket_app

    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("permission store unavailable")

    monkeypatch.setattr(
        websocket_auth,
        "data_service",
        SimpleNamespace(query=unavailable),
        raising=False,
    )
    token = create_token("test-user")
    with TestClient(app) as client:
        with client.websocket_connect("/ws/orders") as websocket:
            websocket.send_json({"type": "auth", "token": token})
            with pytest.raises(WebSocketDisconnect) as disconnected:
                websocket.receive_text()
            assert disconnected.value.code == 1011
            assert manager.active_count(orders.CHANNEL) == 0
