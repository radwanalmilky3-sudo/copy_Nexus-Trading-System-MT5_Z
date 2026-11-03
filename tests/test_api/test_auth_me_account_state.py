import pytest
from fastapi import HTTPException

from services.nexus_api.data_client import DataServiceUnavailable
from services.nexus_api.routers import admin


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [[], [{"user_id": "old-user", "active": False}]])
async def test_me_rejects_session_for_missing_or_disabled_account(rows):
    class Database:
        async def query(self, operation, params):
            assert operation == "user_profile"
            assert params == {"user_id": "old-user"}
            return rows

    with pytest.raises(HTTPException) as error:
        await admin.me(user_id="old-user", db=Database())
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_me_preserves_active_account_profile():
    class Database:
        async def query(self, operation, params):
            return {
                "user_profile": [{"user_id": "active-user", "username": "example", "active": True}],
                "user_role_ids": [{"role_id": "viewer"}],
                "user_permissions": [{"permission_code": "trading.view"}],
            }[operation]

    profile = await admin.me(user_id="active-user", db=Database())
    assert profile["username"] == "example"
    assert profile["roles"] == ["viewer"]
    assert profile["permissions"] == ["trading.view"]


@pytest.mark.asyncio
async def test_me_does_not_clear_session_when_database_is_unavailable():
    class Database:
        async def query(self, operation, params):
            raise DataServiceUnavailable("offline")

    with pytest.raises(DataServiceUnavailable):
        await admin.me(user_id="active-user", db=Database())
