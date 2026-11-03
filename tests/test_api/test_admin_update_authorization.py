from __future__ import annotations

import pytest
from fastapi import HTTPException

from services.nexus_api.routers import admin


@pytest.mark.asyncio
async def test_denied_role_change_does_not_persist_other_user_fields(monkeypatch):
    writes: list[tuple[str, dict]] = []

    class FakeDataService:
        async def query(self, operation: str, params=None):
            assert operation == "user_by_id"
            return [{"user_id": "target", "full_name": "Old name", "email": None}]

    async def require(db, actor: str, permission: str) -> None:
        if permission == "users.edit":
            return
        raise HTTPException(403, f"permission required: {permission}")

    async def post_data(table: str, record: dict) -> None:
        writes.append((table, record))

    async def audit(*args, **kwargs) -> None:
        pass

    monkeypatch.setattr(admin, "_require", require)
    monkeypatch.setattr(admin, "_post_data", post_data)
    monkeypatch.setattr(admin, "_audit", audit)

    with pytest.raises(HTTPException) as exc_info:
        await admin.update_user(
            target_id="target",
            payload=admin.UserUpdate(full_name="New name", role_id="admin"),
            actor="limited-admin",
            db=FakeDataService(),
        )

    assert exc_info.value.status_code == 403
    assert writes == []


@pytest.mark.asyncio
async def test_unknown_role_assignment_is_rejected_before_user_or_role_writes(monkeypatch):
    writes: list[tuple[str, dict]] = []

    class FakeDataService:
        async def query(self, operation: str, params=None):
            if operation == "user_by_id":
                return [{"user_id": "target", "full_name": "Old name", "email": None}]
            if operation == "role_exists":
                return []
            raise AssertionError(f"unexpected query: {operation}")

    async def require(_db, _actor: str, _permission: str) -> None:
        return None

    async def post_data(table: str, record: dict) -> None:
        writes.append((table, record))

    monkeypatch.setattr(admin, "_require", require)
    monkeypatch.setattr(admin, "_post_data", post_data)

    with pytest.raises(HTTPException) as exc_info:
        await admin.update_user(
            target_id="target",
            payload=admin.UserUpdate(full_name="New name", role_id="missing-role"),
            actor="operator",
            db=FakeDataService(),
        )

    assert exc_info.value.status_code == 422
    assert writes == []


@pytest.mark.asyncio
async def test_disabling_user_requires_users_disable_before_any_side_effect(monkeypatch):
    writes: list[tuple[str, dict]] = []
    avatar_saves: list[str] = []

    class FakeDataService:
        async def query(self, operation: str, params=None):
            assert operation == "user_by_id"
            return [{"user_id": "target", "active": True}]

    async def require(_db, _actor: str, permission: str) -> None:
        if permission == "users.edit":
            return
        raise HTTPException(403, f"permission required: {permission}")

    async def post_data(table: str, record: dict) -> None:
        writes.append((table, record))

    def save_avatar(user_id: str, _data_url: str | None) -> str:
        avatar_saves.append(user_id)
        return "avatar-path"

    monkeypatch.setattr(admin, "_require", require)
    monkeypatch.setattr(admin, "_post_data", post_data)
    monkeypatch.setattr(admin, "_save_avatar", save_avatar)

    with pytest.raises(HTTPException) as exc_info:
        await admin.update_user(
            target_id="target",
            payload=admin.UserUpdate(active=False, avatar_data_url="data:image/png;base64,AA=="),
            actor="limited-admin",
            db=FakeDataService(),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "permission required: users.disable"
    assert writes == []
    assert avatar_saves == []


@pytest.mark.asyncio
async def test_self_disable_rejection_happens_before_avatar_write(monkeypatch):
    writes: list[tuple[str, dict]] = []
    avatar_saves: list[str] = []

    class FakeDataService:
        async def query(self, operation: str, params=None):
            assert operation == "user_by_id"
            return [{"user_id": "operator", "active": True}]

    async def require(_db, _actor: str, _permission: str) -> None:
        return None

    async def post_data(table: str, record: dict) -> None:
        writes.append((table, record))

    def save_avatar(user_id: str, _data_url: str | None) -> str:
        avatar_saves.append(user_id)
        return "avatar-path"

    monkeypatch.setattr(admin, "_require", require)
    monkeypatch.setattr(admin, "_post_data", post_data)
    monkeypatch.setattr(admin, "_save_avatar", save_avatar)

    with pytest.raises(HTTPException) as exc_info:
        await admin.update_user(
            target_id="operator",
            payload=admin.UserUpdate(active=False, avatar_data_url="data:image/png;base64,AA=="),
            actor="operator",
            db=FakeDataService(),
        )

    assert exc_info.value.status_code == 409
    assert writes == []
    assert avatar_saves == []


@pytest.mark.asyncio
async def test_unknown_role_permissions_are_rejected_before_permission_writes(monkeypatch):
    writes: list[tuple[str, dict]] = []

    class FakeDataService:
        async def query(self, operation: str, params=None):
            if operation == "role_exists":
                return []
            raise AssertionError(f"unexpected query: {operation}")

    async def require(_db, _actor: str, _permission: str) -> None:
        return None

    async def post_data(table: str, record: dict) -> None:
        writes.append((table, record))

    async def audit(*args, **kwargs) -> None:
        pass

    monkeypatch.setattr(admin, "_require", require)
    monkeypatch.setattr(admin, "_post_data", post_data)
    monkeypatch.setattr(admin, "_audit", audit)

    with pytest.raises(HTTPException) as exc_info:
        await admin.update_role_permissions(
            role_id="missing-role",
            payload=admin.RolePermissionsIn(permissions=["users.view"]),
            actor="operator",
            db=FakeDataService(),
        )

    assert exc_info.value.status_code == 404
    assert writes == []
