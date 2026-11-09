"""
import_historical_data.py — إدخال بيانات OHLCV تاريخية إلى قاعدة بيانات nexus-data
لأغراض الاختبار والتدريب (وضع Paper).

يتقبل الملف ثلاث صيغ:
  1. CSV   — الأعمدة الإلزامية: timestamp, open, high, low, close, volume
  2. JSON  — مصفوفة كائنات بنفس الحقول
  3. MT5   — جلب تلقائي من خادم MT5 المحدد في .env (يحتاج MT5 مفتوحًا)

العملة الافتراضية: XAUUSD على Timeframe H1 (يمكن تغييرها).
البيانات تُخزن في DuckDB (data/nexus.duckdb) ويُنشر حدث Redis لاستهلاك الخدمات الأخرى.

استخدام:
  python scripts/import_historical_data.py --source csv --path data/XAUUSD_H1_2026.csv
  python scripts/import_historical_data.py --source mt5 --symbol XAUUSD --timeframe H1 --days 60
  python scripts/import_historical_data.py --source json --path data/btc_candles.json --symbol BTCUSD

يفضل تشغيله بعد بدء nexus-data:
  python run.py   (أو bootstrap_ensemble.py الذي يدير الأسطول كاملاً)
"""
from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import httpx
import structlog

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:  # cp1256-safe output regardless of the calling console (PowerShell 5.1)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except Exception:
    pass

DATA_URL = os.getenv("NEXUS_DATA_URL", "http://localhost:9001")

log = structlog.get_logger("import_history")


def parse_datetime(value):
    """تحويل خيط زمني إلى datetime بتوقيت UTC — يرفض أي timestamp بلا منطقة زمنية.

    المرحلة 1 (خطة التطوير 2026-11-09): الافتراضي الصامت «الناive = UTC» كان
    يوهم كل شمعة مستوردة بفارق توقيت الخادم (+2h على OneRoyal-Demo). أي سلسلة
    تاريخ يجب أن تحمل إزاحة صريحة (2026-11-09 20:00:00+00:00)؛ الأرقام (unix
    epoch) UTC بطبيعتها وتُقبل كما هي.
    """
    value = str(value).strip()
    aware_formats = (
        "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S.%f%z",
    )
    naive_formats = (
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S", "%d/%m/%Y %H:%M:%S",
    )
    for fmt in aware_formats:
        try:
            return datetime.strptime(value, fmt).astimezone(timezone.utc)
        except ValueError:
            continue
    for fmt in naive_formats:
        try:
            datetime.strptime(value, fmt)
            break  # parses, but carries no timezone → rejected below
        except ValueError:
            continue
    else:
        # Not a datetime string at all — maybe a unix epoch (UTC by definition).
        try:
            num = float(value)
        except ValueError:
            num = None
        if num is not None:
            if num > 1e12:
                return datetime.fromtimestamp(num / 1000, tz=timezone.utc)
            return datetime.fromtimestamp(num, tz=timezone.utc)
        raise ValueError(
            f"timestamp {value!r} is not a recognizable date, epoch, "
            "or timezone-aware timestamp"
        )
    raise ValueError(
        f"timestamp {value!r} has no timezone — supply an explicit UTC offset "
        "(e.g. '2026-11-09 20:00:00+00:00'); refusing to assume UTC"
    )


