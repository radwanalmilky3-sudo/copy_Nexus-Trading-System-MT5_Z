from __future__ import annotations

import abc
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
from shared.http_client import new_client

from shared.fundamental import ProviderHealth


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class FetchResult:
    source_id: str
    success: bool
    records: list[dict[str, Any]] = field(default_factory=list)
    http_status: int | None = None
    latency_ms: float | None = None
    error_code: str | None = None
    error_message: str | None = None
    payload_hash: str | None = None
    health: ProviderHealth = ProviderHealth.UNKNOWN
    started_at: datetime = field(default_factory=utcnow)
    finished_at: datetime | None = None

    @property
    def fetch_run_id(self) -> str:
        return uuid.uuid4().hex


class SourceAdapter(abc.ABC):
    source_id: str
    api_key_env: str | None = None

    def configured(self) -> bool:
        if not self.api_key_env:
            return True
        return bool(os.getenv(self.api_key_env, "").strip())

    @abc.abstractmethod
    async def fetch(self) -> FetchResult:
        raise NotImplementedError

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 15.0,
    ) -> tuple[int, Any, float, str]:
        started = time.perf_counter()
        async with new_client(timeout=timeout, pin_dns=True, follow_redirects=False) as client:
            resp = await client.request(method, url, params=params, json=json_body, headers=headers)
        latency_ms = (time.perf_counter() - started) * 1000.0
        raw = resp.content
        payload_hash = hashlib.sha256(raw).hexdigest()
        resp.raise_for_status()
        return resp.status_code, resp.json(), latency_ms, payload_hash

    async def _request_text(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 15.0,
    ) -> tuple[int, str, float, str]:
        started = time.perf_counter()
        async with new_client(timeout=timeout, pin_dns=True, follow_redirects=False) as client:
            resp = await client.request(method, url, params=params, headers=headers)
        latency_ms = (time.perf_counter() - started) * 1000.0
        payload_hash = hashlib.sha256(resp.content).hexdigest()
        resp.raise_for_status()
        return resp.status_code, resp.text, latency_ms, payload_hash


def normalized_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
