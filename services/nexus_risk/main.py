"""
Nexus Risk — FastAPI service (port 8006).

Provides REST endpoints for risk evaluation, circuit-breaker status, and
position sizing.  Also runs a background Redis Stream consumer that
evaluates incoming trade proposals in real time.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import math
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Literal

import httpx
from shared.http_client import new_client
import structlog
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from shared.config_loader import ConfigLoader
from shared.constants import (
    CACHE_RISK_STATE,
    RedisStream,
    RiskDecision,
    ServiceName,
)
from shared.events import RiskDecisionEvent, TradeCloseEvent
from shared.models import CircuitBreaker, RiskState, TradeProposal
from shared.nexus_trades import is_nexus_comment, partition_positions
from shared.redis_client import RedisClient
from shared.safety import approval_signature
from shared.sessions import detect_session_now
from shared import runtime_settings

import time as _time_mod

from .anti_tilt import AntiTilt, TiltStatus
from .correlation_checker import CorrelationChecker
from .position_sizer import PositionSizer
from .rules_engine import RulesEngine

from shared import setup_logger as _setup_logger
_setup_logger("nexus-risk")
log = structlog.get_logger(__name__)

# ── Globals ───────────────────────────────────────────────────────────────────

redis = RedisClient()
config = ConfigLoader()
rules_engine = RulesEngine(config)
position_sizer = PositionSizer(config)
correlation_checker = CorrelationChecker()
anti_tilt = AntiTilt()

_current_state: dict[str, Any] = {
    "available": False,
    "balance": 0.0,
    "equity": 0.0,
    "daily_loss_pct": 0.0,
    "weekly_dd_pct": 0.0,
    "weekly_dd_source": "fallback",   # "fallback" = series empty/failed (old behavior)
    "open_positions_count": 0,
    "open_positions": [],
    "total_positions_count": 0,
    "external_positions_count": 0,
    "tilt_status": "NORMAL",
    # ── Phase 3 portfolio-gate state (additive; None = unknown until first sync) ──
    # Names mirror what rules_engine.check_all_rules reads: equity_peak,
    # equity_peak_day, open_risk_amount, gross_leverage, correlation_snapshot.
    "equity_peak": 0.0,
    "equity_peak_day": "",
    "dd_from_peak_pct": 0.0,
    "open_risk_usd": None,
    "open_risk_amount": None,     # engine-facing alias of open_risk_usd
    "open_risk_pct": None,
    "gross_leverage": None,
    "correlation_exposure": 0.0,
    "correlation_snapshot": None,  # proposal-time pairs (injected per evaluate)
    "correlation_data_status": "disabled",  # disabled | ok | unavailable
    "daily_trade_count": 0,
    "max_daily_trades": 0,        # engine breaker row reads this key
    "current_session": "",
}
_day_start_balance: float = 0.0  # captured on first successful sync each day
_last_sync_day: str = ""         # ISO date of last balance snapshot
_daily_trade_count: int = 0      # trades executed today (reset on new day / manual reset)
_trades_paused: bool = False     # manual pause flag (cleared by reset-day)
_DAILY_COUNT_KEY = "nexus:risk:daily_trade_count"  # persisted in Redis
_DAILY_COUNT_DAY_KEY = "nexus:risk:daily_count_day"
_RECENT_RESULTS_KEY = "nexus:risk:recent_results"  # list of recent pnl values

# ── Phase 3 portfolio-gate process state ─────────────────────────────────────
# The equity high-water mark is restored from Redis on startup so a restart
# never loses the peak ("peak ينجو من إعادة التشغيل"). It is re-baselined only
# on a new day (mirroring _DAY_START_BALANCE) or by reset-day.
_equity_peak: float = 0.0
_equity_peak_day: str = ""            # ISO date the peak record was last written
_daily_trades_limit_observed: int = 0  # last runtime daily-trade cap seen (breakers)

# Optional injectable bars provider for the real correlation gate. When unset,
# real closes are read from the Redis OHLCV cache nexus-data publishes
# (nexus:ohlcv:{symbol}:{tf}); when those are missing the gate treats the
# input as unverifiable (fail-closed while correlation_threshold is set).
_correlation_bars_provider: Callable[[list[str], int], Any] | None = None
_CORRELATION_TF = os.getenv("NEXUS_CORRELATION_TF", "M15").strip().upper() or "M15"

# ── Nexus-only daily PnL ─────────────────────────────────────────────────────
# The daily-loss breaker must react ONLY to trades this system placed. The MT5
# account is shared (manual trades / other EAs show up as "external"), and on
# 2026-07-16 an external -$1,092 session tripped the 20% breaker and froze
# Nexus for the rest of the day even though Nexus itself was flat (-$0.08).
_NEXUS_DAILY_PNL_KEY = "nexus:risk:nexus_daily_pnl"
_NEXUS_DAILY_PNL_DAY_KEY = "nexus:risk:nexus_daily_pnl_day"


async def _get_nexus_daily_pnl() -> float:
    """Cumulative closed PnL of Nexus-placed trades for the current UTC day."""
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        stored_day = await redis.r.get(_NEXUS_DAILY_PNL_DAY_KEY)
        if stored_day != today:
            return 0.0
        raw = await redis.r.get(_NEXUS_DAILY_PNL_KEY)
        return float(raw) if raw is not None else 0.0
    except Exception:
        log.warning("risk.nexus_daily_pnl.read_failed", exc_info=True)
        raise


async def _add_nexus_daily_pnl(pnl_usd: float) -> None:
    """Accumulate a closed Nexus trade's PnL into today's bucket (day-aware)."""
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        stored_day = await redis.r.get(_NEXUS_DAILY_PNL_DAY_KEY)
        if stored_day != today:
            await redis.r.set(_NEXUS_DAILY_PNL_KEY, "0", ex=172_800)
            await redis.r.set(_NEXUS_DAILY_PNL_DAY_KEY, today, ex=172_800)
        await redis.r.incrbyfloat(_NEXUS_DAILY_PNL_KEY, round(pnl_usd, 2))
    except Exception:
        log.debug("risk.nexus_daily_pnl.update_failed", exc_info=True)
        raise
_DAY_START_BALANCE_KEY = "nexus:risk:day_start_balance"  # persisted across restarts
_EQUITY_PEAK_KEY = "nexus:risk:equity_peak"     # equity high-water mark (Phase 3)
_EQUITY_PEAK_DAY_KEY = "nexus:risk:equity_peak_day"  # ISO date of the peak record
_EQUITY_SERIES_KEY = "nexus:risk:equity_series"       # 7-day (day, equity) series
_OPEN_RISK_SNAPSHOT_KEY = "nexus:risk:open_risk_snapshot"  # Σ(open lots × risk/lot)
_EQUITY_SERIES_MAX_DAYS = 7
_EQUITY_SERIES_TTL_SEC = 10 * 86_400
_DAY_START_DAY_KEY = "nexus:risk:day_start_day"          # ISO date for the balance

SERVICE_NAME = os.getenv("NEXUS_SERVICE_NAME", ServiceName.RISK)
SERVICE_PORT = int(os.getenv("NEXUS_SERVICE_PORT", "9006"))
CONSUMER_GROUP = "nexus-risk-group"
CONSUMER_NAME = "nexus-risk-1"
AGGRESSIVE_TRADING = os.getenv("NEXUS_AGGRESSIVE_TRADING", "false").lower() == "true"
EXECUTOR_URL = os.getenv("NEXUS_EXECUTOR_URL", "http://127.0.0.1:9007")
ACCOUNT_SYNC_INTERVAL = int(os.getenv("NEXUS_ACCOUNT_SYNC_INTERVAL", "30"))

# Watchdog for a dead account-sync loop: `available` is flipped off during
# every sync attempt, but if the loop task itself dies the last success would
# otherwise stay "available" forever. Proposals then fail closed on staleness.
ACCOUNT_STATE_MAX_STALE_SEC = float(
    os.getenv(
        "NEXUS_ACCOUNT_STATE_MAX_STALE_SEC",
        str(max(ACCOUNT_SYNC_INTERVAL * 3, 90)),
    )
)

# Per-message side-effect idempotency records (daily PnL, loss streaks, ...)
# survive long enough to cover any pending-entry reclaim window.
TRADE_CLOSE_EFFECT_IDEM_TTL_SEC = int(
    os.getenv("NEXUS_RISK_IDEMPOTENCY_TTL_SEC", str(30 * 24 * 3600))
)


def _ensure_approval_signing_secret() -> str:
    """Effective approval-signing key — migration-safe read.

    Prefers the dedicated NEXUS_RISK_APPROVAL_SECRET distributed only to
    nexus-risk (sign) and nexus-executor (verify). When it is unset (ad-hoc
    or manual start; run.py and preflight refuse to boot without it) fall back
    once to the legacy NEXUS_INTERNAL_API_SECRET so an in-flight upgrade keeps
    verifying. Signing still fails closed when neither key is configured.
    """
    dedicated = os.getenv("NEXUS_RISK_APPROVAL_SECRET", "").strip()
    if dedicated:
        return dedicated
    legacy = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
    if legacy:
        os.environ["NEXUS_RISK_APPROVAL_SECRET"] = legacy
        log.warning(
            "risk.approval_secret.legacy_fallback_active",
            msg=(
                "NEXUS_RISK_APPROVAL_SECRET is unset; approval signing is "
                "falling back to the shared internal secret. Configure the "
                "dedicated approval key before live trading."
            ),
        )
    return os.getenv("NEXUS_RISK_APPROVAL_SECRET", "").strip()

# Hard session gate — every proposal is checked against the server clock, so
# no caller-supplied state can sneak a trade through at 00:30 rollover again.
# Overridable: NEXUS_ALLOW_OFF_HOURS=true disables the gate entirely.
ALLOW_OFF_HOURS = os.getenv("NEXUS_ALLOW_OFF_HOURS", "false").lower() == "true"
ALLOWED_SESSIONS = {
    s.strip().upper()
    for s in os.getenv("NEXUS_ALLOWED_SESSIONS", "LONDON,NEW_YORK,OVERLAP").split(",")
    if s.strip()
}


# ── Portfolio gates (Phase 3) — data plane ───────────────────────────────────
# cfg fields live on RulesEngineConfig (owned by C1) with None defaults: a gate
# is skipped while its field is None, so an absent `capital:` section keeps
# every decision byte-identical to Phase 2. Every helper below tolerates the
# fields (and even the whole portfolio section) not existing yet.

_PORTFOLIO_CFG_KEYS = (
    "max_drawdown_from_peak_pct",
    "max_portfolio_open_risk_pct",
    "max_gross_leverage",
    "max_net_currency_exposure_pct",
    "correlation_threshold",
    "correlation_lookback_bars",
    "max_same_direction_cluster",
)

# Candidate `capital:` key names (plan names first, plausible aliases after).
_YAML_PORTFOLIO_ALIASES: dict[str, tuple[str, ...]] = {
    "max_drawdown_from_peak_pct": (
        "max_drawdown_from_peak_pct", "drawdown_from_peak_pct", "max_dd_from_peak_pct",
    ),
    "max_portfolio_open_risk_pct": (
        "max_portfolio_open_risk_pct", "portfolio_open_risk_pct", "max_open_risk_pct",
    ),
    "max_gross_leverage": ("max_gross_leverage", "gross_leverage"),
    "max_net_currency_exposure_pct": (
        "max_net_currency_exposure_pct", "net_currency_exposure_pct",
    ),
    "correlation_threshold": ("correlation_threshold", "max_portfolio_correlation"),
    "correlation_lookback_bars": ("correlation_lookback_bars",),
    "max_same_direction_cluster": ("max_same_direction_cluster", "same_direction_cluster"),
}


def _portfolio_cfg_value(name: str) -> Any:
    """Read one portfolio cfg field from the engine config (None when absent)."""
    cfg = getattr(rules_engine, "_cfg", None)
    if cfg is None:
        return None
    return getattr(cfg, name, None)


def _apply_portfolio_gate_cfg_from_yaml() -> None:
    """Pass `capital:` portfolio values into RulesEngineConfig at construction.

    Tolerates absence in both directions: no yaml keys yet (C1 may not have
    added them) and no cfg fields on the engine are both no-ops, so service
    construction behaves exactly like Phase 2 in either case.

    Master switch (Phase 3): `NEXUS_RISK_PORTFOLIO_GATES` empty/absent/off
    (the .env.example default) blocks the whole section — every portfolio
    field stays None and all gates remain skipped even if `capital:` carries
    values, so golden decisions stay byte-identical until the flag is on.
    """
    _flag = os.getenv("NEXUS_RISK_PORTFOLIO_GATES", "").strip().lower()
    if _flag in ("", "0", "off", "false", "no"):
        return
    try:
        raw = config._load_yaml("risk_rules.yaml")
    except Exception:
        return
    capital = raw.get("capital", {}) if isinstance(raw, dict) else {}
    if not isinstance(capital, dict):
        return
    payload: dict[str, Any] = {}
    for field, aliases in _YAML_PORTFOLIO_ALIASES.items():
        for alias in aliases:
            if alias in capital and capital[alias] is not None:
                payload[field] = capital[alias]
                break
    if not payload:
        return
    # Prefer an explicit engine API when C1 exposes one; fall back to direct
    # field assignment only for fields the engine actually declares.
    for api_name in (
        "apply_portfolio_gate_config",
        "apply_portfolio_gates_config",
        "set_portfolio_gate_config",
    ):
        api = getattr(rules_engine, api_name, None)
        if callable(api):
            try:
                api(payload)
                log.info("risk.portfolio_cfg.applied", api=api_name, fields=sorted(payload))
            except Exception:
                log.warning("risk.portfolio_cfg.api_failed", api=api_name, exc_info=True)
            return
    cfg = getattr(rules_engine, "_cfg", None)
    if cfg is None:
        return
    applied = []
    for field, value in payload.items():
        if hasattr(cfg, field):
            try:
                setattr(cfg, field, value)
                applied.append(field)
            except Exception:
                log.debug("risk.portfolio_cfg.set_failed", field=field, exc_info=True)
    if applied:
        log.info("risk.portfolio_cfg.applied", fields=sorted(applied))


_apply_portfolio_gate_cfg_from_yaml()


# ── Equity peak (drawdown-from-peak input) ───────────────────────────────────

async def _persist_equity_peak(day: str) -> None:
    await redis.r.set(_EQUITY_PEAK_KEY, str(_equity_peak), ex=172_800)
    await redis.r.set(_EQUITY_PEAK_DAY_KEY, day, ex=172_800)


async def _update_equity_peak(equity: float, day: str) -> None:
    """Track the equity high-water mark + dd_from_peak_pct on account-sync.

    Follows the _DAY_START_BALANCE pattern: re-baseline on a new day, raise the
    peak whenever equity makes a new high, persist peak + day for restarts.
    """
    global _equity_peak, _equity_peak_day
    if not math.isfinite(equity) or equity <= 0:
        return
    new_day = _equity_peak_day != day
    if new_day or _equity_peak <= 0:
        _equity_peak = equity
        _equity_peak_day = day
        try:
            await _persist_equity_peak(day)
        except Exception:
            log.debug("risk.equity_peak.persist_failed", exc_info=True)
        log.info("risk.equity_peak.baselined", equity_peak=equity, day=day)
    elif equity > _equity_peak:
        _equity_peak = equity
        _equity_peak_day = day
        try:
            await _persist_equity_peak(day)
        except Exception:
            log.debug("risk.equity_peak.persist_failed", exc_info=True)
        log.info("risk.equity_peak.raised", equity_peak=equity, day=day)
    _current_state["equity_peak"] = _equity_peak
    _current_state["equity_peak_day"] = _equity_peak_day
    _current_state["dd_from_peak_pct"] = (
        round(max(0.0, (_equity_peak - equity) / _equity_peak * 100), 4)
        if _equity_peak > 0 else 0.0
    )


async def _restore_equity_peak() -> None:
    """Restore the equity peak from Redis on startup (restart survival gate)."""
    global _equity_peak, _equity_peak_day
    try:
        raw = await redis.r.get(_EQUITY_PEAK_KEY)
        if raw is None:
            return
        peak = float(raw)
        if not math.isfinite(peak) or peak <= 0:
            return
        day_raw = await redis.r.get(_EQUITY_PEAK_DAY_KEY)
        _equity_peak = peak
        _equity_peak_day = str(day_raw) if day_raw else ""
        _current_state["equity_peak"] = peak
        _current_state["equity_peak_day"] = _equity_peak_day
        log.info("risk.equity_peak.restored", equity_peak=peak, day=_equity_peak_day)
    except Exception:
        log.debug("risk.equity_peak.restore_failed", exc_info=True)


# ── 7-day equity series (real weekly drawdown) ───────────────────────────────

def _parse_equity_series(raw: list[Any] | None) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in raw or []:
        try:
            entry = json.loads(item)
        except (TypeError, ValueError):
            continue
        if not isinstance(entry, dict):
            continue
        try:
            equity_val = float(entry.get("equity", 0) or 0)
        except (TypeError, ValueError):
            continue
        if entry.get("day") and math.isfinite(equity_val) and equity_val > 0:
            entries.append({"day": str(entry["day"]), "equity": equity_val})
    return entries


async def _record_equity_series(equity: float, day: str) -> list[dict[str, Any]] | None:
    """Keep the newest 7 (day, equity) entries; today's entry is refreshed.

    Returns None when the series could not be read (caller keeps the previous
    weekly_dd_pct — the documented fallback = old behavior).
    """
    try:
        raw = await redis.r.lrange(_EQUITY_SERIES_KEY, 0, -1)
    except Exception:
        log.debug("risk.equity_series.read_failed", exc_info=True)
        return None
    entries = [e for e in _parse_equity_series(raw) if e["day"] != day]
    entries.insert(0, {"day": day, "equity": float(equity)})
    entries = entries[:_EQUITY_SERIES_MAX_DAYS]
    try:
        await redis.r.delete(_EQUITY_SERIES_KEY)
        await redis.r.rpush(
            _EQUITY_SERIES_KEY,
            *[json.dumps(e, separators=(",", ":")) for e in entries],
        )
        await redis.r.expire(_EQUITY_SERIES_KEY, _EQUITY_SERIES_TTL_SEC)
    except Exception:
        log.debug("risk.equity_series.write_failed", exc_info=True)
    return entries


def _weekly_dd_from_series(entries: list[dict[str, Any]]) -> float | None:
    """(7-day high − current)/high × 100; None = no usable series (fallback)."""
    values = [e["equity"] for e in entries if e.get("equity") and math.isfinite(e["equity"])]
    if not values:
        return None
    high = max(values)
    current = entries[0]["equity"] if entries else 0.0  # newest entry = today
    if high <= 0 or not math.isfinite(current):
        return None
    return round(max(0.0, (high - current) / high * 100), 4)


async def _update_weekly_dd(equity: float, day: str) -> None:
    entries = await _record_equity_series(equity, day)
    if entries is None:
        # Read failure: keep whatever weekly_dd_pct we had (old behavior when
        # there is no real series yet).
        return
    dd = _weekly_dd_from_series(entries)
    if dd is None:
        _current_state["weekly_dd_source"] = "fallback"
        return
    _current_state["weekly_dd_pct"] = dd
    _current_state["weekly_dd_source"] = "equity_series"


async def _restore_weekly_dd() -> None:
    """Recompute weekly_dd from the persisted series on startup."""
    try:
        raw = await redis.r.lrange(_EQUITY_SERIES_KEY, 0, -1)
        entries = _parse_equity_series(raw)
        dd = _weekly_dd_from_series(entries)
        if dd is not None:
            _current_state["weekly_dd_pct"] = dd
            _current_state["weekly_dd_source"] = "equity_series"
            log.info("risk.weekly_dd.restored", weekly_dd_pct=dd, days=len(entries))
    except Exception:
        log.debug("risk.weekly_dd.restore_failed", exc_info=True)


# ── Open-risk budget + gross leverage ────────────────────────────────────────

def _position_open_risk_usd(pos: dict[str, Any]) -> float | None:
    """USD risk at the stop for one open position; None = not computable."""
    try:
        symbol = str(pos.get("symbol", "") or "").strip()
        size = float(pos.get("size", pos.get("lots", 0)) or 0)
        entry = float(pos.get("entry_price", pos.get("entry", 0)) or 0)
        sl = float(pos.get("sl", 0) or 0)
        if not symbol or size <= 0 or entry <= 0 or sl <= 0 or entry == sl:
            return None  # missing/absurd stop ⇒ risk unbounded/unknown
        from shared.asset_specs import get_pip_size, get_pip_value_per_lot

        pip_size = get_pip_size(symbol)
        pip_value = get_pip_value_per_lot(symbol)
        if pip_size <= 0 or pip_value <= 0:
            return None
        risk_usd = size * (abs(entry - sl) / pip_size) * pip_value
        return risk_usd if math.isfinite(risk_usd) else None
    except Exception:
        return None


def _position_notional_usd(pos: dict[str, Any]) -> float | None:
    """Approximate USD notional for gross leverage; None = not convertible."""
    try:
        symbol = str(pos.get("symbol", "") or "").strip().upper().replace("/", "")
        size = float(pos.get("size", pos.get("lots", 0)) or 0)
        price = float(pos.get("current_price", 0) or 0) or float(
            pos.get("entry_price", 0) or 0
        )
        if not symbol or size <= 0 or price <= 0:
            return None
        from shared.asset_specs import get_contract_size

        contract = get_contract_size(symbol)
        if contract <= 0:
            return None
        if symbol.endswith("USD") and not symbol.startswith("USD"):
            notional = contract * price * size   # quote USD (EURUSD, XAUUSD, BTCUSD)
        elif symbol.startswith("USD"):
            notional = contract * size           # base USD (USDJPY, USDCAD, …)
        else:
            return None  # non-USD quote we cannot convert without another rate
        return notional if math.isfinite(notional) else None
    except Exception:
        return None


async def _update_open_risk(equity: float, nexus_positions: list[dict[str, Any]]) -> None:
    """Σ(open lots × risk per lot) snapshot + optional Redis record."""
    total = 0.0
    uncounted = 0
    per_position: list[dict[str, Any]] = []
    for pos in nexus_positions:
        risk_usd = _position_open_risk_usd(pos)
        if risk_usd is None:
            uncounted += 1
            continue
        total += risk_usd
        per_position.append({
            "symbol": str(pos.get("symbol", "")),
            "risk_usd": round(risk_usd, 2),
        })
    complete = uncounted == 0
    _current_state["open_risk_usd"] = round(total, 2) if complete else None
    # Engine-facing alias: rules_engine.check_all_rules reads open_risk_amount
    # (None is tolerated there — the fail-closed unknown check lives in
    # _run_portfolio_gates).
    _current_state["open_risk_amount"] = _current_state["open_risk_usd"]
    _current_state["open_risk_pct"] = (
        round(total / equity * 100, 4) if complete and equity > 0 else None
    )
    _current_state["open_risk_positions_uncounted"] = uncounted
    try:
        max_pct = _portfolio_cfg_value("max_portfolio_open_risk_pct")
        snapshot = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "equity": equity,
            "open_risk_usd": round(total, 2) if complete else None,
            "open_risk_pct": _current_state["open_risk_pct"],
            "budget_usd": round(equity * float(max_pct) / 100.0, 2)
            if max_pct is not None else None,
            "positions": per_position,
            "uncounted_positions": uncounted,
        }
        await redis.r.set(
            _OPEN_RISK_SNAPSHOT_KEY, json.dumps(snapshot, default=str), ex=172_800,
        )
    except Exception:
        log.debug("risk.open_risk.snapshot_failed", exc_info=True)


async def _update_gross_leverage(equity: float, nexus_positions: list[dict[str, Any]]) -> None:
    if equity <= 0 or not math.isfinite(equity):
        _current_state["gross_leverage"] = None
        return
    if not nexus_positions:
        _current_state["gross_leverage"] = 0.0
        return
    total = 0.0
    for pos in nexus_positions:
        notional = _position_notional_usd(pos)
        if notional is None:
            _current_state["gross_leverage"] = None  # cannot verify → unknown
            return
        total += notional
    _current_state["gross_leverage"] = round(total / equity, 4)


# ── Real correlation (behind correlation_threshold cfg) ──────────────────────

_CORR_MIN_CLOSES = 11  # ≥10 return observations, mirroring CorrelationChecker
_CORR_DEFAULT_LOOKBACK = 100


def set_correlation_bars_provider(provider: Callable[[list[str], int], Any] | None) -> None:
    """Inject the bars provider (tests / alternate data sources)."""
    global _correlation_bars_provider
    _correlation_bars_provider = provider


async def _default_correlation_bars_provider(
    symbols: list[str], lookback: int,
) -> dict[str, list[float]]:
    """Real closes from the Redis OHLCV cache nexus-data publishes."""
    out: dict[str, list[float]] = {}
    for sym in symbols:
        closes: list[float] = []
        tfs = []
        for tf in (_CORRELATION_TF, "M15", "M5", "H1"):
            if tf not in tfs:
                tfs.append(tf)
        for tf in tfs:
            try:
                raw = await redis.r.get(f"nexus:ohlcv:{sym.upper()}:{tf}")
            except Exception:
                raw = None
            if not raw:
                continue
            try:
                bars = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if isinstance(bars, list) and bars:
                try:
                    closes = [
                        float(b["close"]) for b in bars
                        if isinstance(b, dict) and b.get("close") is not None
                    ]
                except (TypeError, ValueError, KeyError):
                    closes = []
                if closes:
                    break
        if closes:
            out[sym.upper()] = closes
    return out


async def _fetch_correlation_bars(
    symbols: list[str], lookback: int,
) -> dict[str, list[float]] | None:
    """Fetch aligned close series; None = cannot verify (fail-closed input)."""
    provider = _correlation_bars_provider or _default_correlation_bars_provider
    try:
        result = provider(symbols, lookback)
        if hasattr(result, "__await__"):
            result = await result
    except Exception:
        log.debug("risk.correlation.bars_unavailable", exc_info=True)
        return None
    if not isinstance(result, dict):
        return None
    out: dict[str, list[float]] = {}
    for sym, series in result.items():
        try:
            values = [float(x) for x in series][-lookback:]
        except (TypeError, ValueError):
            continue
        if len(values) >= 2 and all(math.isfinite(v) for v in values):
            out[str(sym).upper()] = values
    return out or None


def _returns_corr(closes_a: list[float], closes_b: list[float]) -> float | None:
    """Pearson correlation of simple returns over the aligned window."""
    n = min(len(closes_a), len(closes_b))
    if n < _CORR_MIN_CLOSES:
        return None
    a, b = closes_a[-n:], closes_b[-n:]
    xs: list[float] = []
    ys: list[float] = []
    for i in range(1, n):
        if a[i - 1] == 0 or b[i - 1] == 0:
            continue
        xs.append(a[i] / a[i - 1] - 1.0)
        ys.append(b[i] / b[i - 1] - 1.0)
    if len(xs) < _CORR_MIN_CLOSES - 1:
        return None
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    cov = sx = sy = 0.0
    for x, y in zip(xs, ys):
        dx, dy = x - mx, y - my
        cov += dx * dy
        sx += dx * dx
        sy += dy * dy
    if sx <= 0 or sy <= 0:
        return None
    corr = cov / math.sqrt(sx * sy)
    return corr if math.isfinite(corr) else None


def _build_correlation_snapshot(
    symbols: list[str], bars: dict[str, list[float]] | None,
) -> dict[str, Any] | None:
    """Pairs snapshot for rules_engine.check_portfolio_correlation.

    All-or-nothing: returns None when any symbol lacks a verifiable window
    (the caller then leaves the engine gate input empty and the configured
    threshold fails closed via _run_portfolio_gates).
    """
    if not bars:
        return None
    ordered: list[str] = []
    for raw in symbols:
        sym = str(raw or "").strip().upper()
        if sym and sym not in ordered:
            ordered.append(sym)
    if len(ordered) < 2:
        return None
    for sym in ordered:
        series = bars.get(sym)
        if not series or len(series) < _CORR_MIN_CLOSES:
            return None
    pairs: dict[str, float] = {}
    min_len = min(len(bars[sym]) for sym in ordered)
    for i in range(len(ordered)):
        for j in range(i + 1, len(ordered)):
            corr = _returns_corr(bars[ordered[i]], bars[ordered[j]])
            if corr is None:
                return None
            pairs[f"{ordered[i]}:{ordered[j]}"] = round(corr, 4)
    return {
        "symbols": ordered,
        "pairs": pairs,
        "matrix": None,
        "lookback_bars": int(min_len),
    }


async def _update_correlation_exposure(nexus_positions: list[dict[str, Any]]) -> None:
    """Real pairwise correlation_exposure — computed only behind cfg."""
    threshold = _portfolio_cfg_value("correlation_threshold")
    if threshold is None:
        _current_state["correlation_data_status"] = "disabled"
        return
    symbols: list[str] = []
    for pos in nexus_positions:
        sym = str(pos.get("symbol", "") or "").strip().upper()
        if sym and sym not in symbols:
            symbols.append(sym)
    if len(symbols) < 2:
        _current_state["correlation_exposure"] = 0.0
        _current_state["correlation_data_status"] = "ok"
        return
    lookback = int(_portfolio_cfg_value("correlation_lookback_bars") or _CORR_DEFAULT_LOOKBACK)
    bars = await _fetch_correlation_bars(symbols, lookback)
    if bars is None or any(sym not in bars for sym in symbols):
        _current_state["correlation_data_status"] = "unavailable"
        log.info("risk.correlation_exposure.unavailable", symbols=symbols)
        return
    exposure = 0.0
    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            corr = _returns_corr(bars[symbols[i]], bars[symbols[j]])
            if corr is None:
                _current_state["correlation_data_status"] = "unavailable"
                return
            exposure = max(exposure, abs(corr))
    _current_state["correlation_exposure"] = round(exposure, 4)
    _current_state["correlation_data_status"] = "ok"


async def _update_portfolio_snapshots(equity: float, nexus_positions: list[dict[str, Any]]) -> None:
    """Every successful sync: peak, weekly series, open risk, gross, correlation.

    Additive and fail-soft: each step logs and continues so a problem in this
    new logic can never block a (stale-free) account sync.
    """
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        await _update_equity_peak(equity, day)
    except Exception:
        log.debug("risk.portfolio_snapshots.peak_failed", exc_info=True)
    try:
        await _update_weekly_dd(equity, day)
    except Exception:
        log.debug("risk.portfolio_snapshots.weekly_failed", exc_info=True)
    try:
        await _update_open_risk(equity, nexus_positions)
    except Exception:
        log.debug("risk.portfolio_snapshots.open_risk_failed", exc_info=True)
    try:
        await _update_gross_leverage(equity, nexus_positions)
    except Exception:
        log.debug("risk.portfolio_snapshots.gross_failed", exc_info=True)
    try:
        await _update_correlation_exposure(nexus_positions)
    except Exception:
        log.debug("risk.portfolio_snapshots.correlation_failed", exc_info=True)
    try:
        _current_state["current_session"] = detect_session_now().value
        _current_state["daily_trade_count"] = _daily_trade_count
        _current_state["max_daily_trades"] = _daily_trades_limit_observed
    except Exception:
        log.debug("risk.portfolio_snapshots.reporting_failed", exc_info=True)


# ── Background account-state sync ───────────────────────────────────────────

async def _sync_account_state() -> None:
    """Periodically fetch real account balance from the executor service."""
    global _day_start_balance, _last_sync_day

    log.info(
        "risk.account_sync.started",
        executor_url=EXECUTOR_URL,
        interval=ACCOUNT_SYNC_INTERVAL,
    )

    async with new_client(timeout=10.0) as client:
        while True:
            # A snapshot is live only after the current sync succeeds; retaining
            # the last values is useful for risk logic, but must not masquerade
            # as a fresh observation in dashboard/API responses.
            _current_state["available"] = False
            try:
                internal_secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
                resp = await client.get(
                    f"{EXECUTOR_URL}/api/executor/positions",
                    headers={"X-Nexus-Internal-Secret": internal_secret},
                )
                resp.raise_for_status()
                data = resp.json()

                if not isinstance(data, dict) or "account" not in data or "positions" not in data:
                    raise ValueError("executor positions response is malformed")
                account = data.get("account", {})
                if not isinstance(account, dict):
                    raise ValueError("executor account snapshot is malformed")
                balance = float(account["balance"])
                equity = float(account["equity"])
                positions = data.get("positions", [])
                if not isinstance(positions, list):
                    raise ValueError("executor positions response is malformed")
                if not all(isinstance(position, dict) for position in positions):
                    raise ValueError("executor position entry is malformed")
                if not math.isfinite(balance) or not math.isfinite(equity):
                    raise ValueError("executor account snapshot contains non-finite values")
                nexus_pos, external_pos = partition_positions(positions)

                if balance > 0:
                    _current_state["balance"] = balance
                    _current_state["equity"] = equity
                    _current_state["total_positions_count"] = len(positions)
                    _current_state["external_positions_count"] = len(external_pos)
                    _current_state["open_positions_count"] = len(nexus_pos)
                    _current_state["open_positions"] = nexus_pos

                    # Track daily drawdown
                    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    if _last_sync_day != today:
                        global _daily_trade_count
                        _day_start_balance = balance
                        _last_sync_day = today
                        _daily_trade_count = 0
                        # Persist so restarts don't lose the true day-start balance
                        try:
                            await redis.r.set(_DAY_START_BALANCE_KEY, str(balance), ex=172_800)
                            await redis.r.set(_DAY_START_DAY_KEY, today, ex=172_800)
                        except Exception:
                            pass
                        log.info(
                            "risk.account_sync.new_day",
                            day_start_balance=balance,
                        )
                    elif _day_start_balance == 0.0 and balance > 0:
                        # Day count was restored from Redis (so _last_sync_day==today)
                        # but day_start_balance wasn't (first start of the day).
                        # Capture it without resetting the trade count.
                        _day_start_balance = balance
                        try:
                            await redis.r.set(_DAY_START_BALANCE_KEY, str(balance), ex=172_800)
                            await redis.r.set(_DAY_START_DAY_KEY, today, ex=172_800)
                        except Exception:
                            pass
                        log.info(
                            "risk.account_sync.day_start_capture",
                            day_start_balance=balance,
                        )

                    _current_state["day_start_balance"] = _day_start_balance
                    if not math.isfinite(_day_start_balance) or _day_start_balance <= 0:
                        raise ValueError("invalid day-start balance for account snapshot")
                    if _day_start_balance > 0:
                        # Daily loss = Nexus-placed trades ONLY (closed today +
                        # floating on open Nexus positions). Account-wide equity
                        # is NOT used: external/manual trades on the shared MT5
                        # account must not trip Nexus's own breaker.
                        closed_nexus_pnl = await _get_nexus_daily_pnl()
                        floating_nexus_pnl = sum(
                            float(p.get("pnl_usd", p.get("pnl", 0)) or 0)
                            for p in nexus_pos
                        )
                        nexus_day_pnl = closed_nexus_pnl + floating_nexus_pnl
                        if not all(math.isfinite(value) for value in (
                            closed_nexus_pnl, floating_nexus_pnl, nexus_day_pnl,
                        )):
                            raise ValueError("account snapshot contains non-finite PnL")
                        daily_loss = max(0.0, -nexus_day_pnl) / _day_start_balance * 100
                        if not math.isfinite(daily_loss):
                            raise ValueError("account snapshot contains non-finite daily loss")
                        _current_state["daily_loss_pct"] = daily_loss
                        _current_state["nexus_daily_pnl"] = round(nexus_day_pnl, 2)

                    # Publish availability only after all risk calculations succeed.
                    _current_state["available"] = True
                    _current_state["last_sync_ok_ts"] = _time_mod.time()
                    # Phase 3 portfolio snapshots (peak / weekly series / open risk /
                    # gross leverage / correlation exposure) — fail-soft: a failure
                    # here logs and continues, never blocking the account sync.
                    await _update_portfolio_snapshots(equity, nexus_pos)
                    log.debug(
                        "risk.account_sync.ok",
                        balance=balance,
                        equity=equity,
                        positions=len(positions),
                        nexus_positions=len(nexus_pos),
                        external_positions=len(external_pos),
                        daily_loss_pct=_current_state["daily_loss_pct"],
                    )
                else:
                    log.warning("risk.account_sync.zero_balance")

            except httpx.ConnectError:
                log.warning("risk.account_sync.executor_unreachable")
            except Exception:
                log.exception("risk.account_sync.error")

            # Refresh the cached risk:state on EVERY sync so the dashboard (which
            # reads the gateway's Redis cache, not this service directly) always
            # sees fresh balance / positions / breakers instead of a stale value
            # that expires after its TTL and renders as all-zeros.
            try:
                await _cache_risk_state()
            except Exception:
                log.debug("risk.account_sync.cache_refresh_failed", exc_info=True)

            await asyncio.sleep(ACCOUNT_SYNC_INTERVAL)


# ── Request / Response Models ─────────────────────────────────────────────────

class EvaluateRequest(BaseModel):
    proposal: TradeProposal
    state: dict[str, Any] = Field(default_factory=dict)
    size_multiplier: float = Field(default=1.0, gt=0.0, le=1.0)
    order_type: Literal["MARKET", "LIMIT", "STOP"] = "MARKET"
    order_price: float = Field(default=0.0, ge=0.0)
    slippage: int = Field(default=10, ge=0, le=1000)


class EvaluateResponse(BaseModel):
    decision: str
    approved_size: float = 0.0
    violations: list[dict[str, Any]] = Field(default_factory=list)
    sizing: dict[str, Any] = Field(default_factory=dict)
    tilt: dict[str, Any] = Field(default_factory=dict)
    proposal_id: str = ""
    approval_expires_at: int = 0
    approval_signature: str = ""
    approval_payload: dict[str, Any] = Field(default_factory=dict)


class RiskStatusResponse(BaseModel):
    state: dict[str, Any]
    tilt: dict[str, Any]
    circuit_breakers: list[dict[str, Any]]


# ── Background Stream Consumer ────────────────────────────────────────────────

async def _risk_stream_consumer() -> None:
    """Consume trade proposals from the agent verdict stream and evaluate."""
    await redis.connect()
    log.info("risk.stream_consumer.started")
    async for delivery in redis.subscribe_deliveries(
        RedisStream.AGENT_VERDICT,
        CONSUMER_GROUP,
        CONSUMER_NAME,
    ):
        event = delivery.event
        try:
            # ── Kill switch check ─────────────────────────────────────
            kill_switch = await redis.cache_get("system:kill_switch")
            if kill_switch:
                log.warning(
                    "risk.kill_switch_active",
                    symbol=getattr(event, "symbol", ""),
                )
                reject_event = RiskDecisionEvent(
                    source=SERVICE_NAME,
                    correlation_id=event.correlation_id,
                    proposal_id="",
                    decision=RiskDecision.REJECT,
                    original_size=0,
                    approved_size=0,
                    reason="Kill switch is active",
                    data={},
                )
                await redis.publish_event(RedisStream.RISK_DECISION, reject_event)
                await delivery.ack()
                continue

            event_data = event.data if isinstance(event.data, dict) else {}
            proposal_data = {
                "symbol": str(getattr(event, "symbol", "") or "").strip().upper(),
                "direction": getattr(event, "verdict", "NO_TRADE"),
                "entry": float(event_data.get("entry", 0)) if event_data.get("entry") else 0,
                "sl": float(event_data.get("sl", 0)) if event_data.get("sl") else 0,
                "tp1": float(event_data.get("tp1", 0)) if event_data.get("tp1") else 0,
                "conviction": float(getattr(event, "conviction", 0)),
            }
            if proposal_data["entry"] == 0 or proposal_data["sl"] == 0:
                await delivery.ack()
                continue

            proposal = TradeProposal(**proposal_data)
            result = await _evaluate_proposal(proposal, _current_state)
            approval_expires_at = 0
            approval_sig = ""
            approval_payload: dict[str, Any] = {}
            if str(result.get("decision")) == str(RiskDecision.APPROVE):
                approval_expires_at = int(_time_mod.time()) + int(os.getenv("NEXUS_RISK_APPROVAL_TTL_SEC", "30"))
                signal_timestamp = _time_mod.time()
                approval_payload = {
                    "version": 1,
                    "proposal_id": proposal.id,
                    "expires_at": approval_expires_at,
                    "symbol": proposal.symbol,
                    "side": str(proposal.direction),
                    "order_type": "MARKET",
                    "entry": proposal.entry,
                    "price": proposal.entry,
                    "sl": proposal.sl,
                    "tp": proposal.tp1,
                    "size": float(result.get("approved_size", 0) or 0),
                    "signal_timestamp": signal_timestamp,
                    "slippage": 10,
                }
                approval_sig = approval_signature(approval_payload)
                if not approval_sig:
                    result["decision"] = RiskDecision.REJECT
                    result["approved_size"] = 0.0
                    result.setdefault("violations", []).append({
                        "rule": "approval_payload_invalid_or_secret_missing",
                        "message": "Risk approval could not be signed; verify the internal secret and approved terms",
                        "message_ar": "تعذر توقيع موافقة المخاطر؛ تحقق من السر الداخلي وتفاصيل الموافقة.",
                    })

            decision_event = RiskDecisionEvent(
                source=SERVICE_NAME,
                correlation_id=event.correlation_id,
                proposal_id=proposal.id,
                decision=result["decision"],
                original_size=proposal.conviction,
                approved_size=result.get("approved_size", 0),
                reason="; ".join(v.get("message", "") for v in result.get("violations", [])),
                data={
                    "symbol": proposal.symbol,
                    "timeframe": str(event_data.get("timeframe", "") or "").strip().upper(),
                    "side": proposal.direction,
                    "direction": proposal.direction,
                    "entry": proposal.entry,
                    "sl": proposal.sl,
                    "tp1": proposal.tp1,
                    "tp": proposal.tp1,
                    "size": float(result.get("approved_size", 0) or 0),
                    "comment": str(event_data.get("comment", "")),
                    "strategy": str(event_data.get("strategy", "genai")),
                    "proposal_id": proposal.id,
                    "risk_approval_expires_at": approval_expires_at,
                    "risk_approval_signature": approval_sig,
                    "risk_approval_payload": approval_payload,
                    "signal_timestamp": approval_payload.get("signal_timestamp", 0),
                    "order_type": "MARKET",
                    "price": proposal.entry,
                    "slippage": 10,
                },
            )
            await redis.publish_event(RedisStream.RISK_DECISION, decision_event)
            # Idempotency: mark the delivery only after the decision is
            # published so a redelivery after an evaluation/publish failure
            # can still retry, while a redelivery of an already-published
            # decision never re-increments daily counts or mints a second
            # approval. A failed mark is tolerated: the ack below still
            # commits the delivery and the executor deduplicates downstream.
            _message_id = str(getattr(delivery, "message_id", "") or "")
            if _message_id:
                try:
                    await redis.mark_processed(
                        RedisStream.AGENT_VERDICT, CONSUMER_GROUP, _message_id,
                    )
                except Exception:
                    log.warning(
                        "risk.stream_consumer.idem_mark_failed",
                        message_id=_message_id,
                        exc_info=True,
                    )
            await delivery.ack()

        except Exception:
            log.exception("risk.stream_consumer.error")


# ── Trade-close stream consumer — feeds anti-tilt + circuit-breaker ─────────

_TRADE_CLOSE_CG = "nexus-risk-tradeclose-cg"
_TRADE_CLOSE_CN = "nexus-risk-tradeclose-1"

# ── Per-direction loss streak (anti-revenge) ─────────────────────────────────
# June 9-11 the system kept re-selling GOLD into a rally — 16 consecutive
# losses, most in the same symbol+direction. After N straight losses on one
# direction, block re-entry on THAT direction for a cooldown window while the
# opposite direction (and other symbols) stay tradeable.

_DIR_LOSS_LIMIT = int(os.getenv("NEXUS_DIR_LOSS_LIMIT", "2"))
_DIR_BLOCK_MINUTES = int(os.getenv("NEXUS_DIR_BLOCK_MINUTES", "60"))
_DIR_LOSS_PREFIX = "nexus:risk:dir_losses:"
_DIR_BLOCK_PREFIX = "nexus:risk:dir_block:"


async def _update_direction_streak(symbol: str, side: str, pnl_usd: float) -> None:
    """Track consecutive losses per symbol+direction; arm the block at the limit."""
    if not symbol or not side:
        return
    dir_key = f"{symbol.upper()}:{side.upper()}"
    if pnl_usd >= 0:
        await redis.r.delete(_DIR_LOSS_PREFIX + dir_key)
        return
    losses = int(await redis.r.incr(_DIR_LOSS_PREFIX + dir_key))
    await redis.r.expire(_DIR_LOSS_PREFIX + dir_key, 86400)
    if losses >= _DIR_LOSS_LIMIT:
        await redis.r.set(
            _DIR_BLOCK_PREFIX + dir_key,
            str(losses),
            ex=_DIR_BLOCK_MINUTES * 60,
        )
        log.warning(
            "risk.direction_blocked",
            symbol=symbol,
            side=side,
            consecutive_losses=losses,
            block_minutes=_DIR_BLOCK_MINUTES,
        )


async def _direction_block_remaining(symbol: str, side: str) -> float:
    """Seconds left in the same-direction re-entry block (0 = not blocked)."""
    try:
        ttl = await redis.r.ttl(f"{_DIR_BLOCK_PREFIX}{symbol.upper()}:{side.upper()}")
        return float(ttl) if ttl and ttl > 0 else 0.0
    except Exception:
        return 0.0


# ── Per-effect idempotency for trade-close side effects ──────────────────────
# Each Redis-backed effect (daily PnL accumulator, anti-tilt update, recent
# results, per-direction loss streak) is claimed by stream message id AFTER it
# succeeds. A redelivery after a mid-batch failure therefore only re-applies
# the effects that never completed — risk effects are never double-applied —
# while a Redis write failure still prevents the ack (ACR-49 contract).

def _trade_close_effect_key(message_id: str, effect: str) -> str:
    return (
        f"{RedisClient.idempotency_key(RedisStream.TRADE_CLOSE, _TRADE_CLOSE_CG, message_id)}"
        f":{effect}"
    )


async def _trade_close_effect_needed(message_id: str, effect: str) -> bool:
    """True when this side effect has not been recorded for this delivery."""
    if not message_id:
        return True
    try:
        return not bool(await redis.r.exists(_trade_close_effect_key(message_id, effect)))
    except Exception:
        log.debug(
            "risk.trade_close.idem_check_failed",
            effect=effect,
            message_id=message_id,
            exc_info=True,
        )
        return True


async def _trade_close_mark_effect(message_id: str, effect: str) -> None:
    """Record that this effect completed for this delivery (dedup on redelivery)."""
    if not message_id:
        return
    await redis.r.set(
        _trade_close_effect_key(message_id, effect),
        "1",
        ex=TRADE_CLOSE_EFFECT_IDEM_TTL_SEC,
    )


async def _trade_close_consumer() -> None:
    """Listen for closed trades and feed results to anti-tilt & circuit-breaker.

    Previously anti_tilt.update() was NEVER called, so the system ignored 17
    consecutive losses without pausing. This consumer fixes that.
    """
    await redis.connect()
    log.info("risk.trade_close_consumer.started")
    async for delivery in redis.subscribe_deliveries(
        RedisStream.TRADE_CLOSE,
        _TRADE_CLOSE_CG,
        _TRADE_CLOSE_CN,
    ):
        event = delivery.event
        message_id = str(getattr(delivery, "message_id", "") or "")
        try:
            data = event.data if isinstance(event.data, dict) else {}
            pnl_usd = float(getattr(event, "pnl_usd", 0) or data.get("pnl_usd", 0) or 0)
            size = float(getattr(event, "size", 0) or data.get("size", 0.01) or 0.01)
            side = str(getattr(event, "side", "") or data.get("side", ""))
            symbol = getattr(event, "symbol", "") or data.get("symbol", "")

            # 0. Nexus-only gate: the position monitor publishes closes for
            # EVERY position on the account, including manual/other-EA trades
            # (empty or foreign comment). Those must not feed anti-tilt,
            # loss streaks, recent-results or the daily-loss accumulator —
            # this system's limits apply to this system's trades only.
            comment = str(data.get("source", "") or "")
            if not is_nexus_comment(comment):
                log.info(
                    "risk.trade_close.external_ignored",
                    symbol=symbol,
                    side=side,
                    pnl_usd=pnl_usd,
                )
                await delivery.ack()
                continue

            # 0b. Accumulate today's Nexus closed PnL (drives daily_loss_pct)
            if await _trade_close_effect_needed(message_id, "daily_pnl"):
                await _add_nexus_daily_pnl(pnl_usd)
                await _trade_close_mark_effect(message_id, "daily_pnl")

            # 1. Feed the anti-tilt detector (at most once per stream message)
            if await _trade_close_effect_needed(message_id, "anti_tilt"):
                status = anti_tilt.update({"pnl_usd": pnl_usd, "size": size})
                await _trade_close_mark_effect(message_id, "anti_tilt")
            else:
                status = anti_tilt.get_tilt_status()
            log.info(
                "risk.trade_close.anti_tilt_updated",
                pnl_usd=pnl_usd,
                tilt_status=status.value,
                consecutive_losses=anti_tilt.get_state_dict().get("consecutive_losses", 0),
            )
            # Absolute state snapshot — safe (idempotent) to rewrite every time.
            await anti_tilt.persist_to_redis(redis.r)

            # 2. Persist recent results for circuit-breaker (last 20 trades)
            if await _trade_close_effect_needed(message_id, "recent_results"):
                result_entry = f"{pnl_usd:.2f}"
                await redis.r.lpush(_RECENT_RESULTS_KEY, result_entry)
                await redis.r.ltrim(_RECENT_RESULTS_KEY, 0, 19)  # keep last 20
                await _trade_close_mark_effect(message_id, "recent_results")

            # 2b. Per-direction loss streak → re-entry block (anti-revenge)
            if await _trade_close_effect_needed(message_id, "dir_streak"):
                await _update_direction_streak(symbol, side, pnl_usd)
                await _trade_close_mark_effect(message_id, "dir_streak")

            # 3. Activate kill switch if tilt detected
            if status == TiltStatus.TILT:
                log.warning(
                    "risk.trade_close.kill_switch_activated",
                    consecutive_losses=anti_tilt.get_state_dict().get("consecutive_losses", 0),
                )
                await redis.cache_set("system:kill_switch", {"reason": "anti_tilt"}, ttl_sec=1800)

            await _cache_risk_state()
            await delivery.ack()

        except Exception:
            log.exception(
                "risk.trade_close_consumer.error",
                message_id=delivery.message_id,
            )


async def _restore_daily_count() -> None:
    """Restore the daily trade count from Redis on service startup.

    This prevents the count from resetting to 0 when run.py respawns the
    service, which previously allowed 16+ trades/day despite a 5/day cap.
    """
    global _daily_trade_count, _last_sync_day
    try:
        stored_day = await redis.r.get(_DAILY_COUNT_DAY_KEY)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if stored_day and stored_day == today:
            stored_count = await redis.r.get(_DAILY_COUNT_KEY)
            if stored_count is not None:
                _daily_trade_count = int(stored_count)
                _last_sync_day = today
                log.info(
                    "risk.daily_count.restored",
                    daily_trade_count=_daily_trade_count,
                    day=today,
                )
        else:
            log.info("risk.daily_count.new_day_or_missing", stored_day=stored_day, today=today)
    except Exception:
        log.debug("risk.daily_count.restore_failed", exc_info=True)


async def _persist_daily_count() -> None:
    """Write the current daily trade count to Redis so it survives restarts."""
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        await redis.r.set(_DAILY_COUNT_KEY, str(_daily_trade_count), ex=86400)
        await redis.r.set(_DAILY_COUNT_DAY_KEY, today, ex=86400)
    except Exception:
        pass


async def _restore_day_start_balance() -> None:
    """Restore day_start_balance from Redis so restarts don't break daily loss calc."""
    global _day_start_balance, _last_sync_day
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        stored_day = await redis.r.get(_DAY_START_DAY_KEY)
        if stored_day and stored_day == today:
            stored_val = await redis.r.get(_DAY_START_BALANCE_KEY)
            if stored_val:
                _day_start_balance = float(stored_val)
                if not _last_sync_day:
                    _last_sync_day = today
                log.info(
                    "risk.day_start_balance.restored",
                    day_start_balance=_day_start_balance,
                    day=today,
                )
    except Exception:
        log.debug("risk.day_start_balance.restore_failed", exc_info=True)


