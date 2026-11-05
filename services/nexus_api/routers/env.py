"""
Safe .env settings API — read/write allow-listed variables of the project
``.env`` file from the dashboard without ever exposing or touching secrets.

Design rules (mirrors the intelligence router's settings endpoints):

* READ  ``GET  /api/system/env``  — requires the same read permission the
  intelligence router uses for ``GET /settings`` (``trading.settings``).
  Parses the **file** (never ``os.environ``) and returns only allow-listed
  keys with their metadata; deny-listed secrets are filtered out entirely —
  neither their key nor their value ever appears in the response.
* WRITE ``POST /api/system/env``  — requires ``trading.settings`` via
  ``_require`` **before any file work**, validates the value against the
  allow-list (type / range / choices / pattern / length / control chars),
  backs the file up first (backup failure ⇒ 503, nothing written), then
  rewrites only the matching ``KEY=`` line in place — order, comments, other
  lines and the original line endings (CRLF vs LF) are preserved — with an
  atomic temp-file + ``os.replace`` write. Backups never collide (a same-second
  backup gets a monotonic ``_2``… suffix) and old ``.env.bak.*`` files are
  pruned down to the newest 20 after a successful write.

Every write requires a service restart to take effect (``run.py`` boots the
services with ``env = {**os.environ}``, so the values are inherited only at
boot), hence ``restart_required: true`` everywhere.
"""
from __future__ import annotations

import logging
import math
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..data_client import DataServiceClient
from ..deps import get_data_service
from ..middleware.auth import CurrentUser
from .admin import _require, require_permission

logger = logging.getLogger(__name__)

from shared.rate_limit import rate_limit_scope

router = APIRouter(prefix="/api/system", tags=["system-env"], dependencies=[rate_limit_scope("env")])
_env_read = require_permission("trading.settings")

# Generic Arabic refusal for anything the UI may not change: unknown keys,
# read-only keys and deny-listed secrets all answer the same way so the API
# never discloses which of them actually exists in the file.
_GENERIC_REFUSAL = "هذا المتغير غير قابل للتعديل من الواجهة"

# ── Deny list — the 12 secrets. Never read, returned, logged or written. ──────

SECRET_KEYS: tuple[str, ...] = (
    "NEXUS_PIN",
    "NEXUS_SECRET_KEY",
    "NEXUS_JWT_SECRET",
    "NEXUS_INTERNAL_API_SECRET",
    "NEXUS_ADMIN_PIN",
    "NEXUS_RISK_APPROVAL_SECRET",
    "MT5_PASSWORD",
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "NEWSAPI_KEY",
    "GNEWS_KEY",
)
_DENY = frozenset(SECRET_KEYS)
assert len(_DENY) == 12, "the deny list must stay at exactly 12 secrets"

# ── Allow list ────────────────────────────────────────────────────────────────
#
# type semantics: bool accepts 0/1/true/false (stored as 1/0), int, float,
# enum (exact choice match), str (pattern + max length).  Every entry is
# editable except category "readonly"; every "danger" entry carries an
# Arabic warning string.

_SYMBOL_RE = re.compile(r"^[A-Z0-9._]{1,16}$")


def _spec(
    key: str,
    type_: str,
    description: str,
    *,
    category: str = "core",
    editable: bool = True,
    min: float | None = None,
    max: float | None = None,
    choices: list[str] | None = None,
    warning: str | None = None,
    pattern: str | None = None,
    max_length: int | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "key": key,
        "type": type_,
        "category": category,
        "editable": editable,
        "restart_required": True,
        "description": description,
    }
    if min is not None:
        entry["min"] = min
    if max is not None:
        entry["max"] = max
    if choices is not None:
        entry["choices"] = list(choices)
    if warning is not None:
        entry["warning"] = warning
    if pattern is not None:
        entry["pattern"] = pattern
    if max_length is not None:
        entry["max_length"] = max_length
    return entry


