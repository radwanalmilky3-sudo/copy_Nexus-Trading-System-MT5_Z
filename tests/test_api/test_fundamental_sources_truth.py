"""Task 5 truth-contract regression: source manager derived status fields."""
from __future__ import annotations

from unittest.mock import AsyncMock

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


class _Store:
    def __init__(self, secret: str | None = None):
        self._secret = secret

    def get_secret(self, source_id, secret_env=None):
        return self._secret


def _source(**overrides):
    base = {
        "source_id": "custom_feed",
        "enabled": True,
        "endpoint": "https://feed.example/data",
        "auth_mode": "none",
        "secret_env": None,
        "secret_optional": True,
        "transport": "json",
        "analysis_mapping": "health_only",
        "analysis_ready": False,
        "freshness_limit_sec": 3600,
        "name_ar": "مصدر مخصص",
    }
    base.update(overrides)
    return base


# ── Derived contract fields ──────────────────────────────────────────────────

def test_health_only_source_is_never_analysis_eligible():
    source = _source(analysis_mapping="health_only", analysis_ready=True)

    truth = fundamental._source_truth_fields(source, None, None, store=_Store())

    assert truth["analysis_eligible"] is False
    assert "health_only" in truth["analysis_reason_ar"] or "الصحة" in truth["analysis_reason_ar"]
    # Stored flag is not silently trusted; the derived contract is explicit.
    assert truth["configuration_status"] == "configured"


def test_missing_required_secret_is_missing_config_with_reason():
    source = _source(auth_mode="query", secret_env="CUSTOM_API_KEY", secret_optional=False)

    truth = fundamental._source_truth_fields(source, None, None, store=_Store(secret=None))

    assert truth["configuration_status"] == "missing_config"
    assert "CUSTOM_API_KEY" in truth["configuration_reason_ar"]
    assert truth["analysis_eligible"] is False


def test_disabled_source_reports_disabled_and_no_eligibility():
    source = _source(enabled=False)

    truth = fundamental._source_truth_fields(source, None, None, store=_Store())

    assert truth["configuration_status"] == "disabled"
    assert truth["connectivity"] == "disabled"
    assert truth["analysis_eligible"] is False
    assert truth["configuration_reason_ar"]


def test_fresh_runtime_health_drives_connectivity_and_freshness():
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    health = {"health": "healthy", "last_success_at": now}
    source = _source(analysis_mapping="cross_asset")

    truth = fundamental._source_truth_fields(source, health, None, store=_Store())

    assert truth["connectivity"] == "healthy"
    assert truth["last_checked_at"] == now
    assert truth["data_freshness"] == "fresh"
    assert truth["verification_source"] == "runtime_health"
    assert truth["analysis_eligible"] is True


def test_stale_runtime_health_marks_data_freshness_stale():
    from datetime import datetime, timedelta, timezone

    old = (datetime.now(timezone.utc) - timedelta(seconds=10_000)).isoformat()
    health = {"health": "healthy", "last_success_at": old}
    source = _source(analysis_mapping="cross_asset")

    truth = fundamental._source_truth_fields(source, health, None, store=_Store())

    assert truth["data_freshness"] == "stale"
    assert truth["analysis_eligible"] is False
    assert truth["analysis_reason_ar"]


def test_unknown_connectivity_without_any_check():
    truth = fundamental._source_truth_fields(_source(), None, None, store=_Store())

    assert truth["connectivity"] == "unknown"
    assert truth["last_checked_at"] is None
    assert truth["data_freshness"] == "unknown"
    assert truth["verification_source"] == "none"
    assert truth["analysis_eligible"] is False


def test_cached_last_test_is_marked_and_preserves_tested_at():
    last_test = {"ok": True, "state": "healthy", "tested_at": "2026-10-18T22:49:02+00:00"}

    truth = fundamental._source_truth_fields(_source(), None, dict(last_test), store=_Store())

    assert truth["last_test"]["result_origin"] == "cached_last_test"
    assert truth["last_test"]["tested_at"] == "2026-10-18T22:49:02+00:00"
    assert truth["last_checked_at"] == "2026-10-18T22:49:02+00:00"
    assert truth["connectivity"] == "healthy"


# ── Live test endpoint marks current vs cached ───────────────────────────────

