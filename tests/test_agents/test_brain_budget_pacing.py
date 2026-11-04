"""D6 acceptance tests — provider-quota spacing + 429-aware retry backoff.

Owner decision (2026-11-05): space out GLM calls instead of raising the
quota. The pacer serializes LLM call *starts* process-wide so the parallel
agent fan-out (A1..A4) cannot burst the provider into the 429 → fail-closed
NO_TRADE cascade documented in API_TEST_REPORT / HANDOFF D6.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from services.nexus_agents import brain_budget


@pytest.fixture(autouse=True)
def _clean_runtime(monkeypatch):
    brain_budget.reset_runtime_state()
    monkeypatch.delenv("NEXUS_LLM_MIN_INTERVAL_SEC", raising=False)
    yield
    brain_budget.reset_runtime_state()


# ── configuration ────────────────────────────────────────────────────────────


def test_min_interval_default_is_one_second():
    assert brain_budget.min_interval_sec() == 1.0


def test_min_interval_env_override_and_clamp(monkeypatch):
    monkeypatch.setenv("NEXUS_LLM_MIN_INTERVAL_SEC", "0.25")
    assert brain_budget.min_interval_sec() == 0.25
    monkeypatch.setenv("NEXUS_LLM_MIN_INTERVAL_SEC", "999")
    assert brain_budget.min_interval_sec() == 60.0  # upper clamp
    monkeypatch.setenv("NEXUS_LLM_MIN_INTERVAL_SEC", "bogus")
    assert brain_budget.min_interval_sec() == 1.0  # safe fallback


# ── classification + backoff ─────────────────────────────────────────────────


def test_rate_limit_error_classification():
    assert brain_budget.is_rate_limit_error("Error code: 429 - too many requests")
    assert brain_budget.is_rate_limit_error("Rate limit reached for model")
    assert brain_budget.is_rate_limit_error("HTTP 429: quota exceeded")
    assert not brain_budget.is_rate_limit_error("Connection refused")
    assert not brain_budget.is_rate_limit_error("timeout after 120s")
    assert not brain_budget.is_rate_limit_error("")


def test_rate_limit_backoff_is_longer_than_plain_backoff():
    plain = brain_budget.backoff_delay(1)
    limited = brain_budget.rate_limit_backoff(1, error="Error code: 429")
    assert limited >= 1.0  # rate-limited waits at least a full second
    # attempt-1 shapes: standard cadence is 2–2.5s, rate-limited is 8–10s
    assert 2.0 <= plain <= 2.5
    assert limited >= 8.0 and limited > plain
    # caps stay bounded so a cycle cannot stall for minutes
    assert brain_budget.rate_limit_backoff(4, error="429") <= 32.0
    # plain failure path falls through to the standard cadence envelope
    assert 2.0 <= brain_budget.rate_limit_backoff(1, error="boom") <= 2.5


# ── pacer behaviour ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pace_noop_when_interval_zero(monkeypatch):
    monkeypatch.setenv("NEXUS_LLM_MIN_INTERVAL_SEC", "0")
    start = time.monotonic()
    for _ in range(5):
        waited = await brain_budget.pace_llm_call()
    assert time.monotonic() - start < 0.05
    assert waited == 0.0


@pytest.mark.asyncio
async def test_pace_serializes_concurrent_starts(monkeypatch):
    monkeypatch.setenv("NEXUS_LLM_MIN_INTERVAL_SEC", "0.05")

    async def _call() -> float:
        return await brain_budget.pace_llm_call()

    start = time.monotonic()
    waited = await asyncio.gather(*[_call() for _ in range(4)])
    elapsed = time.monotonic() - start

    # 4 paced starts at 50ms spacing → total wall time ≥ 3 * 50ms
    assert elapsed >= 0.14, f"starts were not spaced: {elapsed:.3f}s"
    # later callers actually waited; the first caller did not
    assert waited[0] == 0.0
    assert sum(1 for w in waited if w > 0) >= 2


@pytest.mark.asyncio
async def test_pace_returns_quickly_when_calls_already_spaced(monkeypatch):
    # two sequential calls with a real sleep between them → pacer no-ops
    monkeypatch.setenv("NEXUS_LLM_MIN_INTERVAL_SEC", "0.05")
    await brain_budget.pace_llm_call()
    await asyncio.sleep(0.06)
    waited = await brain_budget.pace_llm_call()
    assert waited == 0.0
