"""
diag_mt5.py — تشخيص اتصال MT5 بنفس الطريقة التي تستخدمها nexus-data.

يشغّل مُعامل MT5 المعزول (mt5_worker.py) في عملية فرعية ويعرض النتيجة.
الاستخدام:
    python scripts/diag_mt5.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


async def main() -> int:
    load_env()
    from services.nexus_data.mt5_connector import _mt5_worker

    login = os.getenv("MT5_LOGIN", "0")
    password = os.getenv("MT5_PASSWORD", "")
    server = os.getenv("MT5_SERVER", "")
    path = os.getenv("MT5_PATH", "")

    print("== الإعدادات ==")
    print(f"  MT5_LOGIN  = {login}")
    print(f"  MT5_SERVER = {server}")
    print(f"  MT5_PATH   = {path}")
    print(f"  MT5_PASSWORD = {'***' if password else '(فارغ)'}")
    print()

    print("== 1) ping ببيانات الدخول (مثل nexus-data عند الإقلاع) ==")
    try:
        data = await _mt5_worker(
            {
                "op": "ping",
                "login": login,
                "password": password,
                "server": server,
                "path": path,
            },
            timeout_sec=60.0,
        )
        print(f"  OK = {data.get('ok')}  connected = {data.get('connected')}")
        acct = data.get("account") or {}
        if acct:
            print(f"  الحساب الفعلي = {acct.get('login')} @ {acct.get('server')}")
    except Exception as exc:
        print(f"  FAILED: {type(exc).__name__}: {exc}")

    print()
    print("== 2) ping بزرق النافذة المفتوحة (use_terminal) ==")
    try:
        data = await _mt5_worker(
            {"op": "ping", "use_terminal": True, "path": path},
            timeout_sec=60.0,
        )
        print(f"  OK = {data.get('ok')}  connected = {data.get('connected')}")
        acct = data.get("account") or {}
        if acct:
            print(f"  الحساب الفعلي = {acct.get('login')} @ {acct.get('server')}")
    except Exception as exc:
        print(f"  FAILED: {type(exc).__name__}: {exc}")

    print()
    print("== 3) رموز XAUUSD/BTCUSD ==")
    try:
        data = await _mt5_worker(
            {
                "op": "symbols",
                "use_terminal": True,
                "path": path,
                "expected_login": login,
                "expected_server": server,
                "limit": 5000,
            },
            timeout_sec=60.0,
        )
        names = {s["name"] for s in data.get("symbols", [])}
        for want in ("XAUUSD", "BTCUSD", "XAUUSD.", "GOLD"):
            print(f"  {want}: {'موجود' if want in names else 'غير موجود'}")
        print(f"  إجمالي الرموز = {len(names)}")
    except Exception as exc:
        print(f"  FAILED: {type(exc).__name__}: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
