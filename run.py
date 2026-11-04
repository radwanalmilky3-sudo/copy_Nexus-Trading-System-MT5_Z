#!/usr/bin/env python3
"""
Nexus Trader — Local Development Runner
========================================

Start all (or selected) Nexus microservices from a single command.

Usage examples
--------------
    # Next.js dashboard on :3100 starts by default; use --no-frontend to skip it

    # Only start the API gateway, data engine and risk manager
    python run.py --services nexus-api,nexus-data,nexus-risk

    # Force paper-trading mode with debug logs
    python run.py --paper --log-level DEBUG

    # Enable live trading (requires explicit confirmation)
    python run.py --live --confirm-live


    # Hot-reload during development
    python run.py --reload --log-level DEBUG
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from shared.config_contract import validate_config_contract
from shared.safety import is_secure_jwt_secret, is_secure_risk_approval_secret

# ---------------------------------------------------------------------------
# Service registry
# ---------------------------------------------------------------------------

SERVICE_REGISTRY: Dict[str, int] = {
    "nexus-api":      9000,
    "nexus-data":     9001,
    "nexus-features": 9002,
    "nexus-ml":       9003,
    "nexus-agents":   9004,
    "nexus-news":     9005,
    "nexus-risk":     9006,
    "nexus-executor": 9007,
    "nexus-monitor":  9008,
}

DASHBOARD_PORT = 3100
# Cap dashboard respawns so a genuinely broken build (bad dependency, syntax
# error) surfaces one clear message instead of an infinite restart loop.
_MAX_DASHBOARD_RESTARTS = 3

STARTUP_ORDER: List[str] = [
    "nexus-data",
    "nexus-features",
    "nexus-news",
    "nexus-risk",
    "nexus-ml",
    "nexus-agents",
    "nexus-executor",
    "nexus-monitor",
    "nexus-api",
]

SERVICE_TO_MODULE: Dict[str, str] = {
    "nexus-api":      "services.nexus_api.main:app",
    "nexus-data":     "services.nexus_data.main:app",
    "nexus-features": "services.nexus_features.main:app",
    "nexus-ml":       "services.nexus_ml.main:app",
    "nexus-agents":   "services.nexus_agents.main:app",
    "nexus-news":     "services.nexus_news.main:app",
    "nexus-risk":     "services.nexus_risk.main:app",
    "nexus-executor": "services.nexus_executor.main:app",
    "nexus-monitor":  "services.nexus_monitor.main:app",
}

# ---------------------------------------------------------------------------
# ANSI colours (one per service, cycles if more are added)
# ---------------------------------------------------------------------------

ANSI_COLORS = [
    "\033[36m",   # cyan
    "\033[32m",   # green
    "\033[33m",   # yellow
    "\033[35m",   # magenta
    "\033[34m",   # blue
    "\033[91m",   # bright red
    "\033[92m",   # bright green
    "\033[93m",   # bright yellow
    "\033[94m",   # bright blue
    "\033[95m",   # bright magenta
    "\033[96m",   # bright cyan
]
RESET = "\033[0m"
BOLD = "\033[1m"

IS_WINDOWS = platform.system() == "Windows"
ROOT = Path(__file__).resolve().parent


def _reexec_in_venv_if_available() -> None:
    """Prefer the project .venv over a broken global Python install."""
    if os.environ.get("NEXUS_NO_VENV"):
        return
    venv_python = ROOT / ".venv" / ("Scripts" if IS_WINDOWS else "bin") / (
        "python.exe" if IS_WINDOWS else "python"
    )
    if not venv_python.is_file():
        return
    if Path(sys.executable).resolve() == venv_python.resolve():
        return
    print(f"[nexus] Switching to project venv: {venv_python}", file=sys.stderr, flush=True)
    rc = subprocess.call([str(venv_python)] + sys.argv)
    raise SystemExit(rc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _color(idx: int) -> str:
    return ANSI_COLORS[idx % len(ANSI_COLORS)]


def _log(msg: str, *, style: str = RESET) -> None:
    print(f"{style}[nexus]{RESET} {msg}")


def _log_ok(msg: str) -> None:
    _log(msg, style="\033[32m")


def _log_warn(msg: str) -> None:
    _log(msg, style="\033[33m")


def _log_err(msg: str) -> None:
    _log(msg, style="\033[31m")


def _wait_for_http_ok(url: str, *, timeout_s: float = 120.0, interval_s: float = 0.4) -> bool:
    """Return True once ``url`` responds with HTTP 200 (used to gate DuckDB startup)."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:  # noqa: S310
                if resp.getcode() != 200:
                    time.sleep(interval_s)
                    continue
                # nexus-data: require the DuckDB writer to be ready, not merely
                # a listening HTTP socket.  The service currently uses port 9001
                # (and may be configured differently), so this must not be tied
                # to an obsolete literal port number.
                if "/health" in url:
                    import json
                    body = resp.read().decode("utf-8", errors="replace")
                    try:
                        data = json.loads(body)
                        if (
                            isinstance(data, dict)
                            and data.get("ready") is True
                            and data.get("duckdb") is True
                        ):
                            return True
                    except json.JSONDecodeError:
                        pass
                else:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(interval_s)
    return False


