"""
Nexus Trader — Runtime Settings (front-configurable, shared by all services).

A single source of truth for the operational knobs the user can change live
from the dashboard WITHOUT restarting services or editing YAML:

  - risk budget (daily loss %, risk per trade %)
  - position / trade caps (max open positions, max daily trades)
  - scalping timing (min hold minutes, max hold minutes)
  - strategy research aggressiveness (min candidates, search rounds)

The settings live in Redis under a single key so both the ML pipeline
(nexus-ml) and the risk + agent pipeline (nexus-risk / nexus-agents) read the
exact same values. This unifies what used to be two divergent config sources
(``trading_mode.py`` vs ``risk_rules.yaml``).

Reads are tolerant: if Redis is unavailable the in-code DEFAULTS are returned,
so the system always has sane behaviour.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
from typing import Any

from shared.sessions import TradingSession

try:
    from redis.exceptions import WatchError

    from shared.redis_client import RedisClient
except Exception:  # pragma: no cover - allows import in isolated tests
    RedisClient = None  # type: ignore[assignment]

    class WatchError(Exception):  # type: ignore[no-redef]
        """Placeholder so the CAS-fallback path still works without redis."""

# Raw Redis key (no prefix) shared across every service.
SETTINGS_KEY = "nexus:runtime:settings"

# Persist effectively forever; writers re-set on every update.
_TTL_SEC = 10 * 365 * 24 * 3600

# ── Defaults (user-requested) ────────────────────────────────────────────────
# These are the values the system boots with the first time, before the user
# touches anything from the dashboard.
DEFAULTS: dict[str, Any] = {
    # Risk budget
    "risk_per_trade_pct": 1.0,      # % of equity risked per trade
    "max_daily_loss_pct": 20.0,     # daily loss budget before trades pause
    "max_weekly_dd_pct": 25.0,      # weekly drawdown budget
    # Caps
    "max_open_positions": 5,        # simultaneous positions
    "max_daily_trades": 5,          # trades per day
    # Scalping timing (minutes)
    "min_hold_minutes": 5,          # do not exit before this many minutes
    "max_hold_minutes": 60,         # force-exit after this many minutes
    # Conviction gate (0..1). null/None = use the per-session default.
    "min_conviction_override": None,
    # Strategy research aggressiveness
    "research_min_candidates": 4,   # strategies designed per research cycle
    "research_max_search_rounds": 3,  # keep searching until a good one or N rounds
    "research_interval_sec": 1800,  # base seconds between research cycles
    # Multi-timeframe
    "require_mtf_confirmation": True,
    "min_mtf_agreement": 1,
    # Operational timeframe (synced on scalping/swing mode switch)
    "operational_tf": "M5",
    "trading_mode_type": "scalping",
    # Auto-select M1/M5/M15 from session + volatility + spread (scalping only)
    "auto_tf_selection": True,
    # Local-only GenAI provider. Kept in the wire contract for compatibility,
    # but any patch is coerced to "local".
    "llm_provider": "local",
    # ── Session gate (بوابة الجلسات) ────────────────────────────────────
    # Environment variables seed these DEFAULTS only: a value saved from the
    # Settings tab is stored under the same Redis key and always wins, which
    # is what makes the gate editable from the UI instead of read-only.
    # Enforcement goes through session_gate_policy() so risk + agents agree.
    "off_hours_allowed": os.getenv("NEXUS_ALLOW_OFF_HOURS", "false").strip().lower()
    in ("1", "true", "yes", "on"),
    "allowed_sessions": [
        s.strip().upper()
        for s in os.getenv("NEXUS_ALLOWED_SESSIONS", "LONDON,NEW_YORK,OVERLAP").split(",")
        if s.strip()
    ]
    or ["LONDON", "NEW_YORK", "OVERLAP"],

    # ── Dashboard Settings tab ────────────────────────────────────────────
    # Every knob the General Settings page exposes gets a stored/default value
    # here so the page (via GET /api/intelligence/settings ``defaults``) always
    # has something to render, and so readers see the same effective value the
    # system uses today. Defaults below mirror the services' own fallbacks
    # (risk rules, traders_api, trade_memory, correlation, research cycle).

    # Risk & Sizing
    "max_spread_pips": 3.0,          # reject entries above this spread (pips)
    "sl_atr_multiplier": 1.5,        # SL distance as a multiple of ATR
    "tp_atr_multiplier": 3.0,        # TP distance as a multiple of ATR
    "min_rr_ratio": 1.5,             # minimum reward/risk accepted by the gate
    "max_hold_bars": 50,             # force-exit after this many bars
    "cooling_off_streak": 3,         # consecutive losses before a pause
    "sl_floor_atr_mult": 2.5,        # absolute floor of the SL in ATR multiples
    "entry_displacement_atr_mult": 2.0,  # reject if price already moved N×ATR
    # Signals & quality
    "quality_score_threshold": 0,    # 0 = use TradeMemory's dynamic threshold
    "autonomous_ml": False,          # run ML/DL/RL without GenAI confirmation
    "pre_signal_spread_filter": True,  # block signals while the spread is wide
    "signal_cooldown_sec": 60,       # min seconds between signals per symbol
    "min_confidence_floor": 0.40,    # absolute conviction floor post-adjust
    "conviction_min": 0.55,          # base conviction outside the session
    # Models & training
    "retrain_interval_hours": 4,     # hours between automatic retrains
    "outcome_weight": 5,             # weight of real trades in training
    "allow_synthetic_training": False,  # synthetic samples only as a fallback
    "dl_seq_len": 30,                # Transformer input sequence length
    "dl_confidence_threshold": 0.45,  # min DL confidence to emit a signal
    "rl_n_epochs": 15,               # PPO epochs per retraining cycle
    # Notifications
    "notif_enable_browser": False,   # OS push notifications from the tab
    "notif_blackout": False,         # alert on news-blackout toggles
    "notif_brief": False,            # alert when the daily GenAI brief lands
    "notif_corr_divergence": False,  # alert on HIGH correlation divergence
    # Correlation
    "corr_refresh_sec": 300,         # seconds between correlation recalcs
    "corr_divergence_threshold": 0.25,  # 7d-vs-30d delta flagged as divergence
    "corr_window_default": "7d",     # window opened by the correlation panel
    # Trade memory
    "trade_memory_window": 200,      # recent trades kept for dynamic thresholds
    "cooling_off_duration_sec": 300,  # pause once the loss streak is hit
    # Backtesting
    "backtest_initial_equity": 5000,  # starting equity for new backtests
    "backtest_default_symbol": "XAUUSD",  # symbol pre-selected by the panel
    # GenAI & research
    "disable_research": False,       # pause the weekly strategy research cycle
    "strategy_min_profit_factor": 1.4,  # PF required to promote a strategy
    "strategy_min_win_rate": 0.52,   # WR required to adopt a new strategy
    "genai_max_calls_per_hour": 30,  # GenAI API rate limit
}

# Bounds to keep front-supplied values sane (defensive clamping).
_BOUNDS: dict[str, tuple[float, float]] = {
    "risk_per_trade_pct": (0.1, 5.0),
    "max_daily_loss_pct": (1.0, 50.0),
    "max_weekly_dd_pct": (1.0, 60.0),
    "max_open_positions": (1, 20),
    "max_daily_trades": (1, 100),
    "min_hold_minutes": (0, 240),
    "max_hold_minutes": (1, 1440),
    "research_min_candidates": (1, 12),
    "research_max_search_rounds": (1, 8),
    "research_interval_sec": (120, 7200),
    "min_mtf_agreement": (0, 3),
    # ── Dashboard Settings tab ────────────────────────────────────────────
    # Each tuple must CONTAIN the page.tsx min/max for the key (the contract
    # test parses the page and fails if the UI can offer a value the backend
    # would silently clamp away). Bools/strings are deliberately absent: they
    # are not clamped numerically.
    "max_spread_pips": (0.1, 10.0),
    "sl_atr_multiplier": (1.0, 5.0),
    "tp_atr_multiplier": (2.0, 10.0),
    "min_rr_ratio": (1.0, 5.0),
    "max_hold_bars": (1, 50),            # page range 1..48
    "cooling_off_streak": (2, 10),
    "sl_floor_atr_mult": (1.0, 5.0),
    "entry_displacement_atr_mult": (0.5, 5.0),
    "quality_score_threshold": (0, 90),
    "signal_cooldown_sec": (10, 300),
    "min_confidence_floor": (0.20, 0.70),
    "conviction_min": (0.40, 0.80),
    "retrain_interval_hours": (1, 24),
    "outcome_weight": (1, 10),
    "dl_seq_len": (5, 50),
    "dl_confidence_threshold": (0.30, 0.80),
    "rl_n_epochs": (5, 50),
    "corr_refresh_sec": (60, 3600),
    "corr_divergence_threshold": (0.10, 0.70),
    "trade_memory_window": (20, 500),
    "cooling_off_duration_sec": (60, 3600),
    "backtest_initial_equity": (500, 500000),
    "strategy_min_profit_factor": (1.0, 3.0),
    "strategy_min_win_rate": (0.40, 0.80),
    "genai_max_calls_per_hour": (5, 120),
}

_VALID_TFS = {"M1", "M5", "M15", "M30", "H1", "H4", "D1"}

# Enumerated string knobs (Settings-tab <select> fields): only these values are
# legal. Unknown strings are NEVER coerced to a wrong value — readers fall back
# to the default and writers drop the key (same "garbage ⇒ drop" rule booleans
# use), because persisting e.g. "bogus" as the correlation window or a symbol
# the backtester cannot resolve would silently change behaviour.
_VALID_STRINGS: dict[str, tuple[str, ...]] = {
    "corr_window_default": ("7d", "30d"),
    "backtest_default_symbol": ("XAUUSD", "EURUSD", "BTCUSD", "US500"),
}
# lower-cased lookup → canonical spelling (accepts "7D" / "xauusd" input).
_STRING_CHOICES: dict[str, dict[str, str]] = {
    key: {choice.lower(): choice for choice in choices}
    for key, choices in _VALID_STRINGS.items()
}

# Session names come from shared.sessions (single source of truth); unknown
# names are dropped on read/write so the gate can never trust a typo.
_VALID_SESSIONS: frozenset[str] = frozenset(s.value for s in TradingSession)
_SESSION_ORDER: dict[str, int] = {s.value: i for i, s in enumerate(TradingSession)}


def _coerce_sessions(value: Any) -> list[str]:
    """Normalize a session list: canonical names, canonical order, no dupes.

    Unusable input falls back to the default set (never to an empty list, which
    would silently block every trade); an explicitly empty list is preserved by
    ``sanitize_patch``/``_interpretable`` and stays empty here.
    """
    if isinstance(value, str):
        items: list[Any] = value.split(",")
    elif isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
    else:
        return list(DEFAULTS["allowed_sessions"])
    picked = {str(i).strip().upper() for i in items}
    return sorted(
        (name for name in picked if name in _VALID_SESSIONS),
        key=_SESSION_ORDER.__getitem__,
    )

# Process-local cache so synchronous code paths (e.g. trading_mode helpers) can
# read the most recent values without an await. Refreshed on every async read.
_cache: dict[str, Any] = dict(DEFAULTS)

# Module-level shared client so we DON'T pay the connection-establishment cost
# (which can be ~2s per new connection on Windows) on every settings read.
_shared_client: "RedisClient | None" = None
_last_fetch: float = 0.0
# Throttle remote reads: callers may invoke get_settings() in hot loops; serve
# the cached value if it was refreshed very recently.
_FETCH_TTL_SEC = 5.0


async def _get_shared_client() -> "RedisClient | None":
    """Return a lazily-created, reused, connected RedisClient (or None)."""
    global _shared_client
    if RedisClient is None:
        return None
    if _shared_client is None:
        try:
            _shared_client = RedisClient()
            await _shared_client.connect()
        except Exception:
            _shared_client = None
    return _shared_client


def _coerce(key: str, value: Any) -> Any:
    """Coerce + clamp a single setting; fall back to default on bad input."""
    default = DEFAULTS.get(key)
    if key == "min_conviction_override":
        if value in (None, "", "null"):
            return None
        try:
            v = float(value)
            return max(0.0, min(1.0, v)) if math.isfinite(v) else None
        except (TypeError, ValueError, OverflowError):
            return None
    if key == "llm_provider":
        return "local"
    if key in _STRING_CHOICES:
        # Whitelisted select: canonical value, else the default (never a
        # caller-supplied string the page/UI does not offer).
        if isinstance(value, str):
            found = _STRING_CHOICES[key].get(value.strip().lower())
            if found is not None:
                return found
        return default
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(default, int) and not isinstance(default, bool):
        try:
            v: float = float(value)
        except (TypeError, ValueError, OverflowError):
            return default
        if not math.isfinite(v):
            return default
        lo, hi = _BOUNDS.get(key, (v, v))
        return int(max(lo, min(hi, v)))
    if isinstance(default, float):
        try:
            v = float(value)
        except (TypeError, ValueError, OverflowError):
            return default
        if not math.isfinite(v):
            return default
        lo, hi = _BOUNDS.get(key, (v, v))
        return float(max(lo, min(hi, v)))
    if isinstance(default, list):
        return _coerce_sessions(value)
    return value


def merge_with_defaults(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Return a complete settings dict: defaults overlaid with valid overrides."""
    out = dict(DEFAULTS)
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k in DEFAULTS:
                out[k] = _coerce(k, v)
    return out


