"""
Intelligence Router — signal quality, model performance by regime, GenAI brief,
and dynamic settings read/write for the dashboard.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from ..http_client import new_client
import redis.asyncio as aioredis
from redis.exceptions import WatchError
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..data_client import DataServiceClient
from ..deps import get_data_service
from ..middleware.auth import CurrentUser
from .admin import _require, require_permission
from shared import runtime_settings
from shared.runtime_settings import sanitize_patch

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
_AGENTS_URL = os.getenv("NEXUS_AGENTS_URL", "http://127.0.0.1:9004")

_redis: aioredis.Redis | None = None


async def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(REDIS_URL, decode_responses=True, max_connections=5)
    return _redis


async def _redis_get(key: str) -> str | None:
    """Fetch a key; an unreachable store fails closed with 503."""
    try:
        r = await _get_redis()
        return await r.get(key)
    except Exception as exc:
        logger.warning("intelligence.redis_get.failed", key=key, exc_info=True)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Intelligence store is temporarily unavailable",
        ) from exc


async def _redis_lrange(key: str, start: int, end: int) -> list[str]:
    """Fetch a list range; an unreachable store fails closed with 503."""
    try:
        r = await _get_redis()
        return await r.lrange(key, start, end)
    except Exception as exc:
        logger.warning("intelligence.redis_lrange.failed", key=key, exc_info=True)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Intelligence store is temporarily unavailable",
        ) from exc


def _loads(raw: str, label: str) -> Any:
    """Parse a cached JSON blob; corrupt cache fails closed with 503."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"Corrupt cached {label} data",
        ) from exc


router = APIRouter(prefix="/api/intelligence", tags=["Intelligence"])
_trading_view = require_permission("trading.view")
_fundamental_view = require_permission("fundamental.view")
_trading_settings = require_permission("trading.settings")


# ── Signal Quality ────────────────────────────────────────────────────────────

@router.get("/quality", dependencies=[Depends(_trading_view)])
async def get_signal_quality():
    """Latest signal quality score and filter breakdown.

    Truth contract: an empty store is UNKNOWN (available=false, score/passes
    null) — never a fabricated 0/"blocked" the UI could adopt as a gate.
    """
    raw = await _redis_get("nexus:signal:quality:last")
    if raw:
        data = _loads(raw, "signal quality")
        if isinstance(data, dict):
            data.setdefault("available", True)
        return data
    return {
        "available": False,
        "reason": "not_computed",
        "score": None,
        "max_score": None,
        "threshold": None,
        "passes": None,
        "direction": None,
        "regime": None,
        "session": None,
        "breakdown": {},
        "computed_at": None,
    }


# ── Model Performance by Regime ───────────────────────────────────────────────

@router.get("/models-by-regime", dependencies=[Depends(_trading_view)])
async def get_models_by_regime():
    """WR and trade count for each model broken down by regime.

    Read from TradeMemory metrics (by_regime + by_source cross-reference)
    and the autonomous ML stats.
    """
    raw_metrics = await _redis_get("nexus:trade_memory:metrics")
    if not raw_metrics:
        return {
            "available": False,
            "reason": "not_computed",
            "by_regime": {}, "by_source": {}, "by_session": {}, "by_hour": {},
            "overall": None,
        }
    metrics = _loads(raw_metrics, "trade-memory metrics")
    if not isinstance(metrics, dict) or not metrics:
        # Present-but-empty/unshaped metrics is UNKNOWN — never a zeroed
        # overall record the UI could read as a confirmed 0-trade history.
        return {
            "available": False,
            "reason": "empty_metrics",
            "by_regime": {}, "by_source": {}, "by_session": {}, "by_hour": {},
            "overall": None,
        }
    # Per-field None (not 0): a missing key is unknown, only an explicit
    # stored value — including a genuine 0 — is reported as-is.
    return {
        "available": True,
        "by_regime": metrics.get("by_regime") or {},
        "by_source": metrics.get("by_source") or {},
        "by_session": metrics.get("by_session") or {},
        "by_hour": metrics.get("by_hour") or {},
        "overall": {
            "win_rate": metrics.get("overall_win_rate"),
            "total_trades": metrics.get("total_trades"),
            "total_wins": metrics.get("total_wins"),
            "total_losses": metrics.get("total_losses"),
            "avg_pnl_pips": metrics.get("avg_pnl_pips"),
            "recent_streak": metrics.get("recent_streak") or {},
        },
    }


