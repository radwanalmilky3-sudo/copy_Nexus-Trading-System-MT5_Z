#!/usr/bin/env bash
# nexus_heal.sh — الشفاء الذاتي لبيئة نكسس السحابية
# ---------------------------------------------------------------------------
# يغطي: redis · ممرر :3000 · dashboard :3100 · أسطول 9000-9008 · طزاجة النسخ
# الفلسفة:
#   • الأسطول الحي يديره مشرف run.py (يعيد إقلاع الأبناء تلقائياً) — هذا
#     السكربت لا يقتل ولا يلمس عمليات حية على المنافذ (D9).
#   • إن غاب المشرف كلياً → إقلاع رسمي واحد: run.py --paper.
#   • إن كانت البيئة نفسها مفقودة (تدوير صندوق) → nexus_rebuild.sh أولاً.
#   • 9004 يرد 503 أثناء تقلبات مزوّد GLM المجاني (APR-001 خيار C: مهلة 12ث
#     + TTL 45ث تُصلح ذاتياً خلال ~40ث) — يُعد DEGRADED لا ساقطاً، ولا
#     إعادة إقلاع له (إعادة الإقلاع تزيد العاصفة سوءاً).
#   • خط الطزاجة: backup=OK|STALE_<h>h|UNKNOWN (عتبة 26س) + تنبيه عند 3
#     دورات متتالية غير سليمة.
# الاستخدام: bash scripts/nexus_heal.sh   (مهمة cron كل 5 دقائق)
# ---------------------------------------------------------------------------
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
LOG_DIR="$REPO/logs"; mkdir -p "$LOG_DIR"
REDIS_BIN="/home/z/my-project/redis/bin/redis-server"
REDIS_CLI="/home/z/my-project/redis/bin/redis-cli"
FWD_SCRIPT="$REPO/scripts/port3000_forward.py"
THRESHOLD_H=26

log() { echo "[$(date '+%H:%M:%S')] $*"; }

http_code() { curl -s -o /dev/null -w '%{http_code}' --max-time "${2:-4}" "$1" 2>/dev/null; }
listening() { ss -ltn 2>/dev/null | awk '{print $4}' | rg -q "(:|\.|$1)\$" <<<"$1" && return 0; return 1; }
port_up() { ss -ltn 2>/dev/null | rg -q ":$1[[:space:]]"; }

# ── 0) إن كانت البيئة مفقودة كلياً → إعادة بناء كاملة أولاً ────────────────
if [ ! -x venv-nexus/bin/python3 ]; then
  log "environment missing (recycled box?) → nexus_rebuild.sh"
  bash scripts/nexus_rebuild.sh >> "$LOG_DIR/rebuild.log" 2>&1 || { log "REBUILD_FAILED"; exit 2; }
fi

# ── 1) redis ────────────────────────────────────────────────────────────────
redis_state="DOWN"
if [ -x "$REDIS_CLI" ] && "$REDIS_CLI" -p 6379 ping 2>/dev/null | rg -q PONG; then
  redis_state="OK"
else
  if [ -x "$REDIS_BIN" ]; then
    "$REDIS_BIN" --port 6379 --bind 127.0.0.1 --daemonize yes \
      --dir /home/z/my-project/redis --save "" --appendonly no \
      --logfile /home/z/my-project/redis/redis.log >/dev/null 2>&1
    sleep 1
    "$REDIS_CLI" -p 6379 ping 2>/dev/null | rg -q PONG && redis_state="STARTED"
  else
    redis_state="NO_BIN"
  fi
fi

# ── 2) ممرر :3000 → :3100 ──────────────────────────────────────────────────
fwd_state="OK"
if ! port_up 3000; then
  if [ -f "$FWD_SCRIPT" ]; then
    nohup setsid venv-nexus/bin/python3 "$FWD_SCRIPT" >> "$LOG_DIR/port3000_forward.log" 2>&1 &
    sleep 1
    port_up 3000 && fwd_state="STARTED" || fwd_state="FAIL"
  else
    fwd_state="NO_SCRIPT"
  fi
fi

# ── 3) مشرف run.py / الأسطول ───────────────────────────────────────────────
supervisor_up() { pgrep -f "python3 (run\.py|--split-by-|.*run\.py) --paper" >/dev/null 2>&1 || pgrep -f "run\.py --paper" >/dev/null 2>&1; }
stack_ok=0; stack_total=0; degraded=""
for port in 9000 9001 9002 9003 9004 9005 9006 9007 9008; do
  stack_total=$((stack_total+1))
  code=$(http_code "http://127.0.0.1:$port/health" 4)
  case "$code" in
    200) stack_ok=$((stack_ok+1)) ;;
    503)
      if [ "$port" = "9004" ]; then
        stack_ok=$((stack_ok+1)); degraded="${degraded}9004:degraded_llm "
      else
        degraded="${degraded}$port:503 "
      fi ;;
    *) degraded="${degraded}$port:$code " ;;
  esac
done

if ! supervisor_up; then
  if [ "$stack_ok" -eq 0 ]; then
    log "supervisor absent & stack down → official start (run.py --paper)"
    nohup setsid venv-nexus/bin/python3 run.py --paper > "$LOG_DIR/run_supervisor.log" 2>&1 &
    sleep 20
  else
    # خدمات حية بلا مشرف (إقلاع يدوي قديم) — لا نلمسها، نبلّغ فقط
    degraded="${degraded}supervisor:absent "
  fi
fi

# dashboard
dash_code=$(http_code "http://127.0.0.1:3100/login" 6)
dash_state="UP"
if [ "$dash_code" != "200" ] && [ "$dash_code" != "307" ] && [ "$dash_code" != "302" ]; then
  dash_state="DOWN($dash_code)"
fi

# ── 4) حارس node_modules (المنصة تمسح المجلدات الكبيرة) ────────────────────
nm_state="OK"
if [ ! -e dashboard/node_modules/.package-lock.json ]; then
  log "node_modules wiped → npm ci (guard)…"
  ( cd dashboard && npm ci --no-audit --no-fund >> "$LOG_DIR/npm_ci.log" 2>&1 ) \
    && nm_state="REINSTALLED" || nm_state="FAIL"
fi

# ── 5) طزاجة النسخ الاحتياطي ────────────────────────────────────────────────
backup_state="UNKNOWN"
marker="$LOG_DIR/last_backup.txt"
if [ -f "$marker" ]; then
  ts=$(head -1 "$marker" 2>/dev/null | rg -o '[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}' | head -1 || true)
  if [ -n "$ts" ]; then
    age_h=$(( ( $(date +%s) - $(date -d "$ts" +%s 2>/dev/null || echo 0) ) / 3600 ))
    if [ "$age_h" -le "$THRESHOLD_H" ]; then backup_state="OK"
    else backup_state="STALE_${age_h}h"; fi
  fi
fi
cnt_file="$LOG_DIR/heal_backup_fail_count"
if [ "$backup_state" = "OK" ]; then echo 0 > "$cnt_file"
else
  n=$(cat "$cnt_file" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "$cnt_file"
  if [ "$n" -ge 3 ]; then
    backup_state="$backup_state ALERT_OWNER($n)"
  fi
fi

echo "heal: redis=$redis_state forwarder=$fwd_state dashboard=$dash_state stack=$stack_ok/$stack_total node_modules=$nm_state backup=$backup_state${degraded:+ degraded=[$degraded]}"
