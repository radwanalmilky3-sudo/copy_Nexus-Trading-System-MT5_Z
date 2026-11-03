"""
Asset Correlation Matrix — rolling 7d / 30d Pearson correlations.

Default assets: XAUUSD (GC=F), BTCUSD (BTC-USD), OIL/WTI (CL=F), SPX (^GSPC).
Configurable via nexus:runtime:settings → corr_assets  (dict {name: ticker}).
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ── System-wide alert publisher ───────────────────────────────────────────────
_SYS_ALERT_LOG = "nexus:alerts:log"
_SYS_ALERT_PUB = "nexus:alerts:pubsub"
# Ordered-set of already-published divergence keys.  FIFO eviction (rather than
# a wholesale clear) keeps the dedupe memory bounded without re-arming every
# previously published alert at once.
_published_div_keys: "OrderedDict[str, None]" = OrderedDict()


async def _publish_system_alert(r, alert_type: str, message: str, severity: str = "INFO", **kw) -> None:
    payload = json.dumps({
        "type": alert_type, "message": message, "severity": severity,
        "ts": datetime.now(timezone.utc).isoformat(), **kw,
    })
    try:
        await r.lpush(_SYS_ALERT_LOG, payload)
        await r.ltrim(_SYS_ALERT_LOG, 0, 49)
        await r.expire(_SYS_ALERT_LOG, 86400)
        await r.publish(_SYS_ALERT_PUB, payload)
    except Exception as exc:
        logger.debug("_publish_system_alert failed: %s", exc)


_CORR_KEY = "nexus:correlation:matrix"
_CORR_REFRESH_SEC = 300  # 5 minutes default

_DEFAULT_ASSETS: dict[str, str] = {
    "XAUUSD": "GC=F",
    "BTCUSD": "BTC-USD",
    "OIL":    "CL=F",
    "SPX":    "^GSPC",
}

_WINDOWS = {"7d": 7, "30d": 30}

# Historical "normal" correlation ranges (lo, hi) used for divergence detection.
# Pairs not listed here are monitored only for 7d-vs-30d shift, not norm violation.
_NORM_RANGES: dict[tuple[str, str], tuple[float, float]] = {
    ("XAUUSD", "BTCUSD"): (-0.1,  0.5),
    ("XAUUSD", "OIL"):    ( 0.0,  0.6),
    ("XAUUSD", "SPX"):    (-0.4,  0.2),
    ("BTCUSD", "OIL"):    (-0.1,  0.5),
    ("BTCUSD", "SPX"):    ( 0.2,  0.8),
    ("OIL",    "SPX"):    ( 0.1,  0.6),
}


# ── Price fetching ────────────────────────────────────────────────────────────

def _fetch_prices_sync(assets: dict[str, str], window_days: int = 40):
    """Download daily closing prices via yfinance. Returns pd.DataFrame or None."""
    try:
        import pandas as pd
        import yfinance as yf

        tickers = list(assets.values())
        period = f"{window_days + 10}d"
        raw = yf.download(tickers, period=period, interval="1d", progress=False, auto_adjust=True)
        if raw is None or raw.empty:
            return None

        # yfinance multi-ticker → MultiIndex columns (metric, ticker)
        if isinstance(raw.columns, pd.MultiIndex):
            closes = raw["Close"].copy()
        else:
            # Single ticker — wrap in named column
            closes = raw[["Close"]].copy()
            closes.columns = tickers

        # Rename tickers → asset names
        ticker_to_name = {v: k for k, v in assets.items()}
        closes = closes.rename(columns=ticker_to_name)
        known = [c for c in closes.columns if c in assets]
        if not known:
            return None
        closes = closes[known].dropna(how="all")
        # Restrict to dates where *every* asset actually printed a close.
        # bfill() would backfill future prices into earlier dates (lookahead),
        # and mixing a 7×24 crypto series with equity business days injects
        # artificial zero-return rows that attenuate the correlation.
        closes = closes.dropna(how="any")
        return closes
    except Exception as exc:
        logger.warning("correlation._fetch_prices error: %s", exc)
        return None


# ── Matrix computation ────────────────────────────────────────────────────────

def _compute_corr_matrix(prices, window: int) -> dict[str, dict[str, float | None]]:
    """Pearson correlation on daily pct_change for the last `window` rows.

    Prices are expected to be a common-calendar frame (only dates where every
    asset printed a real close).  pct_change may still produce ±Inf on a zero
    price, so those are coerced to NaN and dropped before correlating.
    """
    subset = prices.tail(window) if len(prices) >= window else prices
    rets = subset.pct_change().replace([np.inf, -np.inf], np.nan).dropna(how="any")
    if rets.empty or len(rets) < 3:
        return {}
    corr = rets.corr()
    result: dict[str, dict[str, float | None]] = {}
    for a in corr.index:
        result[str(a)] = {}
        for b in corr.columns:
            val = corr.loc[a, b]
            result[str(a)][str(b)] = round(float(val), 3) if np.isfinite(val) else None
    return result


# ── Task 8: windowed returns correlation + lag signals ───────────────────────

WINDOW_SIZES: tuple[int, ...] = (20, 60, 120)
MIN_CORR_SAMPLES = 10
CORRELATION_DISCLAIMER = (
    "Correlación observada sobre retornos sincronizados; "
    "no es causa ni garantía de predicción."
)


def _synchronized_returns(prices):
    """pct_change on the common-calendar frame; first row and any remaining
    non-finite values are dropped so every pair shares the same timestamps.
    fill_method=None: never pad/forward-fill prices (that would invent rows)."""
    rets = prices.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    return rets.dropna(how="any")


def compute_windowed_correlation(
    prices,
    windows: tuple[int, ...] = WINDOW_SIZES,
    min_samples: int = MIN_CORR_SAMPLES,
) -> dict[str, dict]:
    """Rolling Pearson correlation from synchronized RETURNS (never levels).

    Each window carries honest per-pair metadata: sample_count, coverage,
    constant_series, insufficient_data.  When the math cannot be trusted the
    correlation is None plus its flag — never a fabricated 0.
    """
    out: dict[str, dict] = {}
    assets = [str(c) for c in prices.columns]
    for w in windows:
        subset = prices.tail(w) if len(prices) >= w else prices
        rets = _synchronized_returns(subset)
        n = int(len(rets))
        expected = max(int(w) - 1, 1)
        coverage = round(min(1.0, n / expected), 3)
        matrix: dict[str, dict[str, float | None]] = {a: {} for a in assets}
        pairs: dict[str, dict] = {}
        for i, a in enumerate(assets):
            for b in assets[i + 1:]:
                sa = rets[a].to_numpy(dtype=float) if a in rets else np.array([])
                sb = rets[b].to_numpy(dtype=float) if b in rets else np.array([])
                insufficient = n < min_samples
                constant = bool(
                    n == 0
                    or (sa.size and np.std(sa) == 0)
                    or (sb.size and np.std(sb) == 0)
                )
                corr: float | None = None
                if not insufficient and not constant:
                    val = float(np.corrcoef(sa, sb)[0, 1])
                    if np.isfinite(val):
                        corr = round(val, 3)
                pairs[f"{a}/{b}"] = {
                    "corr": corr,
                    "sample_count": n,
                    "coverage": coverage,
                    "constant_series": constant,
                    "insufficient_data": insufficient,
                }
                matrix[a][b] = corr
                matrix[b][a] = corr
        for a in assets:
            matrix[a][a] = None
        out[str(int(w))] = {
            "window": int(w),
            "matrix": matrix,
            "pairs": pairs,
            "sample_count": n,
            "coverage": coverage,
        }
    return out


def _to_timestamp(value) -> Any:
    import pandas as pd

    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return ts


def _pearson(a, b) -> float | None:
    if len(a) < MIN_CORR_SAMPLES or len(b) < MIN_CORR_SAMPLES:
        return None
    if np.std(a) == 0 or np.std(b) == 0:
        return None
    val = float(np.corrcoef(a, b)[0, 1])
    return round(val, 3) if np.isfinite(val) else None


def compute_lag_signals(
    prices,
    as_of=None,
    max_lag: int = 6,
    min_samples: int = MIN_CORR_SAMPLES,
    reference: str = "XAUUSD",
) -> dict:
    """Lead/lag of synchronized returns versus the reference asset (gold).

    Direction semantics, fixed by tests/test_features/test_correlation_windows_lag.py:
    - X_LEADS: the pair member moved first; the reference copied it
      `lag_candles` candles later (corr(X[t], ref[t+L]) maximal at L>0).
    - REFERENCE_LEADS: gold moved first; the member followed.
    - IN_SYNC: best alignment at lag 0.

    as_of truncates the frame to timestamps <= as_of BEFORE any return is
    computed, so the future is never read.
    """
    import pandas as pd

    frame = prices
    as_of_iso: str | None = None
    if as_of is not None:
        ts = _to_timestamp(as_of)
        idx = pd.to_datetime(frame.index)
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
        frame = frame.loc[idx <= ts]
        as_of_iso = ts.isoformat()

    ref = str(reference)
    if ref not in frame.columns or frame.empty:
        return {
            "reference": ref,
            "max_lag": int(max_lag),
            "as_of": as_of_iso,
            "reference_missing": ref not in frame.columns,
            "pairs": [],
            "basis": "synchronized_returns",
            "disclaimer": CORRELATION_DISCLAIMER,
        }

    rets = _synchronized_returns(frame)
    ret_ref = rets[ref].to_numpy(dtype=float) if ref in rets else np.array([])
    n = int(len(ret_ref))
    pairs: list[dict] = []
    for col in frame.columns:
        name = str(col)
        if name == ref:
            continue
        ret_x = rets[col].to_numpy(dtype=float) if col in rets else np.array([])
        base = {
            "pair": f"{name}/{ref}",
            "as_of": as_of_iso,
            "sample_count": n,
        }
        if n < min_samples or ret_x.size != n:
            pairs.append({
                **base,
                "direction": None,
                "lead_asset": None,
                "lag_candles": None,
                "best_corr": None,
                "insufficient_data": True,
            })
            continue
        candidates: list[tuple[float, int, str]] = []  # (|corr|, lag, direction)
        corr_at: dict[tuple[str, int], float | None] = {}
        for lag in range(0, int(max_lag) + 1):
            fwd = _pearson(ret_x[: n - lag] if lag else ret_x, ret_ref[lag:] if lag else ret_ref)
            corr_at[("X_LEADS", lag)] = fwd
            if fwd is not None:
                candidates.append((abs(fwd), lag, "X_LEADS"))
        for lag in range(1, int(max_lag) + 1):
            rev = _pearson(ret_ref[: n - lag], ret_x[lag:])
            corr_at[("REFERENCE_LEADS", lag)] = rev
            if rev is not None:
                candidates.append((abs(rev), lag, "REFERENCE_LEADS"))
        if not candidates:
            pairs.append({
                **base,
                "direction": None,
                "lead_asset": None,
                "lag_candles": None,
                "best_corr": None,
                "insufficient_data": True,
            })
            continue
        # Tie-break: larger |corr|, then smaller lag, then in-sync/forward first.
        best_abs, best_lag, best_dir = max(
            candidates,
            key=lambda c: (c[0], -c[1], 1 if c[2] == "REFERENCE_LEADS" else 0),
        )
        corr_val = corr_at[(best_dir, best_lag)]
        if best_dir == "X_LEADS" and best_lag == 0:
            direction, lead, lag_out = "IN_SYNC", None, 0
        elif best_dir == "X_LEADS":
            direction, lead, lag_out = "X_LEADS", name, best_lag
        else:
            direction, lead, lag_out = "REFERENCE_LEADS", ref, best_lag
        pairs.append({
            **base,
            "direction": direction,
            "lead_asset": lead,
            "lag_candles": lag_out,
            "best_corr": corr_val,
            "sample_count": n - lag_out,
            "insufficient_data": False,
        })
    return {
        "reference": ref,
        "max_lag": int(max_lag),
        "as_of": as_of_iso,
        "reference_missing": False,
        "pairs": pairs,
        "basis": "synchronized_returns",
        "disclaimer": CORRELATION_DISCLAIMER,
    }


# ── Divergence detection ──────────────────────────────────────────────────────

def _detect_divergences(
    mat7: dict[str, dict],
    mat30: dict[str, dict],
    threshold: float = 0.25,
) -> list[dict]:
    """Flag pairs where 7d correlation deviates significantly from 30d baseline."""
    divs: list[dict] = []
    assets = list(mat7.keys())

    for i, a in enumerate(assets):
        for b in assets[i + 1:]:
            c7  = mat7.get(a, {}).get(b)
            c30 = mat30.get(a, {}).get(b)
            if c7 is None or c30 is None:
                continue

            shift = round(abs(c7 - c30), 3)
            norm  = _NORM_RANGES.get((a, b)) or _NORM_RANGES.get((b, a))
            out_of_norm = norm and (c7 < norm[0] - 0.15 or c7 > norm[1] + 0.15)

            if shift >= threshold or out_of_norm:
                direction = "creciente" if c7 > c30 else "decreciente"
                severity  = "HIGH" if (shift > 0.45 or out_of_norm) else "MEDIUM"
                divs.append({
                    "pair":        f"{a}/{b}",
                    "corr_7d":     c7,
                    "corr_30d":    c30,
                    "shift":       shift,
                    "severity":    severity,
                    "description": f"{a}/{b}: correlación {direction} ({c30:+.2f}→{c7:+.2f})",
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                })

    return sorted(divs, key=lambda x: x["shift"], reverse=True)


# ── Redis helpers ─────────────────────────────────────────────────────────────

async def _get_assets(redis_client) -> dict[str, str]:
    """Read corr_assets from runtime settings; fall back to defaults."""
    try:
        raw = await redis_client.get("nexus:runtime:settings")
        if raw:
            settings = json.loads(raw)
            custom = settings.get("corr_assets")
            if isinstance(custom, dict) and custom:
                return custom
    except Exception:
        pass
    return dict(_DEFAULT_ASSETS)


async def _get_threshold(redis_client) -> float:
    try:
        raw = await redis_client.get("nexus:runtime:settings")
        if raw:
            s = json.loads(raw)
            return float(s.get("corr_divergence_threshold", 0.25))
    except Exception:
        pass
    return 0.25


# ── Core refresh ──────────────────────────────────────────────────────────────

async def _run_correlation(redis_client) -> None:
    try:
        assets    = await _get_assets(redis_client)
        threshold = await _get_threshold(redis_client)
        loop      = asyncio.get_event_loop()

        prices = await loop.run_in_executor(None, _fetch_prices_sync, assets, 40)
        if prices is None or prices.empty:
            logger.warning("correlation: no price data available, skipping update")
            return

        mat7  = _compute_corr_matrix(prices, 7)
        mat30 = _compute_corr_matrix(prices, 30)
        divs  = _detect_divergences(mat7, mat30, threshold)
        windows = compute_windowed_correlation(prices)
        lag = compute_lag_signals(prices)

        payload = {
            "assets":      list(assets.keys()),
            "matrices":    {"7d": mat7, "30d": mat30},
            "windows":     windows,
            "lag_signals": lag["pairs"],
            "lag_meta":    {k: lag[k] for k in ("reference", "max_lag", "as_of", "basis", "disclaimer")},
            "basis":       "synchronized_returns",
            "disclaimer":  CORRELATION_DISCLAIMER,
            "divergences": divs,
            "updated_at":  datetime.now(timezone.utc).isoformat(),
        }
        await redis_client.set(_CORR_KEY, json.dumps(payload), ex=3600)
        logger.debug(
            "correlation matrix updated: %d assets, %d divergences",
            len(assets), len(divs),
        )

        # Publish new HIGH divergences not yet seen this session
        global _published_div_keys
        for div in divs:
            if div["severity"] == "HIGH":
                key = f"{div['pair']}:{div['corr_7d']:.2f}"
                if key not in _published_div_keys:
                    await _publish_system_alert(
                        redis_client, "CORR_DIVERGENCE",
                        div["description"],
                        severity="HIGH",
                        pair=div["pair"],
                        corr_7d=div["corr_7d"],
                        corr_30d=div["corr_30d"],
                        shift=div["shift"],
                    )
                    _published_div_keys[key] = None
                    # FIFO eviction: bound memory without re-publishing the rest.
                    while len(_published_div_keys) > 100:
                        _published_div_keys.popitem(last=False)
    except Exception:
        logger.warning("correlation._run_correlation error", exc_info=True)


# ── Background loop ───────────────────────────────────────────────────────────

async def correlation_refresh_loop(redis_client, refresh_sec: int = _CORR_REFRESH_SEC) -> None:
    """Background task: compute correlation matrix on startup then every refresh_sec."""
    logger.info("Correlation matrix loop started (refresh=%ds)", refresh_sec)
    await _run_correlation(redis_client)
    while True:
        try:
            await asyncio.sleep(refresh_sec)
            await _run_correlation(redis_client)
        except asyncio.CancelledError:
            logger.info("Correlation loop cancelled")
            return
        except Exception:
            logger.warning("Correlation loop unexpected error", exc_info=True)