# ── GenAI Daily Brief ─────────────────────────────────────────────────────────

@router.get("/genai-brief", dependencies=[Depends(_fundamental_view)])
async def get_genai_brief():
    """Latest GenAI daily macro brief."""
    raw = await _redis_get("nexus:genai:daily_bias")
    if raw:
        return _loads(raw, "genai brief")
    # No generated brief = UNKNOWN outlook, not a fabricated NEUTRAL one
    # (unknown ≠ 0 ≠ NEUTRAL). `error`/`available:false` is the marker the
    # dashboard already honors (GenAIBrief.tsx: payload.error → keep-last-good).
    return {
        "available": False,
        "reason": "not_generated",
        "error": "not_generated",
        "bias": None,
        "summary": None,
        "events": [],
        "updated_at": None,
    }


@router.get("/mtf-context/{symbol}", dependencies=[Depends(_trading_view)])
async def get_mtf_context(symbol: str):
    """Multi-timeframe features and confluence score for a symbol."""
    timeframes = ["M5", "M15", "H1", "H4", "D1"]
    result: dict[str, Any] = {}
    for tf in timeframes:
        raw = await _redis_get(f"nexus:features:{symbol}:{tf}")
        if not raw:
            continue
        data = _loads(raw, "mtf features")
        feats = data.get("features", data) if isinstance(data, dict) else {}
        try:
            ema9 = feats.get("ema_9", 0)
            ema21 = feats.get("ema_21", 0)
            ema50 = feats.get("ema_50", 0)
            close = feats.get("close", 0)
            rsi = feats.get("rsi", 50)
            macd_hist = feats.get("macd_histogram", 0)
            adx = feats.get("adx", 0)
            atr = feats.get("atr_14", feats.get("atr", 0))
            bb_pct = feats.get("bb_pct_b", 0.5)

            if ema9 > ema21 > ema50 and macd_hist > 0:
                bias = "BULLISH"
            elif ema9 < ema21 < ema50 and macd_hist < 0:
                bias = "BEARISH"
            else:
                bias = "NEUTRAL"

            result[tf] = {
                "bias": bias,
                "close": round(float(close), 5),
                "rsi": round(float(rsi), 1),
                "adx": round(float(adx), 1),
                "macd_hist": round(float(macd_hist), 6),
                "atr": round(float(atr), 4),
                "bb_pct_b": round(float(bb_pct), 3),
                "ema_stack": {
                    "ema9": round(float(ema9), 4),
                    "ema21": round(float(ema21), 4),
                    "ema50": round(float(ema50), 4),
                },
            }
        except (TypeError, ValueError):
            # Malformed cached features for one TF: skip it, keep the rest.
            continue

    # Compute confluence score (-4 to +4).
    bull = sum(1 for tf in result if result[tf]["bias"] == "BULLISH")
    bear = sum(1 for tf in result if result[tf]["bias"] == "BEARISH")
    total = len(result)
    alignment = bull - bear
    overall_bias = "BULLISH" if alignment >= 2 else "BEARISH" if alignment <= -2 else "NEUTRAL"

    return {
        "symbol": symbol,
        "timeframes": result,
        "confluence": {
            "alignment_score": alignment,
            "bull_count": bull,
            "bear_count": bear,
            "total_tfs": total,
            "overall_bias": overall_bias,
        },
    }


# ── Dynamic Settings ──────────────────────────────────────────────────────────

class DynamicSettingsUpdate(BaseModel):
    settings: dict[str, Any]


class TemplateSaveRequest(BaseModel):
    """Save the current settings document as a JSON template file on disk."""

    name: str
    description: str = ""