def _interpretable(key: str, value: Any) -> bool:
    """Can ``value`` be turned into a sane setting for ``key``?

    Used on the *write* path only: a malformed value must never be persisted
    as policy.  Garbage ⇒ drop the key (the stored override survives), while
    ``None`` remains the explicit "reset to default" signal handled by
    ``_apply_patch``.  Reads keep their own tolerant behaviour in
    ``merge_with_defaults`` (fall back to default), which is what the
    ``test_runtime_settings_fall_back_to_defaults_on_garbage_input`` contract
    covers — a read that cannot trust the store must still return something
    complete.  Writing that same default back would silently destroy a valid
    override the user already saved.
    """
    default = DEFAULTS.get(key)
    if key == "llm_provider":
        return True
    if key in _STRING_CHOICES:
        # Only the offered options are writable; anything else is dropped so a
        # typo/unknown symbol can never be persisted as policy.
        return isinstance(value, str) and value.strip().lower() in _STRING_CHOICES[key]
    if key == "min_conviction_override":
        if value in (None, "", "null"):
            return True
        try:
            return math.isfinite(float(value))
        except (TypeError, ValueError, OverflowError):
            return False
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.strip().lower() in (
                "1", "true", "yes", "on", "0", "false", "no", "off",
            )
        # "" / "banana" / {} must not silently switch a safety toggle off.
        return isinstance(value, (bool, int, float))
    if isinstance(default, (int, float)) and not isinstance(default, bool):
        try:
            return math.isfinite(float(value))
        except (TypeError, ValueError, OverflowError):
            return False
    if isinstance(default, list):
        if isinstance(value, (list, tuple, set, frozenset)):
            return True
        # A comma-separated string is accepted; "" must not wipe the set.
        if isinstance(value, str):
            return bool(value.strip())
        return False
    return True


