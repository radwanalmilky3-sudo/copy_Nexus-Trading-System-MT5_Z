"""
Nexus Monitor — Performance analytics engine.

Calculates Sharpe ratio, Sortino ratio, max drawdown, profit factor,
equity curves, and daily P&L using numpy/pandas.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import structlog

from shared.models import PerformanceMetrics

log = structlog.get_logger(__name__)

_ANNUALISATION_FACTOR = 252  # trading days per year


@dataclass
class DetailedMetrics:
    total_pnl: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    # Sortino is null when the downside sample is empty/insufficient — a
    # computed 0.0 would falsely read as "measured, and flat".  The explicit
    # ``sortino_available`` flag says whether the ratio is meaningful.
    sortino_ratio: float | None = None
    sortino_available: bool = False
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_rr: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    avg_duration_min: float = 0.0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    expectancy: float = 0.0


def _finite_float(value: Any) -> float | None:
    """Coerce to float, returning None for missing/invalid/non-finite values."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


class PerformanceAnalyzer:
    """Computes comprehensive trading performance metrics."""

    def __init__(self, risk_free_rate: float = 0.0) -> None:
        self._risk_free = risk_free_rate

    # ── Master Calculation ────────────────────────────────────────────────

    def calculate_metrics(self, trades: list[dict[str, Any]]) -> DetailedMetrics:
        if not trades:
            return DetailedMetrics()

        # Drop rows with missing/invalid/non-finite pnl instead of silently
        # aggregating them as 0 — a malformed trade must not dilute the P&L,
        # win rate or drawdown with a fabricated flat result.
        pnls: list[float] = []
        for trade in trades:
            if not isinstance(trade, dict):
                continue
            pnl = _finite_float(trade.get("pnl_usd"))
            if pnl is not None:
                pnls.append(pnl)

        if not pnls:
            log.warning("performance.no_valid_trades", total_rows=len(trades))
            return DetailedMetrics()

        pnl_arr = np.array(pnls, dtype=np.float64)

        wins = pnl_arr[pnl_arr > 0]
        losses = pnl_arr[pnl_arr <= 0]

        total_pnl = float(np.sum(pnl_arr))
        total_trades = len(pnls)
        winning = len(wins)
        losing = len(losses)
        win_rate = (winning / total_trades * 100) if total_trades > 0 else 0
        avg_win = float(np.mean(wins)) if len(wins) > 0 else 0
        avg_loss = float(np.mean(losses)) if len(losses) > 0 else 0

        equity = self.equity_curve(trades)
        eq_values = equity.values if isinstance(equity, pd.Series) else np.cumsum(pnl_arr)
        max_dd = self.calculate_max_drawdown(eq_values)

        rrs = [
            rr for t in trades
            if isinstance(t, dict) and (rr := _finite_float(t.get("rr_ratio"))) is not None
        ]
        durations = [
            d for t in trades
            if isinstance(t, dict) and (d := _finite_float(t.get("duration"))) is not None
        ]

        daily = self.daily_pnl(trades)
        daily_returns = daily.values if isinstance(daily, pd.Series) else pnl_arr
        sharpe = self.calculate_sharpe(daily_returns, self._risk_free)
        sortino, sortino_ok = self.calculate_sortino_detailed(daily_returns)

        profit_factor = self.calculate_profit_factor(trades)
        c_wins, c_losses = self._max_consecutive(pnls)

        expectancy = (win_rate / 100 * avg_win) + ((1 - win_rate / 100) * avg_loss) if total_trades > 0 else 0

        return DetailedMetrics(
            total_pnl=round(total_pnl, 2),
            win_rate=round(win_rate, 2),
            profit_factor=round(profit_factor, 2),
            sharpe_ratio=round(sharpe, 4),
            sortino_ratio=(round(sortino, 4) if sortino_ok else None),
            sortino_available=sortino_ok,
            max_drawdown=round(max_dd, 2),
            max_drawdown_pct=round(max_dd, 2),
            total_trades=total_trades,
            winning_trades=winning,
            losing_trades=losing,
            avg_win=round(avg_win, 2),
            avg_loss=round(avg_loss, 2),
            avg_rr=round(float(np.mean(rrs)), 2) if rrs else 0,
            best_trade=round(float(np.max(pnl_arr)), 2),
            worst_trade=round(float(np.min(pnl_arr)), 2),
            avg_duration_min=round(float(np.mean(durations)), 1) if durations else 0,
            consecutive_wins=c_wins,
            consecutive_losses=c_losses,
            expectancy=round(expectancy, 2),
        )

    def to_shared_model(self, trades: list[dict[str, Any]]) -> PerformanceMetrics:
        m = self.calculate_metrics(trades)
        return PerformanceMetrics(
            total_pnl=m.total_pnl,
            win_rate=m.win_rate,
            profit_factor=m.profit_factor,
            sharpe_ratio=m.sharpe_ratio,
            max_drawdown=m.max_drawdown,
            total_trades=m.total_trades,
            avg_win=m.avg_win,
            avg_loss=m.avg_loss,
        )

    # ── Individual Metric Calculations ────────────────────────────────────

    @staticmethod
    def calculate_sharpe(returns: np.ndarray | pd.Series, risk_free: float = 0.0) -> float:
        arr = np.asarray(returns, dtype=np.float64)
        # NaN inside the series previously produced NaN out (np.std → NaN,
        # which passed the ``std == 0`` guard).  Drop non-finite points first.
        arr = arr[np.isfinite(arr)]
        if len(arr) < 2:
            return 0.0
        excess = arr - risk_free / _ANNUALISATION_FACTOR
        std = np.std(excess, ddof=1)
        if not np.isfinite(std) or std == 0:
            return 0.0
        value = float(np.mean(excess) / std * np.sqrt(_ANNUALISATION_FACTOR))
        return value if np.isfinite(value) else 0.0

    @staticmethod
    def calculate_sortino(
        returns: np.ndarray | pd.Series, risk_free: float = 0.0
    ) -> float:
        """Sortino ratio, or 0.0 when the downside sample is insufficient.

        Kept numeric for backwards compatibility; prefer
        :meth:`calculate_sortino_detailed`, which also reports whether the
        ratio is meaningful (empty/one-point downside → not available).
        """
        value, _ = PerformanceAnalyzer.calculate_sortino_detailed(returns, risk_free)
        return 0.0 if value is None else value

    @staticmethod
    def calculate_sortino_detailed(
        returns: np.ndarray | pd.Series, risk_free: float = 0.0
    ) -> tuple[float | None, bool]:
        """Return ``(sortino_ratio, available)``.

        ``available`` is False — and the ratio None — when there is no
        meaningful downside sample (fewer than two negative excess points, or
        a zero downside deviation).  Callers must surface None rather than
        substituting 0.0, which would be indistinguishable from a real,
        computed ratio.
        """
        arr = np.asarray(returns, dtype=np.float64)
        arr = arr[np.isfinite(arr)]
        if len(arr) < 2:
            return None, False
        excess = arr - risk_free / _ANNUALISATION_FACTOR
        downside = excess[excess < 0]
        if len(downside) < 2:
            return None, False
        downside_std = np.std(downside, ddof=1)
        if not np.isfinite(downside_std) or downside_std == 0:
            return None, False
        value = float(np.mean(excess) / downside_std * np.sqrt(_ANNUALISATION_FACTOR))
        if not np.isfinite(value):
            return None, False
        return value, True

    @staticmethod
    def calculate_max_drawdown(equity_curve: np.ndarray | pd.Series) -> float:
        arr = np.asarray(equity_curve, dtype=np.float64)
        arr = arr[np.isfinite(arr)]
        if len(arr) < 2:
            return 0.0
        peak = np.maximum.accumulate(arr)
        drawdown = peak - arr
        max_dd = float(np.max(drawdown))
        if not np.isfinite(max_dd):
            return 0.0
        peak_at_worst = peak[int(np.argmax(drawdown))]
        if peak_at_worst > 0:
            value = max_dd / peak_at_worst * 100
            return value if np.isfinite(value) else 0.0
        return max_dd

    @staticmethod
    def calculate_profit_factor(trades: list[dict[str, Any]]) -> float:
        gross_profit = 0.0
        gross_loss = 0.0
        for t in trades:
            if not isinstance(t, dict):
                continue
            pnl = _finite_float(t.get("pnl_usd"))
            if pnl is None:
                continue
            if pnl > 0:
                gross_profit += pnl
            elif pnl < 0:
                gross_loss += abs(pnl)
        if gross_loss == 0:
            return gross_profit if gross_profit > 0 else 0.0
        return gross_profit / gross_loss

    @staticmethod
    def calculate_win_rate(trades: list[dict[str, Any]]) -> float:
        valid = [
            t for t in trades
            if isinstance(t, dict) and _finite_float(t.get("pnl_usd")) is not None
        ]
        if not valid:
            return 0.0
        wins = sum(1 for t in valid if float(t["pnl_usd"]) > 0)
        return wins / len(valid) * 100

    # ── Time Series ───────────────────────────────────────────────────────

    @staticmethod
    def daily_pnl(trades: list[dict[str, Any]]) -> pd.Series:
        """Sum pnl by UTC close date.

        Timestamps are parsed as UTC (``utc=True``) so tz-naive and mixed-offset
        rows cannot crash the groupby or silently bucket into the wrong day.
        Unparseable timestamps fall back to per-trade pnl rather than being
        dropped from the series.
        """
        if not trades:
            return pd.Series(dtype=float)

        records = []
        fallback: list[float] = []
        for t in trades:
            if not isinstance(t, dict):
                continue
            pnl = _finite_float(t.get("pnl_usd"))
            if pnl is None:
                continue
            fallback.append(pnl)
            closed_at = t.get("closed_at")
            if closed_at is None:
                continue
            ts = pd.to_datetime(closed_at, utc=True, errors="coerce")
            if pd.isna(ts):
                continue
            records.append({"date": ts.date(), "pnl": pnl})

        if not records:
            return pd.Series(fallback, dtype=float)

        df = pd.DataFrame(records)
        daily = df.groupby("date")["pnl"].sum()
        return daily.astype(float)

    @staticmethod
    def equity_curve(trades: list[dict[str, Any]]) -> pd.Series:
        pnls = []
        for t in trades:
            if not isinstance(t, dict):
                continue
            pnl = _finite_float(t.get("pnl_usd"))
            if pnl is not None:
                pnls.append(pnl)
        cumulative = np.cumsum(pnls, dtype=np.float64)
        return pd.Series(cumulative, dtype=float)

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _max_consecutive(pnls: list[float]) -> tuple[int, int]:
        max_wins = 0
        max_losses = 0
        cur_wins = 0
        cur_losses = 0

        for pnl in pnls:
            if pnl > 0:
                cur_wins += 1
                cur_losses = 0
                max_wins = max(max_wins, cur_wins)
            else:
                cur_losses += 1
                cur_wins = 0
                max_losses = max(max_losses, cur_losses)

        return max_wins, max_losses
