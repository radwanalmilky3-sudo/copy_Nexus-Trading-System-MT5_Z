"""
Nexus Agents — Abstract base class for all trading agents.

Provides:
  - Local LLM instantiation via Ollama/OpenAI-compatible endpoint
  - Prompt loading from YAML files
  - Message publishing to Redis Streams
  - Structured reasoning logs
  - Error handling wrapper
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
import yaml
from langchain_core.prompts import ChatPromptTemplate

from shared.constants import AGENT_COLORS, AGENT_NAMES, AgentID, RedisStream
from shared.events import AgentAnalysisEvent
from shared.models import AgentMessage
from shared.redis_client import RedisClient

from ..state import AgentState

logger = structlog.get_logger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

AGENT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "agents.yaml"


def _load_agent_configs() -> dict[str, Any]:
    if AGENT_CONFIG_PATH.exists():
        with open(AGENT_CONFIG_PATH) as f:
            return yaml.safe_load(f).get("agents", {})
    return {}


_AGENT_CONFIGS = _load_agent_configs()


class BaseAgent(ABC):
    """Abstract base for every Nexus trading agent (A1-A12)."""

    def __init__(
        self,
        agent_id: str,
        name: str,
        *,
        redis_client: RedisClient | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.name = name
        self.redis = redis_client
        self.config = config or _AGENT_CONFIGS.get(agent_id, {})
        self.color = AGENT_COLORS.get(agent_id, "#FFFFFF")
        self.nickname = self.config.get("nickname", name)
        self._prompt_template: ChatPromptTemplate | None = None

    # ── Abstract ──────────────────────────────────────────────────────────

    @abstractmethod
    async def invoke(self, state: AgentState) -> AgentState:
        """Run the agent logic and return the updated state."""
        ...

    # ── LLM Factory ───────────────────────────────────────────────────────

    def _get_llm(self, *, temperature: float | None = None, max_tokens: int | None = None, fast: bool = False):
        """Return the local Ollama/OpenAI-compatible model for this agent.

        Fail-closed: if the local-only provider is not configured/ready, raise
        instead of silently constructing a client that could fall through to a
        cloud endpoint.
        """
        from shared.llm_factory import make_llm, provider_ready, resolve_provider

        temp = temperature or self.config.get("temperature", 0.3)
        tokens = max_tokens or self.config.get("max_tokens", 800)

        resolve_provider()  # validates the local-only contract
        if not provider_ready():
            raise RuntimeError(
                "local LLM provider is not ready — refusing to build a model client"
            )
        model = self.config.get("model_local")
        return make_llm(temperature=temp, max_tokens=tokens, model=model)

    async def _invoke_with_budget(
        self,
        chain,
        input_dict: dict[str, Any],
        *,
        cycle_id: str | None = None,
    ) -> Any:
        """Invoke a local LangChain chain with budget, cap, circuit and timeout guards.

        Guards (all fail closed — they return None rather than calling out):
          - daily token budget (Redis-backed)
          - per-cycle LLM call cap (in-process)
          - provider circuit breaker (in-process, opens after N failures)
          - bounded sequential retry with jittered backoff + hard timeout
        """
        import asyncio

        from ..brain_budget import (
            backoff_delay,
            budget_status,
            max_attempts,
            note_provider_failure,
            note_provider_success,
            provider_circuit_open,
            record_usage,
            reserve_llm_call,
        )

        cycle_key = str(cycle_id or "")

        if provider_circuit_open():
            logger.warning(
                "brain_budget.circuit_open_skip agent=%s", self.agent_id,
            )
            return None

        redis = self.redis
        if redis is not None:
            try:
                status = await budget_status(redis.r)
            except Exception:
                status = {"allowed": True}
            if not status.get("allowed", True):
                logger.warning(
                    "brain_budget.exhausted agent=%s tokens=%d limit=%d",
                    self.agent_id, status.get("total_tokens", 0), status.get("daily_limit_tokens", 0),
                )
                return None

        if not await reserve_llm_call(cycle_key):
            return None

        timeout_sec = max(5, int(os.getenv("NEXUS_LOCAL_LLM_TIMEOUT_SEC", "120")))
        attempts = max_attempts()
        last_exc: Exception | None = None
        result = None
        for attempt in range(1, attempts + 1):
            try:
                result = await asyncio.wait_for(chain.ainvoke(input_dict), timeout=timeout_sec)
                note_provider_success()
                break
            except Exception as exc:
                last_exc = exc
                note_provider_failure(str(exc))
                if attempt < attempts:
                    await asyncio.sleep(backoff_delay(attempt))

        if result is None:
            if last_exc is not None:
                logger.warning(
                    "brain_budget.llm_call_failed agent=%s attempts=%d error=%s",
                    self.agent_id, attempts, str(last_exc)[:200],
                )
                raise last_exc
            return None

        # Record usage from response metadata (best-effort)
        if redis is not None:
            try:
                usage_meta = getattr(result, "response_metadata", {}) or {}
                token_usage = usage_meta.get("token_usage") or {}
                input_t = int(token_usage.get("prompt_tokens", 0) or 0)
                output_t = int(token_usage.get("completion_tokens", 0) or 0)
                if input_t == 0 and output_t == 0:
                    # Fallback: rough character-based estimate
                    content = getattr(result, "content", "") or ""
                    input_est = len(str(input_dict.get("input", ""))) // 4
                    output_est = len(content) // 4
                    await record_usage(redis.r, input_est, output_est)
                else:
                    await record_usage(redis.r, input_t, output_t)
            except Exception:
                pass

        return result

    # ── Prompt Loading ────────────────────────────────────────────────────

    def _load_prompt(self, prompt_name: str | None = None) -> ChatPromptTemplate:
        """Load a system prompt from the YAML prompts directory."""
        if self._prompt_template is not None:
            return self._prompt_template

        fname = prompt_name or self.name.lower().replace(" ", "_")
        yaml_path = PROMPTS_DIR / f"{fname}.yaml"

        if yaml_path.exists():
            with open(yaml_path) as f:
                data = yaml.safe_load(f)
            system_prompt = data.get("system_prompt", "")
        else:
            system_prompt = (
                f"You are {self.nickname}, the {self.name} agent in the Nexus Trader system. "
                f"Role: {self.config.get('role', 'Analyze and provide trading insights.')}"
            )

        self._prompt_template = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{input}"),
        ])
        return self._prompt_template

    # ── Publishing ────────────────────────────────────────────────────────

    async def _publish_message(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
        *,
        state: AgentState | None = None,
    ) -> None:
        """Publish an AgentMessage to Redis for dashboard consumption."""
        if not self.redis:
            return

        msg = AgentMessage(
            agent_id=self.agent_id,
            agent_name=self.name,
            agent_color=self.color,
            message_type="analysis",
            content=content,
            metadata=metadata or {},
        )

        event = AgentAnalysisEvent(
            source=f"agent.{self.agent_id}",
            correlation_id=state.get("cycle_id", "") if state else "",
            agent_id=self.agent_id,
            agent_name=self.name,
            symbol=state.get("symbol", "") if state else "",
            analysis=content,
            confidence=0.0,
            metadata=msg.model_dump(),
        )
        try:
            await self.redis.publish_event(RedisStream.AGENT_ANALYSIS, event)
        except Exception:
            await logger.awarning("agent.publish_failed", agent=self.agent_id)

    # ── Logging ───────────────────────────────────────────────────────────

    async def _log_reasoning(self, reasoning: str, *, state: AgentState | None = None) -> None:
        """Write structured reasoning to the log."""
        await logger.ainfo(
            "agent.reasoning",
            agent_id=self.agent_id,
            agent_name=self.name,
            cycle_id=state.get("cycle_id", "") if state else "",
            symbol=state.get("symbol", "") if state else "",
            reasoning=reasoning[:500],
        )

    # ── Error Wrapper ─────────────────────────────────────────────────────

    async def safe_invoke(self, state: AgentState) -> AgentState:
        """Invoke with error handling — failures are logged and recorded in state."""
        try:
            return await self.invoke(state)
        except Exception as exc:
            error_msg = f"[{self.agent_id}:{self.name}] {exc}"
            state["errors"].append(error_msg)
            state["messages"].append({
                "agent_id": self.agent_id,
                "type": "error",
                "content": error_msg,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            await logger.aexception(
                "agent.invoke_error",
                agent_id=self.agent_id,
                agent_name=self.name,
            )
            return state
