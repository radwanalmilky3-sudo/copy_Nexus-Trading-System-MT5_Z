"""Authenticated HTTP client for durable data owned by nexus-data."""
from __future__ import annotations

import os
from typing import Any

import httpx

from .http_client import new_client


class DataServiceUnavailable(RuntimeError):
    """The data service could not safely provide the requested result."""


class DataServiceRejected(RuntimeError):
    """The data service rejected an internal request or operation."""


class BrokerRequestRejected(DataServiceRejected):
    def __init__(self, status_code: int):
        super().__init__('Broker settings request rejected')
        self.status_code = status_code


class DataServiceClient:
    def __init__(
        self,
        base_url: str | None = None,
        secret: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("NEXUS_DATA_URL", "http://127.0.0.1:9001")).rstrip("/")
        self.secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip() if secret is None else secret.strip()
        self._transport = transport

    async def query(self, operation: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if not self.secret:
            raise DataServiceUnavailable("internal data service credential is not configured")
        try:
            async with new_client(timeout=10.0, transport=self._transport) as client:
                response = await client.post(
                    f"{self.base_url}/api/data/query",
                    headers={"X-Nexus-Internal-Secret": self.secret},
                    json={"operation": operation, "params": params or {}},
                )
        except httpx.HTTPError as exc:
            raise DataServiceUnavailable("nexus-data is unreachable") from exc

        if response.status_code >= 500 or response.status_code in {408, 429}:
            raise DataServiceUnavailable(f"nexus-data returned {response.status_code}")
        if response.status_code >= 400:
            raise DataServiceRejected(f"nexus-data rejected operation ({response.status_code})")
        try:
            payload = response.json()
            rows = payload["rows"]
        except (ValueError, KeyError, TypeError) as exc:
            raise DataServiceUnavailable("nexus-data returned an invalid query response") from exc
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise DataServiceUnavailable("nexus-data returned an invalid row set")
        return rows

    async def broker_settings(self, operation: str, owner_id: str, payload: dict[str, Any]) -> Any:
        allowed={'list_profiles','create_profile','create_account','get_account','get_identity','save_settings','list_events','research_market','research_runs','research_analysis','research_report','sync_sessions'}
        if operation not in allowed:
            raise ValueError('Unsupported broker settings operation')
        if not self.secret:
            raise DataServiceUnavailable('internal data service credential is not configured')
        try:
            async with new_client(timeout=35.0 if operation=='research_market' else 10.0, transport=self._transport) as client:
                response=await client.post(f'{self.base_url}/api/data/broker-settings',
                    headers={'X-Nexus-Internal-Secret':self.secret},
                    json={'operation':operation,'owner_id':owner_id,'payload':payload})
        except httpx.HTTPError:
            raise DataServiceUnavailable('Broker settings service unavailable') from None
        if response.status_code in {404,409,422,413}:
            raise BrokerRequestRejected(response.status_code)
        if not response.is_success:
            raise DataServiceUnavailable('Broker settings service unavailable')
        try:
            result=response.json()['result']
            if not isinstance(result,(dict,list)):
                raise ValueError()
            return result
        except (ValueError,KeyError,TypeError):
            raise DataServiceUnavailable('Invalid broker settings response') from None

    async def mt5_symbols(self, identity: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.secret:
            raise DataServiceUnavailable('internal data service credential is not configured')
        try:
            async with new_client(timeout=25.0, transport=self._transport) as client:
                response = await client.get(f'{self.base_url}/api/data/mt5/symbols', params={'expected_login':identity['login'],'expected_server':identity['server']}, headers={'X-Nexus-Internal-Secret': self.secret})
        except httpx.HTTPError:
            raise DataServiceUnavailable('MT5 symbol service unavailable') from None
        if response.status_code >= 400:
            raise DataServiceUnavailable('MT5 symbol service unavailable')
        try:
            rows=response.json()['symbols']
            if not isinstance(rows,list): raise ValueError()
            return rows
        except (ValueError,KeyError,TypeError):
            raise DataServiceUnavailable('Invalid MT5 symbol response') from None

    async def health(self) -> bool:
        try:
            async with new_client(timeout=2.0, transport=self._transport) as client:
                response = await client.get(f"{self.base_url}/health")
            if response.status_code != 200:
                return False
            data = response.json()
            return data.get("ready") is True and data.get("duckdb") is True
        except (httpx.HTTPError, ValueError, AttributeError):
            return False