class TemplateLoadRequest(BaseModel):
    """Load a template file (stored in config/settings_templates) into the form."""

    file: str


# Single settings document shared with shared.runtime_settings.SETTINGS_KEY;
# nexus-ml / nexus-risk / nexus-agents read the exact same key.
_SETTINGS_KEY = "nexus:runtime:settings"
# Mirror shared/runtime_settings.py: user overrides are permanent until the
# user clears them. This route used to write a 7-day TTL, so every dashboard
# setting silently reverted a week later — shared/runtime_settings.py even
# documented "self-heal a short TTL left behind by other writers (e.g. the
# 7-day intelligence route)".
_SETTINGS_TTL_SEC = 10 * 365 * 24 * 3600
# Optimistic-CAS attempts before degrading to a plain read-modify-write.
_CAS_RETRIES = 5


def _decode_settings(raw: Any) -> dict[str, Any]:
    """Tolerant read of the stored document; anything unusable ⇒ ``{}``."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _apply_patch(document: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Merge a patch in place; ``null`` explicitly removes an override."""
    for key, value in patch.items():
        if value is None:
            document.pop(key, None)
        else:
            document[key] = value
    return document


def _settings_unavailable() -> dict[str, Any]:
    """HTTP 200 + error marker: dashboard contract (settings/page.tsx loadAll).

    The tab keeps the last loaded values and flags the panel instead of
    showing empty fields that look like confirmed defaults.
    """
    return {
        "settings": {},
        "source": "unavailable",
        "error": "settings_store_unavailable",
    }


@router.get("/settings", dependencies=[Depends(_trading_settings)])
async def get_dynamic_settings():
    """Read all user-configurable runtime settings.

    Read-only over Redis: it never calls the GenAI/Ollama endpoint, so an
    unreachable local LLM cannot turn this into a 5xx. An unreachable or
    corrupt store also degrades to the documented error marker instead of
    failing the whole General Settings tab.

    ``settings`` stays the RAW stored document (page contract); a sibling
    ``defaults`` map lets the page render knobs nobody has saved yet.
    """
    try:
        raw = await _redis_get(_SETTINGS_KEY)
        parsed: Any = _loads(raw, "runtime settings") if raw else {}
    except HTTPException as exc:
        if exc.status_code != status.HTTP_503_SERVICE_UNAVAILABLE:
            raise
        logger.warning("settings.read.degraded detail=%s", exc.detail)
        return _settings_unavailable()
    if not isinstance(parsed, dict):
        logger.warning("settings.read.bad_shape type=%s", type(parsed).__name__)
        return _settings_unavailable()
    payload: dict[str, Any] = {
        # Pinned contract: ``settings`` stays the RAW stored document; the page
        # shows ``defaults[key]`` only when the document has no value yet.
        "settings": parsed,
        "source": "redis" if raw else "defaults",
    }
    try:
        payload["defaults"] = dict(runtime_settings.DEFAULTS)
    except Exception:  # noqa: BLE001 - never fail the read over the fallback map
        logger.warning("settings.defaults.unavailable", exc_info=True)
    return payload


async def _cas_store(r: aioredis.Redis, patch: dict[str, Any]) -> dict[str, Any]:
    """WATCH/MULTI read-modify-write of the settings document.

    A plain GET+SET here could drop a concurrent write issued by
    shared.runtime_settings.update_settings (nexus-ml / nexus-risk), which
    uses the same optimistic loop against every writer.
    """
    last: Exception | None = None
    for _ in range(_CAS_RETRIES):
        pipe = r.pipeline()
        try:
            await pipe.watch(_SETTINGS_KEY)
            raw = await pipe.get(_SETTINGS_KEY)
            document = _apply_patch(_decode_settings(raw), patch)
            pipe.multi()
            pipe.set(_SETTINGS_KEY, json.dumps(document, default=str), ex=_SETTINGS_TTL_SEC)
            await pipe.execute()
            return document
        except WatchError as exc:
            last = exc
            continue
        finally:
            try:
                await pipe.reset()
            except Exception:  # noqa: BLE001 - cleanup must never mask the result
                pass
    raise RuntimeError("runtime settings write contention") from last