async def _check_circuit_breaker() -> dict | None:
    """Check recent-trade circuit breaker: if last 10 trades have <20% WR, pause.

    Returns a violation dict if triggered, None otherwise.
    """
    try:
        raw = await redis.r.lrange(_RECENT_RESULTS_KEY, 0, 9)
        if not raw or len(raw) < 5:
            return None  # not enough data

        results = [float(x) for x in raw]
        wins = sum(1 for r in results if r > 0)
        wr = wins / len(results)

        if wr < 0.20 and len(results) >= 8:
            log.warning(
                "risk.circuit_breaker.low_win_rate",
                win_rate=wr,
                last_n=len(results),
                results=results,
            )
            return {
                "rule": "circuit_breaker_win_rate",
                "message": (
                    f"Circuit breaker: win rate {wr:.0%} on last {len(results)} trades. "
                    f"System paused — needs manual reset-day."
                ),
                "current_value": wr,
                "limit_value": 0.20,
            }
    except Exception:
        log.debug("risk.circuit_breaker.check_failed", exc_info=True)
    return None


_ERGODIC_PAUSE_KEY = "nexus:risk:ergodic_pause_until"
_INST_KEY_TPL = "nexus:features:institutional:{symbol}"


async def _get_ergodic_lot_multiplier(symbol: str, base_lot: float) -> tuple[float, dict]:
    """
    Reads pre-computed institutional features and returns a (multiplier, info) tuple.
    multiplier = matrix_profile.position_size_mult × change_points.ensemble_weight
                 × (0.5 if temporal_growth says REDUCE_SIZE_50PCT)

    Falls back to 1.0 if institutional features not yet available — never blocks.
    """
    try:
        raw = await redis.r.get(_INST_KEY_TPL.format(symbol=symbol))
        if not raw:
            return 1.0, {"source": "no_institutional_data"}
        import json as _json
        inst = _json.loads(raw)
        mp_mult = float(inst.get("matrix_profile", {}).get("position_size_mult", 1.0))
        cp_mult = float(inst.get("change_points", {}).get("ensemble_weight", 1.0))
        tg_action = inst.get("temporal_growth", {}).get("action", "NORMAL")
        tg_mult = 0.5 if tg_action == "REDUCE_SIZE_50PCT" else 1.0
        combined = mp_mult * cp_mult * tg_mult
        ergodic_lot = inst.get("ergodic_kelly", {}).get("lot", base_lot)
        return combined, {
            "source": "ergodic",
            "mp_mult": mp_mult,
            "cp_mult": cp_mult,
            "tg_mult": tg_mult,
            "combined_mult": combined,
            "ergodic_lot_suggestion": ergodic_lot,
            "temporal_action": tg_action,
        }
    except Exception:
        return 1.0, {"source": "error_fallback"}


