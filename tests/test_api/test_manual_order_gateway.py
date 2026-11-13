"""Gateway manual-order route — the only user-facing path to NEW exposure.

Every test pins one safety property: the route reuses the deterministic
agent-order chain (central-risk evaluation + signed approval + executor
guard) and never shortcuts it.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from services.nexus_api.middleware.auth import create_token
from services.nexus_api.routers import positions


class _ClientContext:
    def __init__(self, client: AsyncMock) -> None:
        self.client = client

    async def __aenter__(self) -> AsyncMock:
        return self.client

    async def __aexit__(self, *_: object) -> None:
        return None


VALID_BODY = {
    "symbol": "XAUUSD",
    "side": "BUY",
    "lots": 0.05,
    "entry": 2035.5,
    "sl": 2030.5,
    "tp": 2045.5,
}

APPROVAL_PAYLOAD = {
    "version": 1,
    "proposal_id": "prop-manual-1",
    "expires_at": 1893456000,
    "symbol": "XAUUSD",
    "side": "BUY",
    "order_type": "MARKET",
    "entry": 2035.5,
    "price": 2035.5,
    "sl": 2030.5,
    "tp": 2045.5,
    "size": 0.05,
    "signal_timestamp": 1893455990,
    "slippage": 10,
}


def _risk_response(decision: str = "APPROVE") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "decision": decision,
            "approved_size": 0.05 if decision == "APPROVE" else 0.0,
            "violations": [] if decision == "APPROVE" else [
                {"rule": "test", "message": "risk said no"}
            ],
            "proposal_id": "prop-manual-1",
            "approval_expires_at": APPROVAL_PAYLOAD["expires_at"],
            "approval_signature": "sig-abc",
            "approval_payload": APPROVAL_PAYLOAD if decision == "APPROVE" else {},
        },
        request=httpx.Request("POST", "http://risk"),
    )


@pytest.mark.asyncio
async def test_manual_order_rejects_missing_jwt_before_any_downstream_call(
    api_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    client = AsyncMock()
    monkeypatch.setattr(positions, "new_client", lambda **_: _ClientContext(client))

    response = await api_client.post("/api/positions/manual-order", json=VALID_BODY)

    assert response.status_code == 401
    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_manual_order_requires_trading_execute_permission(
    api_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    client = AsyncMock()
    monkeypatch.setattr(positions, "new_client", lambda **_: _ClientContext(client))

    response = await api_client.post(
        "/api/positions/manual-order",
        json=VALID_BODY,
        headers={"Authorization": f"Bearer {create_token('unprivileged-user')}"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "permission required: trading.execute"}
    client.post.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        {"side": "LONG"},  # unknown side
        {"lots": 0.0},  # below minimum lot
        {"entry": 0.0},  # non-positive entry
        {"sl": 2040.0},  # BUY stop-loss above entry — fat finger
        {"tp": 2030.0},  # BUY take-profit below entry — fat finger
    ],
)
async def test_manual_order_fails_closed_on_fat_finger_inputs(
    api_client, monkeypatch: pytest.MonkeyPatch, mutation: dict[str, object]
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    monkeypatch.setattr(positions, "_require", AsyncMock(return_value=None))
    client = AsyncMock()
    monkeypatch.setattr(positions, "new_client", lambda **_: _ClientContext(client))

    response = await api_client.post(
        "/api/positions/manual-order",
        json={**VALID_BODY, **mutation},
        headers={"Authorization": f"Bearer {create_token('authorized-user')}"},
    )

    assert response.status_code == 422
    client.post.assert_not_awaited(), "no risk evaluation may run on invalid terms"


@pytest.mark.asyncio
async def test_manual_order_happy_path_proxies_signed_terms_to_executor(
    api_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-internal-secret")
    monkeypatch.setattr(positions, "_require", AsyncMock(return_value=None))
    client = AsyncMock()
    client.post.side_effect = [
        _risk_response("APPROVE"),
        httpx.Response(
            200,
            json={"status": "FILLED", "ticket": 12345},
            request=httpx.Request("POST", "http://executor"),
        ),
    ]
    monkeypatch.setattr(positions, "new_client", lambda **_: _ClientContext(client))

    response = await api_client.post(
        "/api/positions/manual-order",
        json=VALID_BODY,
        headers={"Authorization": f"Bearer {create_token('authorized-user')}"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "FILLED"

    risk_call, executor_call = client.post.await_args_list
    assert risk_call.args[0].endswith("/api/risk/evaluate")
    assert risk_call.kwargs["headers"] == {"X-Nexus-Internal-Secret": "test-internal-secret"}
    proposal = risk_call.kwargs["json"]["proposal"]
    assert proposal["symbol"] == "XAUUSD"
    assert proposal["direction"] == "BUY"
    assert proposal["sl"] == 2030.5 and proposal["tp1"] == 2045.5

    assert executor_call.args[0].endswith("/api/executor/order")
    assert executor_call.kwargs["headers"] == {"X-Nexus-Internal-Secret": "test-internal-secret"}
    body = executor_call.kwargs["json"]
    assert body["size"] == 0.05, "the executor gets the risk-approved size, not the requested one"
    assert body["price"] == 2035.5 and body["risk_approved_entry"] == 2035.5
    assert body["slippage"] == 10, "must match the signed approval slippage byte-for-byte"
    assert body["proposal_id"] == "prop-manual-1"
    assert body["risk_approval_signature"] == "sig-abc"
    assert body["risk_approval_payload"] == APPROVAL_PAYLOAD, "approval passes verbatim"
    assert body["signal_timestamp"] == APPROVAL_PAYLOAD["signal_timestamp"]
    assert body["risk_approval_expires_at"] == APPROVAL_PAYLOAD["expires_at"]


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["REJECT", "MODIFY"])
async def test_manual_order_risk_rejection_never_reaches_the_executor(
    api_client, monkeypatch: pytest.MonkeyPatch, decision: str
) -> None:
    monkeypatch.setenv("NEXUS_JWT_SECRET", "test-jwt-secret-long-enough-for-hs256")
    monkeypatch.setenv("NEXUS_INTERNAL_API_SECRET", "test-internal-secret")
    monkeypatch.setattr(positions, "_require", AsyncMock(return_value=None))
    client = AsyncMock()
    client.post.side_effect = [_risk_response(decision)]
    monkeypatch.setattr(positions, "new_client", lambda **_: _ClientContext(client))

    response = await api_client.post(
        "/api/positions/manual-order",
        json=VALID_BODY,
        headers={"Authorization": f"Bearer {create_token('authorized-user')}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "RISK_REJECTED"
    assert body["decision"] == decision
    assert client.post.await_count == 1, "only the risk evaluation ran; no executor call"
