"""
StrategyEvaluator — turn a strategy spec into back-tested metrics.

The evaluator is pragmatic:
- It tries to fetch real OHLCV from nexus-data and run the
  built-in :class:`SimpleBacktester`.
- When real data is unavailable (offline dev, fresh install) it falls back
  to a deterministic synthetic price series so the dashboard still has
  meaningful, varied numbers to display.

That keeps the Strategy Lab usable on a fresh checkout without forcing the
user to wait for hours of MT5 history download.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import os
import random
from dataclasses import dataclass
from typing import Any, Sequence

import httpx
from shared.http_client import new_client
import numpy as np
import structlog

from shared.constants import SERVICE_PORTS

from .registry import StrategyRecord

logger = structlog.get_logger(__name__)

DATA_BASE = os.getenv(
    "NEXUS_DATA_URL",
    f"http://127.0.0.1:{SERVICE_PORTS['nexus-data']}",
).rstrip("/")

_PURGED_CV_FOLDS = 5
_PURGED_MIN_FOLD_BARS = 10

_TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}


@dataclass
class EvaluationResult:
    """Aggregated, dashboard-ready performance numbers."""

    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe: float = 0.0
    max_dd_pct: float = 0.0
    total_trades: int = 0
    avg_rr: float = 0.0
    net_pnl_pct: float = 0.0
    recent_results: list[bool] | None = None
    source: str = "synthetic"
    trial_family_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "sharpe": self.sharpe,
            "max_dd_pct": self.max_dd_pct,
            "total_trades": self.total_trades,
            "avg_rr": self.avg_rr,
            "net_pnl_pct": self.net_pnl_pct,
            "recent_results": self.recent_results or [],
            "source": self.source,
            "trial_family_id": self.trial_family_id,
        }


class StrategyEvaluator:
    """Evaluate a :class:`StrategyRecord` against historical OHLCV."""

    def __init__(
        self,
        *,
        symbol: str | None = None,
        timeframe: str = "M5",
        bars: int = 1500,
    ) -> None:
        self._symbol_default = symbol
        self._timeframe = timeframe
        self._bars = bars

    # ── Public API ──────────────────────────────────────────────────────────

    async def evaluate(self, record: StrategyRecord) -> EvaluationResult:
        # Only the OHLCV fetch is I/O (async). Everything after — signal
        # generation (numpy loops) and the backtest — is CPU-bound and would
        # block the event loop, which is what makes the agents service appear
        # frozen (heartbeats stop, /health and /status time out → dashboard
        # shows agents OFFLINE and everything "lags"). Offload that CPU work to
        # a worker thread so the event loop stays responsive.
        symbol = self._pick_symbol(record)
        ohlcv = await self._fetch_ohlcv(symbol, self._timeframe, self._bars)
        return await asyncio.to_thread(self._evaluate_compute, record, symbol, ohlcv)

    def _evaluate_compute(
        self, record: StrategyRecord, symbol: str, ohlcv: "np.ndarray | None",
    ) -> EvaluationResult:
        """Synchronous CPU portion of evaluate() — run inside a worker thread."""
        signals, confidences = self._signals_for(record, ohlcv) if ohlcv is not None else (None, None)

        if ohlcv is not None and signals is not None and signals.any():
            pip_val = _pip_value_for(symbol)
            # Prefer SL/TP-aware backtester (matches live execution)
            try:
                from services.nexus_ml.traders.sl_tp_backtester import SLTPBacktester
                sl_pips, tp_pips = _atr_sl_tp_pips(
                    ohlcv, pip_val, sl_mult=0.75, tp_mult=1.8,
                )
                bars_per_year = 252 * 24 * 12 if self._timeframe == "M5" else 252 * 24 * 4
                sltp_bt = SLTPBacktester(
                    spread_pips=1.5,
                    pip_value=pip_val,
                    initial_capital=10_000.0,
                    risk_per_trade=0.01,
                    max_hold_bars=12,
                    bars_per_year=bars_per_year,
                )
                windows = _purged_fold_windows(
                    len(ohlcv), _PURGED_CV_FOLDS, self._embargo_bars(record),
                )
                if windows:
                    purged = self._purged_cv_metrics(
                        sltp_bt, record, ohlcv, signals,
                        sl_pips, tp_pips, confidences, windows,
                    )
                    if purged is not None and purged.total_trades >= 5:
                        purged.source = "sltp_backtester"
                        return purged
                result = sltp_bt.backtest(signals, sl_pips, tp_pips, ohlcv, confidences)
                metrics = self._from_sltp_backtester(result)
                if metrics.total_trades >= 5:
                    metrics.source = "sltp_backtester"
                    return metrics
            except Exception:
                logger.warning("SLTPBacktester failed, trying SimpleBacktester", exc_info=True)

            try:
                from services.nexus_ml.backtester import SimpleBacktester
                bt = SimpleBacktester(
                    spread_pips=1.5,
                    pip_value=pip_val,
                    initial_capital=10_000.0,
                    risk_per_trade=0.02,
                    bars_per_year=252 * 24 * 12,
                    max_hold_bars=12,
                )
                result = bt.backtest(signals, ohlcv, confidences)
                metrics = self._from_backtester(result, symbol)
                if metrics.total_trades >= 5:
                    metrics.source = "backtester"
                    return metrics
            except Exception:
                pass

        allow_synthetic = os.getenv("NEXUS_ALLOW_SYNTHETIC_METRICS", "0").lower() in ("1", "true")
        if allow_synthetic:
            return self._synthetic_metrics(record)
        return EvaluationResult(source="no_data")

    # ── OHLCV fetch ─────────────────────────────────────────────────────────

    async def _fetch_ohlcv(
        self, symbol: str, timeframe: str, bars: int,
    ) -> np.ndarray | None:
        # Try the nexus-data REST API first
        url = f"{DATA_BASE}/api/data/ohlcv/{symbol}/{timeframe}?limit={bars}"
        data = None
        try:
            async with new_client(timeout=15) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
        except Exception:
            pass

        # Fallback: read directly from Redis cache (written by nexus-data OHLCV publisher)
        if not data or not isinstance(data, list) or len(data) < 50:
            try:
                import redis.asyncio as aioredis
                import json
                redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
                r = aioredis.from_url(redis_url, decode_responses=True)
                raw = await r.get(f"nexus:ohlcv:{symbol}:{timeframe}")
                await r.aclose()
                if raw:
                    data = json.loads(raw)
            except Exception:
                pass

        if not isinstance(data, list) or len(data) < 50:
            return None

        try:
            o = np.asarray([float(d.get("open", 0)) for d in data])
            h = np.asarray([float(d.get("high", 0)) for d in data])
            l = np.asarray([float(d.get("low", 0)) for d in data])
            c = np.asarray([float(d.get("close", 0)) for d in data])
            v = np.asarray([float(d.get("volume", 0)) for d in data])
        except Exception:
            return None

        if len(c) < 50 or not np.all(np.isfinite(c)):
            return None

        return np.stack([o, h, l, c, v], axis=1)

    # ── Signal generation ───────────────────────────────────────────────────

    def _signals_for(
        self, record: StrategyRecord, ohlcv: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Map a strategy *type* to a deterministic signal generator."""
        n = len(ohlcv)
        c = ohlcv[:, 3]
        h = ohlcv[:, 1]
        l = ohlcv[:, 2]
        v = ohlcv[:, 4]
        signals = np.zeros(n, dtype=int)
        conv = np.full(n, 0.6)

        ttype = (record.type or "").lower()

        if "ema" in ttype or "trend" in ttype:
            ema9 = _ema(c, 9)
            ema21 = _ema(c, 21)
            ema50 = _ema(c, 50)
            for i in range(50, n):
                if ema9[i] > ema21[i] > ema50[i] and ema9[i - 1] <= ema21[i - 1]:
                    signals[i] = 1
                    conv[i] = 0.7
                elif ema9[i] < ema21[i] < ema50[i] and ema9[i - 1] >= ema21[i - 1]:
                    signals[i] = -1
                    conv[i] = 0.7
        elif "session" in ttype or "breakout" in ttype:
            window = 20
            for i in range(window + 1, n):
                hi = h[i - window : i].max()
                lo = l[i - window : i].min()
                if c[i] > hi:
                    signals[i] = 1
                elif c[i] < lo:
                    signals[i] = -1
        elif "mean" in ttype or "reversion" in ttype or "s/r" in ttype or "bounce" in ttype:
            window = 30
            mean = _rolling_mean(c, window)
            std = _rolling_std(c, window)
            for i in range(window, n):
                if std[i] <= 0:
                    continue
                z = (c[i] - mean[i]) / std[i]
                vol_avg = v[max(0, i - 20) : i].mean() if i > 0 else 0
                vol_ok = vol_avg > 0 and v[i] >= vol_avg * 1.3
                if z < -1.6 and vol_ok:
                    signals[i] = 1
                    conv[i] = 0.65
                elif z > 1.6 and vol_ok:
                    signals[i] = -1
                    conv[i] = 0.65
        else:
            # generic momentum fallback
            mom = np.zeros(n)
            mom[10:] = c[10:] - c[:-10]
            for i in range(10, n):
                if mom[i] > 0 and c[i] > c[i - 1]:
                    signals[i] = 1
                elif mom[i] < 0 and c[i] < c[i - 1]:
                    signals[i] = -1

        # Ensure not too dense (limit to ~one signal per 3 bars on avg)
        if signals.any() and (signals != 0).sum() > n // 3:
            mask = np.zeros(n, dtype=bool)
            mask[::3] = True
            signals = np.where(mask, signals, 0)
        return signals, conv

    # ── Backtester output → metrics ─────────────────────────────────────────

    def _from_sltp_backtester(self, result: Any) -> EvaluationResult:
        recent = [bool(t.get("pnl_pips", 0) > 0) for t in result.trade_log[-20:]]
        return EvaluationResult(
            win_rate=round(float(result.win_rate), 4),
            profit_factor=round(float(result.profit_factor), 4),
            sharpe=round(float(result.sharpe_ratio), 4),
            max_dd_pct=round(abs(float(result.max_drawdown)) * 100.0, 3),
            total_trades=int(result.total_trades),
            avg_rr=round(float(result.avg_rr), 3),
            net_pnl_pct=round(float(result.total_return) * 100.0, 3),
            recent_results=recent,
        )

    def _from_backtester(self, result: Any, symbol: str) -> EvaluationResult:
        win_rate = float(result.win_rate)
        pf = float(result.profit_factor)
        sh = float(result.sharpe_ratio)
        dd = abs(float(result.max_drawdown) * 100.0)
        trades = int(result.total_trades)
        recent = []
        for trade in result.trade_log[-20:]:
            recent.append(bool(trade.get("pnl_usd", 0) > 0))
        net_pnl = float(result.total_return * 100.0)

        avg_win = abs(float(result.avg_win or 0))
        avg_loss = abs(float(result.avg_loss or 0))
        avg_rr = (avg_win / avg_loss) if avg_loss > 0 else 0.0

        return EvaluationResult(
            win_rate=round(win_rate, 4),
            profit_factor=round(pf, 4),
            sharpe=round(sh, 4),
            max_dd_pct=round(dd, 3),
            total_trades=trades,
            avg_rr=round(avg_rr, 3),
            net_pnl_pct=round(net_pnl, 3),
            recent_results=recent,
        )

    # ── Purged cross-validation (Phase 5ج) ───────────────────────────────────

    def _embargo_bars(self, record: StrategyRecord) -> int:
        """Fold-edge purge width in bars.

        Uses ``record.max_holding_hours`` when available (converted to bars
        for the current timeframe); otherwise the SLTPBacktester's
        ``max_hold_bars=12`` used further below.
        """
        hours = getattr(record, "max_holding_hours", None)
        if isinstance(hours, (int, float)) and hours > 0:
            minutes = _TF_MINUTES.get(self._timeframe.upper(), 5)
            return max(1, int(math.ceil(float(hours) * 60.0 / minutes)))
        return 12

    def _purged_cv_metrics(
        self,
        sltp_bt: Any,
        record: StrategyRecord,
        ohlcv: np.ndarray,
        signals: np.ndarray,
        sl_pips: np.ndarray,
        tp_pips: np.ndarray,
        confidences: np.ndarray,
        windows: list[tuple[int, int]],
    ) -> EvaluationResult | None:
        """Backtest each purged fold and disclose the fold-level family.

        Every fold with trades contributes a sign-test p-value; the family is
        recorded in the trial registry so promotion can verify the trial
        universe was declared.  Returns None on any fold failure so the
        caller keeps the legacy single-window path as fallback.
        """
        fold_pnl: list[list[float]] = []
        fold_results: list[Any] = []
        try:
            for start, end in windows:
                result = sltp_bt.backtest(
                    signals[start:end], sl_pips[start:end], tp_pips[start:end],
                    ohlcv[start:end], confidences[start:end],
                )
                fold_results.append(result)
                fold_pnl.append([float(t.get("pnl_pips", 0.0)) for t in result.trade_log])
        except Exception:
            logger.warning("purged_cv.fold_failed, falling back to single window", exc_info=True)
            return None
        metrics = self._aggregate_fold_results(fold_results)
        metrics.trial_family_id = _disclose_fold_family(record, fold_pnl)
        return metrics

    def _aggregate_fold_results(self, results: list[Any]) -> EvaluationResult:
        """Honest aggregation of per-fold SLTPBacktestResult trade outcomes."""
        pnls = [float(t.get("pnl_pips", 0.0)) for r in results for t in r.trade_log]
        trades = len(pnls)
        if trades == 0:
            return EvaluationResult()
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        gross_win = math.fsum(wins)
        gross_loss = -math.fsum(losses)
        if gross_loss > 0:
            pf = min(9.99, gross_win / gross_loss)
        else:
            pf = 9.99 if gross_win > 0 else 0.0
        avg_win = gross_win / len(wins) if wins else 0.0
        avg_loss = gross_loss / len(losses) if losses else 0.0
        sharpe = math.fsum(float(r.sharpe_ratio) for r in results) / max(len(results), 1)
        dd = max((abs(float(r.max_drawdown)) for r in results), default=0.0)
        net = math.fsum(float(r.total_return) for r in results)
        recent = [p > 0 for p in pnls[-20:]]
        return EvaluationResult(
            win_rate=round(len(wins) / trades, 4),
            profit_factor=round(pf, 4),
            sharpe=round(float(sharpe), 4),
            max_dd_pct=round(dd * 100.0, 3),
            total_trades=trades,
            avg_rr=round((avg_win / avg_loss) if avg_loss > 0 else 0.0, 3),
            net_pnl_pct=round(net * 100.0, 3),
            recent_results=recent,
        )

    # ── Synthetic fallback ──────────────────────────────────────────────────

    def _synthetic_metrics(self, record: StrategyRecord) -> EvaluationResult:
        """Deterministic, varied metrics seeded by the strategy id.

        Used when historical OHLCV is unavailable (offline runs, fresh
        install).  Numbers are realistic but clearly tagged ``synthetic``.
        """
        seed = int(hashlib.sha1(record.id.encode()).hexdigest(), 16) % (2**32)
        rng = random.Random(seed)

        # Bias by strategy type so the values feel right
        ttype = (record.type or "").lower()
        if "trend" in ttype or "ema" in ttype:
            base_win, base_pf = 0.58, 1.7
        elif "session" in ttype or "breakout" in ttype:
            base_win, base_pf = 0.52, 1.55
        elif "reversion" in ttype or "bounce" in ttype:
            base_win, base_pf = 0.66, 2.0
        else:
            base_win, base_pf = 0.55, 1.5

        win = round(min(0.85, max(0.40, base_win + rng.uniform(-0.05, 0.08))), 4)
        pf = round(min(3.5, max(0.6, base_pf + rng.uniform(-0.4, 0.7))), 4)
        sh = round(min(3.0, max(0.2, pf * 0.9 + rng.uniform(-0.4, 0.4))), 4)
        dd = round(max(2.5, min(22.0, 18 - pf * 4 + rng.uniform(-2, 4))), 3)
        trades = rng.randint(40, 220)
        avg_rr = round(min(3.5, max(0.8, (pf - 0.4) + rng.uniform(-0.2, 0.3))), 3)
        net = round((pf - 1) * trades * 0.18 + rng.uniform(-3, 5), 3)

        recent: list[bool] = []
        for _ in range(20):
            recent.append(rng.random() < win)

        return EvaluationResult(
            win_rate=win,
            profit_factor=pf,
            sharpe=sh,
            max_dd_pct=dd,
            total_trades=trades,
            avg_rr=avg_rr,
            net_pnl_pct=net,
            recent_results=recent,
            source="synthetic",
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _pick_symbol(self, record: StrategyRecord) -> str:
        if self._symbol_default:
            return self._symbol_default
        if record.pairs:
            return record.pairs[0].replace("/", "").upper()
        return os.getenv("NEXUS_RESEARCH_SYMBOL", "XAUUSD").upper()


# ── Purged CV + trial disclosure (Phase 5ج) ─────────────────────────────────

def _purged_fold_windows(n_bars: int, n_folds: int, embargo_bars: int) -> list[tuple[int, int]]:
    """Contiguous purged-fold validation windows (label-end purge + embargo).

    A trade opened at bar *t* can stay open for up to ``embargo_bars`` bars,
    so every interior fold edge drops that many bars on both sides: the label
    window of the last eligible bar never straddles a boundary.  Returns []
    when the series is too short — callers must keep the legacy
    single-window path as fallback (existing behaviour is never replaced).
    """
    if n_folds < 2 or n_bars <= 0 or embargo_bars < 0:
        return []
    fold_size = n_bars // n_folds
    if fold_size <= 2 * embargo_bars + _PURGED_MIN_FOLD_BARS:
        return []
    windows: list[tuple[int, int]] = []
    for i in range(n_folds):
        raw_start = i * fold_size
        raw_end = (i + 1) * fold_size if i < n_folds - 1 else n_bars
        start = raw_start + (embargo_bars if i > 0 else 0)
        end = raw_end - (embargo_bars if i < n_folds - 1 else 0)
        if end - start >= _PURGED_MIN_FOLD_BARS:
            windows.append((start, end))
    return windows


def _sign_test_p_value(pnls: Sequence[float]) -> float | None:
    """Two-sided exact sign test of P(win) = 0.5 over nonzero per-trade pnl."""
    n = sum(1 for p in pnls if p != 0)
    if n == 0:
        return None
    wins = sum(1 for p in pnls if p > 0)
    tail_k = min(wins, n - wins)
    tail = math.fsum(math.comb(n, k) for k in range(tail_k + 1)) / (2 ** n)
    return min(1.0, 2.0 * tail)


def _disclose_fold_family(record: StrategyRecord, fold_pnl: list[list[float]]) -> str | None:
    """Disclose the fold-level hypothesis family in the trial registry (Phase 5ج).

    Each fold with at least one non-flat trade contributes a sign-test
    p-value; the family id is unique per evaluation run so re-runs are
    disclosed as fresh families instead of silently reusing an old one.
    Returns None when no fold produced a testable hypothesis.
    """
    p_values = [p for p in (_sign_test_p_value(pnls) for pnls in fold_pnl) if p is not None]
    if not p_values:
        return None
    digest = hashlib.sha1(
        f"{record.id}:{len(fold_pnl)}:".encode() + os.urandom(8),
    ).hexdigest()[:16]
    family_id = f"eval:{record.id}:{digest}"
    try:
        from services.nexus_data.trial_registry import record_family
        record_family(family_id, p_values, method="bh")
    except Exception:
        logger.warning(
            "trial_registry unavailable; family stays undisclosed", family_id=family_id, exc_info=True,
        )
    return family_id


# ── Tiny numeric helpers (avoid pandas dependency in this hot path) ──────────

def _ema(values: np.ndarray, span: int) -> np.ndarray:
    if span <= 1:
        return values.copy()
    alpha = 2.0 / (span + 1.0)
    out = np.zeros_like(values, dtype=float)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def _rolling_mean(values: np.ndarray, window: int) -> np.ndarray:
    if window <= 1:
        return values.copy()
    out = np.zeros_like(values, dtype=float)
    csum = np.cumsum(np.insert(values, 0, 0.0))
    for i in range(len(values)):
        start = max(0, i - window + 1)
        out[i] = (csum[i + 1] - csum[start]) / (i + 1 - start)
    return out


def _rolling_std(values: np.ndarray, window: int) -> np.ndarray:
    out = np.zeros_like(values, dtype=float)
    for i in range(len(values)):
        start = max(0, i - window + 1)
        chunk = values[start : i + 1]
        out[i] = float(chunk.std()) if len(chunk) > 1 else 0.0
    return out


def _atr_sl_tp_pips(
    ohlcv: np.ndarray,
    pip_value: float,
    *,
    sl_mult: float = 0.75,
    tp_mult: float = 1.8,
    period: int = 14,
) -> tuple[np.ndarray, np.ndarray]:
    """Per-bar SL/TP distances in pips from ATR (matches live SLTP calculator)."""
    n = len(ohlcv)
    h = ohlcv[:, 1]
    l = ohlcv[:, 2]
    c = ohlcv[:, 3]
    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))

    atr = np.zeros(n, dtype=float)
    if n >= period:
        atr[period - 1] = tr[:period].mean()
        for i in range(period, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
        atr[: period - 1] = atr[period - 1]
    else:
        atr[:] = tr.mean() if n else 1.0

    atr_pips = np.maximum(atr / pip_value, 1.0)
    sl_pips = np.maximum(atr_pips * sl_mult, 5.0)
    tp_pips = np.maximum(atr_pips * tp_mult, 10.0)
    return sl_pips, tp_pips


def _pip_value_for(symbol: str) -> float:
    from shared.asset_specs import get_pip_size
    return get_pip_size(symbol)


__all__ = ["EvaluationResult", "StrategyEvaluator"]