async def _check_ergodic_circuit_breaker(symbol: str = "XAUUSD") -> dict | None:
    """
    Circuit breaker basado en tasa de crecimiento temporal g (Peters 2019).
    Se dispara antes que el daily_loss_limit del 20% — detecta destrucción
    de capital estadística antes de que sea severa.

    PAUSE_SYSTEM   → g < -0.003 → pausar 30 minutos
    REDUCE_SIZE    → g < 0      → no bloquea, ajuste de tamaño (via _get_ergodic_lot_multiplier)
    """
    try:
        # Check active pause
        pause_raw = await redis.r.get(_ERGODIC_PAUSE_KEY)
        if pause_raw:
            remaining = float(pause_raw) - _time_mod.time()
            if remaining > 0:
                return {
                    "rule": "ergodic_temporal_growth",
                    "message": (
                        f"Ergodic circuit breaker active: g < -0.003. "
                        f"Resume in {remaining/60:.0f}min."
                    ),
                    "current_value": 0.0,
                    "limit_value": -0.003,
                }

        raw = await redis.r.get(_INST_KEY_TPL.format(symbol=symbol))
        if not raw:
            return None
        import json as _json
        inst = _json.loads(raw)
        tg = inst.get("temporal_growth", {})
        if tg.get("action") == "PAUSE_SYSTEM":
            pause_until = _time_mod.time() + 1800
            await redis.r.set(_ERGODIC_PAUSE_KEY, str(pause_until), ex=1800)
            g_val = tg.get("temporal_growth_g", 0.0)
            log.warning(
                "risk.ergodic_circuit_breaker.fired",
                g=g_val, symbol=symbol, duration_min=30,
            )
            return {
                "rule": "ergodic_temporal_growth",
                "message": (
                    f"Ergodic circuit breaker: temporal growth g={g_val:.4f} < -0.003. "
                    f"Capital destruction detected. Paused 30 minutes."
                ),
                "current_value": float(g_val),
                "limit_value": -0.003,
            }
    except Exception:
        log.debug("ergodic_circuit_breaker.check_failed", exc_info=True)
    return None


