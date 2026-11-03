"""Readiness uses the mocked local probe, never a running model or service."""
import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock

import pytest
from fastapi import Response

from shared import llm_factory


@pytest.fixture
def agents(monkeypatch):
    # These dependencies build trading/research machinery, unrelated to health.
    # Load the real main.py privately so stubs cannot leak to other tests.
    graph = ModuleType("services.nexus_agents.graph")
    graph.build_graph = lambda: None
    research = ModuleType("services.nexus_agents.research")
    research.StrategyResearcher = object
    with monkeypatch.context() as imports:
        imports.setitem(sys.modules, graph.__name__, graph)
        imports.setitem(sys.modules, research.__name__, research)
        name = "services.nexus_agents._readiness_test_main"
        path = Path(__file__).resolve().parents[2] / "services/nexus_agents/main.py"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        imports.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        yield module


@pytest.mark.parametrize("probe,expected", [
    ({"status": "healthy", "model_available": True}, True),
    ({"status": "healthy", "model_available": False}, False),
    ({"status": "healthy"}, False),
    ({"status": "degraded", "model_available": False}, False),
    ({"status": "degraded", "model_available": True}, False),
    ({"status": "offline", "model_available": True}, False),
    ({"model_available": True}, False),
    ({"status": "unexpected", "model_available": True}, False),
])
def test_local_probe_requires_healthy_and_available_model(agents, monkeypatch, probe, expected):
    monkeypatch.setattr(llm_factory, "local_health", AsyncMock(return_value=probe))
    monkeypatch.setattr(llm_factory, "local_base_url", lambda: "http://ollama.invalid/v1")
    monkeypatch.setattr(llm_factory, "provider_model", lambda _: "qwen2.5:3b")
    monkeypatch.setattr(agents, "_llm_health_cache", {"ts": 0.0, "result": None})
    monkeypatch.setattr(agents, "_llm_health_lock", asyncio.Lock())
    monkeypatch.setattr(agents.redis_client, "health_check", AsyncMock(return_value=True))
    monkeypatch.setattr(agents, "verify_internal_service_secret", lambda _: None)
    monkeypatch.setattr(agents, "_cycle_store", {})

    async def check():
        local = await agents._get_llm_health()
        response = Response()
        health = await agents.health(response)
        status = await agents.get_agent_status(x_nexus_internal_secret=None)
        return local, response, health, status

    local, response, health, status = asyncio.run(check())

    assert local["online"] is expected
    assert local["status"] == ("ONLINE" if expected else "OFFLINE")
    assert health.ready is expected
    assert health.llm_online is expected
    assert response.status_code == (200 if expected else 503)
    assert status.ready is expected
    assert status.status == ("READY" if expected else "OFFLINE")
