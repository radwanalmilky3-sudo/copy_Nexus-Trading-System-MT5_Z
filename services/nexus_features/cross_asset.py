"""
Cross-Asset Feature Engine

Fetches DXY and US10Y data and computes contextual features for gold trading:
  - dxy_change_5d          5-day % change in DXY index
  - dxy_rsi_14             RSI(14) of DXY
  - dxy_trend              "up" / "down" / "flat" (rolling 20-bar EMA direction)
  - us10y_change_5d        5-day change in 10Y yield (percentage points)
  - us10y_level            current 10Y yield
  - real_rate_proxy        us10y_level - inflation_proxy (crude approximation)
  - gold_dxy_divergence    +1 if gold and DXY are diverging, -1 if converging
                           (5-day % moves, both legs daily frequency)
  - gold_yield_regime      "risk_off" / "risk_on" / "neutral"
  - corr_gold_dxy_20       rolling Pearson correlation of *daily* returns over
                           the common trailing window of real gold and DXY
                           daily closes (null unless both real series exist —
                           never a fabricated/proxy value, never mixed
                           frequencies)

Data sources (tried in order):
  1. Redis cache (nexus:cross_asset:DXY, nexus:cross_asset:US10Y) — fastest,
     fresh for 5 min, then still served (flagged ``stale``) up to _CROSS_ASSET_STALE_TTL
  2. yfinance (primary ticker, then a fallback ticker) — requires internet,
     short exponential backoff after a failure so one Yahoo outage does not
     produce an error line on every feature cycle
  3. Optional proxy only when NEXUS_ALLOW_SYNTHETIC_METRICS=1; otherwise UNAVAILABLE.

Stale-serve never invents values: it re-serves the last *real* payload and
marks it with ``stale``/``stale_age_sec`` plus a warning log.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
_CROSS_ASSET_TTL = 300   # 5-minute freshness window
_CROSS_ASSET_STALE_TTL = 6 * 3600  # keep the last real payload so a Yahoo outage can be stale-served
_CROSS_ASSET_KEY = "nexus:cross_asset:{symbol}"
_CROSS_ASSET_ALL_KEY = "nexus:cross_asset:summary"
_ALLOW_PROXY = os.getenv("NEXUS_ALLOW_SYNTHETIC_METRICS", "0").strip().lower() in {"1", "true", "yes"}

# ── Yahoo Finance ticker mapping ─────────────────────────────────────────────
_YF_TICKERS: dict[str, str] = {
    "DXY":   "DX-Y.NYB",   # Dollar Index futures
    "US10Y": "^TNX",        # 10-Year Treasury yield
    "XAUUSD": "XAUUSD=X",   # Spot gold — daily closes for the DXY correlation
}

# Same-instrument fallbacks, tried after the primary ticker returns no data.
# Yahoo intermittently 404s/omits XAUUSD=X; GC=F is the same real daily gold
# series correlation.py already uses — never a synthetic substitute.
_YF_FALLBACK_TICKERS: dict[str, list[str]] = {
    "XAUUSD": ["GC=F"],
}

# Failure backoff: 60 s doubling up to 15 min, per logical symbol.
_YF_BACKOFF_BASE_SEC = 60.0
_YF_BACKOFF_MAX_SEC = 900.0
_yf_backoff_until: dict[str, float] = {}
_yf_failures: dict[str, int] = {}
_yf_stale_logged: set[str] = set()
_YF_QUIET_DEPTH = 0
_YF_QUIET_PREV_LEVEL: int | None = None

_FALLBACK_VALUES: dict[str, dict[str, float]] = {
    "DXY":   {"level": 104.0, "change_5d": 0.0, "rsi_14": 50.0, "trend_score": 0.0},
    "US10Y": {"level": 4.3,   "change_5d": 0.0},
}


# ── Yahoo failure bookkeeping ────────────────────────────────────────────────

def _yf_candidates(symbol: str) -> list[str]:
    """Primary Yahoo ticker first, then any configured fallback."""
    primary = _YF_TICKERS.get(symbol, symbol)
    return [primary, *_YF_FALLBACK_TICKERS.get(symbol, [])]


def _yf_in_backoff(symbol: str) -> bool:
    return time.monotonic() < _yf_backoff_until.get(symbol, 0.0)


def _yf_mark_success(symbol: str) -> None:
    _yf_backoff_until.pop(symbol, None)
    _yf_failures.pop(symbol, None)
    _yf_stale_logged.discard(symbol)


def _yf_mark_failure(symbol: str, reason: str) -> None:
    fails = _yf_failures.get(symbol, 0) + 1
    _yf_failures[symbol] = fails
    delay = min(_YF_BACKOFF_MAX_SEC, _YF_BACKOFF_BASE_SEC * (2 ** min(fails - 1, 5)))
    _yf_backoff_until[symbol] = time.monotonic() + delay
    if fails <= 2:
        # One warning per outage instead of an error line per feature cycle.
        logger.warning("yfinance unavailable for %s — retrying in %.0fs (%s)", symbol, delay, reason)
    else:
        logger.debug("yfinance still unavailable for %s (failure #%d, next try in %.0fs)",
                     symbol, fails, delay)


@contextmanager
def _quiet_yf_logs():
    """Mute yfinance's own ERROR chatter while we drive a download.

    ``yf.download`` logs one ERROR per failed ticker on top of our own
    warning.  Depth-counted so concurrent downloads (correlation.py runs in a
    loop too) always restore the previous level exactly.
    """
    global _YF_QUIET_DEPTH, _YF_QUIET_PREV_LEVEL
    yf_log = logging.getLogger("yfinance")
    if _YF_QUIET_DEPTH == 0:
        _YF_QUIET_PREV_LEVEL = yf_log.level
        yf_log.setLevel(logging.CRITICAL)
    _YF_QUIET_DEPTH += 1
    try:
        yield
    finally:
        _YF_QUIET_DEPTH -= 1
        if _YF_QUIET_DEPTH == 0 and _YF_QUIET_PREV_LEVEL is not None:
            yf_log.setLevel(_YF_QUIET_PREV_LEVEL)
            _YF_QUIET_PREV_LEVEL = None


# ── Fetch helpers ─────────────────────────────────────────────────────────────

async def _fetch_from_redis(symbol: str, r) -> dict[str, Any] | None:
    try:
        raw = await r.get(_CROSS_ASSET_KEY.format(symbol=symbol))
        if raw:
            data = json.loads(raw)
            # Check freshness
            ts = data.get("fetched_at", "")
            if ts:
                fetched = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                # Naive stamps are treated as UTC; subtracting an aware "now"
                # from a naive value would raise and silently drop the cache.
                if fetched.tzinfo is None:
                    fetched = fetched.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - fetched).total_seconds()
                if age < _CROSS_ASSET_TTL:
                    return data
    except Exception:
        pass
    return None


async def _fetch_stale_from_redis(symbol: str, redis_client) -> dict[str, Any] | None:
    """Last *real* payload for ``symbol`` that outlived the freshness window.

    Stale-serve path for Yahoo outages.  Only already-fetched real data is
    returned (never a proxy/synthetic value) and it is explicitly flagged with
    ``stale``/``stale_age_sec`` so consumers can tell it is not fresh.
    """
    try:
        raw = await redis_client.get(_CROSS_ASSET_KEY.format(symbol=symbol))
        if not raw:
            return None
        data = json.loads(raw)
        if str(data.get("origin", "real")) != "real":
            return None
        ts = str(data.get("fetched_at", ""))
        if not ts:
            return None
        fetched = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - fetched).total_seconds()
        if age > _CROSS_ASSET_STALE_TTL:
            return None
        if symbol not in _yf_stale_logged:
            _yf_stale_logged.add(symbol)
            logger.warning("serving STALE %s payload from cache (age %.0fs) — yfinance unavailable",
                           symbol, age)
        else:
            logger.debug("stale %s payload reused (age %.0fs)", symbol, age)
        data["stale"] = True
        data["stale_age_sec"] = int(age)
        return data
    except Exception:
        return None


def _parse_yf_frame(symbol: str, ticker: str, df) -> dict[str, Any] | None:
    """Validate a yfinance frame and build the cached payload (or None)."""
    if df is None or getattr(df, "empty", True) or len(df) < 6:
        return None

    closes = np.asarray(df["Close"], dtype=float)
    # Single-ticker MultiIndex columns yield an (N, 1) Close frame.
    if closes.ndim == 2 and closes.shape[1] == 1:
        closes = closes[:, 0]
    if closes.ndim != 1 or not np.all(np.isfinite(closes)) or np.any(closes <= 0):
        return None
    current = float(closes[-1])
    prev5 = float(closes[-6])
    # Yield levels and regime thresholds use percentage points, not returns.
    change_5d = current - prev5 if symbol == "US10Y" else (current - prev5) / prev5 * 100
    if not np.isfinite(change_5d):
        return None

    # RSI(14)
    rsi = _compute_rsi(closes, 14)
    trend_score = _compute_trend(closes, 20)

    return {
        "symbol": symbol,
        "ticker": ticker,          # Yahoo ticker actually served (may be a fallback)
        "level": current,
        "change_5d": round(change_5d, 4),
        "rsi_14": round(rsi, 1),
        "trend_score": round(trend_score, 3),
        # Daily closes ride along so the same-frequency DXY correlation
        # can be computed (and re-served from cache) without a second
        # download. Capped to bound the Redis payload.
        "closes": [round(float(c), 6) for c in closes[-60:]],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "yfinance",
        "origin": "real",
    }


def _fetch_from_yfinance(symbol: str, period: str = "60d") -> dict[str, Any] | None:
    # Backing off: skip the network entirely so one Yahoo outage cannot
    # produce an error line on every feature cycle.
    if _yf_in_backoff(symbol):
        logger.debug("yfinance backoff active for %s — skipping download", symbol)
        return None
    try:
        import yfinance as yf  # optional dependency
        last_reason = "no data"
        with _quiet_yf_logs():
            for ticker in _yf_candidates(symbol):
                try:
                    df = yf.download(ticker, period=period, interval="1d",
                                     progress=False, auto_adjust=True)
                except Exception as exc:  # timeout / transport — try next ticker
                    last_reason = f"{ticker}: {type(exc).__name__}"
                    logger.debug("yfinance download failed for %s: %s", ticker, exc)
                    continue
                payload = _parse_yf_frame(symbol, ticker, df)
                if payload is not None:
                    if ticker != _YF_TICKERS.get(symbol, symbol):
                        logger.debug("yfinance fallback ticker %s used for %s", ticker, symbol)
                    _yf_mark_success(symbol)
                    return payload
                last_reason = f"{ticker}: no usable price rows"
        _yf_mark_failure(symbol, last_reason)
        return None
    except ImportError:
        logger.debug("yfinance not installed — real cross-asset source unavailable")
        return None
    except Exception as exc:
        _yf_mark_failure(symbol, str(exc) or type(exc).__name__)
        logger.debug("yfinance fetch failed for %s: %s", symbol, exc)
        return None


async def _resolve_daily_closes(symbol: str, redis_client) -> np.ndarray | None:
    """Daily closes of `symbol` from the cross-asset cache or yfinance.

    Fresh cache first, then a download (backoff-aware), then the last *real*
    cached payload even if it is past the freshness window.  Returns None when
    no real daily series exists at all — callers must treat that as "unknown"
    and publish null/0, never as a flat or proxy series.
    """
    try:
        data = await _fetch_from_redis(symbol, redis_client)
        if data is None:
            data = await asyncio.get_event_loop().run_in_executor(
                None, _fetch_from_yfinance, symbol
            )
            if data is not None:
                try:
                    await redis_client.set(
                        _CROSS_ASSET_KEY.format(symbol=symbol),
                        json.dumps(data), ex=_CROSS_ASSET_STALE_TTL,
                    )
                except Exception:
                    pass
            else:
                # Yahoo unavailable (backoff active or just failed): serve the
                # last real payload instead of dropping the whole series.
                data = await _fetch_stale_from_redis(symbol, redis_client)
        if not data or str(data.get("origin", "real")) != "real":
            return None
        raw = data.get("closes")
        if not isinstance(raw, (list, tuple)) or len(raw) < 21:
            return None
        series = np.asarray(raw, dtype=float)
        if series.ndim != 1 or not np.all(np.isfinite(series)) or np.any(series <= 0):
            return None
        return series
    except Exception as exc:
        logger.debug("daily closes unavailable for %s: %s", symbol, exc)
        return None


async def _compute_dynamic_proxy(redis_client) -> dict[str, dict[str, Any]]:
    """Derive DXY and US10Y proxies from XAUUSD features stored in Redis.

    Gold has strong inverse correlation with DXY (~-0.75) and negative
    relationship with US10Y real yields.  This is not a substitution for
    real data, but gives directional signals that update with every
    XAUUSD feature cycle rather than being permanently hardcoded.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        raw = await redis_client.get("nexus:features:XAUUSD:M5")
        if not raw:
            raise ValueError("no XAUUSD features")
        data = json.loads(raw)
        feats = data.get("features", data)

        gold_rsi = float(feats.get("rsi", 50.0) or 50.0)
        gold_close = float(feats.get("close", 0.0) or 0.0)
        gold_ema9 = float(feats.get("ema_9", gold_close) or gold_close)
        gold_ema50 = float(feats.get("ema_50", gold_close) or gold_close)
        trend_dir = str(feats.get("trend_direction", "SIDEWAYS"))
        trend_strength = float(feats.get("trend_strength", 0.0) or 0.0)

        # DXY inverse proxy
        dxy_rsi = round(100.0 - gold_rsi, 1)
        # trend_score: gold uptrend → DXY downtrend
        if trend_dir == "UPTREND":
            dxy_trend_score = -min(1.0, trend_strength / 100.0)
        elif trend_dir == "DOWNTREND":
            dxy_trend_score = min(1.0, trend_strength / 100.0)
        else:
            dxy_trend_score = 0.0
        # 5d change proxy: momentum from ema9 vs ema50 displacement, inverted
        if gold_close > 0 and gold_ema50 > 0:
            gold_momentum = (gold_close - gold_ema50) / gold_ema50 * 100
            dxy_change_5d = round(-gold_momentum * 0.4, 4)
        else:
            dxy_change_5d = 0.0

        # US10Y inverse proxy: rising gold → falling yields; falling gold → rising yields
        # Map gold RSI to approximate yield pressure: RSI>60 → yields falling, RSI<40 → rising
        if gold_rsi > 60:
            us10y_change = round(-(gold_rsi - 60) * 0.002, 4)   # yields falling
        elif gold_rsi < 40:
            us10y_change = round((40 - gold_rsi) * 0.002, 4)    # yields rising
        else:
            us10y_change = 0.0

        return {
            "DXY": {
                "level": _FALLBACK_VALUES["DXY"]["level"],  # no real DXY level available
                "change_5d": dxy_change_5d,
                "rsi_14": dxy_rsi,
                "trend_score": round(dxy_trend_score, 3),
                "source": "dynamic_gold_proxy",
                "fetched_at": now_iso,
            },
            "US10Y": {
                "level": _FALLBACK_VALUES["US10Y"]["level"],  # static level
                "change_5d": us10y_change,
                "source": "dynamic_gold_proxy",
                "fetched_at": now_iso,
            },
        }
    except Exception as exc:
        logger.debug("cross_asset: dynamic proxy failed (%s) — using static fallback", exc)
        return {
            "DXY": {**_FALLBACK_VALUES["DXY"], "source": "fallback", "fetched_at": now_iso},
            "US10Y": {**_FALLBACK_VALUES["US10Y"], "source": "fallback", "fetched_at": now_iso},
        }


