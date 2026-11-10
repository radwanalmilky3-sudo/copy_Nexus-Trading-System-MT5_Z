#!/usr/bin/env python3
"""فحص جاهزية بيانات NEXUS للقراءة فقط. لا يكتب شيئًا."""
import argparse
import sys
import duckdb

SYMBOLS = ["XAUUSD","XAGUSD","BTCUSD","ETHUSD","DXY","EURUSD","GBPUSD",
           "USDJPY","USDCHF","AUDUSD","USDCAD","US30","US500","WTI"]

TF_SECONDS = {"M1":60,"M5":300,"M15":900,"M30":1800,"H1":3600,"H4":14400,"D1":86400}

OHLCV_REQUIRED = ["symbol","timeframe","timestamp","open","high","low","close",
                  "source","quality","fetched_at"]
OHLCV_NEW = ["bar_open_server_time","bar_open_utc","utc_offset_seconds",
             "ask_open","ask_high","ask_low","ask_close",
             "spread_points","real_volume","row_checksum","session_code"]
TABLES_REQUIRED = ["ohlcv","ohlcv_backfill_runs","broker_server_time_offsets",
                   "broker_symbols","bar_tick_aggregates","symbol_property_snapshots"]
TABLES_OPTIONAL = ["ingest_jobs","fx_route","training_samples"]

results = []

def rec(status, name, detail=""):
    results.append((status, name, detail))

