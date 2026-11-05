"""N6 unification probes (2026-11-05): per-symbol lookups answer 404.

Before N6 the data service mixed two semantics for unknown symbols:
- /api/data/ohlcv/{symbol}/{timeframe}            -> 404  ("No OHLCV data")
- /api/data/flow/{symbol}                         -> 200 honest zero-wrap
- /api/data/ohlcv/.../provenance                  -> 200 honest zero-wrap

qa/COMPONENT_QA_REPORT.md (N6) flagged the split for unification. Decision:
404 is canonical for per-symbol lookups, because (a) the honesty contracts
(UI-05/UI-06) forbid conflating "no data" with real zeros, (b) ohlcv's 404
is load-bearing (nexus_news outcome_collector_v61 short-circuits on it),
(c) flow's only service consumer (nexus_agents analysis_tools) already
degrades to its own zero envelope on any non-200, (d) provenance has no
service consumers. The gateway (nexus-api) surface is unaffected: it never
proxied /api/data/* path-style routes.

Safety: READ-ONLY GET probes against the running nexus-data service;
skips cleanly when the service is unreachable (same convention as
test_ohlcv_research_api_probes.py).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

DATA_BASE = "http://127.0.0.1:9001"

# A symbol the paper environment never ingests (reserved RFC-2606-ish name).
UNKNOWN = "N6UNKNOWNZZZ"


def _get(url: str, timeout: float = 15.0):
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            body = {}
        return exc.code, body
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ConnectionError(str(exc)) from exc


def _reachable() -> None:
    try:
        _get(f"{DATA_BASE}/health", timeout=3.0)
    except ConnectionError as exc:
        pytest.skip(f"nexus-data not reachable at {DATA_BASE}: {exc}")


def test_flow_unknown_symbol_is_404():
    """N6 pin: flow for an unknown symbol is 404, not a zeroed 200 envelope."""
    _reachable()
    status, body = _get(f"{DATA_BASE}/api/data/flow/{UNKNOWN}")
    assert status == 404, f"flow unknown symbol must 404, got {status}: {body}"
    assert "No order-flow data" in str(body.get("detail", ""))


def test_flow_unknown_symbol_legacy_alias_is_404():
    """N6 pin: the /api/flow/{symbol} legacy alias shares the 404 semantics."""
    _reachable()
    status, body = _get(f"{DATA_BASE}/api/flow/{UNKNOWN}")
    assert status == 404, f"legacy flow alias must 404, got {status}: {body}"


def test_ohlcv_unknown_symbol_stays_404():
    """N6 pin: ohlcv keeps its canonical 404 (load-bearing for consumers)."""
    _reachable()
    status, body = _get(f"{DATA_BASE}/api/data/ohlcv/{UNKNOWN}/H1")
    assert status == 404, f"ohlcv unknown symbol must 404, got {status}: {body}"
    assert "No OHLCV data" in str(body.get("detail", ""))


def test_provenance_unknown_symbol_is_404():
    """N6 pin: provenance for an empty series is 404 like ohlcv itself."""
    _reachable()
    status, body = _get(f"{DATA_BASE}/api/data/ohlcv/{UNKNOWN}/H1/provenance")
    assert status == 404, f"provenance unknown symbol must 404, got {status}: {body}"
    assert "No OHLCV data" in str(body.get("detail", ""))


def test_known_symbol_flow_still_200_when_data_exists():
    """N6 pin: 404 fires only on absence — a known pair with data stays 200.

    XAUUSD M1 is the paper environment's primary pair; if it holds bars the
    flow endpoint must keep returning a real (possibly zero-volume) envelope
    with bars_analyzed > 0. Skips if the pair has no data yet so the pin
    never reports a false failure on an empty fresh database.
    """
    _reachable()
    status, ohlcv_body = _get(f"{DATA_BASE}/api/data/ohlcv/XAUUSD/M1?limit=1")
    if status == 404:
        pytest.skip("XAUUSD M1 has no bars yet — 200-pin not applicable")
    assert status == 200, f"XAUUSD M1 ohlcv HTTP {status}: {ohlcv_body}"
    status, body = _get(f"{DATA_BASE}/api/data/flow/XAUUSD")
    assert status == 200, f"flow for a known pair must 200, got {status}: {body}"
    assert int(body.get("bars_analyzed", 0)) > 0