async def _store_settings(r: aioredis.Redis, patch: dict[str, Any]) -> dict[str, Any]:
    """Persist a merged patch; test doubles without a pipeline fall back."""
    try:
        return await _cas_store(r, patch)
    except (WatchError, AttributeError, RuntimeError):
        document = _apply_patch(_decode_settings(await r.get(_SETTINGS_KEY)), patch)
        await r.set(_SETTINGS_KEY, json.dumps(document, default=str), ex=_SETTINGS_TTL_SEC)
        return document


@router.post("/settings")
async def update_dynamic_settings(
    req: DynamicSettingsUpdate,
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
):
    """Write runtime settings to Redis. All services read from here."""
    await _require(db, actor, "trading.settings")
    # Clamp at write time too: readers already coerce on merge, but a raw
    # out-of-range value must never reach the store as policy.
    patch = sanitize_patch(req.settings)
    try:
        r = await _get_redis()
        # Keep the pre-save document as "last settings" so the dashboard can
        # offer one-click rollback after applying a template. Best-effort: a
        # snapshot failure must never fail the save itself.
        await _snapshot_last_settings(r)
        existing = await _store_settings(r, patch)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to save dynamic settings", exc_info=True)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Runtime settings store is temporarily unavailable",
        ) from exc
    return {"status": "saved", "settings": existing}


# ── Settings templates (plain JSON files on disk) ─────────────────────────────
#
# The dashboard saves whole-settings templates as JSON files under
# config/settings_templates so they can be copied, backed up or moved between
# machines, and the page shows the exact folder it writes to. Loading always
# re-runs the values through sanitize_patch + DEFAULTS, so a hand-edited file
# can never push an unknown/out-of-range value into the runtime store.

_TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "config" / "settings_templates"
_LAST_KEY = "nexus:runtime:settings:last"
_TEMPLATE_MAX_BYTES = 1_000_000
# Names become filenames: letters (incl. Arabic), digits, spaces, _ and - only.
_TEMPLATE_NAME_RE = re.compile(r"^[A-Za-z0-9\u0600-\u06FF _\-]{1,64}$")
_TEMPLATE_FILE_RE = re.compile(r"^[A-Za-z0-9\u0600-\u06FF _\-]{1,64}\.json$")
# Windows reserved device names: "con", "CON.json", "nul", "lpt3" … can never
# be created as real files — the OS may refuse the write or silently redirect
# it to a device, so they are rejected for save AND load alike.
_WINDOWS_RESERVED_STEMS = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)


def _validate_template_name(name: str, *, file_name: bool = False) -> None:
    """Single validation gate shared by save (bare ``name``) and load.

    Enforces the character pattern and, case-insensitively, the Windows
    reserved device names — with or without the ``.json`` suffix.
    """
    pattern = _TEMPLATE_FILE_RE if file_name else _TEMPLATE_NAME_RE
    if not pattern.match(name):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "اسم ملف قالب غير صالح"
            if file_name
            else "اسم القالب غير صالح — استخدم حروفًا/أرقامًا/مسافات فقط (بحد أقصى 64 حرفًا)",
        )
    # Windows also ignores trailing spaces/dots in a stem before matching
    # against the reserved list, so normalise those away first.
    stem = re.sub(r"[ .]+$", "", name[:-5] if file_name else name).lower()
    if stem in _WINDOWS_RESERVED_STEMS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "اسم قالب محجوز في ويندوز (CON/PRN/AUX/NUL/COM1-9/LPT1-9) — اختر اسمًا آخر",
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def _snapshot_last_settings(r: Any) -> None:
    """Copy the current document to ``nexus:runtime:settings:last`` (best effort)."""
    try:
        raw = await r.get(_SETTINGS_KEY)
        if not raw:
            return
        doc = json.loads(raw)
        if not isinstance(doc, dict) or not doc:
            return
        await r.set(
            _LAST_KEY,
            json.dumps({"settings": doc, "saved_at": _utc_now()}, default=str),
            ex=_SETTINGS_TTL_SEC,
        )
    except Exception:  # noqa: BLE001 - snapshot is advisory, never fatal
        logger.debug("settings.last_snapshot_failed", exc_info=True)