def read_csv(path):
    rows, out = [], []
    with open(path, newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(row)
    if not rows:
        raise ValueError("ملف CSV فارغ")
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = required - {k.lower() for k in rows[0]}
    if missing:
        raise ValueError(f"أعمدة CSV ناقصة: {missing}")
    for row in rows:
        out.append({
            "timestamp": parse_datetime(row["timestamp"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row.get("volume") or 0),
        })
    return out


def read_json(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("candles") or data.get("data") or []
    if not data:
        raise ValueError("مصفوفة JSON فارغة")
    return parse_bars(data)


def parse_bars(data):
    out = []
    for bar in data:
        if isinstance(bar, (int, float)):
            bar = {"timestamp": bar}
        ts = bar.get("timestamp") or bar.get("time")
        out.append({
            # str/int/float all flow through parse_datetime: strings must be
            # timezone-aware (Phase 1), epochs are UTC by definition.
            "timestamp": parse_datetime(ts) if isinstance(ts, (str, int, float)) else ts,
            "open": float(bar.get("open")),
            "high": float(bar.get("high")),
            "low": float(bar.get("low")),
            "close": float(bar.get("close")),
            "volume": float(bar.get("volume") or bar.get("tick_volume") or 0),
        })
    return out


def read_mt5(symbol, timeframe, days):
    """جلب الشموع من MT5 عبر nexus-data research API."""
    from datetime import datetime as dt
    symbol = symbol.upper().replace("/", "")
    end = dt.now(tz=timezone.utc)
    start = end - timedelta(days=days)
    log.info("جاري جلب التاريخ من MT5", symbol=symbol, timeframe=timeframe, days=days)

    def _fetch():
        async def _inner():
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{DATA_URL}/api/data/research/ohlcvs",
                    json={
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                    },
                )
                if not resp.is_success:
                    raise RuntimeError(
                        f"nexus-data failed: {resp.status_code} {resp.text[:300]}"
                    )
                return resp.json()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(asyncio.run, _inner()).result()

    data = _fetch()
    bars = data.get("bars") or data.get("candles") or []
    if not bars:
        raise RuntimeError("nexus-data لم يعد أي شموع — تأكد من أن MT5 مفتوح ومتصل")
    return parse_bars(bars)


def push_ohlcv(ohlcvs, symbol, timeframe):
    """إدخال الشموع عبر API nexus-data (/candles/<symbol>/<timeframe>)."""
    payload = {
        "symbol": symbol.upper().replace("/", ""),
        "timeframe": timeframe,
        "candles": [
            {
                "timestamp": c["timestamp"].isoformat(),
                "open": c["open"],
                "high": c["high"],
                "low": c["low"],
                "close": c["close"],
                "volume": c["volume"],
            }
            for c in sorted(ohlcvs, key=lambda c: c["timestamp"])
        ],
    }
    url = f"{DATA_URL}/candles/{payload['symbol']}/{timeframe}"
    log.info("جاري إرسال الشموع إلى nexus-data", url=url, n=len(payload["candles"]))

    def _push():
        async def _inner():
            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(url, json=payload)
                if resp.is_success:
                    return resp.json()
                # POST فشل — نجرب PUT
                resp2 = await client.put(url, json=payload)
                return resp2.json() if resp2.is_success else resp2
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(asyncio.run, _inner()).result()

    result = _push()
    log.info(
        "نتيجة الإرسال",
        ok=result.get("ok"),
        written=result.get("written"),
        error=result.get("error", result.get("detail", "")),
    )
    return result


def verify_history(symbol, timeframe):
    """التحقق من عدد الشموع المخزنة بعد الإدخال."""
    async def _check():
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{DATA_URL}/ohlcv/{symbol}/{timeframe}/provenance"
            )
            return resp.json() if resp.is_success else resp.text

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        data = ex.submit(asyncio.run, _check()).result()
    log.info("تأكيد البيانات المخزنة", provenance=data)


def main():
    parser = argparse.ArgumentParser(description="إدخال بيانات OHLCV تاريخية للاختبار")
    parser.add_argument("--source", choices=["csv", "json", "mt5"], default="csv",
                        help="مصدر البيانات")
    parser.add_argument("--path", help="مسار ملف CSV/JSON")
    parser.add_argument("--symbol", default="XAUUSD", help="الرمز (XAUUSD / BTCUSD)")
    parser.add_argument("--timeframe", default="H1", help="الفترة (M1/M5/M15/H1/H4/D1)")
    parser.add_argument("--days", type=int, default=60, help="أيام للتاريخ (لـ MT5)")
    parser.add_argument("--dry-run", action="store_true", help="إظهار ما سيتم فعله فقط")
    parser.add_argument("--replace", action="store_true",
                        help="استبدال الشموع الموجودة (PUT بدلاً من POST)")
    args = parser.parse_args()

    if args.source == "mt5":
        if not args.path:
            args.path = "mt5"
    elif not args.path:
        parser.error("--path مطلوب لمصدر CSV/JSON")

    if args.dry_run:
        print(f"[dry-run] source={args.source} path={args.path} symbol={args.symbol} tf={args.timeframe}")
        return

    try:
        if args.source == "csv":
            ohlcvs = read_csv(args.path)
        elif args.source == "json":
            ohlcvs = read_json(args.path)
        else:
            ohlcvs = read_mt5(args.symbol, args.timeframe, args.days)

        if not ohlcvs:
            log.error("لا توجد بيانات قابلة للقراءة")
            sys.exit(1)

        ohlcvs = [c for c in ohlcvs if c["timestamp"]]
        first, last = ohlcvs[0]["timestamp"], ohlcvs[-1]["timestamp"]
        n = len(ohlcvs)
        log.info("تمت قراءة البيانات", source=args.source, n=n,
                 from_ts=first.isoformat(), to_ts=last.isoformat())

        if not args.replace:
            push_ohlcv(ohlcvs, args.symbol, args.timeframe)
        else:

            def _replace_inner():
                async def _inner():
                    payload = {
                        "symbol": args.symbol.upper().replace("/", ""),
                        "timeframe": args.timeframe,
                        "candles": [
                            {
                                "timestamp": c["timestamp"].isoformat(),
                                "open": c["open"], "high": c["high"],
                                "low": c["low"], "close": c["close"],
                                "volume": c["volume"],
                            }
                            for c in sorted(ohlcvs, key=lambda c: c["timestamp"])
                        ],
                    }
                    url = f"{DATA_URL}/candles/{payload['symbol']}/{args.timeframe}"
                    async with httpx.AsyncClient(timeout=300.0) as client:
                        resp = await client.put(url, json=payload)
                        return resp.json() if resp.is_success else resp.text
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    return ex.submit(asyncio.run, _inner()).result()

            result = _replace_inner()
            log.info("تم الاستبدال الكامل", result=result)

        verify_history(args.symbol, args.timeframe)

    except Exception as exc:
        log.exception("فشل إدخال البيانات", error=str(exc))
        sys.exit(1)

    print("\n✅ اكتمل إدخال البيانات التاريخية بنجاح")
    print(f"   الرمـــز: {args.symbol}   الفترة: {args.timeframe}   العدد: {n}")


if __name__ == "__main__":
    main()
