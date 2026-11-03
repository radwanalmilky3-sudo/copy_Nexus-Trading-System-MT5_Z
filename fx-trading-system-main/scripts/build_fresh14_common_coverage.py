#!/usr/bin/env python3
"""Build common-coverage universe manifest from the fresh 14 Dukascopy DBs.

Read-only: scans each DB's ``hours`` table (hour_utc + status only, no tick
decompression). Computes joint ok-hour coverage for the full 14, slow-horizon
12, and FIX-W 9 universes, plus New-York-close (17:00 ET, DST-aware) daily
common coverage. Produces a JSON manifest + per-symbol TSV.

The ``hours`` table stores only candidate market hours (weekends excluded);
ok + no_data per symbol ≈ 63138 = expected_candidate_hours for 2016-2025.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

DATA = Path("data/dukascopy_sqlite_fresh_20160101_20260101_v111")
OUT = Path("outputs/fresh14_common_coverage_20260802")
RECEIVE = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD", "USDCAD",
    "EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "CADJPY", "USDNOK", "USDSEK",
]
SLOW12 = RECEIVE[:12]
FIXW9 = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD",
         "USDCAD", "USDNOK", "USDSEK"]
UNIFIED_START = datetime(2016, 1, 1, tzinfo=timezone.utc)
UNIFIED_END = datetime(2026, 1, 1, tzinfo=timezone.utc)
NY = ZoneInfo("America/New_York")


def _to_utc_hour(epoch_int: int) -> datetime:
    """hour_utc is stored as second-level UTC epoch (audited: matches ISO hours)."""
    return datetime.fromtimestamp(epoch_int, tz=timezone.utc).replace(minute=0, second=0, microsecond=0)


def load_status(symbol: str) -> dict[datetime, str]:
    db = DATA / f"{symbol}.sqlite"
    uri = f"file:{db.resolve().as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        rows = con.execute("SELECT hour_utc, status FROM hours").fetchall()
    finally:
        con.close()
    return {_to_utc_hour(int(h)): s for h, s in rows}


def joint_ok(statuses: dict[str, dict[datetime, str]], symbols: list[str]) -> dict:
    maps = [statuses[s] for s in symbols]
    common_hours = set.intersection(*(set(m) for m in maps)) if maps else set()
    all_ok = [h for h in common_hours if all(m.get(h) == "ok" for m in maps)]
    all_no_data = [h for h in common_hours if all(m.get(h) == "no_data" for m in maps)]
    mixed = len(common_hours) - len(all_ok) - len(all_no_data)
    return {
        "symbols": symbols,
        "n_symbols": len(symbols),
        "common_candidate_hours": len(common_hours),
        "joint_ok_hours": len(all_ok),
        "joint_no_data_hours": len(all_no_data),
        "mixed_status_hours": mixed,
        "ok_fraction_of_common": round(len(all_ok) / len(common_hours), 6) if common_hours else None,
        "first_ok_hour_utc": min(all_ok).isoformat() if all_ok else None,
        "last_ok_hour_utc": max(all_ok).isoformat() if all_ok else None,
    }


def ny_close_daily(statuses: dict[str, dict[datetime, str]], symbols: list[str]) -> dict:
    """17:00 ET cut-off hour, DST-aware. A day is covered iff that UTC hour is ok in all symbols."""
    maps = [statuses[s] for s in symbols]
    covered = 0
    total = 0
    first = last = None
    d = UNIFIED_START.date()
    end = (UNIFIED_END - timedelta(days=1)).date()
    while d <= end:
        cut_local = datetime(d.year, d.month, d.day, 17, 0, tzinfo=NY)
        cut_utc = cut_local.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        # Only count weekdays as FX session days (weekend hours absent from table)
        if d.weekday() < 5 and all(m.get(cut_utc) == "ok" for m in maps):
            covered += 1
            if first is None:
                first = cut_utc.isoformat()
            last = cut_utc.isoformat()
        if d.weekday() < 5:
            total += 1
        d += timedelta(days=1)
    return {
        "symbols": symbols,
        "n_symbols": len(symbols),
        "ny_close_17ET_weekday_days": total,
        "covered_days": covered,
        "coverage_fraction": round(covered / total, 6) if total else None,
        "first_covered_day_cut_utc": first,
        "last_covered_day_cut_utc": last,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    statuses = {s: load_status(s) for s in RECEIVE}

    # per-symbol sanity (cross-check vs batch manifest counts)
    per_symbol = []
    for s in RECEIVE:
        m = statuses[s]
        ok = sum(1 for v in m.values() if v == "ok")
        nd = sum(1 for v in m.values() if v == "no_data")
        per_symbol.append({"symbol": s, "rows": len(m), "ok_hours": ok,
                           "no_data_hours": nd, "other": len(m) - ok - nd})

    manifest = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "data_directory": str(DATA.resolve()),
        "unified_range": {"start_utc": UNIFIED_START.isoformat(),
                          "end_exclusive_utc": UNIFIED_END.isoformat()},
        "note": "Read-only scan of hours.status; no tick decompression. DST via zoneinfo America/New_York.",
        "per_symbol": per_symbol,
        "hour_joint_coverage": {
            "full_14": joint_ok(statuses, RECEIVE),
            "slow_horizon_12": joint_ok(statuses, SLOW12),
            "fix_w_9": joint_ok(statuses, FIXW9),
        },
        "ny_close_daily_coverage": {
            "full_14": ny_close_daily(statuses, RECEIVE),
            "slow_horizon_12": ny_close_daily(statuses, SLOW12),
            "fix_w_9": ny_close_daily(statuses, FIXW9),
        },
    }
    out_json = OUT / "common_coverage_manifest.json"
    out_json.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    tsv = OUT / "per_symbol_hours.tsv"
    with tsv.open("w") as fh:
        fh.write("symbol\trows\tok_hours\tno_data_hours\tother\n")
        for r in per_symbol:
            fh.write(f"{r['symbol']}\t{r['rows']}\t{r['ok_hours']}\t{r['no_data_hours']}\t{r['other']}\n")

    h = manifest["hour_joint_coverage"]
    d = manifest["ny_close_daily_coverage"]
    print(f"saved {out_json}")
    print(f"hour joint ok: full14={h['full_14']['joint_ok_hours']} "
          f"slow12={h['slow_horizon_12']['joint_ok_hours']} "
          f"fixw9={h['fix_w_9']['joint_ok_hours']}")
    print(f"NY-close daily: full14={d['full_14']['covered_days']}/{d['full_14']['ny_close_17ET_weekday_days']} "
          f"slow12={d['slow_horizon_12']['covered_days']}/{d['slow_horizon_12']['ny_close_17ET_weekday_days']} "
          f"fixw9={d['fix_w_9']['covered_days']}/{d['fix_w_9']['ny_close_17ET_weekday_days']}")


if __name__ == "__main__":
    import json  # noqa
    main()