def _parse_template_text(text: str, label: str) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Return ``(clean_settings, meta, dropped_keys)`` for a template file body."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"قالب غير صالح ({label}): JSON غير صالح") from exc
    if not isinstance(data, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"قالب غير صالح ({label}): يجب أن يكون كائن JSON")
    meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
    raw_settings = data.get("settings") if isinstance(data.get("settings"), dict) else data
    if not isinstance(raw_settings, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"قالب غير صالح ({label}): قسم settings مفقود")
    # Known keys only, clamped to _BOUNDS; nulls dropped (a template carries
    # concrete values, never "delete this override").
    clean = {
        key: value
        for key, value in sanitize_patch(raw_settings).items()
        if key in runtime_settings.DEFAULTS and value is not None
    }
    dropped = sorted(key for key in raw_settings if key not in clean)
    return clean, meta, dropped


def _template_dir() -> Path:
    """Resolve the templates folder, creating it on first use."""
    _TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    return _TEMPLATES_DIR


def _template_is_builtin(path: Path) -> bool:
    """True only when the file already on disk declares ``_meta.builtin``.

    The shipped ``config/settings_templates/optimal.json`` is a builtin: it
    must never be silently replaced by a dashboard save that would persist
    ``builtin: false`` over it. An unreadable/corrupt file is not the shipped
    builtin (those parse), so it falls through to a normal save.
    """
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.debug("settings.templates.builtin_probe_failed file=%s: %s", path.name, exc)
        return False
    meta = data.get("_meta") if isinstance(data, dict) else None
    return bool(meta.get("builtin")) if isinstance(meta, dict) else False


@router.get("/settings/templates", dependencies=[Depends(_trading_settings)])
async def list_settings_templates():
    """List JSON templates on disk + the "last settings" rollback snapshot."""
    entries: list[dict[str, Any]] = []
    try:
        folder = _template_dir()
        for path in sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            entry: dict[str, Any] = {
                "file": path.name,
                "name": path.stem,
                "description": "",
                "builtin": False,
                "keys": 0,
                "size": path.stat().st_size,
                "saved_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
                "valid": True,
                "error": None,
            }
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                meta = data.get("_meta") if isinstance(data, dict) and isinstance(data.get("_meta"), dict) else {}
                settings = data.get("settings") if isinstance(data, dict) else None
                if isinstance(settings, dict):
                    entry["keys"] = len(settings)
                entry["name"] = str(meta.get("name") or path.stem)
                entry["description"] = str(meta.get("description") or "")
                entry["builtin"] = bool(meta.get("builtin"))
            except Exception as exc:  # noqa: BLE001 - list must survive one bad file
                entry["valid"] = False
                entry["error"] = str(exc)[:120]
            entries.append(entry)
    except OSError as exc:
        logger.warning("settings.templates.list_failed path=%s: %s", _TEMPLATES_DIR, exc)

    last: dict[str, Any] | None = None
    try:
        r = await _get_redis()
        raw_last = await r.get(_LAST_KEY)
        if raw_last:
            parsed = json.loads(raw_last)
            if isinstance(parsed, dict) and isinstance(parsed.get("settings"), dict):
                last = parsed
    except Exception:  # noqa: BLE001 - a missing rollback snapshot is not an error
        logger.debug("settings.templates.last_read_failed", exc_info=True)

    return {"path": str(_TEMPLATES_DIR), "templates": entries, "last": last}