_SPECS: list[dict[str, Any]] = [
    # ── core ────────────────────────────────────────────────────────────────
    _spec("NEXUS_ENV", "enum", "بيئة التشغيل",
          choices=["development", "staging", "production"]),
    _spec("NEXUS_MIN_VERDICT_CONVICTION", "int", "أدنى conviction لتنفيذ الصفقة (scalping)",
          min=0, max=100),
    _spec("NEXUS_CONFLICT_LOCK_CONVICTION", "int", "عند بلوغ الطرفين هذا الحد تُفرض NO_TRADE",
          min=0, max=100),
    _spec("NEXUS_TRADING_MODE_TYPE", "enum", "وضع النموذج الأساسي (بذرة عند الإقلاع)",
          choices=["scalping", "swing"]),
    _spec("NEXUS_OPERATIONAL_TF", "enum", "الإطار الزمني التشغيلي (بذرة عند الإقلاع)",
          choices=["M1", "M5", "M15", "H1"]),
    _spec("NEXUS_RESEARCH_INTERVAL_SEC", "int", "دورة البحث عن الاستراتيجيات (ثوانٍ)",
          min=300, max=7200),
    _spec("NEXUS_RESEARCH_BATCH", "int", "عدد الرموز في كل دورة بحث", min=1, max=10),
    _spec("NEXUS_RESEARCH_SYMBOL", "str", "رمز البحث الأساسي",
          pattern=r"^[A-Z0-9._]{1,16}$", max_length=16),
    _spec("NEXUS_DISABLE_RESEARCH", "bool", "إيقاف البحث عن استراتيجيات جديدة"),
    _spec("STRATEGY_MIN_PROFIT_FACTOR", "float", "أدنى Profit Factor لترقية استراتيجية",
          min=1.0, max=5.0),
    _spec("STRATEGY_MIN_WIN_RATE", "float", "أدنى Win Rate لترقية استراتيجية",
          min=0.0, max=1.0),
    _spec("STRATEGY_MIN_SHARPE", "float", "أدنى Sharpe ratio", min=0.0, max=3.0),
    _spec("STRATEGY_MAX_DD_PCT", "float", "أقصى تراجع مسموح DD%", min=0.0, max=100.0),
    _spec("STRATEGY_MIN_TRADES", "int", "أقل عدد صفقات لاعتماد استراتيجية",
          min=1, max=1000),
    _spec("STRATEGY_MIN_NET_PNL_PCT", "float", "أدنى ربح صافي مئوي",
          min=0.0, max=100.0),
    _spec("NEXUS_ML_PRIORITY", "enum", "أولوية ML مقابل وكلاء GenAI",
          choices=["0", "1"]),
    _spec("NEXUS_ACTIVE_SIGNAL_TTL", "int", "صلاحية الإشارة النشطة (ثوانٍ)",
          min=30, max=600),
    _spec("NEXUS_AUTONOMOUS_ML", "bool", "تشغيل خط ML مستقل"),
    _spec("NEXUS_LLM_HEALTH_TIMEOUT_SEC", "int", "مهلة صحة الـ LLM (ثوانٍ)",
          min=5, max=120),
    _spec("NEXUS_LLM_PROVIDER", "enum", "مزود الذكاء الاصطناعي",
          choices=["deepseek", "openai", "gemini", "local"]),
    _spec("NEXUS_LLM_MODEL", "str", "اسم النموذج (مثل qwen2.5:3b)", max_length=64),
    _spec("NEXUS_LOCAL_LLM_URL", "str", "عنوان خادم Ollama المحلي", max_length=200),
    _spec("NEXUS_LOCAL_MODEL", "str", "نموذج Ollama المحلي", max_length=64),
    _spec("IBKR_HOST", "str", "مضيف Interactive Brokers", max_length=64),
    _spec("IBKR_PORT", "int", "منفذ Interactive Brokers", min=1, max=65535),
    _spec("MLFLOW_TRACKING_URI", "str", "عنوان MLflow", max_length=200),
    _spec("MODEL_DIR", "str", "مجلد تخزين النماذج", max_length=200),

    # ── danger (editable, each carries an Arabic warning) ───────────────────
    _spec("NEXUS_AGGRESSIVE_TRADING", "bool", "يخفف عوامل الحماية في الفلاتر",
          category="danger", warning="لا تفعّل مع حساب حقيقي"),
    _spec("NEXUS_DATA_SYNTHETIC_FALLBACK", "bool", "السماح ببيانات مُولَّدة عند غياب MT5",
          category="danger", warning="1 = بيانات وهمية بدل MT5 الحقيقي"),
    _spec("NEXUS_ALLOW_SYNTHETIC_METRICS", "bool", "مقاييس مُولَّدة (تطوير فقط)",
          category="danger", warning="لا تستخدم مع نتائج حقيقية"),
    _spec("NEXUS_ALLOW_SYNTHETIC_TRAINING", "bool", "تدريب على بيانات مُولَّدة (تطوير فقط)",
          category="danger", warning="يفسد تدريب النماذج على بيانات حقيقية"),
    _spec("NEXUS_DUCKDB_ALLOW_SECONDARY_WRITER", "bool", "السماح بكاتب ثانٍ لقاعدة DuckDB",
          category="danger", warning="قد يسبب تعارض كتابة البيانات"),
    _spec("NEXUS_MT5_ISOLATED", "bool", "عزل جلسة MT5",
          category="danger", warning="غيّر فقط إذا أدرت لماذا"),

    # ── readonly (editable: false — display only) ───────────────────────────
    _spec("NEXUS_TRADING_MODE", "str", "وضع التداول — التبديل عبر --live --confirm-live فقط",
          category="readonly", editable=False),
    _spec("NEXUS_ALLOW_OFF_HOURS", "bool",
          "بذرة فقط: بوابة الجلسات المفروضة تُخزَّن في Redis وتتغلب",
          category="readonly", editable=False),
    _spec("DUCKDB_PATH", "str", "مسار قاعدة البيانات",
          category="readonly", editable=False),
    _spec("REDIS_URL", "str", "عنوان Redis",
          category="readonly", editable=False),
    _spec("MT5_LOGIN", "str", "رقم حساب MT5",
          category="readonly", editable=False),
    _spec("MT5_SERVER", "str", "خادم MT5",
          category="readonly", editable=False),
    _spec("NEXUS_MT5_SESSION_EXPORT_PATH", "str", "مسار تصدير جلسات MT5",
          category="readonly", editable=False),
    _spec("NEXUS_BROKER_CALENDAR_POLICY_PATH", "str", "مسار سياسة التقويم",
          category="readonly", editable=False),
]

