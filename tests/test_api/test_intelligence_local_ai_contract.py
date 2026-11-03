"""Local-AI availability contracts over REAL loopback sockets (Agent 4).

Unlike tests/test_local_ai_availability.py (which injects a fake httpx client),
these tests speak HTTP to a real ThreadingHTTPServer on 127.0.0.1 — proving the
ENDPOINT_UNREACHABLE / MODEL_NOT_INSTALLED / INVALID_RESPONSE states are reached
through genuine network behavior, not through mock-only plumbing.

Ollama is never started here; the "service down" case uses a genuinely closed
port (real TCP connection refused).
"""
from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

from services.nexus_api.fundamental_local_ai import GroundedLocalAI

MODEL = "qwen2.5:3b"


# ── Real local HTTP server (OpenAI-compatible stub) ───────────────────────────

def _make_server() -> tuple[ThreadingHTTPServer, SimpleNamespace]:
    state = SimpleNamespace(
        models=[MODEL],
        chat_status=200,
        chat_content=None,
        chat_raw=None,
        sleep_s=0.0,
    )

    class Handler(BaseHTTPRequestHandler):
        server_version = "NexusLocalAIStub/1.0"

        def log_message(self, *_args):  # silence test output
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if state.sleep_s:
                time.sleep(state.sleep_s)
            if self.path.endswith("/models"):
                body = json.dumps(
                    {"data": [{"id": m} for m in state.models]}
                ).encode()
                self._send(200, body)
            else:
                self._send(404, b"{}")

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0) or 0)
            self.rfile.read(length)
            if self.path.endswith("/chat/completions"):
                if state.sleep_s:
                    time.sleep(state.sleep_s)
                if state.chat_status != 200:
                    self._send(state.chat_status, b'{"error":"stub"}')
                    return
                if state.chat_raw is not None:
                    self._send(200, state.chat_raw, "text/plain")
                    return
                body = json.dumps({
                    "choices": [{"message": {"content": state.chat_content or "{}"}}]
                }).encode()
                self._send(200, body)
            else:
                self._send(404, b"{}")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    return server, state


@pytest.fixture
def llm_server() -> Iterator[tuple[str, SimpleNamespace]]:
    server, state = _make_server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", state
    finally:
        server.shutdown()
        server.server_close()


