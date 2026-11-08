"""
extract_mt5_history.py — جلب التاريخ مباشرة من MT5 بدون الاعتماد على nexus-data

يستخدم MT5 Python مباشرة (بما أن السكريبت يعمل بنفس العملية)، ويجلب الشموع
لرمز معين (XAUUSD / BTCUSD) لفترة محددة. يحفظ الناتج بملف JSON قابل للاستخدام
بواسطة import_historical_data.py.

الاستخدام:
  python scripts/extract_mt5_history.py --symbol XAUUSD --timeframe H1 --days 90
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

# إعداد المسار للنموذج المشترك
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import MetaTrader5 as mt5  # noqa: E402

TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}

OUT_FORMATS = ("json", "csv")


def get_account_info():
    """عرض معلومات الحساب للتأكد من الاتصال."""
    acc = mt5.account_info()
    if acc is None:
        raise RuntimeError("لا يمكن جلب معلومات الحساب — تأكد من اتصال MT5")
    return acc


def collect_rates(symbol, tf_code, start_dt, end_dt):
    """جلب الشموع بقطاعات 10 أيام لضمان تحميل التاريخ كاملاً."""
    collected = {}
    current = start_dt
    while current < end_dt:
        segment_end = min(current + timedelta(days=10), end_dt)
        rates = mt5.copy_rates_range(symbol, tf_code, current, segment_end)
        if rates:
            for r in rates:
                collected[int(r["time"])] = r
        current = segment_end
    return sorted(collected.values(), key=lambda r: int(r["time"]))


def format_bar(r):
    return {
        "timestamp": datetime.fromtimestamp(int(r["time"]), tz=timezone.utc).isoformat(),
        "open": float(r["open"]),
        "high": float(r["high"]),
        "low": float(r["low"]),
        "close": float(r["close"]),
        "volume": float(r.get("tick_volume") or r.get("volume") or 0),
    }


def main():
    parser = argparse.ArgumentParser(description="جلب التاريخ من MT5")
    parser.add_argument("--symbol", default="XAUUSD", help="الرمز")
    parser.add_argument("--timeframe", default="H1", choices=list(TIMEFRAME_MAP),
                        help="الفترة")
    parser.add_argument("--days", type=int, default=90, help="الأيام")
    parser.add_argument("--output", help="اسم ملف الإخراج")
    parser.add_argument("--format", choices=OUT_FORMATS, default="json",
                        help="صيغة الإخراج")
    args = parser.parse_args()

    output = args.output or f"{args.symbol}_{args.timeframe}_mt5_history.json"
    if not output.endswith((".json", ".csv")):
        output += ".json"

    # إذا لم يكن MT5 مفتوحًا، نفتح نافذة منفصلة أولاً
    if not mt5.initialize():
        code, msg = mt5.last_error()
        # إذا كان الفشل بسبب فتح نافذة أخرى، نستخدم اتصال مباشر
        if code == -10005:
            # تأكد من فتح نافذة MT5 يدويًا على الحساب المطلوب
            print("تنبيه: MT5 غير متصل ([{}] {})".format(code, msg))
            print("يرجى فتح MetaTrader 5 والتأكد من:")
            print("  1. الاتصال بالحساب حساب MT5 من .env (MT5_LOGIN) على خادم.env (MT5_SERVER)")
            print("  2. إضافة XAUUSD إلى Market Watch")
            print("انتظر حتى يكون MT5 متصلاً، ثم أعد تشغيل السكربت")
            raise SystemExit(1)
        # محاولة فتح نافذة جديدة
        print("جاري فتح نافذة MT5...")
        try:
            subprocess.Popen([
                "C:\\Program Files\\MetaTrader 5\\terminal64.exe",
                "--from-command",
            ], shell=False, creationflags=subprocess.CREATE_NO_WINDOW)
            print("تم فتح MT5 - يرجى تسجيل الدخول بحساب حساب MT5 من .env (MT5_LOGIN)")
            print("انتظر حتى يتم الاتصال، ثم أعد تشغيل السكربت")
            raise SystemExit(1)
        except FileNotFoundError:
            raise SystemExit(
                "لم يتم العثور على terminal64.exe - تأكد من مسار MT5 الصحيح"
            )

    try:
        acc = get_account_info()
        print(f"الحساب: {acc.login} — {acc.server}")
        print(f"العملة: {args.symbol}  الفترة: {args.timeframe}  الأيام: {args.days}")

        end = datetime.now(tz=timezone.utc)
        start = end - timedelta(days=args.days)

        rates = collect_rates(args.symbol, TIMEFRAME_MAP[args.timeframe],
                              start, end)

        if not rates:
            raise SystemExit("لم يتم جلب أي شموع — تأكد من وجود تاريخ محمول")

        bars = [format_bar(r) for r in rates]
        n = len(bars)

        if args.format == "json":
            with open(output, "w", encoding="utf-8") as f:
                json.dump(bars, f, indent=2, ensure_ascii=False)
        else:
            import csv
            with open(output, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
                for b in bars:
                    w.writerow([b["timestamp"], b["open"], b["high"],
                                b["low"], b["close"], b["volume"]])

        print("\nتم جلب {} شمعة وحفظها في: {}".format(n, os.path.abspath(output)))
        print("   من: {}".format(bars[0]['timestamp']))
        print("   إلى: {}".format(bars[-1]['timestamp']))

    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
