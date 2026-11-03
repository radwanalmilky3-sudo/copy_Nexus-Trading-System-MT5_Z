"""Exercise real login against a disposable Redis/data/API stack.

Uses fresh credentials and database files; never loads the project's .env.
Logs and the disposable database are retained under the system temp folder.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]


def request(url: str, payload=None, token: str | None = None, internal_secret: str | None = None, method: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if internal_secret:
        headers["X-Nexus-Internal-Secret"] = internal_secret
    data = json.dumps(payload).encode() if payload is not None else None
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers,method=method), timeout=15) as response:
        return json.load(response)


def wait_ready(url: str, process: subprocess.Popen, timeout: float = 120) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"test service exited ({process.returncode}); inspect temporary logs")
        try:
            result = request(url)
            if result.get("ready") is True or result.get("service") == "nexus-api":
                return result
        except (OSError, urllib.error.URLError, ValueError):
            pass
        time.sleep(0.3)
    raise TimeoutError(f"test service did not become ready: {url}")


def main() -> None:
    for port in (6381, 19011, 19010):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    temp = Path(tempfile.mkdtemp(prefix="nexus-services-smoke-"))
    print(json.dumps({"temporary_directory": str(temp)}), flush=True)
    env = dict(os.environ)
    secret, pin, password = secrets.token_urlsafe(40), secrets.token_hex(12), secrets.token_urlsafe(24)
    env.update({
        "REDIS_URL": "redis://127.0.0.1:6381/0",
        "DUCKDB_PATH": str(temp / "test.duckdb"),
        "TRIAL_REGISTRY_DB": str(temp / "trials.duckdb"),
        "NEXUS_USER_MEDIA_DIR": str(temp / "avatars"),
        "NEXUS_DATA_URL": "http://127.0.0.1:19011",
        "NEXUS_INTERNAL_API_SECRET": secret,
        "NEXUS_JWT_SECRET": secrets.token_urlsafe(48),
        "NEXUS_SECRET_KEY": secrets.token_urlsafe(48),
        "NEXUS_ADMIN_PIN": pin,
        "DEFAULT_BROKER": "disabled", "MT5_LOGIN": "0", "MT5_PASSWORD": "",
        "ENABLE_IBKR": "", "ENABLE_CCXT": "", "CCXT_API_KEY": "",
        "NEXUS_TRADING_MODE": "paper", "NEXUS_SETTINGS__AUTO_TRADE_ENABLED": "false",
        "STREAM_SYMBOLS": "", "PYTHONUNBUFFERED": "1",
    })
    processes: list[subprocess.Popen] = []
    logs = []

    def start(name: str, command: list[str]):
        log = (temp / f"{name}.log").open("w", encoding="utf-8")
        logs.append(log)
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0)
        processes.append(process)
        return process

    try:
        redis = start("redis", [r"C:\redis5\redis-server.exe", "--port", "6381", "--bind", "127.0.0.1", "--save", "", "--appendonly", "no", "--dir", str(temp)])
        data = start("data", [sys.executable, "-m", "uvicorn", "services.nexus_data.main:app", "--host", "127.0.0.1", "--port", "19011"])
        health = wait_ready("http://127.0.0.1:19011/health", data)
        assert health["duckdb"] is True and health["redis"] is True
        assert health["mt5"] is False
        print(json.dumps({"data_ready": True, "brokers_disabled": True}), flush=True)
        api = start("api", [sys.executable, "-m", "uvicorn", "services.nexus_api.main:app", "--host", "127.0.0.1", "--port", "19010"])
        wait_ready("http://127.0.0.1:19010/health", api)
        request("http://127.0.0.1:19010/api/v2/auth/bootstrap", {
            "username": "smoke_admin", "full_name": "Isolated smoke test", "password": password, "admin_pin": pin,
        })
        login = request("http://127.0.0.1:19010/api/v2/auth/login", {"username": "smoke_admin", "password": password})
        profile = request("http://127.0.0.1:19010/api/v2/auth/me", token=login["token"])
        assert profile["username"] == "smoke_admin"
        assert "super_admin" in profile["roles"]
        print(json.dumps({"bootstrap": "passed", "login": "passed", "auth_me": "passed", "production_database_used": False}), flush=True)
        family = {"family_id": "smoke-family", "p_values": [0.01, 0.2]}
        first = request("http://127.0.0.1:19011/internal/trials/family", family, internal_secret=secret)
        retry = request("http://127.0.0.1:19011/internal/trials/family", family, internal_secret=secret)
        rows = request("http://127.0.0.1:19011/internal/trials/get", {"family_id": "smoke-family"}, internal_secret=secret)
        assert first == retry and len(rows["result"]) == 2
        print(json.dumps({"trial_registry": "passed", "idempotent_retry": "passed"}), flush=True)
        other_password=secrets.token_urlsafe(24)
        request('http://127.0.0.1:19010/api/admin/users',{'username':'smoke_other','full_name':'Second isolated user',
                'password':other_password,'role_id':'super_admin'},token=login['token'])
        other=request('http://127.0.0.1:19010/api/v2/auth/login',{'username':'smoke_other','password':other_password})
        base='http://127.0.0.1:19010/api/brokers'
        p=request(base+'/profiles',{'name':'Mine','broker_name':'OneRoyal'},token=login['token'])
        a=request(base+'/accounts',{'profile_id':p['profile_id'],'label':'Demo','server':'OneRoyal-Demo','login':'123456','account_kind':'demo'},token=login['token'])
        path=base+'/accounts/'+a['account_id']
        assert request(base+'/profiles',token=other['token'])==[]
        try:
            request(path,token=other['token'])
            raise AssertionError('cross-owner account leaked')
        except urllib.error.HTTPError as exc:
            assert exc.code==404
        settings=a['settings'];settings['transition'].update(session_start_date='2026-11-02',during_market_closure='yes',from_offset_seconds=10800,to_offset_seconds=7200)
        saved=request(path+'/settings',{'expected_version':1,'settings':settings},token=login['token'],method='PUT')
        assert saved['version']==2 and saved['runtime_effective'] is False and saved['connection_state']=='unconnected'
        assert saved['settings']['transition']['effective_at_utc'] is None
        try:
            request(path+'/settings',{'expected_version':1,'settings':settings},token=login['token'],method='PUT')
            raise AssertionError('stale version overwrote settings')
        except urllib.error.HTTPError as exc:
            assert exc.code==409
        assert request(path,token=login['token'])['version']==2
        if os.name=='nt': data.send_signal(signal.CTRL_BREAK_EVENT)
        else: data.terminate()
        try: data.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if os.name=='nt': subprocess.run(['taskkill','/PID',str(data.pid),'/T','/F'],capture_output=True)
            else: data.kill()
            data.wait(timeout=10)
        data=start('data-restarted',[sys.executable,'-m','uvicorn','services.nexus_data.main:app','--host','127.0.0.1','--port','19011'])
        wait_ready('http://127.0.0.1:19011/health',data)
        reloaded=request(path,token=login['token'])
        assert reloaded['version']==2 and reloaded['settings']['transition']['session_start_date']=='2026-11-02'
        print(json.dumps({'broker_settings':'passed','cross_owner_denied':True,'durable_version':2,'exact_utc_not_invented':True,'runtime_effective':False}),flush=True)
        print(json.dumps({'broker_settings_service_restart_persistence':'passed'}),flush=True)
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                if os.name=='nt': process.send_signal(signal.CTRL_BREAK_EVENT)
                else: process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    if os.name=='nt': subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
                    else: process.kill()
                    process.wait(timeout=10)
        for log in logs:
            log.close()


if __name__ == "__main__":
    main()
