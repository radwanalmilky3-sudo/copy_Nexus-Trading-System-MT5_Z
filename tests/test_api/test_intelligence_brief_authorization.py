from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.nexus_api.middleware.auth import create_token
from services.nexus_api.routers import intelligence


@pytest.mark.asyncio
async def test_brief_generation_proxy_attaches_internal_credential(monkeypatch):
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-agents-secret")
    post = AsyncMock(return_value=SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"status": "generated"},
    ))

    @asynccontextmanager
    async def fake_client(*args, **kwargs):
        yield SimpleNamespace(post=post)

    async def allow_permission(*args, **kwargs):
        return None

    monkeypatch.setattr(intelligence, "new_client", fake_client)
    monkeypatch.setattr(intelligence, "_require", allow_permission)

    await intelligence.trigger_brief(actor="test-user", db=object(), symbol="XAUUSD")

    assert post.await_args.kwargs["headers"] == {
        "X-Nexus-Internal-Secret": "test-agents-secret"
    }


def install_fake_agents_client(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"status": "generated"},
    )
    post = AsyncMock(return_value=response)

    @asynccontextmanager
    async def fake_client(*args, **kwargs):
        yield SimpleNamespace(post=post)

    monkeypatch.setattr(intelligence, "new_client", fake_client)
    return post


@pytest.mark.asyncio
async def test_brief_trigger_rejects_missing_jwt_before_agents_proxy(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    post = install_fake_agents_client(monkeypatch)

    response = await api_client.post("/api/intelligence/brief/trigger?symbol=XAUUSD")

    assert response.status_code == 401
    post.assert_not_awaited()


@pytest.mark.asyncio
async def test_brief_trigger_requires_fundamental_configure_before_agents_proxy(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    post = install_fake_agents_client(monkeypatch)

    response = await api_client.post(
        "/api/intelligence/brief/trigger?symbol=XAUUSD",
        headers={"Authorization": f"Bearer {create_token('unprivileged-user')}"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "permission required: fundamental.configure"}
    post.assert_not_awaited()
