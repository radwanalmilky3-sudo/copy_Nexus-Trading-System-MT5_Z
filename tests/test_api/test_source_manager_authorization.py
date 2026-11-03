from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from services.nexus_api.middleware.auth import create_token
from services.nexus_api.routers import fundamental


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "payload", "required_permission"),
    [
        ("GET", "/api/fundamental/sources/manage", None, "source_manager.view"),
        ("POST", "/api/fundamental/sources/manage", {"source_id": "new"}, "source_manager.edit"),
        ("PUT", "/api/fundamental/sources/manage/example", {"enabled": False}, "source_manager.edit"),
        ("DELETE", "/api/fundamental/sources/manage/example", None, "source_manager.edit"),
        ("POST", "/api/fundamental/sources/manage/example/test", None, "source_manager.test"),
        ("POST", "/api/fundamental/sources/manage/example/secret", {"secret": "do-not-store"}, "source_manager.secrets"),
    ],
)
async def test_source_management_denies_missing_permission_before_store_access(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    required_permission: str,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    checked: list[str] = []
    store_calls: list[bool] = []

    async def deny(db: Any, actor: str, permission: str) -> None:
        checked.append(permission)
        raise HTTPException(403, "permission denied")

    def forbidden_store_access():
        store_calls.append(True)
        raise AssertionError("authorization must run before source-store access")

    monkeypatch.setattr(fundamental, "_require", deny, raising=False)
    monkeypatch.setattr(fundamental, "_source_manager_store", forbidden_store_access)
    response = await api_client.request(
        method,
        path,
        json=payload,
        headers={"Authorization": f"Bearer {create_token('audit-user')}"},
    )

    assert response.status_code == 403
    assert checked == [required_permission]
    assert store_calls == []


@pytest.mark.asyncio
async def test_source_update_with_secret_requires_secrets_permission_too(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    checked: list[str] = []
    store_calls: list[bool] = []

    async def allow_edit_but_deny_secret(db: Any, actor: str, permission: str) -> None:
        checked.append(permission)
        if permission == "source_manager.secrets":
            raise HTTPException(403, "permission denied")

    def forbidden_store_access():
        store_calls.append(True)
        raise AssertionError("secret authorization must run before source-store access")

    monkeypatch.setattr(fundamental, "_require", allow_edit_but_deny_secret, raising=False)
    monkeypatch.setattr(fundamental, "_source_manager_store", forbidden_store_access)
    response = await api_client.put(
        "/api/fundamental/sources/manage/example",
        json={"secret": "do-not-store"},
        headers={"Authorization": f"Bearer {create_token('audit-user')}"},
    )

    assert response.status_code == 403
    assert checked == ["source_manager.edit", "source_manager.secrets"]
    assert store_calls == []


@pytest.mark.asyncio
async def test_source_management_rejects_missing_jwt_before_store_access(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_calls: list[bool] = []

    def forbidden_store_access():
        store_calls.append(True)
        raise AssertionError("authentication must run before source-store access")

    monkeypatch.setattr(fundamental, "_source_manager_store", forbidden_store_access)
    response = await api_client.get("/api/fundamental/sources/manage")

    assert response.status_code == 401
    assert store_calls == []
