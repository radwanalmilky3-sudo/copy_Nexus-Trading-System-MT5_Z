#!/usr/bin/env bash
# backup_nexus.sh — نسخة احتياطية مشفرة (قاعدة + .env) → فرع backups
# ---------------------------------------------------------------------------
# التصميم (T-016/T-017):
#   • لقطة: نسخ data/nexus.duckdb (+.wal) ثم أرشفتها مع .env — الأرشيف
#     مكتفٍ ذاتياً (استرداد كامل حتى لو ضاع الصندوق).
#   • تشفير: AES-256-CBC + PBKDF2 بمفتاح BACKUP_PASSPHRASE من .env.
#   • الدفع: إلى فرع backups على GitHub (دفعات fast-forward دائماً —
#     لا force أبداً)؛ نحتفظ بآخر 5 ملفات في الشجرة.
#   • العلامة: logs/last_backup.txt تُكتب عند نجاح مؤكد فقط
#     (OK بعد دفع مؤكد، LOCAL_ONLY إن لم توجد بيانات اعتماد أصلاً) —
#     PUSH_FAILED يترك التقادم ظاهراً عمداً ليلتقطه nexus_heal.sh.
# الجدولة: cron يومي 04:00+03 (مهمة 504108 سابقاً) + يدوياً بعد أي دورة كبرى.
# ---------------------------------------------------------------------------
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
LOG_DIR="$REPO/logs"; mkdir -p "$LOG_DIR" backups_local
STAMP=$(date '+%Y%m%d-%H%M%S')
ISO=$(date '+%Y-%m-%dT%H:%M:%S%:z')
STAGE=/tmp/nexus_backup_stage

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# بيانات اعتماد الدفع (محلية فقط — لا تُطبع ولا تُلتزم)
if [ -f scripts/ghcred.sh ]; then
  # shellcheck disable=SC1091
  source scripts/ghcred.sh
fi

# ── 1) مفتاح التشفير من .env ────────────────────────────────────────────────
PASS=$(rg -o '^BACKUP_PASSPHRASE=(.+)$' -r '$1' .env 2>/dev/null | head -1)
if [ -z "$PASS" ]; then log "BACKUP_FAIL: no BACKUP_PASSPHRASE in .env"; exit 3; fi

# ── 2) لقطة القاعدة (نسخ ملف — الكاتب الوحيد يحمل قفل الفتح المباشر) ────────
rm -rf "$STAGE"; mkdir -p "$STAGE"
if [ -f data/nexus.duckdb ]; then
  cp data/nexus.duckdb "$STAGE/nexus.duckdb"
  [ -f data/nexus.duckdb.wal ] && cp data/nexus.duckdb.wal "$STAGE/nexus.duckdb.wal"
else
  log "BACKUP_FAIL: data/nexus.duckdb missing"
  exit 3
fi
cp .env "$STAGE/env"

# ── 3) أرشفة + تشفير ────────────────────────────────────────────────────────
tar czf "$STAGE/bundle.tar.gz" -C "$STAGE" nexus.duckdb nexus.duckdb.wal env 2>/dev/null \
  || tar czf "$STAGE/bundle.tar.gz" -C "$STAGE" nexus.duckdb env
NEXUS_BACKUP_KEY="$PASS" openssl enc -aes-256-cbc -pbkdf2 -salt \
  -in "$STAGE/bundle.tar.gz" -out "backups_local/nexus_backup_${STAMP}.enc" \
  -pass env:NEXUS_BACKUP_KEY
ENC="backups_local/nexus_backup_${STAMP}.enc"
[ -s "$ENC" ] || { log "BACKUP_FAIL: encryption produced nothing"; exit 4; }
log "encrypted: $ENC ($(du -h "$ENC" | cut -f1))"

# ── 4) الدفع إلى فرع backups (fast-forward فقط) ────────────────────────────
push_state="LOCAL_ONLY"
if [ -n "${NEXUS_GH_TOKEN:-}" ]; then
  work=/tmp/nx-backups-worktree
  git fetch origin backups >> "$LOG_DIR/backup.log" 2>&1 || true
  rm -rf "$work"
  if git worktree add --detach "$work" origin/backups >> "$LOG_DIR/backup.log" 2>&1 \
     || git worktree add --orphan -b backups "$work" >> "$LOG_DIR/backup.log" 2>&1; then
    cp "$ENC" "$work/"
    # احتفظ بآخر 5 ملفات نسخ فقط في الشجرة
    ( cd "$work" && ls -t nexus_backup_*.enc 2>/dev/null | tail -n +6 | xargs -r git rm -q --cached -- ) || true
    ( cd "$work" && ls -t nexus_backup_*.enc 2>/dev/null | tail -n +6 | xargs -r rm -f -- ) || true
    git -C "$work" add -A
    if git -C "$work" commit -q -m "BACKUP_OK ${STAMP} (encrypted data+env, fast-forward append)" \
       && git -C "$work" push -q origin HEAD:backups >> "$LOG_DIR/backup.log" 2>&1; then
      push_state="PUSHED"
      log "pushed to origin/backups"
    else
      push_state="PUSH_FAILED"
      log "push failed — see backup.log"
    fi
    git worktree remove --force "$work" >> "$LOG_DIR/backup.log" 2>&1 || true
  else
    push_state="PUSH_FAILED"
  fi
else
  log "no gh credentials — LOCAL_ONLY"
fi

rm -rf "$STAGE"

# ── 5) العلامة (نجاح مؤكد فقط) ──────────────────────────────────────────────
if [ "$push_state" = "PUSHED" ] || [ "$push_state" = "LOCAL_ONLY" ]; then
  printf 'OK %s %s\n' "$ISO" "$push_state" > "$LOG_DIR/last_backup.txt"
  echo 0 > "$LOG_DIR/heal_backup_fail_count"
  log "BACKUP_OK ${STAMP} (${push_state})"
  exit 0
else
  log "BACKUP_${push_state} ${STAMP} — no marker (staleness visible to heal)"
  exit 1
fi
