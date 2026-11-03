"""Local model readiness contracts; all HTTP is handled in memory."""
import asyncio

import httpx
import pytest

from shared.llm_factory import local_health


@pytest.mark.parametrize("required,available,expected", [
    ("qwen2.5:3b", "qwen2.5:3b", True),
    ("qwen2.5:3b", "qwen2.5:32b", False),
    ("qwen2.5:32b", "qwen2.5:3b", False),
    ("qwen2.5:3b", "qwen2.5:latest", False),
    ("qwen2.5", "qwen2.5:3b", False),
    ("qwen2.5:3b", "qwen2.5", False),
    ("qwen2.5", "qwen2.5:latest", True),
    ("qwen2.5:latest", "qwen2.5", True),
    ("qwen2.5:3b", "library/qwen2.5:3b", True),
    ("library/qwen2.5:3b", "qwen2.5:3b", True),
    ("registry.ollama.ai/library/qwen2.5:3b", "qwen2.5:3b", True),
    ("qwen2.5", "registry.ollama.ai/library/qwen2.5:latest", True),
    ("QWEN2.5:3B", "qwen2.5:3b", True),
    ("team/qwen2.5:3b", "qwen2.5:3b", False),
    ("qwen2.5:3b", "other.example/library/qwen2.5:3b", False),
    ("registry.example:5000/team/qwen2.5", "registry.example:5000/team/qwen2.5:latest", True),
    ("registry.example:5000/team/qwen2.5:3b", "registry.example:5000/team/qwen2.5:32b", False),
    ("qwen2.5:3b", "mistral:3b", False),
])
@pytest.mark.parametrize("envelope,field", [("data", "id"), ("models", "name")])
def test_local_health_matches_model_identity(monkeypatch, required, available, expected, envelope, field):
    monkeypatch.setenv("NEXUS_LLM_MODEL", required)
    monkeypatch.setenv("NEXUS_LOCAL_LLM_URL", "http://ollama.invalid/v1")
    real_client = httpx.AsyncClient

    def respond(request):
        assert request.method == "GET"
        assert str(request.url) == "http://ollama.invalid/v1/models"
        return httpx.Response(200, json={envelope: [{field: available}]})

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs))

    result = asyncio.run(local_health())

    assert result["model_available"] is expected
    assert result["status"] == ("healthy" if expected else "degraded")
    assert result["required_model"] == required
    assert result["models"] == [available]
    assert bool(result["error"]) is not expected
