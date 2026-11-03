"""Task 8 — local analyst availability contract + intelligence route honesty.

Contract (plan ### المهمة 8 + project_audit/REPAIR_TASK3_20261021.md):
- Distinguish LLM endpoint down / model not installed / timeout / invalid
  response / grounding rejection. Never substitute canned answers.
- Surface the real connection reason (address/model), model name and the
  evidence IDs actually used.
- Hallucination prevention: invented source/claim IDs are rejected with
  answer=None; missing data never becomes an invented explanation.
- /api/intelligence/quality and /correlation must not fabricate 0/NEUTRAL
  envelopes when the store is empty (unknown != 0 != NEUTRAL).
No live model calls, no real prices, no Redis/DuckDB writes.
"""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi import HTTPException

from services.nexus_api.fundamental_local_ai import GroundedLocalAI
from services.nexus_api.routers import intelligence


# ── Fake local OpenAI-compatible runtime ─────────────────────────────────────


class _FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or json.dumps(payload or {})

    def json(self):
        if self._payload is None:
            return json.loads(self.text)
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://127.0.0.1:11434/v1/chat/completions")
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=request, response=self  # type: ignore[arg-type]
            )


class _FakeAsyncClient:
    """Scripted httpx.AsyncClient stand-in; never touches the network."""

    def __init__(self, script: dict[str, _FakeResponse | Exception], timeout: float = 1.0):
        self._script = script
        self.calls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url: str, **kwargs):
        self.calls.append(f"GET {url}")
        item = self._script.get("GET " + url.split("?")[0], self._script.get("GET"))
        if isinstance(item, Exception):
            raise item
        if item is None:
            raise AssertionError(f"unexpected GET {url}")
        return item

    async def post(self, url: str, **kwargs):
        self.calls.append(f"POST {url}")
        item = self._script.get("POST " + url.split("?")[0], self._script.get("POST"))
        if isinstance(item, Exception):
            raise item
        if item is None:
            raise AssertionError(f"unexpected POST {url}")
        return item


def _client(monkeypatch, script: dict) -> _FakeAsyncClient:
    fake = _FakeAsyncClient(script)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: fake)
    return fake


def _analyst() -> GroundedLocalAI:
    ai = GroundedLocalAI()
    ai.timeout = 1.0
    return ai


_VALID_ANSWER = {
    "summary_ar": "الحالة مستندة إلى المصادر المسجلة",
    "what_happened": "سجل المصدر تحديثًا",
    "why_it_matters": "يهم باعتباره سياقًا وصفيًا",
    "transmission": [], "asset_comparison": [], "confirmations": [],
    "contradictions": [], "missing_evidence": [],
    "sources": ["src_alpha"], "claims_used": ["claim_beta"],
    "data_quality_note": "", "uncertainty_note": "",
}

_STRUCT = {
    "asset": "XAUUSD",
    "overview": {"direction": "unknown", "confidence": None},
    "source_health": [{"source_id": "src_alpha", "health": "ok"}],
    "knowledge_claims": [{"claim_id": "claim_beta", "statement_ar": "مبلغ"}],
    "ticker": [],
}


def _chat(answer: dict) -> _FakeResponse:
    return _FakeResponse(200, {
        "choices": [{"message": {"content": json.dumps(answer, ensure_ascii=False)}}]
    })


_MODELS_OK = _FakeResponse(200, {"data": [{"id": "qwen2.5:3b"}, {"id": "other"}]})


# ── Connection states ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_endpoint_down_reports_unreachable_with_real_reason(monkeypatch):
    _client(monkeypatch, {
        "GET http://127.0.0.1:11434/v1/models": httpx.ConnectError("All connection attempts failed"),
    })
    result = await _analyst().analyze("سؤال", _STRUCT)
    assert result["state"] == "unavailable"
    assert result["reason"] == "ENDPOINT_UNREACHABLE"
    assert result["answer"] is None
    assert "11434" in result["endpoint"] or "127.0.0.1" in result["endpoint"]
    assert "All connection attempts failed" in result["error"]
    # No canned prose may appear anywhere in the envelope.
    assert "summary_ar" not in json.dumps(result, ensure_ascii=False)


@pytest.mark.asyncio
async def test_timeout_is_distinguished_from_down(monkeypatch):
    _client(monkeypatch, {
        "GET http://127.0.0.1:11434/v1/models": httpx.ConnectTimeout("timed out"),
    })
    result = await _analyst().analyze("سؤال", _STRUCT)
    assert result["state"] == "unavailable"
    assert result["reason"] == "LLM_TIMEOUT"
    assert result["answer"] is None