def _compute_rsi(prices: np.ndarray, period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss < 1e-10:
        return 50.0 if avg_gain < 1e-10 else 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - 100.0 / (1.0 + rs), 1)


def _compute_trend(prices: np.ndarray, window: int = 20) -> float:
    """Return a -1..+1 score: +1 = strong uptrend, -1 = strong downtrend."""
    if len(prices) < window + 1:
        return 0.0
    ema = np.mean(prices[-window:])
    prev_ema = np.mean(prices[-window - 1:-1])
    delta = ema - prev_ema
    scale = abs(prev_ema) * 0.001 if abs(prev_ema) > 1e-8 else 1e-4
    return float(np.clip(delta / scale, -1.0, 1.0))


# ── Main computation ─────────────────────────────────────────────────────────

async def compute_cross_asset_features(
    symbol: str,
    redis_client,
    gold_closes: np.ndarray | None = None,
    dxy_closes: np.ndarray | None = None,
) -> dict[str, Any]:
    """Compute and cache cross-asset features for gold (or any symbol).

    Returns a feature dict ready to merge into the nexus:features:XAUUSD:* payload.

    ``gold_closes`` (stream-timeframe closes) is accepted for backward
    compatibility but is no longer used for the correlation or the divergence
    signal — those require same-frequency *daily* series, which are resolved
    internally from the cross-asset cache / yfinance.  ``dxy_closes`` may be
    supplied by a caller that already holds real daily DXY closes; otherwise
    the series cached alongside the DXY payload is used.
    """
    # 1. Try Redis cache for DXY and US10Y
    dxy = await _fetch_from_redis("DXY", redis_client)
    us10y = await _fetch_from_redis("US10Y", redis_client)

    # 2. If stale, fetch from yfinance (async wrapper).  When Yahoo is down or
    #    backing off, serve the last real payload before falling back to a
    #    placeholder — never a fabricated value, and always flagged stale.
    if dxy is None:
        dxy = await asyncio.get_event_loop().run_in_executor(None, _fetch_from_yfinance, "DXY")
        if dxy is None:
            dxy = await _fetch_stale_from_redis("DXY", redis_client)
        if dxy is None:
            if _ALLOW_PROXY:
                proxies = await _compute_dynamic_proxy(redis_client)
                dxy = {**proxies["DXY"], "origin": "proxy"}
            else:
                dxy = {"level": 0.0, "change_5d": 0.0, "rsi_14": 50.0, "trend_score": 0.0, "source": "unavailable", "origin": "unavailable", "fetched_at": datetime.now(timezone.utc).isoformat()}
        if not dxy.get("stale"):
            # Real payloads get the long TTL (they are the stale-serve copy);
            # placeholders keep the short one so they are retried quickly.
            _dxy_ttl = _CROSS_ASSET_STALE_TTL if str(dxy.get("origin", "real")) == "real" else _CROSS_ASSET_TTL
            try:
                await redis_client.set(_CROSS_ASSET_KEY.format(symbol="DXY"),
                                       json.dumps(dxy), ex=_dxy_ttl)
            except Exception:
                pass

    if us10y is None:
        us10y = await asyncio.get_event_loop().run_in_executor(None, _fetch_from_yfinance, "US10Y")
        if us10y is None:
            us10y = await _fetch_stale_from_redis("US10Y", redis_client)
        if us10y is None:
            if _ALLOW_PROXY:
                proxies = await _compute_dynamic_proxy(redis_client)
                us10y = {**proxies["US10Y"], "origin": "proxy"}
            else:
                us10y = {"level": 0.0, "change_5d": 0.0, "source": "unavailable", "origin": "unavailable", "fetched_at": datetime.now(timezone.utc).isoformat()}
        if not us10y.get("stale"):
            _us10y_ttl = _CROSS_ASSET_STALE_TTL if str(us10y.get("origin", "real")) == "real" else _CROSS_ASSET_TTL
            try:
                await redis_client.set(_CROSS_ASSET_KEY.format(symbol="US10Y"),
                                       json.dumps(us10y), ex=_us10y_ttl)
            except Exception:
                pass

    dxy_level = float(dxy.get("level", 104.0))
    dxy_change = float(dxy.get("change_5d", 0.0))
    dxy_rsi = float(dxy.get("rsi_14", 50.0))
    dxy_trend = float(dxy.get("trend_score", 0.0))

    us10y_level = float(us10y.get("level", 4.3))
    us10y_change = float(us10y.get("change_5d", 0.0))  # in pp

    dxy_available = str(dxy.get("origin", "real")) not in {"unavailable", "synthetic"}
    us10y_available = str(us10y.get("origin", "real")) not in {"unavailable", "synthetic"}
    cross_asset_available = dxy_available and us10y_available
    # True when any leg is a re-served real payload past its freshness window.
    cross_asset_stale = bool(dxy.get("stale")) or bool(us10y.get("stale"))
    if cross_asset_stale:
        logger.debug("cross_asset features built on stale payload (dxy_stale=%s us10y_stale=%s)",
                     bool(dxy.get("stale")), bool(us10y.get("stale")))

    # ── Gold–DXY correlation (real daily series, same frequency) ─────────
    # A single scalar DXY level carries zero correlation information; the
    # previous implementation published ``-dxy_trend`` under a correlation
    # name, which is a fabricated metric.  Both legs must be *daily* closes
    # from real sources: correlating intraday gold bars against daily DXY
    # bars would mix frequencies and manufacture a meaningless number.  The
    # caller-supplied ``gold_closes`` (stream timeframe) is therefore NOT
    # used here — the traded symbol's daily closes are resolved internally.
    if dxy_available and dxy_closes is None:
        raw_dxy_series = dxy.get("closes")
        if isinstance(raw_dxy_series, (list, tuple)) and len(raw_dxy_series) >= 21:
            try:
                dxy_closes = np.asarray(raw_dxy_series, dtype=float)
            except (TypeError, ValueError):
                dxy_closes = None

    gold_daily = None
    if dxy_available and dxy_closes is not None:
        gold_daily = await _resolve_daily_closes(symbol, redis_client)

    corr_gold_dxy: float | None = None
    if gold_daily is not None and dxy_closes is not None:
        try:
            # Align on the common trailing window (the two series may differ
            # by a bar around each session's close time).
            n = min(len(gold_daily), len(dxy_closes))
            if n >= 21:  # need >= 20 aligned returns
                gold = np.asarray(gold_daily[-n:], dtype=float)
                dxy_series = np.asarray(dxy_closes[-n:], dtype=float)
                if (
                    np.all(np.isfinite(gold))
                    and np.all(np.isfinite(dxy_series))
                    and np.all(gold > 0)
                    and np.all(dxy_series > 0)
                ):
                    gold_ret = np.diff(gold) / gold[:-1]
                    dxy_ret = np.diff(dxy_series) / dxy_series[:-1]
                    if np.std(gold_ret) > 1e-12 and np.std(dxy_ret) > 1e-12:
                        value = float(np.corrcoef(gold_ret, dxy_ret)[0, 1])
                        if np.isfinite(value):
                            corr_gold_dxy = round(value, 3)
        except Exception:
            corr_gold_dxy = None

    # ── Divergence signal ─────────────────────────────────────────────────
    # Gold and DXY should move inversely. Divergence = they're moving the
    # same way.  Both legs are 5-day % changes: ``dxy_change`` is the daily
    # payload's 5-day move, so gold momentum must also be a 5-trading-day
    # move from the daily series.  When no real daily gold series exists the
    # momentum stays 0 and the signal is the neutral 0 — never derived from
    # mixing M5 bars with a 5-day DXY change.
    gold_momentum = 0.0
    if gold_daily is not None and len(gold_daily) >= 6:
        base = float(gold_daily[-6])
        if abs(base) > 1e-9:
            gold_momentum = (float(gold_daily[-1]) - base) / abs(base)

    gold_dxy_divergence = 0
    if abs(dxy_change) > 0.1 and abs(gold_momentum) > 0.0005:
        if (dxy_change > 0 and gold_momentum < 0) or (dxy_change < 0 and gold_momentum > 0):
            gold_dxy_divergence = 1    # normal inverse relationship
        else:
            gold_dxy_divergence = -1   # diverging from expected = caution

    # ── Risk regime ───────────────────────────────────────────────────────
    # Never manufacture a cross-asset confirmation when real/proxy-allowed data is absent.
    if not cross_asset_available:
        gold_yield_regime = "unavailable"
        regime_signal_pts = 0
    else:
        if us10y_change < -0.05 and dxy_change > 0.1:
            gold_yield_regime = "risk_off"
        elif us10y_change > 0.05 and dxy_change > 0.2:
            gold_yield_regime = "risk_on"
        elif us10y_level > 5.0:
            gold_yield_regime = "high_rates"
        else:
            gold_yield_regime = "neutral"
        if gold_yield_regime == "risk_off":
            regime_signal_pts = 5
        elif gold_yield_regime == "neutral":
            regime_signal_pts = 3
        elif gold_yield_regime == "risk_on":
            regime_signal_pts = 1
        else:
            regime_signal_pts = 0

    features = {
        # DXY
        "dxy_level":         round(dxy_level, 3),
        "dxy_change_5d":     round(dxy_change, 4),
        "dxy_rsi_14":        round(dxy_rsi, 1),
        "dxy_trend_score":   round(dxy_trend, 3),
        # US10Y
        "us10y_level":       round(us10y_level, 3),
        "us10y_change_5d":   round(us10y_change, 4),
        # Composite
        "gold_dxy_divergence":   gold_dxy_divergence,
        "gold_yield_regime":     gold_yield_regime,
        "corr_gold_dxy_20":      corr_gold_dxy,
        "cross_asset_signal_pts": regime_signal_pts,
        # Source metadata
        "cross_asset_source":    dxy.get("source", "unknown"),
        "cross_asset_origin":    dxy.get("origin", "unknown"),
        "cross_asset_available": cross_asset_available,
        "cross_asset_updated":   dxy.get("fetched_at", ""),
        # Explicit staleness flag: values are real (already fetched) data that
        # is past the 5-minute freshness window, never synthetic.
        "cross_asset_stale":     cross_asset_stale,
    }

    # Cache the summary for the dashboard
    try:
        summary = {
            "dxy": {k: dxy.get(k) for k in ("level", "change_5d", "rsi_14", "trend_score", "source", "stale")},
            "us10y": {k: us10y.get(k) for k in ("level", "change_5d", "source", "stale")},
            "gold_yield_regime": gold_yield_regime,
            "gold_dxy_divergence": gold_dxy_divergence,
            "corr_gold_dxy_20": corr_gold_dxy,
            "cross_asset_signal_pts": regime_signal_pts,
            "available": cross_asset_available,
            "origin": dxy.get("origin", "unknown"),
            "stale": cross_asset_stale,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await redis_client.set(_CROSS_ASSET_ALL_KEY, json.dumps(summary), ex=_CROSS_ASSET_TTL)
    except Exception:
        pass

    return features


# ── Intraday Shift Monitor (Fase 4) ──────────────────────────────────────────
# Detects material intraday changes in DXY/US10Y or gold_yield_regime changes
# and publishes shift alerts to nexus:cross_asset:shift_alerts (list, max 20, 6h TTL).

_SHIFT_ALERTS_KEY = "nexus:cross_asset:shift_alerts"
_SHIFT_ALERTS_MAX = 20
_SHIFT_ALERTS_TTL = 6 * 3600

_DXY_SHIFT_PCT   = 0.3    # 0.3% move in DXY within one scan interval
_US10Y_SHIFT_BPS = 5.0    # 5 basis points change in US10Y
_PREV_SNAPSHOT: dict[str, Any] = {}


def _detect_regime_shift(prev: dict, curr: dict) -> list[dict[str, Any]]:
    """Compare previous vs current cross-asset snapshot. Return list of shift dicts."""
    shifts = []
    now_iso = datetime.now(timezone.utc).isoformat()

    # DXY level shift
    prev_dxy  = prev.get("dxy", {}).get("level")
    curr_dxy  = curr.get("dxy", {}).get("level")
    if prev_dxy and curr_dxy:
        pct_change = abs(curr_dxy - prev_dxy) / max(abs(prev_dxy), 1e-6) * 100
        if pct_change >= _DXY_SHIFT_PCT:
            direction = "UP" if curr_dxy > prev_dxy else "DOWN"
            shifts.append({
                "type": "DXY_SHIFT",
                "severity": "HIGH" if pct_change >= _DXY_SHIFT_PCT * 2 else "MEDIUM",
                "description": f"DXY moved {direction} {pct_change:.2f}% ({prev_dxy:.2f} → {curr_dxy:.2f})",
                "direction": direction,
                "prev_level": round(prev_dxy, 3),
                "curr_level": round(curr_dxy, 3),
                "pct_change": round(pct_change, 3),
                "detected_at": now_iso,
                "implication": "Headwind for gold" if direction == "UP" else "Tailwind for gold",
            })

    # US10Y shift (basis points)
    prev_y  = prev.get("us10y", {}).get("level")
    curr_y  = curr.get("us10y", {}).get("level")
    if prev_y and curr_y:
        bps_change = abs(curr_y - prev_y) * 100
        if bps_change >= _US10Y_SHIFT_BPS:
            direction = "UP" if curr_y > prev_y else "DOWN"
            shifts.append({
                "type": "US10Y_SHIFT",
                "severity": "HIGH" if bps_change >= _US10Y_SHIFT_BPS * 2 else "MEDIUM",
                "description": f"US10Y moved {direction} {bps_change:.1f}bps ({prev_y:.2f}% → {curr_y:.2f}%)",
                "direction": direction,
                "prev_level": round(prev_y, 3),
                "curr_level": round(curr_y, 3),
                "bps_change": round(bps_change, 1),
                "detected_at": now_iso,
                "implication": "Headwind for gold" if direction == "UP" else "Tailwind for gold",
            })

    # Gold yield regime change
    prev_regime = prev.get("gold_yield_regime")
    curr_regime = curr.get("gold_yield_regime")
    if prev_regime and curr_regime and prev_regime != curr_regime:
        shifts.append({
            "type": "REGIME_CHANGE",
            "severity": "HIGH",
            "description": f"Gold yield regime changed: {prev_regime.upper()} → {curr_regime.upper()}",
            "prev_regime": prev_regime,
            "curr_regime": curr_regime,
            "detected_at": now_iso,
            "implication": {
                "risk_off":   "Gold bullish — yields falling, DXY rising",
                "risk_on":    "Gold bearish — yields rising, growth mode",
                "high_rates": "Strong headwind — yields above 5%",
                "neutral":    "No clear directional bias",
            }.get(curr_regime, "Regime change detected"),
        })

    return shifts


async def _push_shift_alerts(redis_client, shifts: list[dict]) -> None:
    for alert in shifts:
        try:
            await redis_client.lpush(_SHIFT_ALERTS_KEY, json.dumps(alert))
            await redis_client.ltrim(_SHIFT_ALERTS_KEY, 0, _SHIFT_ALERTS_MAX - 1)
            await redis_client.expire(_SHIFT_ALERTS_KEY, _SHIFT_ALERTS_TTL)
            logger.warning("CROSS-ASSET SHIFT: %s — %s", alert["type"], alert["description"])
        except Exception:
            pass


async def shift_monitor_loop(redis_client, check_interval_sec: int = 300) -> None:
    """Background task: compare cross-asset snapshots every check_interval_sec.

    Publishes shift alerts to nexus:cross_asset:shift_alerts when material
    intraday moves are detected in DXY, US10Y, or gold_yield_regime.
    """
    global _PREV_SNAPSHOT
    logger.info("Cross-asset shift monitor started (interval=%ds)", check_interval_sec)

    while True:
        try:
            await asyncio.sleep(check_interval_sec)

            # Fetch current snapshot
            raw = await redis_client.get(_CROSS_ASSET_ALL_KEY)
            if not raw:
                continue
            curr = json.loads(raw)

            # Compare with previous
            if _PREV_SNAPSHOT:
                shifts = _detect_regime_shift(_PREV_SNAPSHOT, curr)
                if shifts:
                    await _push_shift_alerts(redis_client, shifts)

            _PREV_SNAPSHOT = curr

        except asyncio.CancelledError:
            logger.info("Shift monitor cancelled")
            break
        except Exception:
            logger.error("Shift monitor error", exc_info=True)


# ── Background refresh loop (called from nexus_features lifespan) ─────────────

async def cross_asset_refresh_loop(redis_client, interval_sec: int = 300) -> None:
    """Refresh DXY and US10Y every `interval_sec` seconds."""
    logger.info("cross_asset: refresh loop started (interval=%ds)", interval_sec)
    while True:
        try:
            await asyncio.sleep(interval_sec)
            # Freshness (age >= _CROSS_ASSET_TTL) already forces a re-fetch
            # attempt on the next compute.  The former "clear the cached keys"
            # step is gone on purpose: deleting them would discard the stale
            # copy kept for Yahoo outages.
            # Compute and cache a fresh summary (daily gold/DXY closes are
            # resolved internally, so the correlation is computed here too)
            await compute_cross_asset_features("XAUUSD", redis_client)
            logger.debug("cross_asset: refreshed DXY/US10Y")
        except asyncio.CancelledError:
            break
        except Exception:
            logger.warning("cross_asset: refresh error", exc_info=True)
