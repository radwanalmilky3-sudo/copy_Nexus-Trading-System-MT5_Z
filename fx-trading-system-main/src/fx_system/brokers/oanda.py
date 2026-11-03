from __future__ import annotations

from typing import Any

import httpx

from .base import PracticeBroker

PRACTICE_URL = "https://api-fxpractice.oanda.com"


class OandaPracticeBroker(PracticeBroker):
    """Minimal, practice-only OANDA adapter. Production endpoints are deliberately impossible."""

    def __init__(
        self,
        account_id: str,
        token: str,
        *,
        base_url: str = PRACTICE_URL,
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if base_url.rstrip("/") != PRACTICE_URL:
            raise ValueError(
                "Only the OANDA fxPractice endpoint is allowed; live trading is disabled"
            )
        if not account_id or not token:
            raise ValueError("OANDA practice account ID and token are required")
        self.account_id = account_id
        self.client = httpx.Client(
            base_url=PRACTICE_URL,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=timeout,
            transport=transport,
        )

    @staticmethod
    def _instrument(symbol: str) -> str:
        clean = symbol.upper().replace("/", "").replace("_", "")
        if len(clean) != 6:
            raise ValueError(f"Invalid FX symbol: {symbol}")
        return f"{clean[:3]}_{clean[3:]}"

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    def account_summary(self) -> dict[str, Any]:
        return self._request("GET", f"/v3/accounts/{self.account_id}/summary")

    def open_positions(self) -> list[dict[str, Any]]:
        payload = self._request("GET", f"/v3/accounts/{self.account_id}/openPositions")
        return list(payload.get("positions", []))

    def submit_market_order(
        self,
        symbol: str,
        units: int,
        stop_loss: float,
        take_profit: float,
        client_id: str,
        confirm_practice: bool = False,
    ) -> dict[str, Any]:
        if not confirm_practice:
            raise PermissionError("Practice order not submitted: explicit confirmation is required")
        if units == 0:
            raise ValueError("Order units cannot be zero")
        precision = 3 if symbol.upper().replace("_", "").endswith("JPY") else 5
        order = {
            "order": {
                "type": "MARKET",
                "instrument": self._instrument(symbol),
                "units": str(int(units)),
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
                "stopLossOnFill": {"price": f"{stop_loss:.{precision}f}", "timeInForce": "GTC"},
                "takeProfitOnFill": {"price": f"{take_profit:.{precision}f}", "timeInForce": "GTC"},
                "clientExtensions": {
                    "id": client_id[:128],
                    "tag": "fx-portfolio-system",
                },
            }
        }
        return self._request("POST", f"/v3/accounts/{self.account_id}/orders", json=order)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> OandaPracticeBroker:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