@router.post("/settings/templates/save")
async def save_settings_template(
    req: TemplateSaveRequest,
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
):
    """Persist the current settings document as ``<name>.json`` on disk."""
    await _require(db, actor, "trading.settings")
    name = (req.name or "").strip()
    _validate_template_name(name)  # pattern + Windows reserved device names
    # Resolve before writing: the pattern forbids separators, but a link
    # planted inside the folder must never redirect the write outside it —
    # the exact guard load_settings_template already applies.
    folder = _template_dir().resolve()
    path = (folder / f"{name}.json").resolve()
    if path.parent != folder:
        # Traversal attempt (e.g. a symlink/junction to elsewhere) — never
        # leave the folder, and write nothing.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "مسار خارج مجلد القوالب مرفوض")
    # Builtin protection: refuse to overwrite a shipped builtin template, which
    # would otherwise be silently replaced and re-persisted as builtin: false.
    if _template_is_builtin(path):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "هذا قالب مدمج ولا يمكن استبداله — احفظه باسم آخر",
        )
    raw = await _redis_get(_SETTINGS_KEY)
    doc: dict[str, Any] = {}
    if raw:
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            parsed = {}
        if isinstance(parsed, dict):
            doc = parsed
    if not doc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "لا توجد إعدادات محفوظة لحفظها كقالب")
    clean = {k: v for k, v in sanitize_patch(doc).items() if k in runtime_settings.DEFAULTS}
    payload = {
        "_meta": {
            "name": name,
            "description": (req.description or "").strip()[:200],
            "saved_at": _utc_now(),
            "builtin": False,
        },
        "settings": clean,
    }
    try:
        # ``path`` was resolved and proven to be a direct child of the
        # templates folder above, so this write can never leave the folder.
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except HTTPException:
        raise
    except OSError as exc:
        logger.error("settings.templates.save_failed name=%s: %s", name, exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "تعذّر حفظ ملف القالب على القرص",
        ) from exc
    return {"status": "saved", "file": path.name, "path": str(path), "keys": len(clean)}


@router.post("/settings/templates/load")
async def load_settings_template(
    req: TemplateLoadRequest,
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
):
    """Read a template file and return its values ready to fill the form."""
    await _require(db, actor, "trading.settings")
    file_name = (req.file or "").strip()
    _validate_template_name(file_name, file_name=True)  # pattern + reserved
    folder = _template_dir().resolve()
    path = (folder / file_name).resolve()
    if path.parent != folder:
        # Traversal attempt (e.g. "..\\..\\secrets.json") — never leave the folder.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "مسار خارج مجلد القوالب مرفوض")
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"القالب غير موجود: {file_name}")
    if path.stat().st_size > _TEMPLATE_MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "ملف القالب كبير جدًا")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "تعذّرت قراءة ملف القالب") from exc
    clean, meta, dropped = _parse_template_text(text, file_name)
    return {
        "status": "ok",
        "file": path.name,
        "path": str(path),
        "name": str(meta.get("name") or path.stem),
        "description": str(meta.get("description") or ""),
        "settings": clean,
        "dropped": dropped,
    }


# ── Cross-Asset Context ───────────────────────────────────────────────────────

@router.get("/cross-asset", dependencies=[Depends(_trading_view)])
async def get_cross_asset():
    """Current DXY/US10Y cross-asset context for gold trading."""
    raw = await _redis_get("nexus:cross_asset:summary")
    if raw:
        return _loads(raw, "cross-asset summary")
    # Fallback: read individual keys
    dxy_raw = await _redis_get("nexus:cross_asset:DXY")
    us10y_raw = await _redis_get("nexus:cross_asset:US10Y")
    # Honest fallback: with no cached inputs there is no regime and no grade.
    # "neutral" + 3/5 used to be fabricated here (UI-04); missing data must
    # surface as UNKNOWN/null so the UI cannot present a phantom signal.
    return {
        "dxy": _loads(dxy_raw, "cross-asset DXY") if dxy_raw else {"level": None, "source": "no_data"},
        "us10y": _loads(us10y_raw, "cross-asset US10Y") if us10y_raw else {"level": None, "source": "no_data"},
        "gold_yield_regime": "unknown",
        "gold_dxy_divergence": None,
        "cross_asset_signal_pts": None,
        "updated_at": None,
    }


