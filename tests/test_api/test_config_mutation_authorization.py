from __future__ import annotations

from copy import deepcopy

import pytest

from shared.config_loader import AgentConfigSchema, ConfigLoader, RiskRulesSchema, SettingsSchema
from services.nexus_api.deps import get_config
from services.nexus_api.main import app
from services.nexus_api.middleware.auth import create_token


@pytest.fixture
def configured_api_client(api_client):
    loader = ConfigLoader()
    loader._cache = {
        "settings": SettingsSchema().model_dump(),
        "agents": {
            "test-agent": AgentConfigSchema(id="test-agent", name="Test Agent").model_dump(),
        },
        "risk": RiskRulesSchema().model_dump(),
    }
    previous = app.dependency_overrides.get(get_config)
    app.dependency_overrides[get_config] = lambda: loader
    try:
        yield api_client, loader
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_config, None)
        else:
            app.dependency_overrides[get_config] = previous


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "payload", "permission"),
    [
        ("/api/config/settings", {"settings": {"log_level": "DEBUG"}}, "trading.settings"),
        ("/api/config/agents/test-agent", {"enabled": False}, "trading.settings"),
        ("/api/config/risk", {"rules": {"daily_trade_limit": 12}}, "risk.modify"),
    ],
)
async def test_config_mutations_reject_missing_jwt_before_state_change(
    configured_api_client,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    payload: dict,
    permission: str,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    client, loader = configured_api_client
    before = deepcopy(loader._cache)

    response = await client.put(path, json=payload)

    assert response.status_code == 401
    assert loader._cache == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "payload", "permission"),
    [
        ("/api/config/settings", {"settings": {"log_level": "DEBUG"}}, "trading.settings"),
        ("/api/config/agents/test-agent", {"enabled": False}, "trading.settings"),
        ("/api/config/risk", {"rules": {"daily_trade_limit": 12}}, "risk.modify"),
    ],
)
async def test_config_mutations_require_permission_before_state_change(
    configured_api_client,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    payload: dict,
    permission: str,
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    client, loader = configured_api_client
    before = deepcopy(loader._cache)

    response = await client.put(
        path,
        json=payload,
        headers={"Authorization": f"Bearer {create_token('unprivileged-user')}"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": f"permission required: {permission}"}
    assert loader._cache == before
