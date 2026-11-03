"""Intermarket analysis must not turn missing VIX data into a fabricated reading."""

import pytest

from services.nexus_agents.market_context import classify_vix


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({}, (None, "unknown")),
        ({"close": None, "last": None}, (None, "unknown")),
        ({"close": "not-a-number"}, (None, "unknown")),
        ({"close": 14.9}, (14.9, "low_vol")),
        ({"close": 20.0}, (20.0, "normal")),
        ({"last": 26.0}, (26.0, "high_vol")),
    ],
)
def test_vix_context_preserves_missing_and_invalid_values(data, expected):
    assert classify_vix(data) == expected


def test_intermarket_prompt_forbids_inventing_unavailable_instrument_values():
    from pathlib import Path
    import yaml

    prompt_path = (
        Path(__file__).resolve().parents[2]
        / "services"
        / "nexus_agents"
        / "prompts"
        / "intermarket.yaml"
    )
    prompt = yaml.safe_load(prompt_path.read_text(encoding="utf-8"))["system_prompt"]
    assert "Do not invent or infer numeric values for unavailable instruments" in prompt