@pytest.mark.asyncio
async def test_model_not_installed_lists_available_models(monkeypatch):
    _client(monkeypatch, {
        "GET http://127.0.0.1:11434/v1/models": _FakeResponse(200, {"data": [{"id": "tiny"}]}),
    })
    result = await _analyst().analyze("سؤال", _STRUCT)
    assert result["state"] == "unavailable"
    assert result["reason"] == "MODEL_NOT_INSTALLED"
    assert result["model_name"] == result["model_name"].strip()
    assert "tiny" in result["available_models"]
    assert result["answer"] is None


@pytest.mark.asyncio
async def test_invalid_response_is_distinguished(monkeypatch):
    _client(monkeypatch, {
        "GET http://127.0.0.1:11434/v1/models": _MODELS_OK,
        "POST http://127.0.0.1:11434/v1/chat/completions": _FakeResponse(
            200, {"choices": [{"message": {"content": "not json at all"}}]}
        ),
    })
    result = await _analyst().analyze("سؤال", _STRUCT)
    assert result["state"] == "unavailable"
    assert result["reason"] == "INVALID_RESPONSE"
    assert result["schema_valid"] is False
    assert result["answer"] is None


@pytest.mark.asyncio
async def test_http_error_surfaces_status(monkeypatch):
    _client(monkeypatch, {
        "GET http://127.0.0.1:11434/v1/models": _MODELS_OK,
        "POST http://127.0.0.1:11434/v1/chat/completions": _FakeResponse(500, {}),
    })
    result = await _analyst().analyze("سؤال", _STRUCT)
    assert result["state"] == "unavailable"
    assert result["reason"] == "HTTP_500"


# ── Success path (mocked) ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_single_question_success_returns_model_and_evidence_ids(monkeypatch):
    _client(monkeypatch, {
        "GET http://127.0.0.1:11434/v1/models": _MODELS_OK,
        "POST http://127.0.0.1:11434/v1/chat/completions": _chat(_VALID_ANSWER),
    })
    result = await _analyst().analyze("لماذا؟", _STRUCT)
    assert result["state"] == "ready"
    assert result["schema_valid"] is True
    assert result["answer"]["sources"] == ["src_alpha"]
    assert result["model_name"]
    assert result["endpoint"]
    assert result["evidence_ids"] == {"sources": ["src_alpha"], "claims": ["claim_beta"]}
    assert isinstance(result["latency_ms"], (int, float))


@pytest.mark.asyncio
async def test_analyze_never_returns_score_or_confidence_mutation_fields(monkeypatch):
    """Uncalibrated confidence/conflict stays unadopted: the analyst envelope
    carries explanation fields only — no score/weights the pipeline could
    auto-adopt into a No-Trade gate."""
    _client(monkeypatch, {
        "GET http://127.0.0.1:11434/v1/models": _MODELS_OK,
        "POST http://127.0.0.1:11434/v1/chat/completions": _chat(_VALID_ANSWER),
    })
    result = await _analyst().analyze("لماذا؟", _STRUCT)
    banned = {"score", "confidence", "weights", "passes", "no_trade", "decision"}
    assert banned.isdisjoint(result.keys())


# ── Hallucination prevention ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invented_source_id_is_rejected(monkeypatch):
    bad = dict(_VALID_ANSWER, sources=["SRC_INVENTED"])
    _client(monkeypatch, {
        "GET http://127.0.0.1:11434/v1/models": _MODELS_OK,
        "POST http://127.0.0.1:11434/v1/chat/completions": _chat(bad),
    })
    result = await _analyst().analyze("سؤال", _STRUCT)
    assert result["state"] == "rejected"
    assert result["answer"] is None
    assert "UNKNOWN_SOURCE:SRC_INVENTED" in result["hallucination_flags"]


@pytest.mark.asyncio
async def test_missing_data_plus_invented_claim_is_rejected_not_invented(monkeypatch):
    """No sources/claims in the structured input and the model invents one:
    the guard must reject, not narrate."""
    empty_struct = {"asset": "XAUUSD", "source_health": [], "knowledge_claims": [], "ticker": []}
    bad = dict(_VALID_ANSWER, claims_used=["claim_from_air"], sources=[])
    _client(monkeypatch, {
        "GET http://127.0.0.1:11434/v1/models": _MODELS_OK,
        "POST http://127.0.0.1:11434/v1/chat/completions": _chat(bad),
    })
    result = await _analyst().analyze("سؤال", empty_struct)
    assert result["state"] == "rejected"
    assert result["answer"] is None
    assert "UNKNOWN_CLAIM:claim_from_air" in result["hallucination_flags"]


