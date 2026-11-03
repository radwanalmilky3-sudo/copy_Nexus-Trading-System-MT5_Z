"""URL/exception sanitisation for the nexus_news package.

httpx embeds the full request URL (including query strings) in
``HTTPStatusError``/``UnsupportedProtocol``/``TooManyRedirects`` messages.
Several adapters put API keys in query parameters (``apiKey``, ``token``,
``api_key``), so logging or persisting ``str(exc)`` leaks secrets into logs,
Redis health payloads and DuckDB ``source_fetch_runs`` rows.

``safe_url()`` / ``safe_error()`` redact secret-bearing query parameters and
must be used anywhere an outbound URL or HTTP exception may be logged, raised
or stored.  Package-local by design — shared/ is owned elsewhere.
"""
from __future__ import annotations

import re
from typing import Any

# Query-parameter names whose values are always redacted.  Matching is
# case-insensitive and also covers snake_case/camelCase variants.  The
# leading delimiter (or string start) prevents over-matching inside words.
_SENSITIVE_PARAM_RE = re.compile(
    r"(?i)(?:^|([?&\s(]))"
    r"(key|apikey|api_key|api-key|token|access_token|refresh_token|"
    r"secret|client_secret|signature|sig|password|pwd|auth)"
    r"=([^&\s\"'<>)]+)"
)


def safe_url(url: Any) -> str:
    """Return *url* as text with sensitive query-parameter values redacted."""
    return _SENSITIVE_PARAM_RE.sub(r"\1\2=[REDACTED]", str(url))


def safe_error(exc: BaseException) -> str:
    """Stringify *exc* with any embedded secret query-parameter values redacted.

    Use this instead of ``str(exc)`` for httpx (or any) exceptions whose
    message may embed the full request URL.
    """
    return safe_url(str(exc))