def _closed_port_url() -> str:
    """Reserve an ephemeral port, then release it → guaranteed refusal."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}/v1"


def _analyst(base_url: str, monkeypatch, timeout_s: str = "5") -> GroundedLocalAI:
    monkeypatch.setenv("NEXUS_LOCAL_LLM_URL", base_url)
    monkeypatch.setenv("NEXUS_LLM_MODEL", MODEL)
    monkeypatch.delenv("NEXUS_LOCAL_MODEL", raising=False)
    monkeypatch.setenv("NEXUS_LOCAL_AI_TIMEOUT_SEC", timeout_s)
    return GroundedLocalAI()


def _structured_input() -> dict[str, Any]:
    return {
        "asset": "XAUUSD",
        "source_health": [{"source_id": "SRC_ALPHA", "health": "ok"}],
        "knowledge_claims": [{"claim_id": "CLM_ALPHA", "statement_ar": "ادعاء مراجَع"}],
        # Provider prose present in input must be excluded, never forwarded.
        "ticker": [{"ticker_item_id": "TICK_ALPHA", "headline_ar": "عنوان مقدم"}],
    }


def _answer_content(
    sources: tuple[str, ...] = ("SRC_ALPHA",),
    claims: tuple[str, ...] = ("CLM_ALPHA",),
) -> str:
    # Digit-free on purpose: the grounding audit rejects numeric facts in prose.
    return json.dumps({
        "summary_ar": "ملخص الحالة وفق البيانات المقدمة فقط",
        "what_happened": "عُرضت البيانات المتاحة دون استنتاج جديد",
        "why_it_matters": "يساعد على فهم السياق دون أي توصية تنفيذية",
        "transmission": [],
        "asset_comparison": [],
        "confirmations": [],
        "contradictions": [],
        "missing_evidence": ["لا توجد إشارة مؤكدة لبيانات كافية"],
        "sources": list(sources),
        "claims_used": list(claims),
        "data_quality_note": "البيانات محدودة النطاق",
        "uncertainty_note": "الحالة غير مؤكدة",
    }, ensure_ascii=False)


# ── Real connection-refused: the Ollama-disabled state ────────────────────────

@pytest.mark.asyncio
async def test_real_closed_port_surfaces_endpoint_unreachable_not_canned_answer(monkeypatch):
    analyst = _analyst(_closed_port_url(), monkeypatch)

    result = await analyst.analyze("لماذا الحالة هكذا؟", _structured_input())

    assert result["state"] == "unavailable"
    assert result["reason"] == "ENDPOINT_UNREACHABLE"
    assert "ConnectError" in result["error"]
    assert result["answer"] is None
    assert result["endpoint"].startswith("http://127.0.0.1:")
    # Unavailable ⇒ no fabricated evidence, no score/confidence fields.
    assert result["evidence_ids"] == {"sources": [], "claims": []}
    assert "score" not in result and "confidence" not in result


@pytest.mark.asyncio
async def test_real_timeout_is_named_timeout_not_unreachable(llm_server, monkeypatch):
    base_url, state = llm_server
    state.sleep_s = 3.0
    analyst = _analyst(base_url, monkeypatch, timeout_s="1")

    result = await analyst.analyze("سؤال", _structured_input())

    assert result["state"] == "unavailable"
    assert result["reason"] == "LLM_TIMEOUT"
    assert result["answer"] is None


# ── Real HTTP probe: model not installed ──────────────────────────────────────

@pytest.mark.asyncio
async def test_real_http_model_absent_is_model_not_installed_with_model_list(llm_server, monkeypatch):
    base_url, state = llm_server
    state.models = ["tiny-stub-model", "other-stub"]
    analyst = _analyst(base_url, monkeypatch)

    result = await analyst.analyze("سؤال", _structured_input())

    assert result["state"] == "unavailable"
    assert result["reason"] == "MODEL_NOT_INSTALLED"
    assert set(result["available_models"]) == {"tiny-stub-model", "other-stub"}
    assert result["answer"] is None
    assert result["endpoint"] == base_url


# ── Real HTTP happy path: evidence_ids echo grounded IDs ─────────────────────

@pytest.mark.asyncio
async def test_real_http_ready_answer_carries_evidence_ids_and_endpoint(llm_server, monkeypatch):
    base_url, state = llm_server
    state.chat_content = _answer_content()
    analyst = _analyst(base_url, monkeypatch)

    result = await analyst.analyze("لماذا؟", _structured_input())

    assert result["state"] == "ready"
    assert result["schema_valid"] is True
    assert result["evidence_ids"] == {"sources": ["SRC_ALPHA"], "claims": ["CLM_ALPHA"]}
    assert result["endpoint"] == base_url
    assert result["latency_ms"] >= 0
    # Model output must match the echoed evidence IDs exactly (claims_used→claims).
    assert result["answer"]["sources"] == ["SRC_ALPHA"]
    # Provider prose excluded: no headline forwarded to the model context.
    assert "عنوان مقدم" not in json.dumps(result["structured_input"]["ticker"])


@pytest.mark.asyncio
async def test_real_http_invented_source_is_rejected_with_flag(llm_server, monkeypatch):
    base_url, state = llm_server
    state.chat_content = _answer_content(sources=("SRC_INVENTED",))
    analyst = _analyst(base_url, monkeypatch)

    result = await analyst.analyze("لماذا؟", _structured_input())

    assert result["state"] == "rejected"
    assert result["reason"] == "LOCAL_AI_GROUNDING_GUARD"
    assert "UNKNOWN_SOURCE:SRC_INVENTED" in result["hallucination_flags"]
    assert result["answer"] is None


@pytest.mark.asyncio
async def test_real_http_non_json_content_is_invalid_response(llm_server, monkeypatch):
    base_url, state = llm_server
    state.chat_content = "lorem ipsum — not json at all"
    analyst = _analyst(base_url, monkeypatch)

    result = await analyst.analyze("لماذا؟", _structured_input())

    assert result["state"] == "unavailable"
    assert result["reason"] == "INVALID_RESPONSE"
    assert result["answer"] is None


@pytest.mark.asyncio
async def test_real_http_500_is_named_with_status(llm_server, monkeypatch):
    base_url, state = llm_server
    state.chat_status = 500
    analyst = _analyst(base_url, monkeypatch)

    result = await analyst.analyze("لماذا؟", _structured_input())

    assert result["state"] == "unavailable"
    assert result["reason"] == "HTTP_500"
    assert result["answer"] is None
