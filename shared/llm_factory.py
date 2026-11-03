"""Nexus LLM factory.

Providers
---------
- ``local`` (default): OpenAI-compatible endpoint, Ollama by default. No data
  leaves the machine.
- ``zai``: Z.ai cloud (OpenAI-compatible ``/api/paas/v4``). Enabled ONLY when
  ``NEXUS_LLM_PROVIDER=zai`` AND ``ZAI_API_KEY`` is set. Added on explicit
  owner request (2026-11-04) as a lighter alternative to running a local 70B
  model; every other provider name silently falls back to ``local``.

All construction paths fail closed: an unconfigured provider raises instead of
silently falling through to a different endpoint. Key material is read from
the environment only and is never logged or returned by health checks.
"""
from __future__ import annotations

import os
from typing import Any

DEFAULT_PROVIDER = "local"
SUPPORTED_PROVIDERS = ("local", "zai")

ZAI_DEFAULT_BASE_URL = "https://api.z.ai/api/paas/v4"
ZAI_DEFAULT_MODEL = "glm-4.5-flash"


def resolve_provider() -> str:
    raw = (os.getenv("NEXUS_LLM_PROVIDER") or "").strip().lower()
    return raw if raw in SUPPORTED_PROVIDERS else DEFAULT_PROVIDER


def local_base_url() -> str:
    return os.getenv("NEXUS_LOCAL_LLM_URL", "http://127.0.0.1:11434/v1").rstrip("/")


def zai_base_url() -> str:
    return (os.getenv("ZAI_BASE_URL") or ZAI_DEFAULT_BASE_URL).rstrip("/")


def zai_api_key() -> str:
    return os.getenv("ZAI_API_KEY", "").strip()


def zai_model() -> str:
    return (
        os.getenv("NEXUS_LLM_MODEL", "").strip()
        or os.getenv("ZAI_MODEL", "").strip()
        or ZAI_DEFAULT_MODEL
    )


def provider_model(provider: str | None = None) -> str:
    provider = provider or resolve_provider()
    if provider == "zai":
        return zai_model()
    return (
        os.getenv("NEXUS_LLM_MODEL", "").strip()
        or os.getenv("NEXUS_LOCAL_MODEL", "llama3.3:70b").strip()
        or "llama3.3:70b"
    )


def make_llm(
    *,
    temperature: float = 0.3,
    max_tokens: int = 800,
    model: str | None = None,
    request_timeout: int = 30,
):
    from langchain_openai import ChatOpenAI

    provider = resolve_provider()
    global_override = os.getenv("NEXUS_LLM_MODEL", "").strip()

    if provider == "zai":
        key = zai_api_key()
        if not key:
            raise RuntimeError(
                "ZAI_API_KEY is not set — refusing to build a cloud model client"
            )
        return ChatOpenAI(
            base_url=zai_base_url(),
            api_key=key,
            model=global_override or model or zai_model(),
            temperature=temperature,
            max_tokens=max_tokens,
            request_timeout=request_timeout,
        )

    if provider == "local":
        return ChatOpenAI(
            base_url=local_base_url(),
            api_key="local-ollama",
            model=global_override or model or provider_model("local"),
            temperature=temperature,
            max_tokens=max_tokens,
            request_timeout=request_timeout,
        )

    # Unreachable while resolve_provider() only returns SUPPORTED_PROVIDERS,
    # kept as an explicit fail-closed guard.
    raise RuntimeError(f"unsupported LLM provider: {provider!r}")


def provider_ready(provider: str | None = None) -> bool:
    """Synchronous config-level readiness only; use ``llm_health`` for proof."""
    provider = provider or resolve_provider()
    if provider == "zai":
        return bool(zai_base_url() and zai_api_key() and zai_model())
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


async def zai_health(*, timeout: float = 8.0) -> dict[str, Any]:
    """Probe the Z.ai endpoint with a 1-token completion; never returns the key."""
    import time
    import httpx

    base = zai_base_url()
    key = zai_api_key()
    required = zai_model()
    started = time.perf_counter()
    if not key:
        return {
            "provider": "zai",
            "status": "offline",
            "endpoint": base,
            "required_model": required,
            "model_available": False,
            "latency_ms": 0.0,
            "error": "ZAI_API_KEY is not set",
        }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": required,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                },
            )
        latency = round((time.perf_counter() - started) * 1000.0, 2)
        if resp.status_code == 200:
            return {
                "provider": "zai",
                "status": "healthy",
                "endpoint": base,
                "required_model": required,
                "model_available": True,
                "latency_ms": latency,
                "error": "",
            }
        return {
            "provider": "zai",
            "status": "degraded",
            "endpoint": base,
            "required_model": required,
            "model_available": False,
            "latency_ms": latency,
            "error": f"HTTP {resp.status_code} from Z.ai endpoint",
        }
    except Exception as exc:
        return {
            "provider": "zai",
            "status": "offline",
            "endpoint": base,
            "required_model": required,
            "model_available": False,
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 2),
            "error": str(exc),
        }


async def llm_health(*, timeout: float = 8.0) -> dict[str, Any]:
    """Provider-aware health probe used by the API layer."""
    provider = resolve_provider()
    if provider == "zai":
        return await zai_health(timeout=timeout)
    return await local_health(timeout=timeout)
