from __future__ import annotations

import pytest
from pathlib import PurePosixPath
from types import SimpleNamespace

import run
from services.nexus_executor import main as executor


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b'{"ready":true,"duckdb":true}', True),
        (b'{"ready":true,"duckdb":false}', False),
        (b'{"ready":false,"duckdb":true}', False),
        (b'{"ready":1,"duckdb":true}', False),
        (b"not-json", False),
        (b"[]", False),
    ],
)
def test_data_health_gate_requires_valid_ready_and_duckdb(
    monkeypatch: pytest.MonkeyPatch, payload: bytes, expected: bool
) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def getcode(self):
            return 200

        def read(self):
            return payload

    monkeypatch.setattr(run.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    ticks = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(run.time, "time", lambda: next(ticks, 2.0))
    monkeypatch.setattr(run.time, "sleep", lambda _seconds: None)

    assert run._wait_for_http_ok("http://localhost:9001/health", timeout_s=1, interval_s=0) is expected


def test_run_process_lookup_uses_a_literal_windows_project_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[str] = []

    def fake_run(args, **_kwargs):
        commands.append(args[-1])
        return SimpleNamespace(
            stdout=(
                f"100|1|python.exe {run.ROOT}/run.py --paper\n"
                f"321|100|python.exe -m uvicorn services.nexus_api.main:app --app-dir {run.ROOT} --port 9000\n"
            )
        )

    monkeypatch.setattr(run, "IS_WINDOWS", True)
    monkeypatch.setattr(run.subprocess, "run", fake_run)

    assert run._collect_run_py_pids() == {100, 321}
    assert "Get-CimInstance Win32_Process" in commands[0]


def test_run_process_lookup_does_not_match_arbitrary_uvicorn_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[str] = []

    def fake_run(args, **_kwargs):
        commands.append(args[-1])
        return SimpleNamespace(
            stdout=(
                f"100|1|python.exe {run.ROOT}/run.py --paper\n"
                f"321|100|python.exe -m uvicorn services.nexus_api.main:app --app-dir {run.ROOT} --port 9000\n"
                "400|1|python.exe -m uvicorn unrelated.main:app --port 9000\n"
            )
        )

    monkeypatch.setattr(run, "IS_WINDOWS", True)
    monkeypatch.setattr(run.subprocess, "run", fake_run)

    assert run._collect_run_py_pids() == {100, 321}
    assert "Win32_Process" in commands[0]
    assert "|uvicorn|" not in commands[0]


def test_run_process_lookup_uses_runner_parentage_for_service_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[str] = []

    def fake_run(args, **_kwargs):
        commands.append(args[-1])
        return SimpleNamespace(
            stdout=(
                f"100|1|python.exe {run.ROOT}/run.py --paper\n"
                f"321|100|python.exe -m uvicorn services.nexus_api.main:app --app-dir {run.ROOT} --port 9000\n"
                f"322|321|python.exe -m uvicorn services.nexus_data.main:app --port 9001\n"
            )
        )

    monkeypatch.setattr(run, "IS_WINDOWS", True)
    monkeypatch.setattr(run.subprocess, "run", fake_run)

    assert run._collect_run_py_pids() == {100, 321, 322}
    assert ".ParentProcessId" in commands[0]


def test_run_process_lookup_includes_only_nexus_service_descendants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = PurePosixPath("/workspace/nexus")
    monkeypatch.setattr(run, "ROOT", root)
    output = "\n".join(
        [
            f"100 1 /usr/bin/python {root}/run.py --paper",
            f"101 100 /usr/bin/python -m uvicorn services.nexus_api.main:app --app-dir {root} --port 9000",
            "102 1 /usr/bin/python -m uvicorn services.nexus_other.main:app --port 8000",
            f"103 101 /usr/bin/python -m uvicorn services.nexus_data.main:app --app-dir {root} --port 9001",
        ]
    )

    monkeypatch.setattr(run, "IS_WINDOWS", False)
    monkeypatch.setattr(
        run.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=output),
    )
    assert run._collect_run_py_pids() == {100, 101, 103}


