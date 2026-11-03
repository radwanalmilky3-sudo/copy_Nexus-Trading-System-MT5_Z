from __future__ import annotations

import math
from collections import Counter
from typing import Any

import numpy as np
import pandas as pd

from .models import BacktestResult


def equity_frame(result: BacktestResult) -> pd.DataFrame:
    rows = [
        {
            "timestamp": point.timestamp,
            "cash": point.cash,
            "unrealized_pnl": point.unrealized_pnl,
            "equity": point.equity,
            "open_positions": point.open_positions,
            "gross_leverage": point.gross_leverage,
            "drawdown": point.drawdown,
        }
        for point in result.equity
    ]
    return pd.DataFrame(rows).set_index("timestamp") if rows else pd.DataFrame()


def trades_frame(result: BacktestResult) -> pd.DataFrame:
    return pd.DataFrame([trade.to_dict() for trade in result.trades])


def calculate_metrics(result: BacktestResult) -> dict[str, Any]:
    equity = equity_frame(result)
    trades = trades_frame(result)
    initial = float(
        result.metadata.get("initial_equity", equity["equity"].iloc[0] if len(equity) else 0)
    )
    final = float(
        result.metadata.get("final_cash", equity["equity"].iloc[-1] if len(equity) else initial)
    )
    total_return = final / initial - 1 if initial else 0.0
    years = 0.0
    if len(equity) > 1:
        years = (equity.index[-1] - equity.index[0]).total_seconds() / (365.25 * 86400)
    cagr = (final / initial) ** (1 / years) - 1 if initial > 0 and final > 0 and years > 0 else 0.0
    returns = equity["equity"].pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    if len(equity) > 1:
        median_seconds = np.median(np.diff(equity.index.view("int64"))) / 1e9
        periods_per_year = (
            min(24 * 365.25, 365.25 * 86400 / median_seconds) if median_seconds > 0 else 252
        )
    else:
        periods_per_year = 252
    volatility = float(returns.std(ddof=0) * math.sqrt(periods_per_year)) if len(returns) else 0.0
    sharpe = (
        float(returns.mean() / returns.std(ddof=0) * math.sqrt(periods_per_year))
        if len(returns) > 1 and returns.std(ddof=0) > 0
        else 0.0
    )
    downside = returns[returns < 0]
    sortino = (
        float(returns.mean() / downside.std(ddof=0) * math.sqrt(periods_per_year))
        if len(downside) > 1 and downside.std(ddof=0) > 0
        else 0.0
    )
    max_drawdown = float(equity["drawdown"].max()) if len(equity) else 0.0

    if trades.empty:
        trade_metrics = {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "average_win": 0.0,
            "average_loss": 0.0,
            "payoff_ratio": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "expectancy_r": 0.0,
            "average_holding_hours": 0.0,
            "max_holding_hours": 0.0,
            "costs": 0.0,
        }
    else:
        winners = trades.loc[trades["net_pnl"] > 0, "net_pnl"]
        losers = trades.loc[trades["net_pnl"] < 0, "net_pnl"]
        average_win = float(winners.mean()) if len(winners) else 0.0
        average_loss = float(losers.mean()) if len(losers) else 0.0
        gross_profit = float(winners.sum())
        gross_loss = abs(float(losers.sum()))
        trade_metrics = {
            "trades": int(len(trades)),
            "wins": int(len(winners)),
            "losses": int(len(losers)),
            "win_rate": float(len(winners) / len(trades)),
            "average_win": average_win,
            "average_loss": average_loss,
            "payoff_ratio": average_win / abs(average_loss) if average_loss else 0.0,
            "profit_factor": gross_profit / max(gross_loss, 1e-12) if gross_profit else 0.0,
            "expectancy": float(trades["net_pnl"].mean()),
            "expectancy_r": float(trades["r_multiple"].mean()),
            "average_holding_hours": float(trades["holding_hours"].mean()),
            "max_holding_hours": float(trades["holding_hours"].max()),
            "costs": float(trades["costs"].sum()),
        }

    rejection_counts = Counter(item.get("reason", "unknown") for item in result.rejected_signals)
    return {
        "initial_equity": initial,
        "final_equity": final,
        "total_return": total_return,
        "cagr": cagr,
        "annualized_volatility": volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "calmar": cagr / max_drawdown if max_drawdown else 0.0,
        "max_gross_leverage": float(equity["gross_leverage"].max()) if len(equity) else 0.0,
        **trade_metrics,
        "rejected_signals": len(result.rejected_signals),
        "rejection_reasons": dict(rejection_counts),
    }


def robust_screen_score(metrics: dict[str, Any], minimum_trades: int = 20) -> float:
    """Conservative ranking score; never presented as an expected return forecast."""
    if metrics["trades"] < minimum_trades:
        return -1_000.0 + metrics["trades"]
    profit_factor = min(float(metrics["profit_factor"]), 3.0)
    return float(
        0.45 * np.clip(metrics["sharpe"], -3, 3)
        + 0.25 * (profit_factor - 1)
        + 0.20 * np.clip(metrics["expectancy_r"], -2, 2)
        - 1.50 * metrics["max_drawdown"]
        - 0.10 * max(0, metrics["max_holding_hours"] / 168 - 1)
    )
