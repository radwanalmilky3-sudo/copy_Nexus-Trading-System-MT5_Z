#!/usr/bin/env bash
# nexus_rebuild.sh — إعادة بناء بيئة نكسس من الصفر (صندوق مُمسوح/مُدوَّر)
# ---------------------------------------------------------------------------
# الغرض: بعد أي تدوير للصندوق (محو كامل لـ/home/z/my-project) يرجع هذا
# السكربت المنظومة للعمل بأمر واحد، من مستودع GitHub فقط:
#   venv-nexus (torch CPU أولاً) → redis من المصدر إن غاب → npm ci →
#   بناء إنتاجي → مجلد data/ → فحص .env
# لا يُقلع الأسطول هنا — ذلك عمل run.py (الإقلاع الرسمي).
#
# الاستخدام:
#   bash scripts/nexus_rebuild.sh              # كل شيء الناقص
#   bash scripts/nexus_rebuild.sh --skip-build # تخطّ بناء الداشبورد
# ---------------------------------------------------------------------------
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
LOG_DIR="$REPO/logs"; mkdir -p "$LOG_DIR"
log() { echo "[$(date '+%H:%M:%S')] $*"; }

SKIP_BUILD=0
[ "${1:-}" = "--skip-build" ] && SKIP_BUILD=1

# ── 1) venv-nexus ───────────────────────────────────────────────────────────
if [ ! -x venv-nexus/bin/python3 ]; then
  log "venv-nexus missing → creating (python3 $(python3 -V 2>&1 | rg -o '[0-9.]+' || true))"
  python3 -m venv venv-nexus
  venv-nexus/bin/pip install --upgrade pip -q
fi
PY=venv-nexus/bin/python3

if ! "$PY" -c "import fastapi, duckdb, redis" >/dev/null 2>&1; then
  log "installing python deps (torch CPU wheel first)…"
  grep -v '^MetaTrader5' requirements.txt > /tmp/req-linux.txt
  "$PY" -m pip install torch --index-url https://download.pytorch.org/whl/cpu -q || true
  "$PY" -m pip install -r /tmp/req-linux.txt -q
fi
# أدوات الاختبار ليست في requirements.txt (الدرس من تدوير 2026-11-06: بوابة pytest
# تسقط ب"No module named pytest" بعد إعادة بناء نظيفة) — تُضمن دائماً.
if ! "$PY" -c "import pytest" >/dev/null 2>&1; then
  log "installing test deps (pytest/pytest-asyncio)…"
  "$PY" -m pip install pytest pytest-asyncio -q
fi
log "python deps: OK ($("$PY" -c 'import importlib.metadata as m; print(len(m.distributions()))') packages)"

# ── 2) redis ────────────────────────────────────────────────────────────────
REDIS_BIN="/home/z/my-project/redis/bin/redis-server"
if [ ! -x "$REDIS_BIN" ]; then
  log "redis binary missing → building 7.4.1 from source…"
  mkdir -p /home/z/my-project/redis
  work=/tmp/redis-build; rm -rf "$work"; mkdir -p "$work"
  curl -sL -o "$work/redis.tar.gz" https://download.redis.io/releases/redis-7.4.1.tar.gz
  tar xzf "$work/redis.tar.gz" -C "$work" --strip-components=1
  make -C "$work" -j2 MALLOC=libc -s >/dev/null
  mkdir -p /home/z/my-project/redis/bin
  cp "$work/src/redis-server" "$work/src/redis-cli" /home/z/my-project/redis/bin/
fi
log "redis binary: OK"

# ── 3) dashboard node_modules + بناء إنتاجي ────────────────────────────────
cd "$REPO/dashboard"
if [ ! -d node_modules ] || [ ! -e node_modules/.package-lock.json ]; then
  log "node_modules missing → npm ci (المنصة تمسح المجلدات الكبيرة)…"
  npm ci --no-audit --no-fund > "$LOG_DIR/npm_ci.log" 2>&1
fi
if [ "$SKIP_BUILD" != "1" ] && [ ! -f .next/BUILD_ID ]; then
  log "production build missing → npm run build (~دقائق)…"
  npm run build > "$LOG_DIR/npm_build.log" 2>&1
  log "build done: BUILD_ID=$(cat .next/BUILD_ID 2>/dev/null || echo '?')"
fi
cd "$REPO"

# ── 4) data dir + .env ──────────────────────────────────────────────────────
mkdir -p data logs
if [ ! -f .env ]; then
  log ".env missing → REFUSING to invent secrets. استخدم gen_env أو اطلب من المالك."
  exit 3
fi
log ".env: present"

log "NEXUS_REBUILD_DONE"