def test_run_process_lookup_includes_owned_dashboard_tree_but_not_other_node_apps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = PurePosixPath("/workspace/nexus")
    output = "\n".join(
        [
            f"100 1 /usr/bin/python {root}/run.py --paper",
            f"101 100 /usr/bin/python -m uvicorn services.nexus_api.main:app --app-dir {root} --port 9000",
            "104 100 cmd.exe /c npm run dev -- --port 3100",
            f"105 104 node {root}/dashboard/node_modules/next/dist/bin/next dev --port 3100",
            "106 1 node unrelated-dashboard/node_modules/next/dist/bin/next dev --port 3100",
        ]
    )

    monkeypatch.setattr(run, "ROOT", root)
    monkeypatch.setattr(run, "IS_WINDOWS", False)
    monkeypatch.setattr(
        run.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=output),
    )

    assert run._collect_run_py_pids() == {100, 101, 104, 105}


def test_spawned_services_include_project_root_for_process_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(pid=321)

    monkeypatch.setattr(run.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(run, "_log", lambda _message: None)
    monkeypatch.setattr(run, "IS_WINDOWS", True)
    monkeypatch.setattr(run.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, raising=False)

    manager = run.ProcessManager(root=PurePosixPath("/workspace/nexus"))
    manager.spawn_service("nexus-api", 9000, "blue")

    command = captured["command"]
    assert isinstance(command, list)
    app_dir_index = command.index("--app-dir")
    assert command[app_dir_index + 1] == "/workspace/nexus"
    assert captured["kwargs"]["creationflags"] == 512


def test_runner_distributes_risk_approval_secret_only_to_risk_and_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spawned: dict[str, dict[str, str]] = {}

    def fake_popen(command, **kwargs):
        name = kwargs["env"].get("NEXUS_SERVICE_NAME", "dashboard")
        spawned[name] = kwargs["env"]
        return SimpleNamespace(pid=321)

    monkeypatch.setattr(run, "IS_WINDOWS", False)
    monkeypatch.setattr(run.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(run, "_log", lambda _message: None)
    env = {
        "NEXUS_INTERNAL_API_SECRET": "shared-test-secret",
        "NEXUS_RISK_APPROVAL_SECRET": "isolated-test-approval-secret",
    }
    manager = run.ProcessManager(root=PurePosixPath("/workspace/nexus"))

    manager.spawn_service("nexus-risk", 9006, "blue", env_override=env)
    manager.spawn_service("nexus-executor", 9007, "green", env_override=env)
    manager.spawn_service("nexus-data", 9001, "yellow", env_override=env)
    manager.spawn_dashboard("cyan", env_override=env)

    assert spawned["nexus-risk"]["NEXUS_RISK_APPROVAL_SECRET"] == env["NEXUS_RISK_APPROVAL_SECRET"]
    assert spawned["nexus-executor"]["NEXUS_RISK_APPROVAL_SECRET"] == env["NEXUS_RISK_APPROVAL_SECRET"]
    assert "NEXUS_RISK_APPROVAL_SECRET" not in spawned["nexus-data"]
    assert "NEXUS_RISK_APPROVAL_SECRET" not in spawned["dashboard"]


def test_unreachable_redis_does_not_print_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    redis_url = "redis://audit-user:audit-password@redis.internal:6379/0"
    logged_errors: list[str] = []
    monkeypatch.setattr(
        run,
        "_ensure_dotenv",
        lambda _root: {"NEXUS_SECRET_KEY": "not-used", "REDIS_URL": redis_url},
    )
    monkeypatch.setattr(run, "_check_redis", lambda _url: False)
    monkeypatch.setattr(run, "_log", lambda _message: None)
    monkeypatch.setattr(run, "_log_ok", lambda _message: None)
    monkeypatch.setattr(run, "_log_err", logged_errors.append)

    with pytest.raises(SystemExit):
        run._check_prerequisites(run.Path("."))

    assert logged_errors
    assert "audit-user" not in "\n".join(logged_errors)
    assert "audit-password" not in "\n".join(logged_errors)


def test_stop_listeners_skips_processes_not_owned_by_nexus(monkeypatch: pytest.MonkeyPatch) -> None:
    killed: list[int] = []
    monkeypatch.setattr(run, "_is_port_in_use", lambda _port: True)
    monkeypatch.setattr(run, "_collect_pids_on_ports", lambda _ports: {111, 222})
    monkeypatch.setattr(run, "_collect_run_py_pids", lambda: {222})
    monkeypatch.setattr(run, "_kill_pid", lambda pid: killed.append(pid) or True)
    monkeypatch.setattr(run, "_wait_for_ports_free", lambda ports: list(ports))
    monkeypatch.setattr(run, "_log_ok", lambda _message: None)
    monkeypatch.setattr(run, "_log_warn", lambda _message: None)

    stopped = run._stop_listeners_on_ports([9001])

    assert stopped == 1
    assert killed == [222]


def test_stop_listeners_fails_safe_when_process_ownership_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    killed: list[int] = []
    monkeypatch.setattr(run, "_is_port_in_use", lambda _port: True)
    monkeypatch.setattr(run, "_collect_pids_on_ports", lambda _ports: {111})
    monkeypatch.setattr(run, "_collect_run_py_pids", lambda: set())
    monkeypatch.setattr(run, "_kill_pid", lambda pid: killed.append(pid) or True)
    monkeypatch.setattr(run, "_wait_for_ports_free", lambda ports: list(ports))
    monkeypatch.setattr(run, "_log_ok", lambda _message: None)
    monkeypatch.setattr(run, "_log_warn", lambda _message: None)

    stopped = run._stop_listeners_on_ports([9001])

    assert stopped == 0
    assert killed == []


def test_windows_shutdown_signals_group_then_kills_owned_process_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions: list[tuple[str, object]] = []

    class FakeProcess:
        pid = 4321
        returncode = None

        def poll(self):
            return None

        def terminate(self):
            actions.append(("terminate", self.pid))

        def kill(self):
            actions.append(("kill", self.pid))

        def send_signal(self, sig):
            actions.append(("signal", sig))

        def wait(self, timeout=None):
            raise run.subprocess.TimeoutExpired("fake", timeout)

    manager = run.ProcessManager(root=PurePosixPath("/workspace/nexus"))
    manager.processes.append(
        run.ManagedProcess(
            name="dashboard",
            proc=FakeProcess(),
            port=3100,
            color="",
        )
    )
    monkeypatch.setattr(run, "IS_WINDOWS", True)
    monkeypatch.setattr(run.signal, "CTRL_BREAK_EVENT", 1, raising=False)
    monkeypatch.setattr(run, "_log_warn", lambda _message: None)
    monkeypatch.setattr(run, "_log", lambda _message: None)
    monkeypatch.setattr(run, "_log_ok", lambda _message: None)
    monkeypatch.setattr(
        run,
        "_kill_pid",
        lambda pid: actions.append(("tree_kill", pid)) or True,
    )

    manager.shutdown()

    assert actions == [("signal", 1), ("tree_kill", 4321)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("approved_size", "expected_size"),
    [(0.01, 0.01), (0.08, 0.05)],
)
async def test_fixed_lots_never_increases_risk_approved_size(
    monkeypatch: pytest.MonkeyPatch,
    approved_size: float,
    expected_size: float,
) -> None:
    monkeypatch.setenv("NEXUS_FIXED_LOTS", "BTCUSD=0.05")
    monkeypatch.setattr(executor, "_lot_caps", lambda: (0.50, 40_000.0))

    actual_size = await executor._clamp_lot_size(approved_size, "BTCUSD")

    assert actual_size == expected_size
