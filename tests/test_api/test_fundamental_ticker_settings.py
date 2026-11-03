"""Task 5: news-ticker settings priority — personal > general > default."""
from __future__ import annotations

import pytest

from services.nexus_api.routers import fundamental


@pytest.fixture(autouse=True)
def _no_external_network(monkeypatch):
    """No test in this file may reach the real internet (TDD rule)."""
    import socket

    def _blocked(sock, address=None, *_a, **_k):
        host = address[0] if isinstance(address, tuple) and address else str(address)
        # asyncio's own loopback self-pipe must keep working; only the
        # internet is off-limits for these tests.
        if str(host) in {"127.0.0.1", "::1", "localhost"}:
            return _orig_connect(sock, address, *_a, **_k)
        raise RuntimeError(f"external network access is blocked in Task 5 tests: {host!r}")

    _orig_connect = socket.socket.connect
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


class _Redis:
    def __init__(self, store: dict | None = None) -> None:
        self.store = store if store is not None else {}

    async def cache_get(self, key: str, *, prefix: bool = True):
        return self.store.get(key)

    async def cache_set(self, key: str, value, *, ttl_sec: int = 60, prefix: bool = True):
        self.store[key] = value


class _Db:
    def __init__(self, rows):
        self.rows = rows

    async def query(self, table, filters=None):
        if table == "notification_preferences":
            return self.rows
        return []


@pytest.mark.asyncio
async def test_personal_settings_win_over_general_and_defaults():
    redis = _Redis({"news:ticker:settings": {"speed": "fast", "minimum_severity": "high", "enabled": True}})
    db = _Db([{
        "user_id": "u1",
        "ticker_enabled": False,
        "minimum_severity": "critical",
        "assets_json": '["XAUUSD"]',
        "domains_json": '["news"]',
        "tts_enabled": False,
    }])

    settings = await fundamental.ticker_settings("u1", None, redis, db)

    assert settings["enabled"] is False          # personal wins over general/default
    assert settings["minimum_severity"] == "critical"
    assert settings["speed"] == "fast"           # general wins over default
    assert settings["assets"] == ["XAUUSD"]
    assert settings["audio_enabled"] is False


@pytest.mark.asyncio
async def test_general_settings_win_over_defaults_when_no_personal_row():
    redis = _Redis({"news:ticker:settings": {"speed": "slow", "maximum_severity_hint": "x", "critical_audio": False}})
    db = _Db([])

    settings = await fundamental.ticker_settings("u1", None, redis, db)

    assert settings["speed"] == "slow"
    assert settings["critical_audio"] is False
    assert settings["enabled"] is True           # default
    assert settings["position"] == "top"         # default


@pytest.mark.asyncio
async def test_unset_personal_columns_fall_back_to_general_not_silently_to_no():
    redis = _Redis({"news:ticker:settings": {"enabled": True, "source_outage_alerts": False, "show_breaking": True}})
    db = _Db([{
        "user_id": "u1",
        "ticker_enabled": None,
        "show_source_outage": None,
        "show_breaking": None,
        "assets_json": None,
        "minimum_severity": None,
    }])

    settings = await fundamental.ticker_settings("u1", None, redis, db)

    # NULL/absent personal values must not silently override the general config.
    assert settings["enabled"] is True
    assert settings["source_outage_alerts"] is False
    assert settings["show_breaking"] is True
    assert settings["assets"] == fundamental.DEFAULT_TICKER_SETTINGS["assets"]
    assert settings["minimum_severity"] == "medium"


@pytest.mark.asyncio
async def test_ticker_endpoint_uses_same_priority_for_active_items():
    redis = _Redis({
        "news:ticker:active": [{"ticker_item_id": "t1", "severity": "high"}],
        "news:ticker:settings": {"speed": "fast"},
    })
    db = _Db([{"user_id": "u1", "ticker_enabled": False}])

    payload = await fundamental.ticker("u1", None, redis, db)

    assert payload["state"] == "ready"
    assert payload["items"] == [{"ticker_item_id": "t1", "severity": "high"}]
    assert payload["settings"]["enabled"] is False
    assert payload["settings"]["speed"] == "fast"
    assert payload["user_id"] == "u1"