_last_trade_ts_by_dir: dict[str, float] = {}   # in-memory fallback when Redis is down
_STACK_COOLDOWN_SEC = int(os.getenv("NEXUS_STACK_COOLDOWN_SEC", "120"))
_STACK_KEY_PREFIX = "nexus:risk:last_trade:"


async def _stack_cooldown_remaining(dir_key: str) -> float:
    """Seconds left in the same-direction cooldown.

    Redis-backed so the cooldown survives service restarts (a respawn used to
    reset the in-memory dict and allow immediate same-direction stacking).
    """
    try:
        ttl = await redis.r.ttl(_STACK_KEY_PREFIX + dir_key)
        if ttl and ttl > 0:
            return float(ttl)
    except Exception:
        pass
    last = _last_trade_ts_by_dir.get(dir_key, 0.0)
    if not last:
        return 0.0
    elapsed = _time_mod.monotonic() - last
    return max(0.0, _STACK_COOLDOWN_SEC - elapsed)


async def _mark_stack_cooldown(dir_key: str) -> None:
    _last_trade_ts_by_dir[dir_key] = _time_mod.monotonic()
    try:
        await redis.r.set(_STACK_KEY_PREFIX + dir_key, "1", ex=_STACK_COOLDOWN_SEC)
    except Exception:
        log.debug("risk.stack_cooldown.persist_failed", exc_info=True)


