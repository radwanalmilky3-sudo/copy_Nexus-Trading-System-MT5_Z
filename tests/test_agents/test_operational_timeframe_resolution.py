"""Operational timeframe selection for agent evaluation inputs."""

from services.nexus_agents.main import _resolve_operational_timeframe


def test_signal_timeframe_is_not_overridden_by_runtime_settings():
    assert _resolve_operational_timeframe(
        "M15",
        env_timeframe="M5",
        dynamic_timeframe="M5",
        cached_timeframe="M5",
    ) == "M15"