def _is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _collect_pids_on_ports(ports: List[int]) -> set[int]:
    pids: set[int] = set()
    for port in ports:
        if IS_WINDOWS:
            result = subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue "
                    f"| Select-Object -ExpandProperty OwningProcess",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.isdigit():
                    pids.add(int(line))
        elif _is_port_in_use(port):
            result = subprocess.run(
                ["bash", "-lc", f"lsof -ti tcp:{port} 2>/dev/null || true"],
                check=False,
                capture_output=True,
                text=True,
            )
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.isdigit():
                    pids.add(int(line))
    return pids


def _collect_run_py_pids() -> set[int]:
    """Find this project's runner, services, and its dashboard process tree."""
    processes: list[tuple[int, int, str]] = []
    if IS_WINDOWS:
        command = (
            "Get-CimInstance Win32_Process | ForEach-Object { "
            "[Console]::WriteLine((' {0}|{1}|{2}' -f $_.ProcessId, "
            "$_.ParentProcessId, [string]$_.CommandLine).TrimStart()) }"
        )
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command", command,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3 and parts[0].strip().isdigit() and parts[1].strip().isdigit():
                processes.append((int(parts[0]), int(parts[1]), parts[2]))
    else:
        result = subprocess.run(
            ["ps", "-eo", "pid=,ppid=,args="],
            check=False,
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            parts = line.strip().split(None, 2)
            if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
                processes.append((int(parts[0]), int(parts[1]), parts[2]))
    root = str(ROOT).casefold()
    service_pattern = re.compile(r"services\.nexus_[a-z0-9_]+\.main:app", re.IGNORECASE)
    runner_pattern = re.compile(r"(?:^|[\\/\s])run\.py(?:\s|$)", re.IGNORECASE)
    dashboard_pattern = re.compile(
        r"(?:\bnpm(?:\.cmd)?\s+run\s+dev\b|npm-cli\.js\s+run\s+dev\b)"
        r".*--port\s+3100\b",
        re.IGNORECASE,
    )
    by_pid = {pid: (parent, cmdline) for pid, parent, cmdline in processes}
    service_pids = {
        pid
        for pid, _parent, cmdline in processes
        if root in cmdline.casefold() and service_pattern.search(cmdline)
    }
    runner_pids: set[int] = set()

    # Resolve the service workers and their uvicorn children, then identify
    # only the run.py ancestors proved by that project-specific service chain.
    changed = True
    while changed:
        changed = False
        for pid, parent, cmdline in processes:
            if pid not in service_pids and parent in service_pids and service_pattern.search(cmdline):
                service_pids.add(pid)
                changed = True
            if pid in service_pids and parent in by_pid:
                parent_cmdline = by_pid[parent][1]
                if runner_pattern.search(parent_cmdline) and parent not in runner_pids:
                    runner_pids.add(parent)
                    changed = True

    # Dashboard launchers are owned only when their direct parent is one of
    # those proven runner PIDs. Once anchored, include that launcher's children
    # (npm/Next/Node), not unrelated Node processes elsewhere on the machine.
    dashboard_pids = {
        pid
        for pid, parent, cmdline in processes
        if parent in runner_pids and dashboard_pattern.search(cmdline)
    }
    changed = True
    while changed:
        changed = False
        for pid, parent, _cmdline in processes:
            if pid not in dashboard_pids and parent in dashboard_pids:
                dashboard_pids.add(pid)
                changed = True

    return service_pids | runner_pids | dashboard_pids


def _kill_pid(pid: int) -> bool:
    if IS_WINDOWS:
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            capture_output=True,
        )
        return result.returncode == 0
    result = subprocess.run(
        ["bash", "-lc", f"kill -TERM {pid} 2>/dev/null; sleep 1; kill -KILL {pid} 2>/dev/null"],
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def _wait_for_ports_free(ports: List[int], timeout_s: float = 15.0) -> List[int]:
    """Poll until the given ports stop listening. Returns those still busy.

    Windows tears a killed process's listening socket down asynchronously, so
    a fixed 1s sleep frequently reported ports as "still in use" and made
    startup abort on a conflict that resolved itself a moment later.
    """
    deadline = time.time() + timeout_s
    pending = list(ports)
    while pending and time.time() < deadline:
        pending = [p for p in pending if _is_port_in_use(p)]
        if not pending:
            break
        time.sleep(0.5)
    return pending


def _stop_listeners_on_ports(ports: List[int]) -> int:
    """Stop only confirmed Nexus-owned listeners on the given ports."""
    busy_before = {port for port in ports if _is_port_in_use(port)}
    listeners = _collect_pids_on_ports(ports)
    nexus_pids = _collect_run_py_pids()
    pids = listeners & nexus_pids
    for pid in sorted(listeners - nexus_pids):
        _log_warn(f"Skipping PID {pid} on a Nexus port: project ownership is unconfirmed")
    stopped = 0
    for pid in sorted(pids):
        if _kill_pid(pid):
            stopped += 1

    still_busy = set(_wait_for_ports_free(sorted(busy_before)))
    for port in sorted(busy_before):
        if port not in still_busy:
            _log_ok(f"Freed port :{port}")
        else:
            _log_warn(f"Port :{port} still in use — stop the process manually")
    return stopped


def _stop_all_services() -> None:
    ports = sorted(set(SERVICE_REGISTRY.values()) | {DASHBOARD_PORT})
    _log(f"Stopping Nexus processes on ports {', '.join(str(p) for p in ports)} ...")
    freed = _stop_listeners_on_ports(ports)

    for pid in sorted(_collect_run_py_pids()):
        if _kill_pid(pid):
            freed += 1
            _log_ok(f"Stopped lingering process (PID {pid})")

    if freed:
        _log_ok(f"Stopped {freed} process tree(s). Wait 2s then run: python run.py")
    else:
        _log("No Nexus listeners found on known ports.")


def _check_redis(url: str) -> bool:
    """Return True when Redis responds to PING.

    Tries the ``redis`` Python package first.  Falls back to a raw TCP
    socket check so the runner still works when the package isn't installed.
    """
    # Parse host/port from redis://host:port style URLs
    host, port = "127.0.0.1", 6379
    if "://" in url:
        netloc = url.split("://", 1)[1].split("/")[0]
        parts = netloc.rsplit(":", 1)
        host = parts[0] or "127.0.0.1"
        if len(parts) == 2:
            try:
                port = int(parts[1])
            except ValueError:
                pass

    # Method 1: redis-py library (preferred — sends a real PING)
    try:
        import redis as _redis  # noqa: WPS433

        r = _redis.Redis(host=host, port=port, socket_connect_timeout=2)
        return r.ping()
    except ImportError:
        pass
    except Exception:
        return False

    # Method 2: raw TCP socket probe
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect((host, port))
            s.sendall(b"PING\r\n")
            data = s.recv(64)
            return b"+PONG" in data
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------


def _ensure_dotenv(root: Path) -> dict[str, str]:
    env_path = root / ".env"
    if not env_path.exists():
        example = root / ".env.example"
        if example.exists():
            _log_warn(".env not found – copying from .env.example")
            import shutil

            shutil.copy(example, env_path)
        else:
            _log_err(".env file is missing and no .env.example to copy from.")
            sys.exit(1)

    try:
        from dotenv import dotenv_values

        # Only keep concrete string values so they can be exported to child
        # processes without introducing "None" or non-string env values.
        parsed = dotenv_values(env_path)
        return {
            str(k): str(v)
            for k, v in parsed.items()
            if k and v is not None
        }
    except ImportError:
        _log_err("python-dotenv is not installed. Run: pip install python-dotenv")
        sys.exit(1)


REQUIRED_ENV_VARS = [
    "NEXUS_SECRET_KEY",
    "NEXUS_INTERNAL_API_SECRET",
    "NEXUS_RISK_APPROVAL_SECRET",
    "NEXUS_JWT_SECRET",
    "REDIS_URL",
]


def _validate_env(env: dict[str, str]) -> None:
    missing = [v for v in REQUIRED_ENV_VARS if not env.get(v)]
    if missing:
        _log_err(f"Missing required env vars: {', '.join(missing)}")
        _log_err("Set them in your .env file.")
        sys.exit(1)
    if not is_secure_jwt_secret(env.get("NEXUS_JWT_SECRET", "")):
        _log_err("NEXUS_JWT_SECRET must be a unique secret of at least 32 UTF-8 bytes; sample values are rejected.")
        sys.exit(1)
    if not is_secure_risk_approval_secret(
        env.get("NEXUS_RISK_APPROVAL_SECRET", ""),
        env.get("NEXUS_INTERNAL_API_SECRET", ""),
    ):
        _log_err(
            "NEXUS_RISK_APPROVAL_SECRET must be a unique secret of at least 32 UTF-8 bytes and differ from NEXUS_INTERNAL_API_SECRET."
        )
        sys.exit(1)


def _check_prerequisites(root: Path) -> dict[str, str]:
    _log("Running prerequisite checks ...")
    env = _ensure_dotenv(root)
    _validate_env(env)
    validate_config_contract()

    redis_url = env.get("REDIS_URL", "redis://localhost:6379")
    if not _check_redis(redis_url):
        _log_err("Redis is not reachable at the configured URL.")
        _log_err("Start the local Redis service on 127.0.0.1:6379")
        sys.exit(1)
    _log_ok("Redis OK")
    return env


def _check_port_conflicts(
    services: Dict[str, int],
    include_dashboard: bool,
    *,
    auto_stop: bool = True,
) -> Dict[str, int]:
    """Return services whose ports are free. Auto-stops stale Nexus listeners once."""
    ports_to_check = dict(services)
    if include_dashboard:
        ports_to_check["dashboard"] = DASHBOARD_PORT

    def _scan() -> tuple[Dict[str, int], List[str]]:
        clean: Dict[str, int] = {}
        conflicts: List[str] = []
        for name, port in ports_to_check.items():
            if _is_port_in_use(port):
                conflicts.append(f"  {name} -> :{port}")
            else:
                clean[name] = port
        return clean, conflicts

    clean, conflicts = _scan()
    if conflicts and auto_stop and not os.environ.get("NEXUS_NO_AUTOSTOP"):
        _log_warn("Stale Nexus processes detected on occupied ports — stopping them ...")
        _stop_all_services()
        # Give the OS time to actually release the sockets before re-scanning;
        # a fixed 2s sleep raced with Windows' asynchronous socket teardown and
        # aborted startup over conflicts that cleared a second later.
        still = _wait_for_ports_free(sorted(ports_to_check.values()))
        if still:
            _log_warn(f"Waiting on ports: {', '.join(str(p) for p in still)}")
        clean, conflicts = _scan()
        auto_stop = False  # only retry once

    if conflicts:
        _log_err("Port conflicts — cannot start until these ports are free:")
        for c in conflicts:
            _log_err(c)
        _log_err("Run: python run.py --stop")
        sys.exit(1)

    _log_ok("No port conflicts")
    return clean


# ---------------------------------------------------------------------------
# Process management
# ---------------------------------------------------------------------------


@dataclass
class ManagedProcess:
    name: str
    proc: subprocess.Popen
    port: int
    color: str
    healthy: bool = False


@dataclass
class ProcessManager:
    root: Path
    processes: List[ManagedProcess] = field(default_factory=list)
    _shutting_down: bool = False
    _streamed: set[str] = field(default_factory=set, repr=False)
    _dashboard_restarts: int = 0

    def spawn_service(
        self,
        name: str,
        port: int,
        color: str,
        *,
        reload: bool = False,
        log_level: str = "INFO",
        env_override: Optional[dict] = None,
    ) -> ManagedProcess:
        module = SERVICE_TO_MODULE[name]
        cmd = [
            sys.executable, "-m", "uvicorn",
            module,
            "--app-dir", str(self.root),
            "--host", "127.0.0.1",
            "--port", str(port),
            "--log-level", log_level.lower(),
        ]
        if reload:
            cmd.append("--reload")

        env = {**os.environ}
        if env_override:
            env.update(env_override)
        if name not in {"nexus-risk", "nexus-executor"}:
            env.pop("NEXUS_RISK_APPROVAL_SECRET", None)
        env["NEXUS_SERVICE_NAME"] = name
        env["NEXUS_SERVICE_PORT"] = str(port)
        # Ensure the project root is on PYTHONPATH so `shared` package is importable
        root_str = str(self.root)
        env["PYTHONPATH"] = root_str + (os.pathsep + env.get("PYTHONPATH", ""))
        # Force UTF-8 in child stdio so non-ASCII chars (em-dashes, structlog
        # box drawings) cannot crash the parent's reader thread on Windows
        # (default cp1252) — see https://docs.python.org/3/using/cmdline.html#cmdoption-X-utf8
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONNOUSERSITE", "1")

        proc = subprocess.Popen(
            cmd,
            cwd=str(self.root),
            env=env,
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
        )
        mp = ManagedProcess(name=name, proc=proc, port=port, color=color)
        self.processes.append(mp)
        _log(f"{color}{name}{RESET} started (PID {proc.pid}, port {port})")
        return mp

    def spawn_dashboard(self, color: str, *, env_override: Optional[dict] = None) -> ManagedProcess:
        dashboard_dir = self.root / "dashboard"
        cmd = ["npm", "run", "dev", "--", "--port", str(DASHBOARD_PORT)]
        if IS_WINDOWS:
            # Windows cannot execute npm.cmd directly through CreateProcess
            # (PATHEXT is not applied), so wrap it in cmd.  Never delete
            # `.next`: the runner contract forbids destroying user/build
            # files — a corrupt build must surface as a capped dashboard
            # restart failure instead of silently wiping the directory.
            cmd = ["cmd", "/c", f"npm run dev -- --port {DASHBOARD_PORT}"]

        env = {**os.environ}
        if env_override:
            env.update(env_override)
        env.pop("NEXUS_RISK_APPROVAL_SECRET", None)
        # 2026-11-05 fix: NEXT_PUBLIC_* values are inlined into the browser
        # bundle. Absolute 127.0.0.1 URLs made external browsers (preview
        # gateway, HTTPS) fetch a loopback address -> "Failed to fetch".
        # Empty = same-origin /api (next.config.js rewrites proxy server-side
        # to nexus-api) and window.location-derived WS origin (gateway-ws.ts).
        env.setdefault("NEXT_PUBLIC_API_URL", "")
        env.setdefault("NEXT_PUBLIC_WS_GATEWAY_URL", "")

        proc = subprocess.Popen(
            cmd,
            cwd=str(dashboard_dir),
            env=env,
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
        )
        mp = ManagedProcess(name="dashboard", proc=proc, port=DASHBOARD_PORT, color=color)
        self.processes.append(mp)
        _log(f"{color}dashboard{RESET} started (PID {proc.pid}, port {DASHBOARD_PORT})")
        return mp

    # --- Output streaming (per-process thread) ---
    def _stream_output(self, mp: ManagedProcess) -> None:
        import threading

        def _reader():
            assert mp.proc.stdout is not None
            try:
                while True:
                    try:
                        line = mp.proc.stdout.readline()
                    except UnicodeDecodeError as exc:
                        # Should not happen now that we force UTF-8 with
                        # errors="replace", but keep this guard so a single
                        # bad byte never tears the whole stack down.
                        print(
                            f"{mp.color}[{mp.name}]{RESET} <decode-error: {exc}>"
                        )
                        continue
                    except Exception as exc:  # pragma: no cover - defensive
                        print(
                            f"{mp.color}[{mp.name}]{RESET} <reader-error: {exc}>"
                        )
                        break
                    if not line:
                        break
                    print(f"{mp.color}[{mp.name}]{RESET} {line.rstrip()}")
            finally:
                try:
                    mp.proc.stdout.close()
                except Exception:
                    pass

        t = threading.Thread(target=_reader, daemon=True)
        t.start()

    def start_streaming(self) -> None:
        for mp in self.processes:
            if mp.name in self._streamed:
                continue
            self._streamed.add(mp.name)
            self._stream_output(mp)

    # --- Health checks ---
    def health_check(
        self,
        *,
        reload: bool = False,
        log_level: str = "INFO",
        env_override: Optional[dict] = None,
    ) -> None:
        for mp in self.processes:
            if mp.proc.poll() is not None:
                _log_err(f"{mp.name} exited unexpectedly (code {mp.proc.returncode})")
                if mp.name == "dashboard":
                    # Respawn the UI too — previously only Python services were
                    # restarted, so a dashboard crash left the stack headless
                    # while this loop logged the same error every 10s forever.
                    if self._dashboard_restarts >= _MAX_DASHBOARD_RESTARTS:
                        if not mp.healthy:
                            _log_err(
                                f"dashboard failed {self._dashboard_restarts}x — giving up. "
                                f"Run 'npm run dev' in ./dashboard to see the error."
                            )
                        self.processes.remove(mp)
                        continue
                    self._dashboard_restarts += 1
                    _log_warn(
                        f"Auto-restarting dashboard "
                        f"({self._dashboard_restarts}/{_MAX_DASHBOARD_RESTARTS}) ..."
                    )
                    try:
                        self._streamed.discard(mp.name)
                        self.processes.remove(mp)
                        new_mp = self.spawn_dashboard(mp.color, env_override=env_override)
                        self._stream_output(new_mp)
                    except Exception as exc:
                        _log_err(f"Failed to restart dashboard: {exc}")
                    continue
                if mp.name in SERVICE_TO_MODULE:
                    _log_warn(f"Auto-restarting {mp.name} ...")
                    try:
                        self._streamed.discard(mp.name)
                        self.processes.remove(mp)
                        new_mp = self.spawn_service(
                            mp.name, mp.port, mp.color,
                            reload=reload,
                            log_level=log_level,
                            env_override=env_override,
                        )
                        self._stream_output(new_mp)
                        _log_ok(f"{mp.name} restarted (PID {new_mp.proc.pid})")
                    except Exception as exc:
                        _log_err(f"Failed to restart {mp.name}: {exc}")
                continue
            if mp.name == "dashboard":
                alive = _is_port_in_use(mp.port)
            else:
                alive = _is_port_in_use(mp.port)
            if alive and not mp.healthy:
                mp.healthy = True
                _log_ok(f"{mp.name} healthy on :{mp.port}")
            elif not alive and mp.healthy:
                mp.healthy = False
                _log_warn(f"{mp.name} stopped responding on :{mp.port}")

    # --- Graceful shutdown ---
    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        _log_warn("Shutting down all services ...")
        for mp in reversed(self.processes):
            if mp.proc.poll() is None:
                _log(f"Stopping {mp.color}{mp.name}{RESET} (PID {mp.proc.pid})")
                if IS_WINDOWS:
                    # Give the whole owned console process group a graceful
                    # shutdown; terminating cmd.exe alone can orphan npm/node.
                    mp.proc.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    mp.proc.send_signal(signal.SIGTERM)
        deadline = time.time() + 8
        for mp in self.processes:
            remaining = max(0, deadline - time.time())
            try:
                mp.proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                _log_warn(f"Force-killing {mp.name}")
                if IS_WINDOWS:
                    # Popen.kill() only kills the wrapper process on Windows.
                    # taskkill /T is scoped to this runner-owned process tree.
                    _kill_pid(mp.proc.pid)
                else:
                    mp.proc.kill()
        _log_ok("All services stopped.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nexus-run",
        description="Nexus Trader -- local development runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--stop",
        action="store_true",
        help="Stop Nexus services listening on the configured 9000-9008/3100 ports",
    )
    p.add_argument(
        "--services",
        type=str,
        default=None,
        help="Comma-separated list of services to start (default: all)",
    )
    p.add_argument(
        "--no-frontend",
        action="store_true",
        help="Do not start the Next.js dashboard (default: dashboard runs on :3100)",
    )
    p.add_argument(
        "--with-frontend",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--paper", action="store_true", help="Force paper trading mode")
    mode.add_argument("--live", action="store_true", help="Force live trading mode")
    p.add_argument("--confirm-live", action="store_true", help="Required alongside --live")

    p.add_argument("--reload", action="store_true", help="Enable uvicorn auto-reload for development")
    p.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Log level (default: INFO)",
    )
    p.add_argument(
        "--preflight",
        action="store_true",
        help="Run preflight checks (MT5, Redis, .env) and exit",
    )
    p.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Start services without running preflight.py first",
    )
    p.add_argument(
        "--replace-running",
        action="store_true",
        help="Explicitly stop stale Nexus listeners on occupied ports before starting. Default: never stop existing services.",
    )
    return p


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    # Force UTF-8 on Windows consoles that default to cp1252
    if IS_WINDOWS:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = build_parser()
    args = parser.parse_args()

    if args.stop:
        _stop_all_services()
        sys.exit(0)

    if args.preflight:
        preflight_script = Path(__file__).resolve().parent / "preflight.py"
        rc = subprocess.call([sys.executable, str(preflight_script)])
        sys.exit(rc)

    if args.live and not args.confirm_live:
        _log_err("Live trading requires --confirm-live for safety.")
        sys.exit(1)

    root = Path(__file__).resolve().parent

    # Enable ANSI on Windows 10+
    if IS_WINDOWS:
        os.system("")  # noqa: S605  — enables VT100 sequences on Win10

    print(f"\n{BOLD}+======================================+{RESET}")
    print(f"{BOLD}|       NEXUS TRADER  -  Dev Runner    |{RESET}")
    print(f"{BOLD}+======================================+{RESET}\n")

    # Pre-flight (MT5 symbols, Redis, .env recommendations) ───────────────
    if not args.skip_preflight:
        preflight_script = root / "preflight.py"
        if preflight_script.exists():
            _log("Running pre-flight checks (python preflight.py) ...")
            rc = subprocess.call([sys.executable, str(preflight_script), "--no-services"])
            if rc != 0:
                _log_err("Pre-flight failed. Fix issues above or use --skip-preflight to bypass.")
                sys.exit(rc)
            _log_ok("Pre-flight passed")

    # Prerequisites ────────────────────────────────────────────────────────
    env = _check_prerequisites(root)

    # Base process environment comes from .env so all services read the same
    # values without requiring shell-level exports.
    env_override: dict[str, str] = dict(env)
    env_override.setdefault("PYTHONIOENCODING", "utf-8")
    env_override.setdefault("PYTHONUTF8", "1")
    env_override.setdefault("NEXUS_MT5_ISOLATED", "1")

    # Keep broker variable names backward-compatible across services.
    if "DEFAULT_BROKER" in env_override and "NEXUS_DEFAULT_BROKER" not in env_override:
        env_override["NEXUS_DEFAULT_BROKER"] = env_override["DEFAULT_BROKER"]
    elif "NEXUS_DEFAULT_BROKER" in env_override and "DEFAULT_BROKER" not in env_override:
        env_override["DEFAULT_BROKER"] = env_override["NEXUS_DEFAULT_BROKER"]

    # Local dev: every service reaches its peers on localhost using the registry
    # ports.
    _url_env_map = {
        "NEXUS_API_URL":      "nexus-api",
        "NEXUS_DATA_URL":     "nexus-data",
        "NEXUS_FEATURES_URL": "nexus-features",
        "NEXUS_ML_URL":       "nexus-ml",
        "NEXUS_AGENTS_URL":   "nexus-agents",
        "NEXUS_NEWS_URL":     "nexus-news",
        "NEXUS_RISK_URL":     "nexus-risk",
        "NEXUS_EXECUTOR_URL": "nexus-executor",
    }
    for _env_name, _svc in _url_env_map.items():
        env_override.setdefault(
            _env_name, f"http://127.0.0.1:{SERVICE_REGISTRY[_svc]}"
        )
    # 2026-11-05 fix: keep browser-bound URLs same-origin (see dashboard
    # launch comment above) — the gateway proxies server-side instead.
    env_override["NEXT_PUBLIC_API_URL"] = ""
    env_override["NEXT_PUBLIC_WS_URL"] = ""
    env_override["NEXT_PUBLIC_WS_GATEWAY_URL"] = ""

    # Trading mode override
    if args.paper:
        env_override["NEXUS_TRADING_MODE"] = "paper"
        _log_ok("Trading mode: PAPER")
    elif args.live:
        env_override["NEXUS_TRADING_MODE"] = "live"
        _log_warn("Trading mode: LIVE -- real money at risk!")
    else:
        mode = env.get("NEXUS_TRADING_MODE", "paper").strip().lower()
        if mode in ("live", "production", "prod"):
            _log_warn("LIVE in .env is not activated implicitly; use --live --confirm-live. Falling back to PAPER.")
            env_override["NEXUS_TRADING_MODE"] = "paper"
            mode = "paper"
        _log(f"Trading mode: {mode.upper()} (safe resolved mode)")

    # Resolve services ─────────────────────────────────────────────────────
    if args.services:
        requested = [s.strip() for s in args.services.split(",")]
        unknown = [s for s in requested if s not in SERVICE_REGISTRY]
        if unknown:
            _log_err(f"Unknown services: {', '.join(unknown)}")
            _log_err(f"Available: {', '.join(SERVICE_REGISTRY)}")
            sys.exit(1)
        ordered = [s for s in STARTUP_ORDER if s in requested]
    else:
        ordered = list(STARTUP_ORDER)

    selected: Dict[str, int] = {s: SERVICE_REGISTRY[s] for s in ordered}
    if args.no_frontend and args.with_frontend:
        _log_err("Use either --no-frontend or --with-frontend, not both.")
        sys.exit(1)
    # Dashboard starts with the stack unless --no-frontend (--with-frontend is a no-op, kept for old scripts)
    include_dashboard = not args.no_frontend

    available = _check_port_conflicts(selected, include_dashboard, auto_stop=args.replace_running)
    # Remove dashboard key (handled separately) but remember if it survived
    dash_ok = available.pop("dashboard", None) is not None if include_dashboard else False
    include_dashboard = include_dashboard and dash_ok
    selected = {s: p for s, p in selected.items() if s in available}

    if not selected:
        _log_err("No services can start -- all ports are occupied.")
        sys.exit(1)

    # Spawn ────────────────────────────────────────────────────────────────
    manager = ProcessManager(root=root)

    def _handle_signal(sig, _frame):
        manager.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    _log(f"Starting {len(selected)} service(s) ...\n")

    ordered_pairs = list(selected.items())
    color_idx = 0

    def _spawn(name: str, port: int) -> None:
        nonlocal color_idx
        manager.spawn_service(
            name,
            port,
            _color(color_idx),
            reload=args.reload,
            log_level=args.log_level,
            env_override=env_override,
        )
        color_idx += 1
        time.sleep(0.4)

    # Clean up owned children even when a later startup step fails.
    try:
        # DuckDB (Windows): nexus-data must open the DB file for write before any
        # other process opens it read-only (e.g. nexus-api), or startup races and fails.
        if "nexus-data" in selected:
            _spawn("nexus-data", selected["nexus-data"])
            manager.start_streaming()
            health_url = f"http://127.0.0.1:{selected['nexus-data']}/health"
            _log("Waiting for nexus-data (DuckDB writer) before starting peers …")
            if not _wait_for_http_ok(health_url):
                _log_err("nexus-data did not become healthy in time — see logs above.")
                manager.shutdown()
                sys.exit(1)
            _log_ok("nexus-data ready")

        for name, port in ordered_pairs:
            if name == "nexus-data" and "nexus-data" in selected:
                continue
            _spawn(name, port)

        if include_dashboard:
            manager.spawn_dashboard(_color(color_idx), env_override=env_override)

        manager.start_streaming()

        _log_ok("\nAll services launched. Press Ctrl+C to stop.\n")

        # Health-check loop ────────────────────────────────────────────────────
        while True:
            time.sleep(10)
            manager.health_check(
                reload=args.reload,
                log_level=args.log_level,
                env_override=env_override,
            )
            alive = sum(1 for p in manager.processes if p.proc.poll() is None)
            if alive == 0:
                _log_err("All processes have exited.")
                break
    except KeyboardInterrupt:
        pass
    finally:
        manager.shutdown()


if __name__ == "__main__":
    _reexec_in_venv_if_available()
    main()
