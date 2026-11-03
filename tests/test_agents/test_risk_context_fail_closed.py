import pytest

from services.nexus_agents.agents import risk_manager as risk_manager_module
from services.nexus_agents.agents.risk_manager import RiskManagerAgent
from services.nexus_agents.state import initial_state
from services.nexus_agents.tools import risk_tools


@pytest.mark.asyncio
async def test_exposure_request_forwards_internal_service_credential(monkeypatch):
    captured = {}

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "daily_loss_pct": 0.0,
                "weekly_dd_pct": 0.0,
                "open_positions": 0,
                "consecutive_losses": 0,
            }

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, _url, **kwargs):
            captured.update(kwargs)
            return Response()

    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-service-secret")
    monkeypatch.setattr(risk_tools, "new_client", lambda **_kwargs: Client())

    result = await risk_tools.check_exposure()

    assert result["available"] is True
    assert captured["headers"] == {
        "X-Nexus-Internal-Secret": "test-service-secret"
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"available": False, "daily_loss_pct": 0, "weekly_dd_pct": 0,
     "open_positions": 0, "consecutive_losses": 0},
    {"daily_loss_pct": 0},
    {"daily_loss_pct": float("nan"), "weekly_dd_pct": 0,
     "open_positions": 0, "consecutive_losses": 0},
])
async def test_incomplete_or_unavailable_exposure_fails_closed(monkeypatch, payload):
    class Response:
        status_code = 200

        @staticmethod
        def json():
            return payload

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(risk_tools, "new_client", lambda **_kwargs: Client())

    result = await risk_tools.check_exposure()

    assert result["available"] is False


@pytest.mark.asyncio
async def test_unavailable_exposure_rejects_agent_side_risk_check(monkeypatch):
    async def unavailable():
        return {
            "available": False,
            "daily_loss_pct": 0.0,
            "weekly_dd_pct": 0.0,
            "open_positions": 0,
        }

    async def equity():
        return 1000.0

    monkeypatch.setattr(risk_manager_module, "check_exposure", unavailable)
    monkeypatch.setattr(risk_manager_module, "_get_account_equity", equity)

    state = initial_state(
        symbol="XAUUSD",
        session="LONDON",
        verdict="BUY",
        verdict_conviction=85,
    )

    result = await RiskManagerAgent().invoke(state)

    assert result["risk_decision"] == "REJECT"
    assert result["position_size"] == 0.0
    reasoning = result["risk_reasoning"]
    assert "exposure_unavailable" in reasoning or "exposure could not be verified" in reasoning.lower()
