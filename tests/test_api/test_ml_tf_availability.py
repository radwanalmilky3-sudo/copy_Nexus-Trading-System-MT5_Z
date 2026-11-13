"""TF availability fallback — the autonomous pipeline must not starve.

Regression: the dynamic selector picked M5 (scalping rules) while the data
pipeline only publishes M15 features, so every autonomous cycle skipped
("no features for selected timeframe") and no signal ever reached the
agents. _freshest_feature_tf is the availability probe the cycle now uses.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from services.nexus_ml.traders_api import _freshest_feature_tf


class _FakeRedis:
    def __init__(self, present: set[str]) -> None:
        self.present = present

    async def get(self, key: str):
        return b"{}" if key in self.present else None


@pytest.mark.asyncio
async def test_prefers_the_requested_tf_when_it_has_features() -> None:
    with patch(
        "services.nexus_ml.traders_api._get_redis",
        AsyncMock(return_value=_FakeRedis({"nexus:features:XAUUSD:M5"})),
    ):
        assert await _freshest_feature_tf("XAUUSD", preferred="M5") == "M5"


@pytest.mark.asyncio
async def test_falls_back_to_the_tf_that_actually_has_features() -> None:
    # Selector wants M5; only M15 is published (the live regression).
    with patch(
        "services.nexus_ml.traders_api._get_redis",
        AsyncMock(return_value=_FakeRedis({"nexus:features:XAUUSD:M15"})),
    ):
        assert await _freshest_feature_tf("XAUUSD", preferred="M5") == "M15"


@pytest.mark.asyncio
async def test_returns_none_when_no_tf_has_features() -> None:
    with patch(
        "services.nexus_ml.traders_api._get_redis",
        AsyncMock(return_value=_FakeRedis(set())),
    ):
        assert await _freshest_feature_tf("XAUUSD", preferred="M5") is None
