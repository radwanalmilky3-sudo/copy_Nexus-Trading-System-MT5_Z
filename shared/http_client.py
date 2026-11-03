"""Shared HTTP client factory for all inter-service calls.

Services used to build a fresh ``httpx.AsyncClient`` per request. httpx
constructs an SSL context on each instantiation, and
``ssl.create_default_context()`` reads the whole system CA bundle off disk —
measured at ~1.4 s of CPU per client on this host.

A CPU profile of the API gateway attributed **95% of its CPU** to that single
call: it pinned the event loop at 100% of a core and pushed even local routes
like ``/health`` from ~10 ms to 1–3 s, which surfaced in the dashboard as
"gateway offline". nexus_agents creates 17 of these per evaluation cycle.

Every inter-service call is plain HTTP to 127.0.0.1, so one process-wide
context is enough. Passing an already-built ``SSLContext`` as ``verify`` makes
httpx skip the expensive construction entirely (~4000x faster to instantiate).
"""
from __future__ import annotations

import ssl
import anyio
import httpcore
from typing import Any

import httpx

from shared.source_manager import resolve_public_ip

# Built once at import; reused by every client this process creates.
_SSL_CONTEXT = ssl.create_default_context()


class _PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Connect to one validated IP while preserving the request hostname."""

    def __init__(self) -> None:
        self._backend = httpcore.AnyIOBackend()

    async def connect_tcp(self, host: str, port: int, timeout: float | None = None,
                          local_address: str | None = None,
                          socket_options: Any = None) -> httpcore.AsyncNetworkStream:
        pinned = await anyio.to_thread.run_sync(resolve_public_ip, host)
        return await self._backend.connect_tcp(
            pinned, port, timeout=timeout, local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(self, path: str, timeout: float | None = None,
                                  socket_options: Any = None) -> httpcore.AsyncNetworkStream:
        return await self._backend.connect_unix_socket(path, timeout=timeout, socket_options=socket_options)

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class _PinnedAsyncHTTPTransport(httpx.AsyncBaseTransport):
    def __init__(self, **kwargs: Any) -> None:
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=kwargs.pop("ssl_context"),
            max_connections=kwargs.pop("max_connections", 100),
            max_keepalive_connections=kwargs.pop("max_keepalive_connections", 20),
            keepalive_expiry=kwargs.pop("keepalive_expiry", 5.0),
            http1=kwargs.pop("http1", True),
            http2=kwargs.pop("http2", False),
            retries=kwargs.pop("retries", 0),
            network_backend=_PinnedNetworkBackend(),
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        response = await self._pool.handle_async_request(req)
        return httpx.Response(
            status_code=response.status,
            headers=response.headers,
            stream=httpx._transports.default.AsyncResponseStream(response.stream),
            extensions=response.extensions,
            request=request,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()


def new_client(**kwargs: Any) -> httpx.AsyncClient:
    """``httpx.AsyncClient`` that reuses the shared SSL context.

    Accepts the same keyword arguments as ``httpx.AsyncClient``; an explicit
    ``verify`` passed by the caller still wins.
    """
    kwargs.setdefault("verify", _SSL_CONTEXT)
    pin_dns = bool(kwargs.pop("pin_dns", False))
    if pin_dns:
        if kwargs.get("follow_redirects", False):
            raise ValueError("pinned HTTP clients must not follow redirects")
        if kwargs.get("transport") is not None:
            raise ValueError("pinned HTTP clients must not also pass transport")
        verify = kwargs.pop("verify")
        if not isinstance(verify, ssl.SSLContext):
            # httpx accepts bool/str for verify, but the pinned transport takes
            # an SSLContext only; anything else must fail here rather than as a
            # confusing httpcore error on the first request.
            raise ValueError("pinned HTTP clients require an SSLContext for verify")
        limits = kwargs.pop("limits", httpx.Limits())
        kwargs["transport"] = _PinnedAsyncHTTPTransport(
            ssl_context=verify,
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_keepalive_connections,
            keepalive_expiry=limits.keepalive_expiry,
        )
    return httpx.AsyncClient(**kwargs)
