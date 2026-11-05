"""Scope-based rate limiter — owner-approved design (2026-11-05, «موافق»).

Fixed-window counters backed by Redis (same house pattern as
``services/nexus_api/routers/admin.py::_auth_rate_guard``), keyed by
``nexus:rl:<scope>:<identity>`` where the identity is the client IP
(XFF-aware when the direct peer is loopback, mirroring the documented
gateway deployment).

Approved scopes and defaults (requests per window):

==============  ====  --------------------------------------------------
scope           /min  surface
==============  ====  --------------------------------------------------
admin           30    admin management routes (auth keeps its own guards)
risk            20    routers/risk.py
edit_close      60    positions close/modify mutations
ea              240   routers/ea.py bridge
ml              6     ml heavy POST actions only (status reads stay open)
backtest        10    backtest POST runs only (reads stay open)
env             10    routers/env.py
==============  ====  ======================================================

Overrides (read per request, no restart needed):

* ``NEXUS_RL_ENABLED=0``              global kill-switch (allow everything)
* ``NEXUS_RL_<SCOPE>_LIMIT``          limit for one scope; ``0`` disables it
* ``NEXUS_RL_<SCOPE>_WINDOW_SEC``     window length (default 60)

Fail-open policy: if Redis is unavailable the request passes. A limiter
must never take trading down; the auth guards in ``admin.py`` set the
precedent.
"""
from __future__ import annotations

import os
from typing import Any, Awaitable, Callable

from fastapi import Depends, HTTPException, Request, status

DEFAULT_LIMITS: dict[str, int] = {
    "admin": 30,
    "risk": 20,
    "edit_close": 60,
    "ea": 240,
    "ml": 6,
    "backtest": 10,
    "env": 10,
}
DEFAULT_WINDOW_SEC = 60.0
_KEY_PREFIX = "nexus:rl:"
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _client_identity(request: Request) -> str:
    """Peer identity, XFF-aware behind loopback (documented gateway setup)."""
    peer = request.client.host if request.client else "unknown"
    xff = request.headers.get("x-forwarded-for", "")
    if xff and peer in _LOOPBACK:
        peer = xff.split(",")[0].strip()
    return peer or "unknown"


def _client(request: Request) -> Any | None:
    """Raw async redis client installed by the lifespan (``app.state``)."""
    return getattr(request.app.state, "nexus_redis", None)


def rate_limit_scope(scope: str) -> Depends:
    """FastAPI dependency enforcing the fixed-window limit for ``scope``.

    Returns ``Depends(_check)`` so routers can use it directly:
    ``dependencies=[rate_limit_scope("admin")]``.
    """
    if scope not in DEFAULT_LIMITS:
        raise ValueError(f"unknown rate-limit scope: {scope!r}")

    async def _check(request: Request) -> None:
        if os.getenv("NEXUS_RL_ENABLED", "").strip() == "0":
            return
        env_scope = scope.upper()
        try:
            limit = int(
                os.getenv(f"NEXUS_RL_{env_scope}_LIMIT", str(DEFAULT_LIMITS[scope]))
            )
            window = float(
                os.getenv(f"NEXUS_RL_{env_scope}_WINDOW_SEC", str(DEFAULT_WINDOW_SEC))
            )
        except ValueError:
            limit, window = DEFAULT_LIMITS[scope], DEFAULT_WINDOW_SEC
        if limit <= 0 or window <= 0:
            return
        client = _client(request)
        if client is None:
            return  # fail-open: limiter must never take the service down
        key = f"{_KEY_PREFIX}{scope}:{_client_identity(request)}"
        try:
            count = await client.incr(key)
            if count == 1:
                await client.expire(key, max(1, int(window)))
            ttl = await client.ttl(key)
        except Exception:  # noqa: BLE001 — fail-open, matches auth guards
            return
        if count > limit:
            retry_after = ttl if ttl and ttl > 0 else max(1, int(window))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"rate limit exceeded for '{scope}'; retry later",
                headers={"Retry-After": str(retry_after)},
            )

    return Depends(_check)
