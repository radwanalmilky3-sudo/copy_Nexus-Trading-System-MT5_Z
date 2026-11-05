#!/usr/bin/env bash
# qa/live_gate.sh — بوابة التحقق الحي الكاملة في نداء واحد (المنصة تقتل
# العمليات الخلفية بين النداءات — فالإقلاع والفحص يجب أن يعيشا معاً).
set -uo pipefail
cd /home/z/my-project/Nexus-Trading-System-MT5
LOG=logs/run_supervisor.log
REDIS_BIN=/home/z/my-project/redis/bin/redis-server
REDIS_CLI=/home/z/my-project/redis/bin/redis-cli

echo "== 1) redis =="
"$REDIS_BIN" --port 6379 --bind 127.0.0.1 --daemonize yes \
  --dir /home/z/my-project/redis --save "" --appendonly no \
  --logfile /home/z/my-project/redis/redis.log >/dev/null 2>&1
sleep 1
"$REDIS_CLI" -p 6379 ping

echo "== 2) fleet start (run.py --paper) =="
mkdir -p logs data
nohup setsid venv-nexus/bin/python3 run.py --paper > "$LOG" 2>&1 &
SUP=$!
echo "supervisor pid $SUP"

echo "== 3) poll 9 services =="
deadline=$(( $(date +%s) + 180 ))
last=""
while [ "$(date +%s)" -lt "$deadline" ]; do
  ok=0; line=""
  for p in 9000 9001 9002 9003 9004 9005 9006 9007 9008; do
    c=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:$p/health" 2>/dev/null)
    [ "$c" = "200" ] && ok=$((ok+1))
    line="$line $p:$c"
  done
  dash=$(curl -s -o /dev/null -w '%{http_code}' --max-time 4 "http://127.0.0.1:3100/login" 2>/dev/null)
  last="stack=$ok/9 dash=$dash |$line"
  if [ "$ok" -ge 9 ] && { [ "$dash" = "200" ] || [ "$dash" = "307" ]; }; then break; fi
  sleep 5
done
echo "POLL_RESULT: $last"

echo "== 4) bootstrap owner (fresh DB) =="
PIN=$(rg -o '^NEXUS_ADMIN_PIN=(.+)$' -r '$1' .env | head -1)
PASS=$(rg -o '^NEXUS_ADMIN_PASSWORD=(.+)$' -r '$1' .env | head -1)
boot=$(curl -s --max-time 15 -X POST http://127.0.0.1:9000/api/v2/auth/bootstrap \
  -H 'Content-Type: application/json' \
  -d "{\"admin_pin\":\"$PIN\",\"username\":\"redhwan\",\"full_name\":\"Owner\",\"password\":\"$PASS\",\"language\":\"ar\",\"timezone\":\"Asia/Aden\"}")
echo "bootstrap: $(echo "$boot" | head -c 120)"

echo "== 5) security headers live =="
echo "-- :9000/health --"
curl -s -D - -o /dev/null --max-time 5 http://127.0.0.1:9000/health | rg -i "x-frame|x-content|referrer-policy|permissions-policy|content-security|cache-control" || echo "HEADERS_MISSING_9000"
echo "-- :3100/login --"
curl -s -D - -o /dev/null --max-time 6 http://127.0.0.1:3100/login | rg -i "x-frame|x-content|referrer-policy|permissions-policy|content-security|cache-control" || echo "HEADERS_MISSING_3100"

echo "== 6) 9004 LLM probe (بعد مهلة استقرار 50ث — APR-001: تقلبات الإقلاع تُصلح ذاتياً) =="
sleep 50
curl -s --max-time 20 http://127.0.0.1:9004/health | head -c 260; echo

echo "== 7) Playwright UI suite (5 scenarios) =="
timeout 240 /home/z/.venv/bin/python qa/playwright/run_suite.py 2>&1 | tail -15
echo "SUITE_EXIT=$?"

echo "== 8) supervisor log tail =="
tail -5 "$LOG"
