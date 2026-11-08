"""
test_historical_import.py — فحص صحة إدخال البيانات التاريخية

يقوم بـ:
1. الاتصال بقاعدة DuckDB والتحقق من وجود جداول OHLCV
2. التحقق من اكتمال البيانات (غياب القيم الفارغة)
3. فحص تسلسل التواريخ
4. عرض إحصائيات أساسية لكل رمز/timeframe

الاستخدام:
  python scripts/test_historical_import.py
"""
import argparse
import sys
from datetime import datetime

import duckdb

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))

DB_PATH = "data/nexus.duckdb"


def check_table(conn, table: str) -> dict:
    """فحص جدول OHLCV ورجوع إحصائيات."""
    q = f"""
        SELECT
            symbol,
            timeframe,
            COUNT(*) as bar_count,
            MIN(timestamp) as first_bar,
            MAX(timestamp) as last_bar,
            COUNT(*) - COUNT(close) as missing_close,
            COUNT(*) - COUNT(open) as missing_open,
            COUNT(*) - COUNT(high) as missing_high,
            COUNT(*) - COUNT(low) as missing_low,
            COUNT(*) - COUNT(volume) as missing_volume
        FROM {table}
        GROUP BY symbol, timeframe
        ORDER BY symbol, timeframe
    """
    rows = conn.execute(q).fetchall()
    return [
        {
            "symbol": r[0],
            "timeframe": r[1],
            "count": int(r[2]),
            "first": str(r[3]),
            "last": str(r[4]),
            "missing_close": int(r[5]),
            "missing_open": int(r[6]),
            "missing_high": int(r[7]),
            "missing_low": int(r[8]),
            "missing_volume": int(r[9]),
        }
        for r in rows
    ]


def check_series_validity(conn, symbol: str, timeframe: str) -> dict:
    """فحص استمرارية السلسلة الزمنية وجدول الفجوات."""
    q = f"""
        WITH bars AS (
            SELECT timestamp,
                   EXTRACT(EPOCH FROM (timestamp - LAG(timestamp) OVER (ORDER BY timestamp))) as gap_sec
            FROM ohlcv
            WHERE symbol = ? AND timeframe = ?
        )
        SELECT COUNT(*) as n_bars,
               COUNT(*) FILTER (WHERE gap_sec IS NULL) as n_gaps,
               MAX(gap_sec) as max_gap_sec
        FROM bars
    """
    r = conn.execute(q, (symbol, timeframe)).fetchone()
    q2 = f"""
        SELECT timestamp, gap_sec
        FROM (
            SELECT timestamp,
                   EXTRACT(EPOCH FROM (timestamp - LAG(timestamp) OVER (ORDER BY timestamp))) as gap_sec
            FROM ohlcv
            WHERE symbol = ? AND timeframe = ?
        ) t
        WHERE gap_sec > 0
        ORDER BY timestamp DESC
        LIMIT 20
    """
    gaps = conn.execute(q2, (symbol, timeframe)).fetchall()
    return {"n_bars": int(r[0]), "gaps": int(r[1]), "max_gap_sec": int(r[2]), "gaps_details": gaps}


def main():
    parser = argparse.ArgumentParser(description="فحص إدخال البيانات التاريخية")
    parser.add_argument("--symbol", default="XAUUSD", help="الرمز للفحص التفصيلي")
    parser.add_argument("--timeframe", default="H1", help="الفترة للفحص التفصيلي")
    parser.add_argument("--table", default="ohlcv", help="اسم الجدول")
    args = parser.parse_args()

    try:
        conn = duckdb.connect(DB_PATH)
    except Exception as exc:
        print(f"❌ فشل الاتصال بقاعدة البيانات: {exc}")
        sys.exit(1)

    print(f"\n📊 قاعدة البيانات: {DB_PATH}")
    print("=" * 70)

    # 1. الجداول المتاحة
    tables = conn.execute("SHOW TABLES").fetchall()
    print(f"\n📁 الجداول المتاحة ({len(tables)}):")
    for t in tables:
        print(f"   - {t[0]}")

    # 2. إحصائيات OHLCV
    print("\n📈 إحصائيات OHLCV:")
    data = check_table(conn, args.table)
    if not data:
        print("   ⚠️  لا توجد بيانات في جدول OHLCV")
    else:
        print(f"   {'symbol':12} {'tf':7} {'count':>8} {'first':<22} {'last':<22} {'missing_close':>14}")
        for d in data:
            print(f"   {d['symbol']:12} {d['timeframe']:7} {d['count']:>8} {d['first']:<22} {d['last']:<22} {d['missing_close']:>14}")

    # 3. التحقق من السلسلة
    print("\n🔍 التحقق من سلسلة XAUUSD H1:")
    stats = check_series_validity(conn, args.symbol, args.timeframe)
    print(f"   عدد الشموع:     {stats['n_bars']}")
    print(f"   عدد الفجوات:    {stats['gaps']}")
    print(f"   أكبر فجوة (ث):  {stats['max_gap_sec']}")
    if stats['gaps_details']:
        print("   آخر 5 فجوات:")
        for ts, gap in stats['gaps_details'][:5]:
            print(f"      {ts}  ->  {gap} ثانية")

    # 4. فحص التناقضات البسيطة (high < low)
    q3 = f"""
        SELECT symbol, timeframe,
               COUNT(*) FILTER (WHERE high < low) as n_invalid
        FROM ohlcv
        GROUP BY symbol, timeframe
        HAVING COUNT(*) FILTER (WHERE high < low) > 0
    """
    bad = conn.execute(q3).fetchall()
    if bad:
        print("\n⚠️  بيانات غير صحيحة (high < low):")
        for r in bad:
            print(f"   {r[0]}/{r[1]}: {r[2]} شموع")
    else:
        print("\n✅ لا توجد تناقضات في high/low")

    # 5. فحص أسعار قريبة من الصفر
    q4 = f"""
        SELECT symbol, timeframe,
               COUNT(*) FILTER (WHERE close <= 0) as n_zero_close
        FROM ohlcv
        GROUP BY symbol, timeframe
        HAVING COUNT(*) FILTER (WHERE close <= 0) > 0
    """
    zeros = conn.execute(q4).fetchall()
    if zeros:
        print("\n⚠️  أسعار close <= 0:")
        for r in zeros:
            print(f"   {r[0]}/{r[1]}: {r[2]}")
    else:
        print("✅ لا توجد أسعار close <= 0")

    print("\n✅ اكتمل الفحص")


if __name__ == "__main__":
    main()
