from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from services.nexus_executor import main as executor_main


@pytest.mark.asyncio
async def test_entry_context_uses_explicit_timeframe_and_never_defaults_to_m5(monkeypatch):
    class Redis:
        def __init__(self):
            self.reads = []
            self.writes = {}
            self.cached_timeframe = "M15"

        async def get(self, key):
            self.reads.append(key)
            return json.dumps({"timeframe": self.cached_timeframe, "features": {"close": 123.0}})

        async def set(self, key, value, **kwargs):
            self.writes[key] = value

    fake = Redis()
    monkeypatch.setattr(executor_main, "redis", SimpleNamespace(r=fake))

    await executor_main._save_entry_ctx("order-1", "XAUUSD", "BUY", 123.0, 122.0, 125.0)
    assert fake.reads == []
    assert fake.writes == {}

    await executor_main._save_entry_ctx(
        "order-2", "XAUUSD", "BUY", 123.0, 122.0, 125.0, timeframe="M15",
    )
    assert fake.reads == ["nexus:features:XAUUSD:M15"]
    saved = json.loads(fake.writes["nexus:trade:entry_ctx:order-2"])
    assert saved["timeframe"] == "M15"

    fake.cached_timeframe = "M15"
    await executor_main._save_entry_ctx(
        "order-3", "XAUUSD", "BUY", 123.0, 122.0, 125.0, timeframe="M5",
    )
    assert "nexus:trade:entry_ctx:order-3" not in fake.writes