# ── Portfolio gates (Phase 3) — gate wiring ──────────────────────────────────
# C1's rules_engine.check_all_rules already runs peak-DD → open-risk →
# gross-leverage → portfolio-correlation whenever the matching `capital:` cfg
# field is set AND the state input exists. The inputs main.py feeds are
# equity_peak / equity_peak_day, open_risk_amount, gross_leverage and the
# proposal-time correlation_snapshot (injected in _evaluate_proposal before
# check_all_rules). The engine skips silently on missing inputs; while a gate
# is configured, main.py treats unknown safety inputs as violations (the
# fail-closed convention of account_state_unavailable /
# fundamental_state_unavailable) so a broken data path can never silently
# disable a portfolio gate.


def _gate_violation(
    rule: str, message: str, current: Any, limit: Any, severity: str = "CRITICAL",
) -> dict[str, Any]:
    return {
        "rule": rule,
        "message": message,
        "severity": severity,
        "current_value": current,
        "limit_value": limit,
    }


def _remaining_open_risk_budget_usd(state: dict[str, Any]) -> float | None:
    """Risk budget still available for a NEW position, in USD.

    ``None`` = the portfolio open-risk gate is disabled (cfg
    ``max_portfolio_open_risk_pct`` is None) ⇒ no clamp. Prefers the engine's
    ``remaining_open_risk_budget`` helper (identical formula) and falls back to
    ``equity × max_pct/100 − open_risk``. Fail-closed while configured: a
    non-positive equity or an unknown open-risk snapshot yields ``0.0`` (no
    room for new risk) instead of silently granting the full budget.
    """
    cfg = getattr(rules_engine, "_cfg", None)
    max_pct = (
        getattr(cfg, "max_portfolio_open_risk_pct", None) if cfg is not None else None
    )
    if max_pct is None:
        return None
    try:
        max_pct = float(max_pct)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(max_pct) or max_pct <= 0:
        return None
    try:
        equity = float(state.get("equity", 0) or 0)
    except (TypeError, ValueError):
        equity = 0.0
    if not math.isfinite(equity) or equity <= 0:
        return 0.0
    try:
        raw = state.get("open_risk_usd")
        open_usd = float(raw) if raw is not None else None
    except (TypeError, ValueError):
        open_usd = None
    if open_usd is None or not math.isfinite(open_usd):
        return 0.0
    helper = getattr(rules_engine, "remaining_open_risk_budget", None)
    if callable(helper):
        try:
            result = float(helper(equity, open_usd))
            if math.isfinite(result):
                return max(0.0, result)
        except Exception:
            log.debug("risk.open_risk.helper_failed", exc_info=True)
    return max(0.0, equity * max_pct / 100.0 - max(open_usd, 0.0))