_ALLOW: dict[str, dict[str, Any]] = {s["key"]: s for s in _SPECS}
assert not (_DENY & set(_ALLOW)), "a secret key must never be allow-listed"

_MAX_VALUE_LEN = 512


def _env_path() -> Path:
    """Repo-root ``.env`` — module level so tests can monkeypatch it."""
    return Path(__file__).resolve().parents[3] / ".env"


class EnvUpdate(BaseModel):
    key: str
    value: str


# ── File parsing (GET) ────────────────────────────────────────────────────────

def _strip_inline_comment(rest: str) -> str:
    """``value   # comment`` → ``value`` (``abc#def`` keeps its hash)."""
    for i, ch in enumerate(rest):
        if ch == "#" and (i == 0 or rest[i - 1].isspace()):
            return rest[:i].strip()
    return rest.strip()


def _parse_env_text(text: str) -> dict[str, str]:
    """Flat ``KEY=value`` map of the file; comments and ``export`` stripped."""
    parsed: dict[str, str] = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export "):
            s = s[len("export "):].strip()
        if "=" not in s:
            continue
        key, _, rest = s.partition("=")
        key = key.strip()
        if not key:
            continue
        parsed.setdefault(key, _strip_inline_comment(rest))
    return parsed


def _read_env_text(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8")
    except OSError as exc:
        logger.error("env.read_failed path=%s", path)
        raise HTTPException(503, "تعذّر قراءة ملف الإعدادات") from exc
    except UnicodeDecodeError as exc:
        logger.error("env.read_failed_encoding path=%s", path)
        raise HTTPException(503, "ملف الإعدادات بترميز غير مدعوم") from exc


@router.get("/env", dependencies=[Depends(_env_read)])
async def get_env_settings() -> dict[str, Any]:
    """Allow-listed ``.env`` variables with metadata. Secrets never appear."""
    path = _env_path()
    parsed = _parse_env_text(_read_env_text(path)) if path.exists() else {}

    vars_out: list[dict[str, Any]] = []
    for spec in _SPECS:
        entry: dict[str, Any] = {
            "key": spec["key"],
            "type": spec["type"],
            "category": spec["category"],
            "editable": spec["editable"],
            "restart_required": True,
            "description": spec["description"],
        }
        if "min" in spec:
            entry["min"] = spec["min"]
        if "max" in spec:
            entry["max"] = spec["max"]
        if "choices" in spec:
            entry["choices"] = list(spec["choices"])
        if "warning" in spec:
            entry["warning"] = spec["warning"]
        if spec["type"] == "str" and "max_length" in spec:
            entry["max"] = spec["max_length"]
        if spec["key"] in parsed:
            entry["value"] = parsed[spec["key"]]
            entry["unset"] = False
        else:
            entry["value"] = None
            entry["unset"] = True
        vars_out.append(entry)

    mode = parsed.get("NEXUS_TRADING_MODE", "") or "paper"
    return {
        "env_file": str(path),
        "vars": vars_out,
        "secrets_protected": len(_DENY),
        "mode": mode.strip().lower(),
    }


# ── Validation (POST) ─────────────────────────────────────────────────────────

def _reject(message: str) -> None:
    raise HTTPException(400, message)


def _validate_value(spec: dict[str, Any], raw: str) -> str:
    """Validate ``raw`` against the allow-list spec; return the stored form."""
    type_ = spec["type"]

    if len(raw) > _MAX_VALUE_LEN:
        _reject(f"القيمة طويلة جداً (الحد الأقصى {_MAX_VALUE_LEN} حرفاً)")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        _reject("القيمة تحتوي على أحرف غير مسموحة (أسطر أو أحرف تحكم)")

    value = raw.strip()

    if type_ == "bool":
        low = value.lower()
        if low in ("1", "true"):
            return "1"
        if low in ("0", "false"):
            return "0"
        _reject("قيمة غير صالحة للنوع bool — المتوقع 0 أو 1 أو true أو false")

    if type_ == "int":
        if not re.fullmatch(r"[+-]?[0-9]+", value):
            _reject(f"قيمة غير صالحة للنوع int — النطاق المتوقع {spec['min']}..{spec['max']}")
        number = int(value, 10)
        if number < spec["min"] or number > spec["max"]:
            _reject(f"قيمة غير صالحة للنوع int — النطاق المتوقع {spec['min']}..{spec['max']}")
        return str(number)

    if type_ == "float":
        try:
            number = float(value)
        except ValueError:
            number = None
        if number is None or not math.isfinite(number) or number < spec["min"] or number > spec["max"]:
            _reject(f"قيمة غير صالحة للنوع float — النطاق المتوقع {spec['min']}..{spec['max']}")
        return value

    if type_ == "enum":
        if value not in spec["choices"]:
            _reject("قيمة غير صالحة — المتوقع أحد: " + ", ".join(spec["choices"]))
        return value

    # str
    max_length = spec.get("max_length")
    if max_length is not None and len(value) > max_length:
        _reject(f"قيمة غير صالحة — الحد الأقصى {max_length} حرفاً")
    pattern = spec.get("pattern")
    if pattern is not None and not _SYMBOL_RE.match(value):
        _reject(f"قيمة غير صالحة — النمط المتوقع {pattern}")
    return value


# ── Backup + atomic in-place write (POST) ─────────────────────────────────────

# Keep at most this many ``.env.bak.*`` files so periodic edits never fill the
# disk; pruning only ever touches names matching ``.env.bak.*``.
_BACKUP_KEEP = 20


def _backup_env(path: Path) -> Path:
    """Copy ``.env`` → ``.env.bak.<UTC yyyymmdd_HHMMSS>`` before any write.

    Two writes inside the same second would otherwise overwrite each other's
    backup, so a colliding name gets a monotonic ``_2``, ``_3``… suffix and no
    backup is ever lost.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f".env.bak.{stamp}")
    copy_no = 1
    while backup.exists():
        copy_no += 1
        backup = path.with_name(f".env.bak.{stamp}_{copy_no}")
    try:
        shutil.copy2(path, backup)
    except OSError as exc:
        logger.error("env.backup_failed key_stamp=%s", stamp)
        raise HTTPException(
            503, "تعذّر إنشاء نسخة احتياطية من ملف الإعدادات — لم تُجرَ أي تعديلات"
        ) from exc
    return backup.resolve()


def _prune_backups(path: Path, key: str) -> None:
    """Keep only the newest ``_BACKUP_KEEP`` ``.env.bak.*`` files.

    Only files strictly matching ``.env.bak.*`` inside the ``.env`` directory
    are candidates — never ``.env`` itself, ``.env.example`` or anything else.
    Called after a successful write: hygiene only, so any failure is logged as
    a warning (key only, never a value) and never fails the request.
    """
    try:
        backups = [p for p in path.parent.glob(".env.bak.*") if p.is_file()]
        if len(backups) <= _BACKUP_KEEP:
            return
        # Newest first; name breaks mtime ties deterministically.
        backups.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
        for stale in backups[_BACKUP_KEEP:]:
            stale.unlink()
    except Exception:  # noqa: BLE001 - pruning must never fail the request
        logger.warning("env.backup_prune_failed key=%s", key)


def _line_parts(line: str) -> tuple[str, str]:
    """Split a physical line into (content, original line ending)."""
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    if line.endswith("\r"):
        return line[:-1], "\r"
    return line, ""


_KEY_LINE_RE_CACHE: dict[str, re.Pattern[str]] = {}


def _key_line_re(key: str) -> re.Pattern[str]:
    pattern = _KEY_LINE_RE_CACHE.get(key)
    if pattern is None:
        pattern = re.compile(
            rf"^(?P<prefix>(?:export[ \t]+)?{re.escape(key)}[ \t]*=[ \t]*)"
            rf"(?P<value>[^#]*?)"
            rf"(?P<gap>[ \t]*)(?P<comment>#.*)?$"
        )
        _KEY_LINE_RE_CACHE[key] = pattern
    return pattern


def _detect_eol(text: str) -> str:
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    return "\r\n" if crlf >= lf and (crlf or lf) else "\n"


def _write_value(path: Path, key: str, value: str) -> None:
    """Replace only the ``KEY=`` line (append if absent) and write atomically.

    Order, every other line, comments and each line's own ending are kept
    byte-for-byte; the temp file lives in the same directory so ``os.replace``
    is atomic on the same filesystem.
    """
    text = _read_env_text(path)
    lines = text.splitlines(keepends=True)
    eol = _detect_eol(text)

    out: list[str] = []
    replaced = False
    regex = _key_line_re(key)
    for line in lines:
        content, line_eol = _line_parts(line)
        match = regex.match(content)
        if not replaced and match:
            comment = match.group("comment")
            # Keep the exact spacing that preceded the inline comment.
            tail = (match.group("gap") + comment) if comment else ""
            out.append(match.group("prefix") + value + tail + line_eol)
            replaced = True
        else:
            out.append(content + line_eol)

    if not replaced:
        if out and not out[-1].endswith(("\r\n", "\n", "\r")):
            out[-1] += eol
        out.append(f"{key}={value}{eol}")

    payload = "".join(out).encode("utf-8")
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:  # pragma: no cover - best-effort cleanup
            pass


@router.post("/env")
async def update_env_setting(
    req: EnvUpdate,
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
):
    """Validate, back up and atomically write one allow-listed ``.env`` key."""
    # Permission first — before the file is even touched.
    await _require(db, actor, "trading.settings")

    key = req.key.strip()
    spec = _ALLOW.get(key)
    if key in _DENY or spec is None or not spec["editable"]:
        raise HTTPException(400, _GENERIC_REFUSAL)

    value = _validate_value(spec, req.value)

    path = _env_path()
    backup = _backup_env(path)          # failure ⇒ 503, file untouched
    try:
        _write_value(path, key, value)
    except HTTPException:
        raise
    except OSError as exc:
        logger.error("env.write_failed key=%s", key)
        raise HTTPException(503, "تعذّر حفظ ملف الإعدادات") from exc

    # Audit: KEY only — never the value.
    logger.info("env.setting_written key=%s", key)
    # Hygiene after a successful write: cap backup accumulation. Best effort —
    # a prune failure must never fail a write that already succeeded.
    _prune_backups(path, key)
    return {
        "status": "saved",
        "key": key,
        "value": value,
        "backup": str(backup),
        "restart_required": True,
    }