@pytest.mark.asyncio
async def test_missing_data_with_endpoint_down_stays_unavailable(monkeypatch):
    empty_struct = {"asset": "XAUUSD", "source_health": [], "knowledge_claims": []}
    _client(monkeypatch, {
        "GET http://127.0.0.1:11434/v1/models": httpx.ConnectError("refused"),
    })
    result = await _analyst().analyze("سؤال", empty_struct)
    assert result["state"] == "unavailable"
    assert result["answer"] is None


@pytest.mark.asyncio
async def test_optional_us10y_absence_does_not_block_analysis(monkeypatch):
    """US10Y optional/not-selected must not block the analyst context."""
    struct = dict(_STRUCT, cross_asset={"US10Y": {"state": "not_selected"}})
    _client(monkeypatch, {
        "GET http://127.0.0.1:11434/v1/models": _MODELS_OK,
        "POST http://127.0.0.1:11434/v1/chat/completions": _chat(_VALID_ANSWER),
    })
    result = await _analyst().analyze("سؤال", struct)
    assert result["state"] == "ready"
    assert result["answer"]["sources"] == ["src_alpha"]


# ── Intelligence routes: honesty envelopes ──────────────────────────────────


@pytest.mark.asyncio
async def test_quality_route_empty_store_is_unknown_not_zero(monkeypatch):
    class EmptyRedis:
        async def get(self, _key):
            return None

    async def redis():
        return EmptyRedis()

    monkeypatch.setattr(intelligence, "_get_redis", redis)
    result = await intelligence.get_signal_quality()
    assert result["available"] is False
    assert result["score"] is None
    assert result["passes"] is None
    assert result["threshold"] is None
    assert result["reason"] == "not_computed"


@pytest.mark.asyncio
async def test_quality_route_passthrough_keeps_real_payload(monkeypatch):
    payload = {
        "score": 72, "max_score": 100, "threshold": 60, "passes": True,
        "direction": "BUY", "regime": "trend", "session": "london",
        "computed_at": "2026-10-21T08:00:00Z", "breakdown": {"spread": {"ok": True, "pts": 12, "detail": "ok"}},
    }

    class Store:
        async def get(self, key):
            return json.dumps(payload) if key == "nexus:signal:quality:last" else None

    async def redis():
        return Store()

    monkeypatch.setattr(intelligence, "_get_redis", redis)
    result = await intelligence.get_signal_quality()
    assert result["score"] == 72
    assert result["passes"] is True
    assert result["available"] is True


@pytest.mark.asyncio
async def test_correlation_route_empty_store_is_unavailable_not_zero_matrix(monkeypatch):
    class EmptyRedis:
        async def get(self, _key):
            return None

    async def redis():
        return EmptyRedis()

    monkeypatch.setattr(intelligence, "_get_redis", redis)
    result = await intelligence.get_correlation()
    assert result["available"] is False
    assert result["reason"] == "no_snapshot"
    assert result["windows"] == {}
    assert result["lag_signals"] == []
    assert result["updated_at"] is None
    # No fabricated correlation numbers hiding in the fallback.
    encoded = json.dumps(result)
    assert "0.0" not in encoded and "0," not in encoded


@pytest.mark.asyncio
async def test_correlation_route_passthrough_preserves_windows_and_lag(monkeypatch):
    payload = {
        "assets": ["XAUUSD", "BTCUSD"],
        "matrices": {"7d": {}, "30d": {}},
        "windows": {"20": {"pairs": {"BTCUSD/XAUUSD": {"corr": 0.5, "sample_count": 19}}}},
        "lag_signals": [{"pair": "BTCUSD/XAUUSD", "direction": "X_LEADS", "lag_candles": 3}],
        "divergences": [],
        "basis": "synchronized_returns",
        "disclaimer": "no es causa ni garantía",
        "updated_at": "2026-10-21T09:00:00Z",
    }

    class Store:
        async def get(self, key):
            return json.dumps(payload) if key == "nexus:correlation:matrix" else None

    async def redis():
        return Store()

    monkeypatch.setattr(intelligence, "_get_redis", redis)
    result = await intelligence.get_correlation()
    assert result["available"] is True
    assert result["windows"]["20"]["pairs"]["BTCUSD/XAUUSD"]["corr"] == 0.5
    assert result["lag_signals"][0]["lag_candles"] == 3
    assert result["basis"] == "synchronized_returns"
    assert "no es causa ni garantía" in result["disclaimer"]