def _run_portfolio_gates(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Fail-closed inputs for the portfolio gates C1 runs in check_all_rules.

    Called from _evaluate_proposal right after check_all_rules; every check
    skips while its cfg field is None, so default config keeps golden
    decisions byte-exact.
    """
    out: list[dict[str, Any]] = []

    # 1) Drawdown from peak — the engine skips when peak/equity is unknown.
    max_peak_dd = _portfolio_cfg_value("max_drawdown_from_peak_pct")
    if max_peak_dd is not None:
        peak = state.get("equity_peak")
        equity = state.get("equity")
        valid = (
            isinstance(peak, (int, float))
            and math.isfinite(float(peak))
            and float(peak) > 0
            and isinstance(equity, (int, float))
            and math.isfinite(float(equity))
            and float(equity) > 0
        )
        if not valid:
            out.append(_gate_violation(
                "dd_from_peak_unavailable",
                "Equity peak / drawdown-from-peak input unavailable",
                "unknown", round(float(max_peak_dd), 2),
            ))

    # 2) Open-risk budget — the engine receives 0.0 for a missing snapshot, so
    #    an unknown value must be rejected here while the budget is configured.
    max_open = _portfolio_cfg_value("max_portfolio_open_risk_pct")
    if max_open is not None and state.get("open_risk_usd") is None:
        out.append(_gate_violation(
            "open_risk_unavailable",
            "Open-risk snapshot unavailable while portfolio budget is configured",
            "unknown", round(float(max_open), 2),
        ))

    # 3) Gross leverage — None means the open notionals are not verifiable
    #    (non-USD-convertible symbol) while a cap is configured.
    max_gross = _portfolio_cfg_value("max_gross_leverage")
    if max_gross is not None and state.get("gross_leverage") is None:
        out.append(_gate_violation(
            "gross_leverage_unavailable",
            "Gross leverage inputs unavailable while cap is configured",
            "unknown", round(float(max_gross), 2),
        ))

    # 4) Correlation — the engine skips when the snapshot is missing; with open
    #    positions and a configured threshold that gap must fail closed.
    corr_threshold = _portfolio_cfg_value("correlation_threshold")
    if corr_threshold is not None and not state.get("correlation_snapshot"):
        open_positions = state.get("open_positions") or []
        if isinstance(open_positions, list) and open_positions:
            out.append(_gate_violation(
                "correlation_data_unavailable",
                "Correlation inputs unavailable while correlation_threshold is configured",
                "unavailable", round(float(corr_threshold), 4),
            ))

    # 5) Net currency exposure — no feed exists in main.py yet; enabling the
    #    cap without one must fail closed instead of passing silently.
    max_net_exp = _portfolio_cfg_value("max_net_currency_exposure_pct")
    if max_net_exp is not None and state.get("net_currency_exposure_pct") is None:
        out.append(_gate_violation(
            "net_currency_exposure_unavailable",
            "Net currency exposure input unavailable while cap is configured",
            "unknown", round(float(max_net_exp), 2),
        ))

    return out

async def _evaluate_proposal(
    proposal: TradeProposal,
    _state: dict[str, Any],
) -> dict[str, Any]:
    global _daily_trade_count, _daily_trades_limit_observed
    # Safety state is sourced from the account-sync path only. Never allow a
    # request or event payload to relax limits or inflate sizing inputs.
    merged = dict(_current_state)

    # Retained balances must never authorize new exposure after a failed sync.
    try:
        account_valid = merged.get("available") is True and all(
            math.isfinite(float(merged[key]))
            for key in ("balance", "equity", "daily_loss_pct")
        ) and float(merged["balance"]) > 0
    except (KeyError, TypeError, ValueError, OverflowError):
        account_valid = False
    if not account_valid:
        return {
            "decision": RiskDecision.REJECT,
            "approved_size": 0.0,
            "violations": [{
                "rule": "account_state_unavailable",
                "message": "Authoritative account snapshot unavailable or invalid",
                "message_ar": "بيانات الحساب المعتمدة غير متاحة أو غير صالحة؛ تم منع الصفقة احترازيًا.",
            }],
            "sizing": {}, "tilt": anti_tilt.get_state_dict(),
        }

    # Staleness watchdog: a dead account-sync task leaves `available=True`
    # with frozen numbers. Enforced only when a real sync has stamped the
    # snapshot; synthetic states without the stamp keep the checks above.
    _synced_at = merged.get("last_sync_ok_ts")
    if isinstance(_synced_at, (int, float)):
        try:
            _synced_ok = math.isfinite(float(_synced_at)) and (
                _time_mod.time() - float(_synced_at)
            ) <= ACCOUNT_STATE_MAX_STALE_SEC
        except (TypeError, ValueError, OverflowError):
            _synced_ok = False
        if not _synced_ok:
            return {
                "decision": RiskDecision.REJECT,
                "approved_size": 0.0,
                "violations": [{
                    "rule": "account_state_stale",
                    "message": (
                        f"Authoritative account snapshot is older than "
                        f"{ACCOUNT_STATE_MAX_STALE_SEC:.0f}s"
                    ),
                    "message_ar": "بيانات الحساب المعتمدة قديمة؛ تم منع الصفقة احترازيًا.",
                }],
                "sizing": {}, "tilt": anti_tilt.get_state_dict(),
            }

    # ── Canonical execution state — fail closed for new exposure ────────
    try:
        auto_trade = await redis.cache_get("system:auto_trade")
        if auto_trade is not True:
            return {
                "decision": RiskDecision.REJECT,
                "approved_size": 0.0,
                "violations": [{
                    "rule": "auto_trade_off",
                    "message": "Auto-trade is not explicitly enabled",
                    "message_ar": "التداول الآلي غير مفعل بشكل صريح.",
                }],
                "sizing": {}, "tilt": anti_tilt.get_state_dict(),
            }
        blackout = await redis.cache_get("fundamental:blackout")
        if (
            not isinstance(blackout, dict)
            or not isinstance(blackout.get("state"), str)
            or not isinstance(blackout.get("active"), bool)
        ):
            return {
                "decision": RiskDecision.REJECT, "approved_size": 0.0,
                "violations": [{
                    "rule": "fundamental_state_unavailable",
                    "message": "Fundamental blackout state unavailable",
                    "message_ar": "حالة حظر الأخبار الأساسية غير متاحة؛ تم المنع احترازيًا.",
                }],
                "sizing": {}, "tilt": anti_tilt.get_state_dict(),
            }
        if isinstance(blackout, dict):
            b_state = str(blackout.get("state", "unknown")).lower()
            if blackout["active"] or b_state != "clear":
                return {
                    "decision": RiskDecision.REJECT, "approved_size": 0.0,
                    "violations": [{
                        "rule": "NEWS_BLACKOUT",
                        "message": str(blackout.get("reason", "Fundamental/news blackout active")),
                        "message_ar": str(blackout.get("reason_ar", "تم منع الصفقة بسبب نافذة خبر عالي التأثير.")),
                    }],
                    "sizing": {}, "tilt": anti_tilt.get_state_dict(),
                }
    except Exception as exc:
        return {
            "decision": RiskDecision.REJECT, "approved_size": 0.0,
            "violations": [{
                "rule": "safety_state_error",
                "message": f"Safety state unavailable: {exc}",
                "message_ar": "تعذر التحقق من حالة الأمان؛ تم المنع احترازيًا.",
            }],
            "sizing": {}, "tilt": anti_tilt.get_state_dict(),
        }

    # ── Tilt check — BLOCK if anti-tilt detected emotional trading ──────
    tilt_status = anti_tilt.get_tilt_status()
    if tilt_status == TiltStatus.TILT:
        return {
            "decision": RiskDecision.REJECT,
            "approved_size": 0.0,
            "violations": [{
                "rule": "anti_tilt",
                "message": (
                    f"Anti-tilt active: {anti_tilt.get_state_dict().get('consecutive_losses', 0)} "
                    f"consecutive losses. Cooldown {anti_tilt.get_cooldown_remaining():.0f}min remaining."
                ),
            }],
            "sizing": {},
            "tilt": anti_tilt.get_state_dict(),
        }

    # ── Hard session gate (server clock, not caller-supplied state) ─────
    # Policy comes from the runtime document so the Settings tab controls it;
    # the env constants below remain the default when nothing was saved.
    _off_hours_ok, _allowed_sessions = await _session_gate_policy()
    if not _off_hours_ok:
        _session_now = detect_session_now()
        if _session_now.value not in _allowed_sessions:
            return {
                "decision": RiskDecision.REJECT,
                "approved_size": 0.0,
                "violations": [{
                    "rule": "session_gate",
                    "message": (
                        f"Session {_session_now.value} not in allowed set "
                        f"{sorted(_allowed_sessions)} (change it in Settings → "
                        f"بوابة الجلسات, or NEXUS_ALLOWED_SESSIONS / "
                        f"NEXUS_ALLOW_OFF_HOURS)"
                    ),
                }],
                "sizing": {},
                "tilt": anti_tilt.get_state_dict(),
            }

    # ── Circuit-breaker: low win rate on last N trades → pause ──────────
    cb_violation = await _check_circuit_breaker()
    if cb_violation:
        return {
            "decision": RiskDecision.REJECT,
            "approved_size": 0.0,
            "violations": [cb_violation],
            "sizing": {},
            "tilt": anti_tilt.get_state_dict(),
        }

    # ── Ergodic circuit breaker: temporal growth g (Peters 2019) ────────
    ergodic_cb = await _check_ergodic_circuit_breaker(proposal.symbol)
    if ergodic_cb:
        return {
            "decision": RiskDecision.REJECT,
            "approved_size": 0.0,
            "violations": [ergodic_cb],
            "sizing": {},
            "tilt": anti_tilt.get_state_dict(),
        }

    # ── Anti-stacking guard ──────────────────────────────────────────────
    # The account-state sync runs every 30s, so back-to-back proposals can each
    # see "0 open positions" and stack 3 trades in the same direction before the
    # first one is reflected. Enforce a per-(symbol,direction) cooldown so we
    # never pile onto the same bet within the window.
    _dir_key = f"{proposal.symbol.upper()}:{str(proposal.direction).upper()}"
    _cooldown_left = await _stack_cooldown_remaining(_dir_key)
    if _cooldown_left > 0:
        return {
            "decision": RiskDecision.REJECT,
            "approved_size": 0.0,
            "violations": [{
                "rule": "anti_stacking",
                "message": (
                    f"Same-direction {proposal.direction} on {proposal.symbol} "
                    f"within cooldown ({_cooldown_left:.0f}s of "
                    f"{_STACK_COOLDOWN_SEC}s remaining)"
                ),
            }],
            "sizing": {},
            "tilt": anti_tilt.get_state_dict(),
        }

    # ── Anti-revenge: direction blocked after consecutive losses ────────
    _block_left = await _direction_block_remaining(proposal.symbol, str(proposal.direction))
    if _block_left > 0:
        return {
            "decision": RiskDecision.REJECT,
            "approved_size": 0.0,
            "violations": [{
                "rule": "direction_loss_block",
                "message": (
                    f"{proposal.direction} on {proposal.symbol} blocked after "
                    f"{_DIR_LOSS_LIMIT}+ consecutive losses "
                    f"({_block_left / 60:.0f}min remaining)"
                ),
            }],
            "sizing": {},
            "tilt": anti_tilt.get_state_dict(),
        }

    if merged.get("balance", 0) == 0:
        log.warning(
            "risk.evaluate.balance_not_synced",
            symbol=proposal.symbol,
            msg="Balance is 0 — account sync may not have completed yet",
        )

    # ── Apply front-configurable runtime settings (daily loss %, caps) ──
    settings = await runtime_settings.get_settings(redis)
    rules_engine.apply_runtime_overrides(settings)

    # Manual pause flag — when set, reject everything until reset-day.
    if _trades_paused:
        return {
            "decision": RiskDecision.REJECT,
            "approved_size": 0.0,
            "violations": [{"rule": "manual_pause", "message": "Trading manually paused"}],
            "sizing": {},
            "tilt": anti_tilt.get_state_dict(),
        }

    # Daily trade cap (front-configurable). 0/absent = unlimited.
    max_daily_trades = int(settings.get("max_daily_trades", 0) or 0)
    # Observe the live cap + count for get_active_circuit_breakers (G5):
    # the engine's daily_trade_limit row reads these state keys.
    _daily_trades_limit_observed = max_daily_trades
    _current_state["max_daily_trades"] = max_daily_trades
    _current_state["daily_trade_count"] = _daily_trade_count
    if max_daily_trades > 0 and _daily_trade_count >= max_daily_trades:
        return {
            "decision": RiskDecision.REJECT,
            "approved_size": 0.0,
            "violations": [{
                "rule": "daily_trade_limit",
                "message": f"Daily trade limit reached ({_daily_trade_count}/{max_daily_trades})",
                "current_value": _daily_trade_count,
                "limit_value": max_daily_trades,
            }],
            "sizing": {},
            "tilt": anti_tilt.get_state_dict(),
        }

    # ── Phase 3: proposal-time correlation snapshot (engine gate input) ──
    # Behind correlation_threshold only — default config never touches Redis
    # here, so golden decisions stay byte-exact. With open positions the pairs
    # include the proposal symbol; unverifiable bars leave the input None
    # (engine skips its gate, _run_portfolio_gates fails closed while set).
    if _portfolio_cfg_value("correlation_threshold") is not None:
        merged["correlation_snapshot"] = None
        _open_syms: list[str] = []
        for _pos in merged.get("open_positions") or []:
            if not isinstance(_pos, dict):
                continue
            _sym = str(_pos.get("symbol", "") or "").strip().upper()
            if _sym and _sym not in _open_syms:
                _open_syms.append(_sym)
        if _open_syms:
            try:
                _lookback = int(
                    _portfolio_cfg_value("correlation_lookback_bars")
                    or _CORR_DEFAULT_LOOKBACK
                )
                _syms = list(_open_syms)
                _base_sym = str(proposal.symbol or "").strip().upper()
                if _base_sym and _base_sym not in _syms:
                    _syms.append(_base_sym)
                _bars = await _fetch_correlation_bars(_syms, _lookback)
                merged["correlation_snapshot"] = _build_correlation_snapshot(
                    _syms, _bars,
                )
            except Exception:
                log.debug("risk.correlation.snapshot_failed", exc_info=True)
                merged["correlation_snapshot"] = None

    passed, violations = rules_engine.check_all_rules(proposal, merged)
    violation_dicts = [
        {
            "rule": v.rule,
            "message": v.message,
            "severity": v.severity,
            "current_value": v.current_value,
            "limit_value": v.limit_value,
        }
        for v in violations
    ]
    # ── Phase 3: fail-closed portfolio-gate inputs (after engine gates) ──
    violation_dicts.extend(_run_portfolio_gates(merged))
    passed = not violation_dicts

    if not passed:
        return {
            "decision": RiskDecision.REJECT,
            "approved_size": 0.0,
            "violations": violation_dicts,
            "sizing": {},
            "tilt": anti_tilt.get_state_dict(),
        }

    # Front-configurable risk-per-trade (% of equity), still capped by the
    # rules-engine hardcoded max_risk_per_trade floor via check_all_rules above.
    risk_cap = float(settings.get("risk_per_trade_pct", 1.0))
    # Trade memory stats for Kelly + profit-edge sizing
    win_rate, avg_win, avg_loss, edge_mult = 0.0, 0.0, 0.0, 1.0
    try:
        import json as _json
        raw_metrics = await redis.cache_get("nexus:trade_memory:metrics", prefix=False)
        if raw_metrics and isinstance(raw_metrics, dict):
            overall = raw_metrics.get("overall", {})
            win_rate = float(overall.get("win_rate", 0) or 0)
            avg_win = float(overall.get("avg_win_pips", 0) or 0)
            avg_loss = float(overall.get("avg_loss_pips", 0) or 0)
            net_pnl = float(overall.get("net_pnl_usd", 0) or 0)
            if net_pnl > 0 and win_rate >= 0.55:
                edge_mult = min(1.5, 1.0 + (win_rate - 0.5))
            elif net_pnl < 0:
                edge_mult = max(0.6, 1.0 + net_pnl / max(merged.get("balance", 1000), 1) * 10)
    except Exception:
        pass

    effective_risk_pct = min(
        proposal.conviction * 2.5,
        risk_cap,
        rules_engine._cfg.max_risk_per_trade_pct,
    )
    sizing = position_sizer.calculate_size(
        balance=merged.get("balance", 10_000),
        risk_pct=effective_risk_pct,
        entry=proposal.entry,
        sl=proposal.sl,
        vol_regime=merged.get("vol_regime", "medium"),
        tilt_status=anti_tilt.get_tilt_status().value.lower(),
        session=merged.get("session", "london"),
        symbol=proposal.symbol,
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        profit_edge_mult=edge_mult,
    )

    adjusted_size = position_sizer.scale_by_conviction(sizing.lots, proposal.conviction)
    final_risk_budget_pct = min(effective_risk_pct, sizing.risk_pct_used)
    # Conviction scaling (×1.15 at high conviction) runs AFTER the sizer's cap —
    # re-clamp so no approved size can ever exceed the balance/hard-ceiling lots.
    adjusted_size = round(
        min(
            adjusted_size,
            position_sizer.max_allowed_lots(merged.get("balance", 10_000)),
            position_sizer.max_lots_for_risk(
                merged.get("balance", 10_000), proposal.entry, proposal.sl,
                proposal.symbol, final_risk_budget_pct,
            ),
        ),
        2,
    )

    # ── Ergodic lot multiplier (Peters 2019) ────────────────────────────
    ergodic_mult, ergodic_info = await _get_ergodic_lot_multiplier(
        proposal.symbol, adjusted_size
    )
    if ergodic_mult < 1.0:
        pre_ergodic = adjusted_size
        adjusted_size = round(
            min(
                adjusted_size * ergodic_mult,
                position_sizer.max_allowed_lots(merged.get("balance", 10_000)),
                position_sizer.max_lots_for_risk(
                    merged.get("balance", 10_000), proposal.entry, proposal.sl,
                    proposal.symbol, final_risk_budget_pct,
                ),
            ),
            2,
        )
        log.info(
            "risk.ergodic_size_adjusted",
            symbol=proposal.symbol,
            before=pre_ergodic,
            after=adjusted_size,
            mult=ergodic_mult,
        )

    # ── Phase 3: portfolio open-risk budget clamp (size vs REMAINING) ────
    # Plan: the new position is measured against what is LEFT of
    # equity × max_portfolio_open_risk_pct, not the full balance. The remaining
    # budget is passed through the sizer's balance-denominated risk_pct API so
    # the lot cap corresponds to exactly `remaining` USD of stop risk. The
    # budget helper returns None while the gate is disabled (cfg None), which
    # leaves default sizing untouched; a zero/unknown remaining budget clamps
    # to 0.0 and the min-lot check below rejects with its existing rule.
    _remaining_risk_usd = _remaining_open_risk_budget_usd(merged)
    if _remaining_risk_usd is not None and adjusted_size > 0:
        try:
            _clamp_balance = float(merged.get("balance", 10_000))
        except (TypeError, ValueError):
            _clamp_balance = 0.0
        if (
            _remaining_risk_usd <= 0
            or not math.isfinite(_clamp_balance)
            or _clamp_balance <= 0
        ):
            adjusted_size = 0.0
        else:
            _remaining_pct = min(
                _remaining_risk_usd / _clamp_balance * 100.0,
                final_risk_budget_pct,
            )
            _budget_lots = position_sizer.max_lots_for_risk(
                _clamp_balance, proposal.entry, proposal.sl,
                proposal.symbol, _remaining_pct,
            )
            if _budget_lots < adjusted_size:
                log.info(
                    "risk.portfolio_budget.clamped",
                    symbol=proposal.symbol,
                    before=adjusted_size,
                    after=_budget_lots,
                    remaining_usd=round(_remaining_risk_usd, 2),
                )
                adjusted_size = round(_budget_lots, 2)

    if adjusted_size < position_sizer._min_lot_step:
        return {
            "decision": RiskDecision.REJECT,
            "approved_size": 0.0,
            "violations": [{
                "rule": "risk_budget_below_minimum_lot",
                "message": "Risk budget cannot support the minimum lot size",
                "message_ar": "ميزانية المخاطر لا تسمح بالحد الأدنى لحجم العقد.",
            }],
            "sizing": {"risk_pct_used": 0.0, "capped": True},
            "tilt": anti_tilt.get_state_dict(),
        }

    risk_violation = rules_engine.check_max_risk_per_trade(
        adjusted_size, proposal.entry, proposal.sl,
        merged.get("balance", 10_000), symbol=proposal.symbol,
    )
    if risk_violation:
        return {
            "decision": RiskDecision.REJECT,
            "approved_size": 0.0,
            "violations": [{
                "rule": risk_violation.rule,
                "message": risk_violation.message,
                "severity": risk_violation.severity,
                "current_value": risk_violation.current_value,
                "limit_value": risk_violation.limit_value,
            }],
            "sizing": {},
            "tilt": anti_tilt.get_state_dict(),
        }

    # Count this approval toward the daily trade cap + record for anti-stacking.
    _daily_trade_count += 1
    _current_state["daily_trade_count"] = _daily_trade_count
    await _mark_stack_cooldown(_dir_key)
    # Persist count to Redis so it survives service restarts (run.py respawn).
    asyncio.ensure_future(_persist_daily_count())

    return {
        "decision": RiskDecision.APPROVE,
        "approved_size": adjusted_size,
        "violations": violation_dicts,
        "sizing": {
            "lots": adjusted_size,
            "raw_lots": sizing.lots,
            "risk_pct_used": rules_engine.risk_pct_for_size(
                adjusted_size, proposal.entry, proposal.sl,
                merged.get("balance", 10_000), proposal.symbol,
            ),
            "kelly_fraction": sizing.kelly_fraction,
            "vol_factor": sizing.vol_factor,
            "tilt_factor": sizing.tilt_factor,
            "session_factor": sizing.session_factor,
            "capped": sizing.capped,
            "ergodic": ergodic_info,
        },
        "tilt": anti_tilt.get_state_dict(),
    }


# ── G5 honest breakers — main-side live signals ───────────────────────────────
# Rows whose live signal is decided in main.py are resolved into
# state["breaker_state"] — the engine's documented G5 contract — instead of
# being reported as hardcoded triggered:False: session_gate (server clock),
# anti_stacking + trade_cooldown (same-direction re-entry cooldown), and
# anti_revenge (per-direction loss block). Tracked state can only ADD a trip;
# it can never mask a live engine computation.


async def _main_breaker_overrides() -> dict[str, dict[str, Any]]:
    """Actual main-side circuit-breaker state for get_active_circuit_breakers."""
    now_iso = datetime.now(timezone.utc).isoformat()
    out: dict[str, dict[str, Any]] = {}

    def _add(name: str, reason: str) -> None:
        out[name] = {"triggered": True, "reason": reason, "triggered_at": now_iso}

    # session_gate — same live policy _evaluate_proposal enforces.
    try:
        _off_hours_ok, _allowed_sessions = await _session_gate_policy()
        if not _off_hours_ok:
            session_now = detect_session_now()
            if session_now.value not in _allowed_sessions:
                _add(
                    "session_gate",
                    f"Session {session_now.value} not in allowed set "
                    f"{sorted(_allowed_sessions)}",
                )
    except Exception:
        log.debug("risk.breakers.session_probe_failed", exc_info=True)

    # anti_stacking / trade_cooldown — any live same-direction re-entry
    # cooldown (in-memory map first, then Redis keys that survived restarts).
    active_cooldowns: list[str] = []
    for dir_key in list(_last_trade_ts_by_dir):
        try:
            if await _stack_cooldown_remaining(dir_key) > 0:
                active_cooldowns.append(dir_key)
        except Exception:
            break
    try:
        async for key in redis.r.scan_iter(_STACK_KEY_PREFIX + "*"):
            suffix = key.decode() if isinstance(key, (bytes, bytearray)) else str(key)
            suffix = suffix[len(_STACK_KEY_PREFIX):]
            if suffix and suffix not in active_cooldowns:
                ttl = await redis.r.ttl(key)
                if ttl and ttl > 0:
                    active_cooldowns.append(suffix)
    except Exception:
        log.debug("risk.breakers.cooldown_scan_failed", exc_info=True)
    if active_cooldowns:
        shown = ", ".join(sorted(active_cooldowns)[:4])
        _add("anti_stacking", f"Same-direction cooldown active: {shown}")
        _add(
            "trade_cooldown",
            f"Re-entry cooldown active ({_STACK_COOLDOWN_SEC}s): {shown}",
        )

    # anti_revenge — any live per-direction block after consecutive losses.
    blocked: list[str] = []
    try:
        async for key in redis.r.scan_iter(_DIR_BLOCK_PREFIX + "*"):
            suffix = key.decode() if isinstance(key, (bytes, bytearray)) else str(key)
            suffix = suffix[len(_DIR_BLOCK_PREFIX):]
            ttl = await redis.r.ttl(key)
            if ttl and ttl > 0:
                blocked.append(suffix)
    except Exception:
        log.debug("risk.breakers.block_scan_failed", exc_info=True)
    if blocked:
        _add(
            "anti_revenge",
            "Direction re-entry blocked after consecutive losses: "
            + ", ".join(sorted(blocked)[:4]),
        )

    return out


async def _breaker_report_state() -> dict[str, Any]:
    """State dict for get_active_circuit_breakers: fresh counters + overrides.

    daily_trade_count / max_daily_trades are refreshed from the live globals so
    the engine's daily_trade_limit row is honest without waiting for the next
    account sync; breaker_state carries the main-side live signals above.
    """
    limit = _daily_trades_limit_observed
    if limit <= 0:
        try:
            limit = int(_current_state.get("max_daily_trades", 0) or 0)
        except (TypeError, ValueError):
            limit = 0
    return {
        **_current_state,
        "daily_trade_count": _daily_trade_count,
        "max_daily_trades": limit,
        "breaker_state": await _main_breaker_overrides(),
    }


# ── Cache risk state to Redis ────────────────────────────────────────────────

async def _cache_risk_state() -> None:
    tilt = anti_tilt.get_state_dict()
    breakers = rules_engine.get_active_circuit_breakers(await _breaker_report_state())
    cfg = rules_engine._cfg
    open_count = int(_current_state.get("open_positions_count", 0))
    state = RiskState(
        available=bool(_current_state.get("available", False)),
        balance=_current_state.get("balance", 0.0),
        equity=_current_state.get("equity", 0.0),
        daily_loss_pct=_current_state.get("daily_loss_pct", 0.0),
        weekly_dd_pct=_current_state.get("weekly_dd_pct", 0.0),
        open_positions=open_count,
        correlation_exposure=_current_state.get("correlation_exposure", 0.0),
        tilt_status=tilt["status"],
        circuit_breakers=[CircuitBreaker(**b) for b in breakers],
        # Live enforced limits so the dashboard shows the real config (20% daily,
        # 25% weekly, etc.) instead of its hardcoded fallbacks.
        max_daily_loss_pct=cfg.max_daily_loss_pct,
        max_weekly_drawdown_pct=cfg.max_weekly_drawdown_pct,
        open_positions_count=open_count,
        max_positions=cfg.max_open_positions,
        max_correlation=cfg.max_correlation,
        consecutive_losses=int(tilt.get("consecutive_losses", 0)),
        current_session=str(_current_state.get("current_session", "")),
    )
    await redis.cache_set(
        CACHE_RISK_STATE,
        state.model_dump(mode="json"),
        ttl_sec=90,  # > sync interval (30s) so the cache never gaps to zeros
        prefix=False,
    )


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Migration-safe approval-signing secret (dedicated key, legacy fallback).
    _ensure_approval_signing_secret()
    await redis.connect()
    # Restore persistent state that survives service restarts
    await _restore_daily_count()
    await _restore_day_start_balance()
    # Phase 3: equity peak + weekly series must survive restarts too
    await _restore_equity_peak()
    await _restore_weekly_dd()
    # Phase 3 (G5): observe the runtime daily-trade cap from boot so the
    # daily_trade_limit breaker row is honest before the first proposal.
    try:
        _boot_settings = await runtime_settings.get_settings(redis)
        global _daily_trades_limit_observed
        _daily_trades_limit_observed = int(_boot_settings.get("max_daily_trades") or 0)
        _current_state["max_daily_trades"] = _daily_trades_limit_observed
    except Exception:
        log.debug("risk.boot.settings_observed_failed", exc_info=True)
    await anti_tilt.restore_from_redis(redis.r)
    log.info("risk.service.started", port=SERVICE_PORT)
    consumer_task = asyncio.create_task(_risk_stream_consumer())
    sync_task = asyncio.create_task(_sync_account_state())
    close_task = asyncio.create_task(_trade_close_consumer())
    try:
        yield
    finally:
        for task in (consumer_task, sync_task, close_task):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await redis.disconnect()
        log.info("risk.service.stopped")


# ── FastAPI App ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Nexus Risk",
    version="2.0.0",
    lifespan=lifespan,
)


def _verify_internal_service_secret(provided_secret: str | None) -> None:
    internal_secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
    if not internal_secret:
        raise HTTPException(503, "NEXUS_INTERNAL_API_SECRET is not configured")
    if not provided_secret or not hmac.compare_digest(internal_secret, provided_secret):
        raise HTTPException(403, "invalid internal service credential")


@app.get("/health")
async def health():
    redis_ok = await redis.health_check()
    return {
        "service": SERVICE_NAME,
        "status": "healthy" if redis_ok else "degraded",
        "redis": redis_ok,
        "tilt_status": anti_tilt.get_tilt_status().value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/risk/status", response_model=RiskStatusResponse)
async def get_risk_status(
    x_nexus_internal_secret: str | None = Header(default=None),
):
    _verify_internal_service_secret(x_nexus_internal_secret)
    tilt = anti_tilt.get_state_dict()
    breakers = rules_engine.get_active_circuit_breakers(await _breaker_report_state())
    await _cache_risk_state()
    return RiskStatusResponse(
        state=_current_state,
        tilt=tilt,
        circuit_breakers=breakers,
    )


@app.get("/api/risk/exposure")
async def get_exposure(
    x_nexus_internal_secret: str | None = Header(default=None),
):
    _verify_internal_service_secret(x_nexus_internal_secret)
    """Exposure snapshot — only Nexus-tagged positions count toward limits."""
    return {
        "daily_loss_pct": _current_state.get("daily_loss_pct", 0.0),
        "weekly_dd_pct": _current_state.get("weekly_dd_pct", 0.0),
        "open_positions": _current_state.get("open_positions_count", 0),
        "positions": _current_state.get("open_positions", []),
        "total_positions": _current_state.get("total_positions_count", 0),
        "external_positions": _current_state.get("external_positions_count", 0),
        "consecutive_losses": anti_tilt.get_state_dict().get("consecutive_losses", 0),
        "tilt_status": anti_tilt.get_tilt_status().value,
        "daily_pnl": 0.0,
        # Phase 3: real portfolio-gate exposure instead of the old hardcoded 0.
        "correlation_exposure": _current_state.get("correlation_exposure", 0.0),
        "correlation_data_status": _current_state.get("correlation_data_status", "disabled"),
        "equity_peak": _current_state.get("equity_peak", 0.0),
        "equity_peak_day": _current_state.get("equity_peak_day", ""),
        "dd_from_peak_pct": _current_state.get("dd_from_peak_pct", 0.0),
        "open_risk_usd": _current_state.get("open_risk_usd"),
        "open_risk_pct": _current_state.get("open_risk_pct"),
        "gross_leverage": _current_state.get("gross_leverage"),
        "weekly_dd_source": _current_state.get("weekly_dd_source", "fallback"),
    }


@app.get("/api/risk/circuit-breakers")
async def get_circuit_breakers(
    x_nexus_internal_secret: str | None = Header(default=None),
):
    _verify_internal_service_secret(x_nexus_internal_secret)
    breakers = rules_engine.get_active_circuit_breakers(await _breaker_report_state())
    return {
        "circuit_breakers": breakers,
        # G5 honesty: only rows actually triggered count as "any_triggered".
        "any_triggered": any(bool(b.get("triggered")) for b in breakers),
        "count": len(breakers),
    }


@app.post("/api/risk/evaluate", response_model=EvaluateResponse)
async def evaluate_trade(
    req: EvaluateRequest,
    x_nexus_internal_secret: str | None = Header(default=None),
):
    _verify_internal_service_secret(x_nexus_internal_secret)

    proposal = req.proposal.model_copy(
        update={"symbol": str(req.proposal.symbol).strip().upper()}
    )
    if not proposal.symbol:
        raise HTTPException(status_code=422, detail="Proposal symbol is required")
    if req.order_type == "MARKET" and req.order_price != 0:
        raise HTTPException(
            status_code=422,
            detail="Market orders must use zero execution price; proposal entry is signed separately",
        )
    if req.order_type in {"LIMIT", "STOP"} and not math.isclose(
        req.order_price, req.proposal.entry, rel_tol=0.0, abs_tol=1e-9
    ):
        raise HTTPException(
            status_code=422,
            detail="Pending-order price must match the risk-evaluated proposal entry",
        )
    try:
        result = await _evaluate_proposal(proposal, _current_state)
        result["proposal_id"] = proposal.id
        if str(result.get("decision")) == str(RiskDecision.APPROVE):
            # Apply regime policy before signing, and never let it increase the
            # size approved by the core risk engine.
            risk_size = float(result.get("approved_size", 0) or 0)
            policy_size = math.floor(risk_size * req.size_multiplier * 100 + 1e-9) / 100
            if req.size_multiplier < 1.0 and policy_size < 0.01:
                result["decision"] = RiskDecision.REJECT
                result["approved_size"] = 0.0
                result.setdefault("violations", []).append({
                    "rule": "policy_size_below_minimum_lot",
                    "message": "Risk policy reduction is below the supported 0.01 minimum lot",
                    "message_ar": "تخفيض سياسة المخاطر أقل من الحد الأدنى المدعوم لحجم الصفقة (0.01).",
                })
                sizing_result = result.get("sizing")
                if isinstance(sizing_result, dict):
                    sizing_result["lots"] = 0.0
                    sizing_result["risk_pct_used"] = 0.0
            else:
                result["approved_size"] = (
                    min(risk_size, policy_size) if req.size_multiplier < 1.0 else risk_size
                )
                if req.size_multiplier < 1.0:
                    sizing_result = result.get("sizing")
                    if isinstance(sizing_result, dict):
                        sizing_result["lots"] = result["approved_size"]
                        try:
                            original_risk_pct = float(sizing_result.get("risk_pct_used", 0) or 0)
                            sizing_result["risk_pct_used"] = round(
                                original_risk_pct * result["approved_size"] / risk_size,
                                6,
                            ) if risk_size > 0 else 0.0
                        except (TypeError, ValueError, ZeroDivisionError):
                            sizing_result["risk_pct_used"] = 0.0
            if str(result.get("decision")) == str(RiskDecision.APPROVE):
                expires = int(_time_mod.time()) + int(os.getenv("NEXUS_RISK_APPROVAL_TTL_SEC", "30"))
                signal_timestamp = _time_mod.time()
                approval_payload = {
                    "version": 1,
                    "proposal_id": proposal.id,
                    "expires_at": expires,
                    "symbol": proposal.symbol,
                    "side": str(proposal.direction),
                    "order_type": req.order_type,
                    "entry": proposal.entry,
                    "price": req.order_price,
                    "sl": proposal.sl,
                    "tp": proposal.tp1,
                    "size": float(result["approved_size"]),
                    "signal_timestamp": signal_timestamp,
                    "slippage": req.slippage,
                }
                signature = approval_signature(approval_payload)
                if not signature:
                    result = {
                        "decision": RiskDecision.REJECT,
                        "approved_size": 0.0,
                        "violations": [{
                            "rule": "approval_payload_invalid_or_secret_missing",
                            "message": "Risk approval could not be signed; verify the internal secret and approved terms",
                            "message_ar": "تعذر توقيع موافقة المخاطر؛ تحقق من السر الداخلي وتفاصيل الموافقة.",
                        }],
                        "sizing": {}, "tilt": anti_tilt.get_state_dict(),
                        "proposal_id": proposal.id,
                        "approval_expires_at": 0,
                        "approval_signature": "",
                        "approval_payload": {},
                    }
                else:
                    result["approval_expires_at"] = expires
                    result["approval_signature"] = signature
                    result["approval_payload"] = approval_payload
        await _cache_risk_state()
        return EvaluateResponse(**result)
    except Exception as exc:
        log.exception("risk.evaluate.error")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Front-configurable settings + day reset ─────────────────────────────────

class SettingsPatch(BaseModel):
    """Partial update of runtime settings (only provided keys change)."""
    risk_per_trade_pct: float | None = None
    max_daily_loss_pct: float | None = None
    max_weekly_dd_pct: float | None = None
    max_open_positions: int | None = None
    max_daily_trades: int | None = None
    min_hold_minutes: int | None = None
    max_hold_minutes: int | None = None
    min_conviction_override: float | None = None
    research_min_candidates: int | None = None
    research_max_search_rounds: int | None = None
    research_interval_sec: int | None = None
    require_mtf_confirmation: bool | None = None
    min_mtf_agreement: int | None = None
    # Session gate — editable from the Settings tab (was env-only/read-only).
    off_hours_allowed: bool | None = None
    allowed_sessions: list[str] | None = None


async def _session_gate_policy() -> tuple[bool, set[str]]:
    """Gate policy as enforced right now: Redis override beats the env default.

    ``get_settings`` is throttled (5s) and falls back to the process cache, so
    calling this on every proposal costs at most one Redis read per window.
    """
    try:
        doc: Any = await runtime_settings.get_settings(redis)
    except Exception:  # store unreachable ⇒ cached document (itself env-seeded)
        doc = None
    return runtime_settings.session_gate_policy(
        doc,
        default_off_hours=ALLOW_OFF_HOURS,
        default_sessions=ALLOWED_SESSIONS,
    )


@app.get("/api/risk/settings")
async def get_settings_endpoint(
    x_nexus_internal_secret: str | None = Header(default=None),
):
    """Return the current front-configurable runtime settings + live counters."""
    _verify_internal_service_secret(x_nexus_internal_secret)
    settings = await runtime_settings.get_settings(redis)
    # Reported policy == enforced policy (same helper _evaluate_proposal uses),
    # so the Settings tab can never show a gate that differs from the engine.
    _off_hours_ok, _allowed_sessions = await _session_gate_policy()
    return {
        "settings": settings,
        "session_gate": {
            "off_hours_allowed": _off_hours_ok,
            "allowed_sessions": sorted(_allowed_sessions),
        },
        "daily_trade_count": _daily_trade_count,
        "trades_paused": _trades_paused,
        "daily_loss_pct": _current_state.get("daily_loss_pct", 0.0),
        "day_start_balance": _day_start_balance,
    }


@app.post("/api/risk/settings")
async def update_settings_endpoint(
    patch: SettingsPatch,
    x_nexus_internal_secret: str | None = Header(default=None),
):
    """Update runtime settings from the dashboard. Only provided keys change."""
    _verify_internal_service_secret(x_nexus_internal_secret)
    global _daily_trades_limit_observed
    provided = {k: v for k, v in patch.model_dump().items() if v is not None}
    # Same contract as the intelligence route: clamp known keys to their bounds
    # and drop values that cannot be interpreted, so a malformed patch can never
    # be persisted as live policy (sanitize_patch passes None through as a
    # reset, which this filter has already removed).
    provided = runtime_settings.sanitize_patch(provided)
    try:
        merged = await runtime_settings.update_settings(provided, redis)
    except Exception as exc:
        log.exception("risk.settings.persist_failed")
        raise HTTPException(503, "Runtime settings could not be saved") from exc
    rules_engine.apply_runtime_overrides(merged)
    # Keep the breaker observation in step with the just-saved cap (G5) so the
    # daily_trade_limit row is accurate without waiting for the next sync.
    try:
        _daily_trades_limit_observed = int(merged.get("max_daily_trades") or 0)
        _current_state["max_daily_trades"] = _daily_trades_limit_observed
    except (TypeError, ValueError):
        pass
    log.info("risk.settings.updated", changed=list(provided.keys()))
    return {"settings": merged, "changed": list(provided.keys())}


@app.get("/api/exposure")
async def get_exposure(
    x_nexus_internal_secret: str | None = Header(default=None),
):
    _verify_internal_service_secret(x_nexus_internal_secret)
    """Portfolio exposure snapshot for the GenAI risk manager (A8).

    A8's tools/risk_tools.check_exposure() has always called this path, but
    the endpoint never existed — every call 404'd and fell back to all-zeros,
    so A8's daily-loss / weekly-DD / max-positions breakers were inert.
    Serving it from _current_state also means A8 automatically inherits the
    Nexus-only daily-loss accounting.
    """
    return {
        "daily_loss_pct": _current_state.get("daily_loss_pct", 0.0),
        "weekly_dd_pct": _current_state.get("weekly_dd_pct", 0.0),
        "open_positions": _current_state.get("open_positions_count", 0),
        "positions": _current_state.get("open_positions", []),
        "consecutive_losses": anti_tilt.get_state_dict().get("consecutive_losses", 0),
        "tilt_status": _current_state.get("tilt_status", "NORMAL"),
        "daily_pnl": _current_state.get("nexus_daily_pnl", 0.0),
        "correlation_exposure": _current_state.get("correlation_exposure", 0.0),
        # Phase 3 portfolio-gate inputs (additive).
        "equity_peak": _current_state.get("equity_peak", 0.0),
        "equity_peak_day": _current_state.get("equity_peak_day", ""),
        "dd_from_peak_pct": _current_state.get("dd_from_peak_pct", 0.0),
        "open_risk_usd": _current_state.get("open_risk_usd"),
        "open_risk_pct": _current_state.get("open_risk_pct"),
        "gross_leverage": _current_state.get("gross_leverage"),
        "weekly_dd_source": _current_state.get("weekly_dd_source", "fallback"),
    }


# ── Reset-day audit (Phase 3 / G5) ───────────────────────────────────────────

def _reset_audit_insert(
    audit_id: str, caller: str, ts_iso: str, pre_clear_json: str,
) -> None:
    """Synchronous DuckDB insert (invoked in a worker thread).

    CREATE TABLE IF NOT EXISTS with nullable columns so the table bootstraps
    on first use next to the other Nexus DuckDB stores.
    """
    duckdb_path = os.getenv("DUCKDB_PATH", "./data/nexus.duckdb")
    parent = os.path.dirname(duckdb_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    import duckdb

    conn = duckdb.connect(duckdb_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS risk_reset_audit (
                id VARCHAR,
                caller VARCHAR,
                ts TIMESTAMPTZ,
                pre_clear_json TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO risk_reset_audit (id, caller, ts, pre_clear_json) "
            "VALUES (?, ?, ?, ?)",
            [audit_id, caller, ts_iso, pre_clear_json],
        )
    finally:
        conn.close()


async def _write_reset_audit(
    pre_clear: dict[str, Any], caller: str = "api:reset-day",
) -> None:
    """Persist one reset-day audit row; log-and-continue on any failure.

    The lineage pattern used elsewhere: an audit write problem must never
    block the reset itself, but it is always surfaced in the logs.
    """
    audit_id = uuid.uuid4().hex
    ts_iso = datetime.now(timezone.utc).isoformat()
    try:
        await asyncio.wait_for(
            asyncio.to_thread(
                _reset_audit_insert,
                audit_id,
                caller,
                ts_iso,
                json.dumps(pre_clear, default=str, sort_keys=True),
            ),
            timeout=5.0,
        )
        log.info("risk.reset_day.audit_written", audit_id=audit_id, caller=caller)
    except Exception:
        log.warning("risk.reset_day.audit_write_failed", exc_info=True)


async def _rebaseline_portfolio_state(equity: float) -> None:
    """reset-day: peak := current equity, 7-day series := [today @ equity].

    Without this the equity-peak gate would carry the pre-reset high-water
    mark into the fresh day (blocking every proposal) and the weekly series
    would keep anchoring the new week to the old peak.
    """
    global _equity_peak, _equity_peak_day
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if math.isfinite(equity) and equity > 0:
        _equity_peak = float(equity)
        _equity_peak_day = day
        try:
            await _persist_equity_peak(day)
        except Exception:
            log.debug("risk.reset_day.peak_persist_failed", exc_info=True)
        _current_state["equity_peak"] = _equity_peak
        _current_state["equity_peak_day"] = day
        _current_state["dd_from_peak_pct"] = 0.0
    try:
        await redis.r.delete(_EQUITY_SERIES_KEY)
        await redis.r.rpush(
            _EQUITY_SERIES_KEY,
            json.dumps({"day": day, "equity": float(equity)}, separators=(",", ":")),
        )
        await redis.r.expire(_EQUITY_SERIES_KEY, _EQUITY_SERIES_TTL_SEC)
        _current_state["weekly_dd_pct"] = 0.0
        _current_state["weekly_dd_source"] = "equity_series"
    except Exception:
        log.debug("risk.reset_day.series_rebaseline_failed", exc_info=True)


@app.post("/api/risk/reset-day")
async def reset_day(x_nexus_internal_secret: str | None = Header(default=None)):
    """Reset the daily risk budget so trades resume even after limits were hit.

    Re-baselines the day-start balance to the current equity (daily loss → 0),
    clears the daily trade counter, clears the manual pause flag, and clears any
    kill switch. Use this to 'start a fresh day' on demand.
    """
    _verify_internal_service_secret(x_nexus_internal_secret)
    global _day_start_balance, _daily_trade_count, _trades_paused, _last_sync_day
    equity = _current_state.get("equity", 0.0) or _current_state.get("balance", 0.0)
    # Fail closed: never re-baseline the daily-loss denominator from a
    # missing or stale snapshot. Zeroing counters against an unknown balance
    # would silently erase a real drawdown and re-open the loss budget.
    _reset_synced_at = _current_state.get("last_sync_ok_ts")
    try:
        _reset_snapshot_fresh = (
            _current_state.get("available") is True
            and isinstance(_reset_synced_at, (int, float))
            and math.isfinite(float(_reset_synced_at))
            and (_time_mod.time() - float(_reset_synced_at)) <= ACCOUNT_STATE_MAX_STALE_SEC
            and isinstance(equity, (int, float))
            and math.isfinite(float(equity))
            and float(equity) > 0
        )
    except (TypeError, ValueError, OverflowError):
        _reset_snapshot_fresh = False
    if not _reset_snapshot_fresh:
        raise HTTPException(
            status_code=503,
            detail=(
                "Authoritative account snapshot unavailable or stale; "
                "day reset refused (fail-closed)"
            ),
        )
    # Phase 3 (G5): audit the pre-clear values FIRST, then re-baseline the
    # portfolio-gate state so the fresh day cannot inherit the old peak or
    # 7-day series (both would otherwise keep blocking trading).
    await _write_reset_audit({
        "equity": float(equity),
        "balance": _current_state.get("balance", 0.0),
        "day_start_balance": _day_start_balance,
        "daily_loss_pct": _current_state.get("daily_loss_pct", 0.0),
        "weekly_dd_pct": _current_state.get("weekly_dd_pct", 0.0),
        "weekly_dd_source": _current_state.get("weekly_dd_source", ""),
        "daily_trade_count": _daily_trade_count,
        "trades_paused": _trades_paused,
        "equity_peak": _equity_peak,
        "equity_peak_day": _equity_peak_day,
        "open_risk_usd": _current_state.get("open_risk_usd"),
        "gross_leverage": _current_state.get("gross_leverage"),
        "tilt_status": anti_tilt.get_state_dict().get("status", ""),
    })
    await _rebaseline_portfolio_state(float(equity))
    if equity > 0:
        _day_start_balance = equity
        # Persist the re-baselined value — without this, the next service
        # restart restores the STALE pre-reset baseline from Redis, and a
        # 20% breaker on an inflated denominator allows far larger absolute
        # losses than the account can actually afford.
        try:
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            await redis.r.set(_DAY_START_BALANCE_KEY, str(equity), ex=172_800)
            await redis.r.set(_DAY_START_DAY_KEY, today_str, ex=172_800)
        except Exception:
            log.debug("risk.reset_day.day_start_persist_failed", exc_info=True)
    _current_state["day_start_balance"] = _day_start_balance
    _current_state["daily_loss_pct"] = 0.0
    _current_state["weekly_dd_pct"] = 0.0
    _daily_trade_count = 0
    _trades_paused = False
    _last_sync_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        anti_tilt.reset()
    except Exception:
        pass
    try:
        await redis.cache_delete("system:kill_switch")
    except Exception:
        pass
    # Clear circuit-breaker results + persist zeroed count
    try:
        await redis.r.delete(_RECENT_RESULTS_KEY)
        await _persist_daily_count()
    except Exception:
        pass
    # Full clean slate: Nexus daily-PnL accumulator, per-direction re-entry
    # blocks/streaks, and the ergodic pause — "reset day" from the dashboard
    # must leave nothing armed.
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        await redis.r.set(_NEXUS_DAILY_PNL_KEY, "0", ex=172_800)
        await redis.r.set(_NEXUS_DAILY_PNL_DAY_KEY, today, ex=172_800)
        _current_state["nexus_daily_pnl"] = 0.0
        for pattern in (f"{_DIR_LOSS_PREFIX}*", f"{_DIR_BLOCK_PREFIX}*"):
            async for key in redis.r.scan_iter(pattern):
                await redis.r.delete(key)
        await redis.r.delete(_ERGODIC_PAUSE_KEY)
    except Exception:
        log.debug("risk.reset_day.extra_clears_failed", exc_info=True)
    await _cache_risk_state()
    log.info("risk.reset_day", new_day_start_balance=_day_start_balance)
    return {
        "status": "ok",
        "message": "Daily risk budget reset — trading resumed",
        "day_start_balance": _day_start_balance,
        "daily_trade_count": _daily_trade_count,
    }


@app.post("/api/risk/pause")
async def pause_trading(
    paused: bool = True,
    x_nexus_internal_secret: str | None = Header(default=None),
):
    """Manually pause or resume trading (separate from the daily limits)."""
    _verify_internal_service_secret(x_nexus_internal_secret)
    global _trades_paused
    _trades_paused = bool(paused)
    return {"status": "ok", "trades_paused": _trades_paused}