@router.get("/asset-profile/{symbol}", dependencies=[Depends(_trading_view)])
async def get_asset_profile(symbol: str):
    """Trading parameters for a given symbol (from AssetProfile)."""
    try:
        from shared.asset_profile import get_profile, profile_to_dict
        profile = get_profile(symbol)
        return profile_to_dict(profile)
    except Exception as exc:
        logger.warning("asset-profile.error symbol=%s: %s", symbol, exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Asset profile lookup failed",
        ) from exc


@router.get("/shift-alerts", dependencies=[Depends(_trading_view)])
async def get_shift_alerts(limit: int = 10):
    """Recent intraday cross-asset shift alerts (DXY/US10Y/regime changes)."""
    raw = await _redis_lrange("nexus:cross_asset:shift_alerts", 0, limit - 1)
    return {"alerts": [_loads(x, "shift alerts") for x in raw], "count": len(raw)}


# ── News Sentinel (Fase 4) ────────────────────────────────────────────────────

@router.get("/news-alerts", dependencies=[Depends(_fundamental_view)])
async def get_news_alerts(limit: int = 20):
    """Recent high/medium-impact news alerts from the sentinel."""
    raw = await _redis_lrange("nexus:news:sentinel:alerts", 0, limit - 1)
    return {"alerts": [_loads(x, "news alerts") for x in raw], "count": len(raw)}


@router.get("/news-blackout", dependencies=[Depends(_fundamental_view)])
async def get_news_blackout():
    """Active blackout window status (HIGH-impact event ±30min)."""
    raw = await _redis_get("nexus:news:sentinel:blackout")
    if raw:
        return _loads(raw, "news blackout")
    return {"active": False, "reason": "no scan yet", "events": [], "ends_at": None}


@router.get("/brief-status", dependencies=[Depends(_fundamental_view)])
async def get_brief_status():
    """Status of the daily brief service (last run, ok/error, next run)."""
    status_val = await _redis_get("nexus:genai:brief:status") or "unknown"
    last_run = await _redis_get("nexus:genai:brief:last_run")
    return {"status": status_val, "last_run": last_run}


# ── Correlation Matrix (Fase 5) ───────────────────────────────────────────────

_CORR_FALLBACK_ASSETS = ["XAUUSD", "BTCUSD", "OIL", "SPX"]


@router.get("/correlation", dependencies=[Depends(_trading_view)])
async def get_correlation():
    """Rolling asset correlation (windows 20/60/120 on synchronized returns).

    Truth contract: no snapshot → available=false with EMPTY windows/lag
    lists, never a zero matrix. Observed correlation is context, not cause
    or prediction.
    """
    raw = await _redis_get("nexus:correlation:matrix")
    if raw:
        data = _loads(raw, "correlation matrix")
        if isinstance(data, dict):
            data.setdefault("available", bool(data.get("updated_at")))
            if data.get("updated_at"):
                data.setdefault("basis", "synchronized_returns")
                data.setdefault(
                    "disclaimer",
                    "Correlación observada sobre retornos sincronizados; "
                    "no es causa ni garantía de predicción.",
                )
            data.setdefault("windows", {})
            data.setdefault("lag_signals", [])
        return data
    return {
        "available": False,
        "reason": "no_snapshot",
        "assets": _CORR_FALLBACK_ASSETS,
        "matrices": {"7d": {}, "30d": {}},
        "windows": {},
        "lag_signals": [],
        "divergences": [],
        "basis": None,
        "disclaimer": None,
        "updated_at": None,
    }


# ── RL Lifecycle Actions ──────────────────────────────────────────────────────

@router.get("/lifecycle-actions", dependencies=[Depends(_trading_view)])
async def get_lifecycle_actions():
    """Current RL lifecycle action recommendations for all open positions."""
    raw = await _redis_get("nexus:rl:lifecycle:all")
    if raw:
        return {"actions": _loads(raw, "lifecycle actions"), "source": "rl_lifecycle"}
    return {"actions": [], "source": "no_positions"}