def q(con, sql):
    try:
        return con.execute(sql).fetchall()
    except Exception as e:
        return e

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/nexus.duckdb")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--symbols", default=",".join(SYMBOLS))
    a = ap.parse_args()
    symbols = [s.strip() for s in a.symbols.split(",") if s.strip()]

    try:
        con = duckdb.connect(a.db, read_only=True)
    except Exception as e:
        print(f"CANNOT OPEN DB: {e}")
        sys.exit(2)
    con.execute("SET TimeZone='UTC'")

    tables = {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables").fetchall()}
    for t in TABLES_REQUIRED:
        rec("PASS" if t in tables else "FAIL", f"table {t}")
    for t in TABLES_OPTIONAL:
        rec("PASS" if t in tables else "WARN", f"table {t} (optional)")

    if "ohlcv" not in tables:
        return report()

    cols = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='ohlcv'").fetchall()}
    for c in OHLCV_REQUIRED:
        rec("PASS" if c in cols else "FAIL", f"ohlcv.{c}")
    for c in OHLCV_NEW:
        rec("PASS" if c in cols else "FAIL", f"ohlcv.{c} (new field)")

    if "timestamp" not in cols:
        rec("SKIPPED", "data checks", "ohlcv.timestamp missing")
        return report()

    # 1) تكرار
    r = q(con, "SELECT COUNT(*) FROM (SELECT symbol,timeframe,timestamp FROM ohlcv "
               "GROUP BY ALL HAVING COUNT(*)>1)")
    if isinstance(r, Exception): rec("FAIL", "duplicates", str(r))
    else: rec("PASS" if r[0][0]==0 else "FAIL", "no duplicate (symbol,tf,timestamp)", f"{r[0][0]} groups")

    # 2) قيود OHLC
    r = q(con, "SELECT COUNT(*) FROM ohlcv WHERE high < GREATEST(open,close) "
               "OR low > LEAST(open,close) OR high < low")
    if isinstance(r, Exception): rec("FAIL", "OHLC constraints", str(r))
    else: rec("PASS" if r[0][0]==0 else "FAIL", "OHLC constraints", f"{r[0][0]} bad rows")

    # 3) الشمعة المتكونة غير موجودة
    bad_forming = 0
    for tf, sec in TF_SECONDS.items():
        r = q(con, f"SELECT COUNT(*) FROM ohlcv WHERE timeframe='{tf}' "
                   f"AND epoch(timestamp) + {sec} > epoch(now())")
        if isinstance(r, Exception):
            rec("FAIL", "forming bar excluded", str(r)); bad_forming = None; break
        bad_forming += r[0][0]
    if bad_forming is not None:
        rec("PASS" if bad_forming==0 else "FAIL", "forming bar excluded", f"{bad_forming} rows")

    # 4) اتساق UTC مع الإزاحة
    if "bar_open_utc" in cols:
        r = q(con, "SELECT COUNT(*) FROM ohlcv WHERE bar_open_utc IS NOT NULL "
                   "AND bar_open_server_time IS NOT NULL AND utc_offset_seconds IS NOT NULL "
                   "AND epoch(bar_open_utc) <> epoch(bar_open_server_time) - utc_offset_seconds")
        if isinstance(r, Exception): rec("FAIL", "UTC = server - offset", str(r))
        else: rec("PASS" if r[0][0]==0 else "FAIL", "UTC = server - offset", f"{r[0][0]} mismatches")

        r = q(con, "SELECT COUNT(*), COUNT(bar_open_utc) FROM ohlcv")
        if not isinstance(r, Exception):
            total, filled = r[0]
            pct = 100*filled/total if total else 0
            rec("PASS" if pct>=99.9 else "FAIL", "bar_open_utc filled", f"{pct:.2f}%")

    # 5) جدول الإزاحات
    if "broker_server_time_offsets" in tables:
        r = q(con, "SELECT COUNT(*) FROM broker_server_time_offsets")
        n = 0 if isinstance(r, Exception) else r[0][0]
        rec("PASS" if n>0 else "FAIL", "offset table not empty", f"{n} rows")

    # 6) تغطية Ask لكل رمز
    # Phase 2 (development plan): رموز بلا عمق -> ask_source='unavailable'.
    # Bars whose source provably serves no tick stream are an explicit,
    # documented limitation — coverage is measured over the bars we EXPECT
    # to carry asks (total minus marked), and an all-marked symbol is a
    # WARN (visible, but not a pipeline failure).
    if "ask_close" in cols:
        r = q(con, "SELECT symbol, COUNT(*), COUNT(ask_close), "
                   "COUNT(*) FILTER (WHERE ask_source = 'unavailable') "
                   "FROM ohlcv GROUP BY symbol")
        if isinstance(r, Exception): rec("FAIL", "ask coverage", str(r))
        else:
            for sym, total, ask, unavail in r:
                expected = total - unavail
                if expected <= 0:
                    rec("WARN", f"ask coverage {sym}",
                        f"0.0% — all {total} bars ask_source='unavailable' "
                        "(broker serves no tick stream)")
                    continue
                pct = 100*ask/expected
                st = "PASS" if pct>=95 else ("WARN" if pct>0 else "FAIL")
                rec(st, f"ask coverage {sym}", f"{pct:.1f}%")

    # 7) تجميع الـ ticks منطقي
    if "bar_tick_aggregates" in tables:
        r = q(con, "SELECT COUNT(*) FROM bar_tick_aggregates WHERE tick_count<0 "
                   "OR buy_tick_count+sell_tick_count > tick_count")
        if isinstance(r, Exception): rec("FAIL", "tick aggregates consistent", str(r))
        else: rec("PASS" if r[0][0]==0 else "FAIL", "tick aggregates consistent", f"{r[0][0]} bad")

    # 8) ربط كل رمز من الـ14 بالوسيط
    if "broker_symbols" in tables:
        r = q(con, "SELECT column_name FROM information_schema.columns WHERE table_name='broker_symbols'")
        bcols = {x[0] for x in r} if not isinstance(r, Exception) else set()
        key = "instrument_code" if "instrument_code" in bcols else None
        if key is None:
            rec("WARN", "broker_symbols key column", f"columns found: {sorted(bcols)}")
        else:
            r = q(con, f"SELECT {key} FROM broker_symbols")
            mapped = {x[0] for x in r} if not isinstance(r, Exception) else set()
            for s in symbols:
                rec("PASS" if s in mapped else "FAIL", f"broker mapping {s}")

    # 9) لقطات المواصفات لكل رمز
    if "symbol_property_snapshots" in tables:
        r = q(con, "SELECT column_name FROM information_schema.columns "
                   "WHERE table_name='symbol_property_snapshots'")
        scols = {x[0] for x in r} if not isinstance(r, Exception) else set()
        if "symbol" not in scols:
            rec("WARN", "snapshot symbol column", f"columns: {sorted(scols)}; verify manually")
        else:
            r = q(con, "SELECT symbol, COUNT(*) FROM symbol_property_snapshots GROUP BY symbol")
            have = dict(r) if not isinstance(r, Exception) else {}
            for s in symbols:
                rec("PASS" if have.get(s,0)>0 else "FAIL", f"spec snapshot {s}",
                    f"{have.get(s,0)} snapshots")

    # 10) فجوات غير مفسرة في M1 (heuristic)
    r = q(con, f"""
        WITH m AS (
          SELECT symbol, timestamp,
                 LAG(timestamp) OVER (PARTITION BY symbol ORDER BY timestamp) prev
          FROM ohlcv WHERE timeframe='M1'
            AND timestamp >= now() - INTERVAL {a.days} DAY)
        SELECT symbol, COUNT(*) FROM m
        WHERE epoch(timestamp)-epoch(prev) > 60 AND epoch(timestamp)-epoch(prev) < 7200
        GROUP BY symbol""")
    if isinstance(r, Exception): rec("WARN", "M1 gaps", str(r))
    else:
        if not r: rec("PASS", f"M1 gaps last {a.days}d", "none under 2h")
        for sym, n in r: rec("WARN", f"M1 gaps {sym}", f"{n} gaps under 2h (review)")

    # 11) تسريب في عينات التدريب (إن وُجد الجدول)
    if "training_samples" in tables:
        r = q(con, "SELECT COUNT(*) FROM training_samples "
                   "WHERE feature_available_at > decision_time")
        if isinstance(r, Exception): rec("FAIL", "no leakage in training_samples", str(r))
        else: rec("PASS" if r[0][0]==0 else "FAIL", "no leakage in training_samples",
                  f"{r[0][0]} leaking rows")

    return report()

def report():
    w = max((len(n) for _,n,_ in results), default=20)
    for st, name, det in results:
        print(f"{st:8} {name:<{w}}  {det}")
    fails = sum(1 for s,_,_ in results if s=="FAIL")
    warns = sum(1 for s,_,_ in results if s=="WARN")
    print(f"\nSUMMARY: {'NOT READY' if fails else 'READY'} | FAIL={fails} WARN={warns}")
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
