"""Run the local settings/research UI without broker login or order services.

Settings-mode contract (task 1 of the audit remediation plan):
- spawns only nexus-data, nexus-api and the dashboard: no broker auto-login
  (MT5_LOGIN=0 disables nexus-data's auto connect), no executor/risk/agents
  and therefore no trading listener;
- readiness is a ready health payload — nexus-data additionally proves the
  DuckDB writer — never a bare open HTTP port;
- the data gate runs before the API spawn so the API never races the DuckDB
  writer;
- any startup failure shuts down every process this script spawned (no
  orphans) and leaves foreign listeners on busy ports untouched;
- the dashboard is spawned through the ProcessManager so its restart attempts
  stay capped instead of being an unmonitored raw process.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import dotenv_values  # noqa: E402

import run  # noqa: E402
from run import ProcessManager  # noqa: E402

SETTINGS_SERVICES = (("nexus-data", 9001), ("nexus-api", 9000))
DASHBOARD_PORT = run.DASHBOARD_PORT
READY_TIMEOUT_S = 300.0
READY_INTERVAL_S = 0.5


def listening(port: int) -> bool:
    with socket.socket() as client:
        client.settimeout(1)
        return client.connect_ex(("127.0.0.1", port)) == 0


def build_env(base: Optional[dict] = None) -> dict:
    """Settings-mode child environment: trading credentials forced off."""
    source = dict(os.environ) if base is None else dict(base)
    source.update(
        {k: v for k, v in dotenv_values(ROOT / ".env").items() if v is not None}
    )
    source.update(
        MT5_LOGIN="0",
        MT5_PASSWORD="",
        ENABLE_IBKR="",
        ENABLE_CCXT="",
        NEXUS_TRADING_MODE="paper",
        NEXUS_MT5_ISOLATED="1",
        PYTHONIOENCODING="utf-8",
        PYTHONUTF8="1",
        NEXUS_DATA_URL="http://127.0.0.1:9001",
        NEXT_PUBLIC_API_URL="http://127.0.0.1:9000",
        NEXT_PUBLIC_WS_URL="ws://127.0.0.1:9000",
        NEXT_PUBLIC_WS_GATEWAY_URL="ws://127.0.0.1:9000",
    )
    return source


def check_prerequisites(env: dict) -> None:
    """Fail before spawning anything when Redis cannot answer PING."""
    if not run._check_redis(env.get("REDIS_URL", "")):
        raise RuntimeError(
            "Redis unavailable — settings stack not started (nothing spawned)"
        )


def _fetch_health(url: str) -> tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=3) as response:  # noqa: S310
        return (response.getcode() or 0), response.read()


def wait_ready(
    url: str,
    *,
    name: str,
    require_duckdb: bool = False,
    timeout_s: float = READY_TIMEOUT_S,
    interval_s: float = READY_INTERVAL_S,
) -> bool:
    """True only when the health payload reports ready.

    A 200 response alone never counts: the JSON body must contain
    ``ready is True``.  The data service must additionally prove the DuckDB
    writer (``duckdb is True``) so the API cannot race its owner.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            status, body = _fetch_health(url)
        except (urllib.error.URLError, TimeoutError, OSError):
            status, body = 0, b""
        if status == 200:
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict) and data.get("ready") is True:
                if not require_duckdb or data.get("duckdb") is True:
                    return True
        time.sleep(interval_s)
    return False


def run_settings_stack(
    manager,
    env: dict,
    *,
    listening_fn: Optional[Callable[[int], bool]] = None,
    wait_fn: Optional[Callable[..., bool]] = None,
    ready_timeout_s: float = READY_TIMEOUT_S,
) -> list:
    """Spawn and gate the settings stack; roll back everything on failure."""
    is_listening = listening_fn or listening
    wait = wait_fn or wait_ready
    spawned: list = []

    try:
        check_prerequisites(env)
        for name, port in SETTINGS_SERVICES:
            if not is_listening(port):
                manager.spawn_service(name, port, "", env_override=env)
                spawned.append(name)
                manager.start_streaming()
            gate_url = f"http://127.0.0.1:{port}/health"
            if not wait(
                gate_url,
                name=name,
                require_duckdb=(name == "nexus-data"),
                timeout_s=ready_timeout_s,
            ):
                raise RuntimeError(
                    f"{name} did not report ready within {ready_timeout_s:.0f}s; "
                    "aborting settings startup"
                )
        if not is_listening(DASHBOARD_PORT):
            manager.spawn_dashboard("", env_override=env)
            spawned.append("dashboard")
    except BaseException:
        manager.shutdown()
        raise
    return spawned


def main() -> None:
    env = build_env()
    print(
        "SETTINGS ONLY: broker auto-login disabled; no executor/risk/agents started",
        flush=True,
    )
    manager = ProcessManager(root=ROOT)
    run_settings_stack(manager, env)

    # Auxiliary read-only gallery for the audit screenshots (not a Nexus
    # service, no trading port). Never deleted or restarted by the stack.
    if not listening(4188):
        subprocess.Popen(
            [sys.executable, "-m", "http.server", "4188", "--bind", "127.0.0.1",
             "--directory", str(ROOT / "project_audit" / "ui-audit-20261020")],
            env=env,
        )

    while True:
        manager.health_check(env_override=env)
        time.sleep(10)


if __name__ == "__main__":
    main()
