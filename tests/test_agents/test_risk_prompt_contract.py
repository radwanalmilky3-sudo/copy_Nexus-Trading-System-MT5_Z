"""Risk-agent prompt must not present stale limits as runtime policy."""
from pathlib import Path

import yaml


def test_risk_prompt_uses_runtime_context_and_defers_to_central_risk_service():
    prompt_path = (
        Path(__file__).resolve().parents[2]
        / "services"
        / "nexus_agents"
        / "prompts"
        / "risk_manager.yaml"
    )
    prompt = yaml.safe_load(prompt_path.read_text(encoding="utf-8"))["system_prompt"]

    stale_limits = (
        "Max daily loss: 5%",
        "Max weekly drawdown: 8%",
        "Max simultaneous positions: 3",
        "Max correlation between positions: 0.7",
        "Max spread: 2x rolling average",
        "5 consecutive losses",
    )

    assert not any(limit in prompt for limit in stale_limits)
    assert "Use only the risk limits and measurements supplied in the review context" in prompt
    assert "The central nexus-risk service is the authority for the final decision" in prompt