@pytest.mark.asyncio
async def test_connection_test_endpoint_marks_result_as_current_test(monkeypatch):
    store = type("S", (), {
        "get_source": lambda self, sid: _source(source_id=sid),
        "get_secret": lambda self, sid, env=None: None,
        "secret_backend": "windows_dpapi_current_user",
        "list_sources": lambda self: [],
        "dir": "/tmp/disposable-source-store",
    })()
    monkeypatch.setattr(fundamental, "_source_manager_store", lambda: store)
    monkeypatch.setattr(fundamental, "_require", AsyncMock(return_value=None))
    monkeypatch.setattr(
        fundamental, "_connection_test",
        AsyncMock(return_value={"ok": True, "state": "healthy", "source_id": "custom_feed"}),
    )
    redis = _Redis()
    db = AsyncMock()

    result = await fundamental.test_managed_source("custom_feed", "user-1", db, redis)

    assert result["result_origin"] == "current_test"
    assert result["ok"] is True
    cached = redis.store["fundamental:sources:last_tests"]["custom_feed"]
    assert cached["result_origin"] == "current_test"


@pytest.mark.asyncio
async def test_manage_sources_attaches_cached_marker_and_contract(monkeypatch):
    store = type("S", (), {
        "list_sources": lambda self: [_source(source_id="custom_feed")],
        "get_source": lambda self, sid: _source(source_id=sid),
        "get_secret": lambda self, sid, env=None: None,
        "secret_backend": "windows_dpapi_current_user",
        "dir": "/tmp/disposable-source-store",
    })()
    monkeypatch.setattr(fundamental, "_source_manager_store", lambda: store)
    monkeypatch.setattr(fundamental, "_require", AsyncMock(return_value=None))
    redis = _Redis({
        "fundamental:sources:last_tests": {
            "custom_feed": {"ok": False, "state": "degraded", "tested_at": "2026-10-18T23:08:32+00:00"},
        },
    })
    db = AsyncMock()

    payload = await fundamental.manage_sources("user-1", db, redis)
    entry = payload["sources"][0]

    assert entry["last_test"]["result_origin"] == "cached_last_test"
    assert entry["configuration_status"] == "configured"
    assert entry["analysis_eligible"] is False
    assert entry["analysis_reason_ar"]
    assert "secret" not in entry  # redaction preserved: no secret material
    assert entry["secret_configured"] is False


# ── Every actually-enabled registry source (no auto-enable, no fabricated ready) ──

def test_every_registry_source_has_truthful_status_and_nothing_gets_enabled():
    """Walk the real 25-source registry with an empty secret store.

    Contract: a source with an unset required key is missing_config, a health_only
    source is never analysis-eligible, and deriving truth never flips `enabled`.
    """
    from services.nexus_news.fundamental.source_registry import SOURCE_BY_ID

    empty_store = _Store(secret=None)
    initially_enabled = {sid: bool(d.enabled) for sid, d in SOURCE_BY_ID.items()}

    for sid, definition in SOURCE_BY_ID.items():
        source = {
            "source_id": sid,
            "enabled": definition.enabled,
            "endpoint": definition.base_endpoint,
            "auth_type": getattr(definition, "auth_type", "none"),
            "auth_mode": getattr(definition, "auth_type", "none"),
            "secret_env": getattr(definition, "api_key_env", None),
            "secret_optional": getattr(definition, "auth_type", "none") == "optional_key",
            "analysis_mapping": "health_only",
            "analysis_ready": False,
            "freshness_limit_sec": definition.freshness_limit_sec,
            "name_ar": definition.name_ar,
        }
        truth = fundamental._source_truth_fields(source, None, None, store=empty_store)

        assert truth["configuration_status"] in {"configured", "missing_config", "disabled"}, sid
        assert truth["analysis_eligible"] is False, sid
        assert truth["analysis_reason_ar"], sid
        if not source["enabled"]:
            # disabled is reported first: an inactive source needs no key to be off.
            assert truth["configuration_status"] == "disabled", sid
        elif source["secret_env"] and not source["secret_optional"]:
            assert truth["configuration_status"] == "missing_config", sid
        # Truth derivation must never mutate the enablement state.
        assert source["enabled"] == initially_enabled[sid], sid

    # No source is enabled by this test run: the registry was only read.
    assert {sid: bool(d.enabled) for sid, d in SOURCE_BY_ID.items()} == initially_enabled
