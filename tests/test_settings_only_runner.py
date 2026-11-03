"""Regression tests for the settings-only runner contract (Task 1).

Contract under test:
- settings mode spawns Redis-checked data/API/dashboard only; never
  executor/risk/agents and never a real MT5 login in child processes;
- readiness means a ready payload, not a bare HTTP 200 port open;
- the data (DuckDB writer) gate runs before the API spawn;
- startup failure shuts down spawned processes (no orphans);
- foreign listeners on busy ports are neither killed nor duplicated;
- the dashboard is tracked by the ProcessManager restart limit;
- run.py never deletes .next when spawning the dashboard;
- the websockets requirement agrees between root and API requirements.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_settings_module():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location(
        "nexus_start_settings_only", ROOT / "scripts" / "start_settings_only.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeManager:
    """Records spawns the way ProcessManager tracks managed processes."""

    def __init__(self, root=None, events: list[str] | None = None):
        self.root = root
        self.events = events if events is not None else []
        self.spawned: list[str] = []
        self.processes: list[SimpleNamespace] = []
        self.shutdown_calls = 0
        self.captured_envs: dict[str, dict | None] = {}

    def spawn_service(self, name, port, color, *, reload=False, log_level="INFO",
                      env_override=None):
        self.events.append(f"spawn:{name}")
        self.spawned.append(name)
        self.captured_envs[name] = env_override
        mp = SimpleNamespace(
            name=name, port=port, healthy=False,
            proc=SimpleNamespace(poll=lambda: None, returncode=None),
        )
        self.processes.append(mp)
        return mp

    def spawn_dashboard(self, color, *, env_override=None):
        self.events.append("spawn:dashboard")
        self.spawned.append("dashboard")
        self.captured_envs["dashboard"] = env_override
        mp = SimpleNamespace(
            name="dashboard", port=3100, healthy=False,
            proc=SimpleNamespace(poll=lambda: None, returncode=None),
        )
        self.processes.append(mp)
        return mp

    def start_streaming(self):
        self.events.append("stream")

    def health_check(self, *, reload=False, log_level="INFO", env_override=None):
        return None

    def shutdown(self):
        self.shutdown_calls += 1
        self.events.append("shutdown")


def _ready_gate(monkeypatch, mod, results_by_name: dict[str, bool], events=None):
    def fake_wait_ready(url, *, name, **_kwargs):
        if events is not None:
            events.append(f"ready:{name}")
        return results_by_name.get(name, True)

    monkeypatch.setattr(mod, "wait_ready", fake_wait_ready)


# --- environment isolation -------------------------------------------------


def test_settings_env_disables_broker_and_trading_credentials():
    mod = _load_settings_module()
    env = mod.build_env(
        {"MT5_LOGIN": "5091125", "MT5_PASSWORD": "real-password",
         "ENABLE_IBKR": "1", "ENABLE_CCXT": "1"}
    )

    assert env["MT5_LOGIN"] == "0"
    assert env["MT5_PASSWORD"] == ""
    assert env["ENABLE_IBKR"] == ""
    assert env["ENABLE_CCXT"] == ""
    assert env["NEXUS_TRADING_MODE"] == "paper"
    assert env.get("NEXUS_MT5_ISOLATED") == "1"


def test_spawned_children_receive_disabled_trading_env(monkeypatch):
    mod = _load_settings_module()
    manager = FakeManager()
    monkeypatch.setattr(mod, "check_prerequisites", lambda env: None)
    monkeypatch.setattr(mod, "listening", lambda port: False)
    _ready_gate(monkeypatch, mod, {})

    mod.run_settings_stack(manager, mod.build_env({}))

    for name in ("nexus-data", "nexus-api"):
        child_env = manager.captured_envs[name]
        assert child_env is not None, name
        assert child_env["MT5_LOGIN"] == "0"
        assert child_env["ENABLE_IBKR"] == ""
        assert child_env["ENABLE_CCXT"] == ""


def test_settings_mode_spawns_only_settings_services(monkeypatch):
    mod = _load_settings_module()
    manager = FakeManager()
    monkeypatch.setattr(mod, "check_prerequisites", lambda env: None)
    monkeypatch.setattr(mod, "listening", lambda port: False)
    _ready_gate(monkeypatch, mod, {})

    mod.run_settings_stack(manager, mod.build_env({}))

    allowed = {"nexus-data", "nexus-api", "dashboard"}
    forbidden = {"nexus-executor", "nexus-risk", "nexus-agents", "nexus-ml",
                 "nexus-news", "nexus-features"}
    assert set(manager.spawned) <= allowed
    assert forbidden.isdisjoint(manager.spawned)


# --- readiness gate ---------------------------------------------------------


def _fake_health(monkeypatch, mod, status: int, payload: bytes):
    monkeypatch.setattr(mod, "_fetch_health", lambda _url: (status, payload))


def test_wait_ready_rejects_http_200_while_payload_not_ready(monkeypatch):
    mod = _load_settings_module()
    _fake_health(monkeypatch, mod, 200, json.dumps(
        {"status": "healthy", "ready": False, "duckdb": True}).encode())

    assert mod.wait_ready(
        "http://127.0.0.1:9001/health", name="nexus-data",
        require_duckdb=True, timeout_s=0.2, interval_s=0.02,
    ) is False


def test_wait_ready_requires_duckdb_writer_for_data(monkeypatch):
    mod = _load_settings_module()
    _fake_health(monkeypatch, mod, 200, json.dumps(
        {"ready": True, "duckdb": False}).encode())

    assert mod.wait_ready(
        "http://127.0.0.1:9001/health", name="nexus-data",
        require_duckdb=True, timeout_s=0.2, interval_s=0.02,
    ) is False


def test_wait_ready_accepts_api_payload_with_string_duckdb(monkeypatch):
    mod = _load_settings_module()
    _fake_health(monkeypatch, mod, 200, json.dumps(
        {"status": "healthy", "ready": True, "duckdb": "connected"}).encode())

    assert mod.wait_ready(
        "http://127.0.0.1:9000/health", name="nexus-api",
        require_duckdb=False, timeout_s=0.2, interval_s=0.02,
    ) is True


def test_wait_ready_rejects_non_json_200(monkeypatch):
    mod = _load_settings_module()
    _fake_health(monkeypatch, mod, 200, b"OK")

    assert mod.wait_ready(
        "http://127.0.0.1:9000/health", name="nexus-api",
        require_duckdb=False, timeout_s=0.2, interval_s=0.02,
    ) is False


# --- startup ordering -------------------------------------------------------


def test_api_spawn_waits_for_data_ready_gate(monkeypatch):
    mod = _load_settings_module()
    events: list[str] = []
    manager = FakeManager(events=events)
    monkeypatch.setattr(mod, "check_prerequisites", lambda env: None)
    monkeypatch.setattr(mod, "listening", lambda port: False)
    _ready_gate(monkeypatch, mod, {}, events=events)

    mod.run_settings_stack(manager, {})

    assert events == [
        "spawn:nexus-data",
        "stream",
        "ready:nexus-data",
        "spawn:nexus-api",
        "stream",
        "ready:nexus-api",
        "spawn:dashboard",
    ]


# --- prerequisites and failure cleanup --------------------------------------


def test_redis_unavailable_aborts_without_spawning(monkeypatch):
    import run as run_mod

    mod = _load_settings_module()
    manager = FakeManager()
    monkeypatch.setattr(run_mod, "_check_redis", lambda url: False)

    with pytest.raises(RuntimeError, match="(?i)redis"):
        mod.run_settings_stack(manager, {"REDIS_URL": "redis://127.0.0.1:6379/0"})

    assert manager.spawned == []
    assert manager.shutdown_calls == 1


def test_data_boot_failure_shuts_down_spawned_processes(monkeypatch):
    mod = _load_settings_module()
    manager = FakeManager()
    monkeypatch.setattr(mod, "check_prerequisites", lambda env: None)
    monkeypatch.setattr(mod, "listening", lambda port: False)
    _ready_gate(monkeypatch, mod, {"nexus-data": False})

    with pytest.raises(RuntimeError, match="nexus-data"):
        mod.run_settings_stack(manager, {})

    assert manager.spawned == ["nexus-data"]
    assert manager.shutdown_calls == 1


def test_api_boot_failure_shuts_down_data_too(monkeypatch):
    mod = _load_settings_module()
    manager = FakeManager()
    monkeypatch.setattr(mod, "check_prerequisites", lambda env: None)
    monkeypatch.setattr(mod, "listening", lambda port: False)
    _ready_gate(monkeypatch, mod, {"nexus-api": False})

    with pytest.raises(RuntimeError, match="nexus-api"):
        mod.run_settings_stack(manager, {})

    assert "nexus-data" in manager.spawned
    assert manager.shutdown_calls == 1


# --- foreign listeners and duplicate runs ------------------------------------


def test_foreign_listener_on_data_port_is_left_untouched(monkeypatch):
    mod = _load_settings_module()
    manager = FakeManager()
    busy = {9001}
    monkeypatch.setattr(mod, "check_prerequisites", lambda env: None)
    monkeypatch.setattr(mod, "listening", lambda port: port in busy)
    _ready_gate(monkeypatch, mod, {})

    mod.run_settings_stack(manager, {})

    assert "nexus-data" not in manager.spawned
    assert "nexus-api" in manager.spawned
    assert manager.shutdown_calls == 0


def test_existing_ready_stack_is_not_started_twice(monkeypatch):
    mod = _load_settings_module()
    manager = FakeManager()
    monkeypatch.setattr(mod, "check_prerequisites", lambda env: None)
    monkeypatch.setattr(mod, "listening", lambda port: True)
    _ready_gate(monkeypatch, mod, {})

    mod.run_settings_stack(manager, {})

    assert manager.spawned == []
    assert manager.shutdown_calls == 0


def test_busy_port_without_ready_payload_fails_safe_without_kill(monkeypatch):
    mod = _load_settings_module()
    manager = FakeManager()
    monkeypatch.setattr(mod, "check_prerequisites", lambda env: None)
    monkeypatch.setattr(mod, "listening", lambda port: port == 9001)
    _ready_gate(monkeypatch, mod, {"nexus-data": False})

    with pytest.raises(RuntimeError, match="nexus-data"):
        mod.run_settings_stack(manager, {})

    assert "nexus-data" not in manager.spawned
    assert manager.shutdown_calls == 1


# --- dashboard tracking ------------------------------------------------------


def test_dashboard_is_tracked_by_manager_with_restart_limit(monkeypatch):
    mod = _load_settings_module()
    manager = FakeManager()
    monkeypatch.setattr(mod, "check_prerequisites", lambda env: None)
    monkeypatch.setattr(mod, "listening", lambda port: False)
    _ready_gate(monkeypatch, mod, {})

    mod.run_settings_stack(manager, {})

    tracked = [p.name for p in manager.processes]
    assert "dashboard" in tracked, (
        "dashboard must be a manager-tracked process so the restart attempt "
        "limit applies instead of an unmonitored raw spawn"
    )


def test_run_spawn_dashboard_never_deletes_next(monkeypatch):
    import run as run_mod

    captured: dict[str, list] = {}

    def fake_popen(cmd, **_kwargs):
        captured["cmd"] = [str(part) for part in cmd]
        return SimpleNamespace(pid=42)

    monkeypatch.setattr(run_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(run_mod, "IS_WINDOWS", True)
    monkeypatch.setattr(run_mod, "_log", lambda *_args, **_kwargs: None)

    manager = run_mod.ProcessManager(root=ROOT)
    manager.spawn_dashboard("cyan")

    joined = " ".join(captured["cmd"]).lower()
    assert "rmdir" not in joined
    assert ".next" not in joined
    assert "npm" in joined


# --- websockets requirement contract -----------------------------------------


def _websockets_pin(requirements: Path) -> str | None:
    for line in requirements.read_text(encoding="utf-8").splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry.lower().startswith("websockets"):
            return entry
    return None


def test_websockets_pin_consistent_between_root_and_api_requirements():
    from packaging.requirements import Requirement
    import importlib.metadata as metadata

    root_pin = _websockets_pin(ROOT / "requirements.txt")
    api_pin = _websockets_pin(ROOT / "services" / "nexus_api" / "requirements.txt")
    assert root_pin, "root requirements must pin websockets"
    assert api_pin, "api requirements must pin websockets"

    installed = metadata.version("websockets")
    assert Requirement(root_pin).specifier.contains(installed, prereleases=True), (
        f"installed websockets {installed} violates root pin {root_pin}"
    )
    assert Requirement(api_pin).specifier.contains(installed, prereleases=True), (
        f"installed websockets {installed} violates API pin {api_pin}"
    )