@router.post("/brief/trigger")
async def trigger_brief(
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
    symbol: str = "XAUUSD",
):
    """Manually trigger a GenAI brief (proxies to nexus-agents)."""
    await _require(db, actor, "fundamental.configure")
    internal_secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
    if not internal_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "NEXUS_INTERNAL_API_SECRET is not configured")
    try:
        async with new_client(timeout=90.0) as client:
            resp = await client.post(
                f"{_AGENTS_URL}/api/agents/brief/generate",
                params={"symbol": symbol},
                headers={"X-Nexus-Internal-Secret": internal_secret},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("brief trigger upstream failed: %s", exc)
        raise HTTPException(
            exc.response.status_code,
            f"nexus-agents brief generation failed ({exc.response.status_code})",
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning("brief trigger failed: %s", exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "nexus-agents unreachable for brief generation",
        ) from exc


@router.get("/lifecycle-actions/{ticket}", dependencies=[Depends(_trading_view)])
async def get_lifecycle_action_for_ticket(ticket: int):
    """RL lifecycle action for a specific position ticket."""
    raw = await _redis_get(f"nexus:rl:lifecycle:{ticket}")
    if raw:
        return _loads(raw, f"lifecycle action {ticket}")
    return {"ticket": ticket, "action": "HOLD", "confidence": 0.0, "model": "not_found"}


@router.get("/trade-memory", dependencies=[Depends(_trading_view)])
async def get_trade_memory_full():
    """Full trade memory snapshot: metrics, thresholds, bias."""
    try:
        r = await _get_redis()
        metrics_raw = await r.get("nexus:trade_memory:metrics")
        thresholds_raw = await r.get("nexus:trade_memory:thresholds")
        trades_raw = await r.get("nexus:trade_memory:trades")
        metrics = json.loads(metrics_raw) if metrics_raw else {}
        thresholds = json.loads(thresholds_raw) if thresholds_raw else {}
        trades = json.loads(trades_raw) if trades_raw else []
        if not isinstance(metrics, dict) or not isinstance(thresholds, dict) or not isinstance(trades, list):
            raise ValueError("Trade memory snapshot has an invalid shape")
        return {
            "metrics": metrics,
            "thresholds": thresholds,
            "recent_trades": trades[-20:],
        }
    except Exception as exc:
        logger.warning("trade-memory.unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Trade memory is temporarily unavailable",
        ) from exc



@router.get("/institutional/{symbol}", dependencies=[Depends(_trading_view)])
async def get_institutional_features(symbol: str):
    """
    Pre-computed institutional features: Hurst, Kelly ergódico, Lyapunov, etc.
    Calculados cada 60s por nexus_features. TTL Redis 300s.
    """
    key = f"nexus:features:institutional:{symbol.upper()}"
    try:
        r = await _get_redis()
        raw = await r.get(key)
    except Exception as exc:
        logger.warning("institutional_features.redis_failed: %s", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Intelligence store is temporarily unavailable",
        ) from exc
    if raw:
        return {"status": "ok", "symbol": symbol.upper(), "data": _loads(raw, "institutional features")}
    # Fallback: proxy to nexus_features directly
    features_url = os.getenv(
        "NEXUS_FEATURES_URL", "http://127.0.0.1:9002"
    )
    internal_secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
    if not internal_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "NEXUS_INTERNAL_API_SECRET is not configured",
        )
    try:
        async with new_client(timeout=5.0) as client:
            resp = await client.get(
                f"{features_url}/api/features/institutional/{symbol.upper()}",
                headers={"X-Nexus-Internal-Secret": internal_secret},
            )
    except httpx.HTTPError as exc:
        logger.warning("institutional_features.proxy_unreachable: %s", exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "nexus-features unreachable",
        ) from exc
    if resp.status_code == 200:
        try:
            return resp.json()
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                "nexus-features returned an invalid payload",
            ) from exc
    return {"status": "calculating", "symbol": symbol.upper(), "data": None}