def sanitize_patch(values: dict[str, Any]) -> dict[str, Any]:
    """Coerce and clamp client-supplied overrides *before* they are persisted.

    ``None`` is passed through untouched because writers treat it as
    "delete this override".  Unknown keys pass through as well (extras are
    tolerated by design); known keys are clamped with the very same
    ``_coerce``/``_BOUNDS`` rules ``merge_with_defaults`` applies on read, so
    an out-of-range value can never be stored as policy.

    Known keys whose value cannot be interpreted at all (``"not-a-number"``,
    ``""``, a stray dict) are **dropped** rather than coerced to the default:
    a bad write must not silently reset a setting the user already saved.
    """
    clean: dict[str, Any] = {}
    for key, value in values.items():
        if value is None:
            clean[key] = None
        elif key not in DEFAULTS:
            clean[key] = value
        elif _interpretable(key, value):
            clean[key] = _coerce(key, value)
    return clean


def get_cached() -> dict[str, Any]:
    """Synchronous best-effort read of the last-known settings (no await)."""
    return dict(_cache)


def session_gate_policy(
    settings: Any = None,
    *,
    default_off_hours: bool = False,
    default_sessions: Any = None,
) -> tuple[bool, set[str]]:
    """Resolve the session gate as ``(off_hours_allowed, allowed_sessions)``.

    ``settings`` defaults to the process cache, which every async read
    refreshes, so synchronous enforcement paths (agents graph, risk breaker
    probes) stay live without an ``await``. Values saved from the Settings tab
    win; when a key is absent the env-derived defaults passed by the caller are
    used, keeping ``NEXUS_ALLOW_OFF_HOURS`` / ``NEXUS_ALLOWED_SESSIONS`` working
    as the deployment default.

    ``"OFF_HOURS"`` appearing in the allowed set is equivalent to switching the
    off-hours toggle on — the historical behaviour of
    ``ALLOW_OFF_HOURS or "OFF_HOURS" in ALLOWED_SESSIONS``.
    """
    doc = _cache if settings is None else settings
    if not isinstance(doc, dict):
        doc = {}

    if (
        "allowed_sessions" in doc
        and _interpretable("allowed_sessions", doc.get("allowed_sessions"))
    ):
        allowed = set(_coerce_sessions(doc.get("allowed_sessions")))
    else:
        # Absent or unusable value ⇒ the caller's deployment default (an
        # explicitly empty list is interpretable, so it is kept as a kill switch).
        allowed = {
            str(s).strip().upper() for s in (default_sessions or ()) if str(s).strip()
        }

    stored_off = doc.get("off_hours_allowed")
    off_ok = bool(stored_off) if isinstance(stored_off, bool) else bool(default_off_hours)
    return (off_ok or "OFF_HOURS" in allowed), allowed


