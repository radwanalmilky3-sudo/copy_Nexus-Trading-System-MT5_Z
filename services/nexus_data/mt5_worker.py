"""
Isolated MetaTrader 5 worker for nexus-data.

The MetaTrader5 Python extension can crash the host process on Windows
(STATUS_HEAP_CORRUPTION / 0xC0000374). nexus-data calls this helper in a
short-lived subprocess so a native crash kills only the worker, not the
FastAPI service.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any


def _fail(message: str, code: int = 1) -> None:
    print(json.dumps({"ok": False, "error": message}), flush=True)
    raise SystemExit(code)


def _timeframes(mt5) -> dict[str, int]:
    return {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }


def _timeframe_seconds(timeframe: str) -> int:
    return {"M1": 60, "M5": 300, "M15": 900, "M30": 1800,
            "H1": 3600, "H4": 14400, "D1": 86400}[timeframe]


def _initialise(mt5, payload: dict[str, Any]) -> None:
    # Credentials come from the environment, never the stdin payload. The
    # payload is the arg to asyncio's communicate(), whose internal `input`
    # local is dumped by rich tracebacks on any subprocess error — sending
    # the password there printed it in clear text in the logs. Env vars are
    # not shown in tracebacks. (Payload is still read as a fallback so an
    # older caller keeps working.)
    if payload.get("use_terminal"):
        path = payload.get("path") or ""
        if not path:
            _fail("MT5 terminal path is not configured", 2)
        if not mt5.initialize(path=path):
            code, msg = mt5.last_error()
            _fail(f"MT5 initialize failed: [{code}] {msg}", 2)
        return
    kwargs: dict[str, Any] = {
        "login": int(os.getenv("MT5_LOGIN") or payload.get("login") or 0),
        "password": os.getenv("MT5_PASSWORD") or payload.get("password") or "",
        "server": os.getenv("MT5_SERVER") or payload.get("server") or "",
    }
    path = payload.get("path") or ""
    if path:
        kwargs["path"] = path
    if not mt5.initialize(**kwargs):
        code, msg = mt5.last_error()
        _fail(f"MT5 initialize failed: [{code}] {msg}", 2)


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception as exc:
        _fail(f"bad worker payload: {exc}")

    try:
        import MetaTrader5 as mt5  # type: ignore[import-untyped]
    except Exception as exc:
        _fail(f"MetaTrader5 import failed: {exc}", 2)

    op = payload.get("op")
    symbol = str(payload.get("symbol") or "").upper().replace("/", "")
    broker_symbol = str(payload.get("broker_symbol") or symbol)

    try:
        _initialise(mt5, payload)
        if payload.get('use_terminal') and op in ('research_history','research_live'):
            account=mt5.account_info()
            if account is None or str(account.login)!=str(payload.get('expected_login')) or account.server!=payload.get('expected_server'):
                _fail('Selected account does not match the open MT5 terminal',9)
        if symbol and not mt5.symbol_select(broker_symbol, True):
            _fail(f"MT5 symbol_select failed for {broker_symbol!r}", 3)

        if op in ('research_history','research_live'):
            tf_name=str(payload.get('timeframe','M15'))
            tf=_timeframes(mt5).get(tf_name)
            if tf is None: _fail('Unsupported timeframe',5)
            if op=='research_history':
                start=datetime.fromisoformat(payload['start'].replace('Z','+00:00'))
                end=datetime.fromisoformat(payload['end'].replace('Z','+00:00'))
                rates=mt5.copy_rates_range(broker_symbol,tf,start,end)
            else:
                rates=mt5.copy_rates_from_pos(broker_symbol,tf,0,100)
            if rates is None: _fail('MT5 history unavailable',6)
            if len(rates)>50000: _fail('Requested period exceeds 50000 candles; choose a shorter period',6)
            current=mt5.copy_rates_from_pos(broker_symbol,tf,0,1)
            if current is None or not len(current):_fail('Cannot verify the currently forming candle',6)
            cutoff=int(current[0]['time'])
            bars=[{'time':int(r['time']),'open':float(r['open']),'high':float(r['high']),'low':float(r['low']),'close':float(r['close']),'volume':float(r['tick_volume'])} for r in rates if int(r['time'])<cutoff]
            tick=mt5.symbol_info_tick(broker_symbol) if op=='research_live' else None
            again=mt5.account_info()
            if again is None or str(again.login)!=str(payload.get('expected_login')) or again.server!=payload.get('expected_server'):
                _fail('MT5 account changed during read',9)
            out={'ok':True,'bars':bars,'tick':{'bid':tick.bid,'ask':tick.ask,'time':tick.time} if tick else None,'captured_at':datetime.now(timezone.utc).isoformat()}
        elif op == "ping":
            info = mt5.account_info()
            out = {
                "ok": True,
                "connected": info is not None,
                "account": info._asdict() if info is not None else None,
            }
        elif op == "tick":
            tick = mt5.symbol_info_tick(broker_symbol)
            if tick is None:
                _fail(f"MT5 returned no tick for {broker_symbol!r}", 4)
            out = {
                "ok": True,
                "tick": {
                    "symbol": symbol,
                    "bid": float(tick.bid),
                    "ask": float(tick.ask),
                    "timestamp": datetime.fromtimestamp(tick.time, tz=timezone.utc).isoformat(),
                },
            }
        elif op == "ohlcv":
            tf = _timeframes(mt5).get(str(payload.get("timeframe") or "M15"))
            if tf is None:
                _fail(f"unsupported timeframe: {payload.get('timeframe')}", 5)
            count = int(payload.get("count") or 500)
            if count < 1:
                _fail("count must be at least 1", 5)
            rates = mt5.copy_rates_from_pos(broker_symbol, tf, 0, count)
            if rates is None or len(rates) == 0:
                _fail(f"MT5 returned no OHLCV for {broker_symbol!r}", 6)
            rates = list(rates)
            now_epoch = int(datetime.now(timezone.utc).timestamp())
            if now_epoch - int(rates[-1]["time"]) < _timeframe_seconds(str(payload.get("timeframe") or "M15")):
                rates = rates[:-1]
            if not rates:
                _fail(f"MT5 returned no completed OHLCV for {broker_symbol!r}", 6)
            out = {
                "ok": True,
                "bars": [
                    {
                        "symbol": symbol,
                        "timeframe": payload.get("timeframe") or "M15",
                        "open": float(r["open"]),
                        "high": float(r["high"]),
                        "low": float(r["low"]),
                        "close": float(r["close"]),
                        "volume": float(r["tick_volume"]),
                        "timestamp": datetime.fromtimestamp(r["time"], tz=timezone.utc).isoformat(),
                    }
                    for r in rates[-count:]
                ],
            }
        elif op == "ohlcv_range":
            tf_name = str(payload.get("timeframe") or "M15")
            tf = _timeframes(mt5).get(tf_name)
            if tf is None:
                _fail(f"unsupported timeframe: {tf_name}", 5)
            start = datetime.fromisoformat(str(payload["start"]).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(payload["end"]).replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            if start > end:
                _fail("start must be less than or equal to end", 5)
            rates = mt5.copy_rates_range(broker_symbol, tf, start, end)
            if rates is None or len(rates) == 0:
                _fail(f"MT5 returned no OHLCV for {broker_symbol!r} in range", 6)
            rates = list(rates)
            now_epoch = int(datetime.now(timezone.utc).timestamp())
            if now_epoch - int(rates[-1]["time"]) < _timeframe_seconds(tf_name):
                rates = rates[:-1]
            if not rates:
                _fail("MT5 returned no completed OHLCV in range", 6)
            out = {
                "ok": True,
                "bars": [
                    {
                        "symbol": symbol,
                        "timeframe": tf_name,
                        "open": float(r["open"]), "high": float(r["high"]),
                        "low": float(r["low"]), "close": float(r["close"]),
                        "volume": float(r["tick_volume"]),
                        "timestamp": datetime.fromtimestamp(r["time"], tz=timezone.utc).isoformat(),
                    }
                    for r in rates
                ],
            }
        elif op == "account":
            info = mt5.account_info()
            if info is None:
                _fail("MT5 account_info returned None", 7)
            out = {"ok": True, "account": info._asdict()}
        elif op == "symbols":
            account = mt5.account_info()
            if account is None or str(account.login)!=str(payload.get('expected_login')) or account.server!=payload.get('expected_server'):
                _fail('Selected account does not match the open MT5 terminal', 9)
            limit = min(max(int(payload.get("limit") or 10000), 1), 10000)
            rows = list(mt5.symbols_get() or [])[:limit]
            out = {"ok": True, "symbols": [
                {
                    "category": (str(getattr(r, "path", "") or "").split("\\", 1)[0] or "غير مصنف"),
                    "name": str(getattr(r, "name", "")),
                    "description": str(getattr(r, "description", "") or ""),
                    "path": str(getattr(r, "path", "") or ""),
                    "visible": bool(getattr(r, "visible", False)),
                } for r in rows if str(getattr(r, "name", ""))
            ]}
        else:
            _fail(f"unsupported op: {op}", 8)
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass

    print(json.dumps(out, default=str), flush=True)


if __name__ == "__main__":
    main()
