#!/usr/bin/env zsh
# Run read-only G0 deep microstructure audit on the fresh 14 DBs, serially.
# Writes per-symbol PASS/FAIL + elapsed to a summary; full stderr/stdout to a log.
set -u
cd /Users/open/fx-trading-system
DATA=data/dukascopy_sqlite_fresh_20160101_20260101_v111
OUT=outputs/dukascopy_audit_fresh_v111_20260802
SUMMARY=$OUT/_audit_run_summary.txt
LOG=$OUT/_audit_run.log
mkdir -p "$OUT"
ALL="EURUSD GBPUSD USDJPY USDCHF AUDUSD NZDUSD USDCAD EURGBP EURJPY GBPJPY AUDJPY CADJPY USDNOK USDSEK"
SYMBOLS="${1:-$ALL}"
echo "start $(date -u +%Y-%m-%dT%H:%M:%SZ) symbols=$SYMBOLS" >> "$SUMMARY"
for s in ${=SYMBOLS}; do
  sha=$(awk '{print $1}' "$DATA/${s}.sqlite.sha256")
  t0=$SECONDS
  uv run python scripts/audit_dukascopy_sqlite.py \
    "$DATA/${s}.sqlite" --symbol "$s" --output-dir "$OUT" \
    --expected-file-sha256 "$sha" >> "$LOG" 2>&1
  rc=$?
  dt=$((SECONDS - t0))
  printf "%s rc=%d elapsed=%dm%02ds sha=%s\n" "$s" "$rc" $((dt/60)) $((dt%60)) "${sha:0:12}" >> "$SUMMARY"
done
echo "done $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$SUMMARY"