# Alias used by nexus-agents (position_manager, main)
get_cached_settings = get_cached


async def get_settings(
    redis: "RedisClient | None" = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Async read from Redis, merged with defaults. Updates the local cache.

    Reuses a shared connection and throttles remote reads (``_FETCH_TTL_SEC``)
    so hot-loop callers don't hammer Redis. Pass ``force=True`` to bypass the
    throttle (e.g. right after an update).
    """
    global _cache, _last_fetch
    import time as _t

    if not force and (_t.monotonic() - _last_fetch) < _FETCH_TTL_SEC:
        return dict(_cache)

    r = redis or await _get_shared_client()
    try:
        raw = await r.cache_get(SETTINGS_KEY, prefix=False) if r else None
        merged = merge_with_defaults(raw if isinstance(raw, dict) else None)
        _cache = merged
        _last_fetch = _t.monotonic()
        return merged
    except Exception:
        return dict(_cache)


async def update_settings(
    patch: dict[str, Any],
    redis: "RedisClient | None" = None,
) -> dict[str, Any]:
    """Persist a merged patch, then cache and return it. Raise on write failure.

    The stored document is updated in place: keys outside ``DEFAULTS`` that
    other writers put under ``SETTINGS_KEY`` (e.g. the dashboard General
    Settings tab's ``notif_*`` / ``corr_*`` / ``trade_memory_*`` / ``dl_*``
    overrides written via ``POST /api/intelligence/settings``) are preserved
    instead of being rewritten with a defaults-only document.  The
    read-modify-write runs inside a WATCH/MULTI optimistic loop so concurrent
    writers cannot silently drop each other's patch (lost update).
    """
    global _cache
    r = redis or await _get_shared_client()
    if r is None:
        raise RuntimeError("Cannot persist runtime settings: Redis is unavailable")
    document = await _update_document(r, patch or {})
    merged = merge_with_defaults(document)
    _cache = merged
    return merged


# ── Atomic persistence internals ─────────────────────────────────────────────

# Optimistic CAS attempts before degrading to the legacy non-atomic write.
_MAX_CAS_RETRIES = 8


def _decode_document(raw: Any) -> dict[str, Any]:
    """Best-effort decode of the raw stored document; anything else ⇒ ``{}``."""
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, (bytes, str)):
        try:
            decoded = json.loads(raw)
        except ValueError:
            return {}
        return dict(decoded) if isinstance(decoded, dict) else {}
    return {}


def _build_document(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Merge a patch over the stored document WITHOUT dropping unknown keys.

    Known keys are coerced/clamped exactly as before; keys outside
    ``DEFAULTS`` (dashboard-only overrides consumed via raw Redis reads, e.g.
    ``trade_memory.py``'s ``trade_memory_window``) pass through untouched.
    """
    view = merge_with_defaults(base)
    extras = {k: v for k, v in base.items() if k not in DEFAULTS}
    document: dict[str, Any] = {**extras, **view}
    for k, v in patch.items():
        if k in DEFAULTS:
            document[k] = _coerce(k, v)
    return document


async def _update_document(r: "RedisClient", patch: dict[str, Any]) -> dict[str, Any]:
    """Read-modify-write ``SETTINGS_KEY``; degrade to plain read+SET on CAS failure."""
    try:
        return await _cas_update(r, patch)
    except (WatchError, RuntimeError, AttributeError):
        # WATCH is unavailable (client without ``.r``, e.g. test doubles) or
        # contention was never resolved: fall back to the legacy non-atomic
        # read + write rather than failing the caller's save outright.  Any
        # other exception (connection loss, ...) still propagates so callers
        # keep their 503 semantics.
        raw = await r.cache_get(SETTINGS_KEY, prefix=False)
        document = _build_document(_decode_document(raw), patch)
        await r.cache_set(SETTINGS_KEY, document, ttl_sec=_TTL_SEC, prefix=False)
        return document


async def _cas_update(r: "RedisClient", patch: dict[str, Any]) -> dict[str, Any]:
    """Optimistic WATCH/MULTI update of the whole settings document."""
    last: Exception | None = None
    for _ in range(_MAX_CAS_RETRIES):
        pipe = r.r.pipeline()
        try:
            await pipe.watch(SETTINGS_KEY)
            raw = await pipe.get(SETTINGS_KEY)
            document = _build_document(_decode_document(raw), patch)
            pipe.multi()
            # Always re-set the long TTL: this also self-heals a short TTL
            # left behind by other writers (e.g. the 7-day intelligence route).
            pipe.set(SETTINGS_KEY, json.dumps(document, default=str), ex=_TTL_SEC)
            await pipe.execute()
            return document
        except WatchError as exc:
            last = exc
            continue
        finally:
            try:
                await pipe.reset()
            except Exception:  # noqa: BLE001 - cleanup must never mask the error
                pass
    raise last if last else RuntimeError("runtime settings CAS update failed")


__all__ = [
    "DEFAULTS",
    "SETTINGS_KEY",
    "get_settings",
    "get_cached",
    "get_cached_settings",
    "update_settings",
    "merge_with_defaults",
]
