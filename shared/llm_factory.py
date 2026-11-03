"""Nexus local-only LLM factory.

All GenAI agents are forced through a local OpenAI-compatible endpoint (Ollama
by default). Cloud providers are intentionally unsupported in this build.
"""
from __future__ import annotations

import os
from typing import Any

DEFAULT_PROVIDER = "local"
SUPPORTED_PROVIDERS = ("local",)


def resolve_provider() -> str:
    return "local"


def provider_model(provider: str | None = None) -> str:
    return (
        os.getenv("NEXUS_LLM_MODEL", "").strip()
        or os.getenv("NEXUS_LOCAL_MODEL", "llama3.3:70b").strip()
        or "llama3.3:70b"
    )


def local_base_url() -> str:
    return os.getenv("NEXUS_LOCAL_LLM_URL", "http://127.0.0.1:11434/v1").rstrip("/")


def make_llm(
    *,
    temperature: float = 0.3,
    max_tokens: int = 800,
    model: str | None = None,
    request_timeout: int = 30,
):
    from langchain_openai import ChatOpenAI

    global_override = os.getenv("NEXUS_LLM_MODEL", "").strip()
    return ChatOpenAI(
        base_url=local_base_url(),
        api_key="local-ollama",
        model=global_override or model or provider_model("local"),
        temperature=temperature,
        max_tokens=max_tokens,
        request_timeout=request_timeout,
    )


def provider_ready(provider: str | None = None) -> bool:
    """Synchronous config-level readiness only; use ``local_health`` for proof."""
    return bool(local_base_url() and provider_model("local"))


def _model_identity(name: str) -> tuple[str, str, str, str]:
    """Expand Ollama's default registry, namespace and tag without losing tags.

    A colon in a registry port is not a model tag. Ollama compares name
    components case-insensitively; only an omitted tag aliases ``latest``.
    """
    path, separator, model = name.casefold().rpartition("/")
    model, tag_separator, tag = model.partition(":")
    if not tag_separator:
        tag = "latest"
    if not separator:
        host, namespace = "registry.ollama.ai", "library"
    else:
        host, host_separator, namespace = path.rpartition("/")
        if not host_separator:
            host, namespace = "registry.ollama.ai", path
    return host, namespace, model, tag


async def local_health(*, timeout: float = 4.0) -> dict[str, Any]:
    """Verify endpoint reachability and model availability without cloud fallbacks."""
    import time
    import httpx

    base = local_base_url()
    required = provider_model("local")
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{base}/models")
        latency = round((time.perf_counter() - started) * 1000.0, 2)
        resp.raise_for_status()
        payload = resp.json()
        raw_models = payload.get("data", payload.get("models", [])) if isinstance(payload, dict) else []
        names: list[str] = []
        for item in raw_models if isinstance(raw_models, list) else []:
            if isinstance(item, dict):
                names.append(str(item.get("id") or item.get("name") or ""))
            elif item:
                names.append(str(item))
        names = [n for n in names if n]
        required_identity = _model_identity(required)
        model_ok = any(_model_identity(n) == required_identity for n in names)
        return {
            "provider": "local",
            "status": "healthy" if model_ok else "degraded",
            "endpoint": base,
            "required_model": required,
            "model_available": model_ok,
            "models": names,
            "latency_ms": latency,
            "error": "" if model_ok else f"required local model not found: {required}",
        }
    except Exception as exc:
        return {
            "provider": "local",
            "status": "offline",
            "endpoint": base,
            "required_model": required,
            "model_available": False,
            "models": [],
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 2),
            "error": str(exc),
        }
