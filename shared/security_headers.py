"""Security response headers for every Nexus HTTP surface (T-012, 2026-11-06).

Adds a conservative, breakage-free hardening set to every HTTP response:
anti-framing (``X-Frame-Options: DENY`` plus ``CSP: frame-ancestors 'none'``),
MIME-sniffing protection, referrer minimisation, and browser feature
gating. ``Cache-Control: no-store`` is applied only when the handler did
not set ``Cache-Control`` itself — existing caching decisions always win,
so static/proxied content that opts into caching is untouched.

Deliberately NOT here: HSTS. It is a TLS-time header and the fleet serves
plain HTTP on loopback; browsers must ignore it over http:// anyway. Wire
HSTS (and a full CSP) at the reverse proxy when the fleet is first exposed
externally — qa/HANDOFF.md §6 keeps that as the deployment-time item.

The middleware is pure ASGI: it never reads the request, never performs
I/O, and passes WebSocket/lifespan scopes through untouched, so it adds
no measurable latency and cannot alter handler behaviour.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

# Headers added to every response unless already present (exact names are
# sent lower-case per HTTP/2 convention; HTTP/1.1 clients are case-insensitive).
SECURITY_HEADERS: tuple[tuple[str, str], ...] = (
    ("x-content-type-options", "nosniff"),
    ("x-frame-options", "DENY"),
    ("referrer-policy", "strict-origin-when-cross-origin"),
    ("permissions-policy", "camera=(), microphone=(), geolocation=()"),
    ("content-security-policy", "frame-ancestors 'none'"),
)

# Trading data must not linger in shared/browser caches; applied only when
# the handler (or a proxy in front of us) has not chosen a policy itself.
DEFAULT_CACHE_CONTROL = "no-store"

ASGIApp = Callable[[dict, Any, Any], Awaitable[None]]


class SecurityHeadersMiddleware:
    """ASGI middleware injecting the hardening headers into every response.

    Compatible with Starlette's ``app.add_middleware(SecurityHeadersMiddleware)``:
    the single positional ``app`` argument is all Starlette passes.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: dict) -> None:
            if message["type"] == "http.response.start":
                raw = message.get("headers") or []
                present = {
                    key.decode("latin-1").lower() for key, _ in raw
                }
                additions = [
                    (name.encode("latin-1"), value.encode("latin-1"))
                    for name, value in SECURITY_HEADERS
                    if name not in present
                ]
                if "cache-control" not in present:
                    additions.append(
                        (b"cache-control", DEFAULT_CACHE_CONTROL.encode("latin-1"))
                    )
                if additions:
                    message["headers"] = list(raw) + additions
            await send(message)

        await self.app(scope, receive, send_with_headers)
