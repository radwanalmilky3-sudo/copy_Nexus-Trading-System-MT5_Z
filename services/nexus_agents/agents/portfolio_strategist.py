"""
A12 — El Estratega: Portfolio Strategist agent.

Operates in two modes:
  - Reactive mode: after each trade close — analyses the trade
  - Reflective mode: every 4 hours — reviews portfolio performance

Tracks win rate, profit factor, Sharpe ratio, max drawdown.
Performs anti-tilt detection, model drift checks, and strategy adjustments.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
import yaml

from shared.redis_client import RedisClient

from ..state import AgentState
from ..tools.market_tools import query_duckdb
from ..tools.risk_tools import check_exposure
from .base_agent import BaseAgent

logger = structlog.get_logger(__name__)

RISK_RULES_PATH = Path(__file__).resolve().parents[3] / "config" / "risk_rules.yaml"


def _load_thresholds() -> dict[str, Any]:
    """Anti-tilt + drawdown thresholds from config/risk_rules.yaml (ACR-63 style)."""
    fallback: dict[str, Any] = {
        "loss_streak_warning": 6,
        "loss_streak_pause": 9,
        "max_daily_loss_pct": 20.0,
        "max_weekly_drawdown_pct": 25.0,
        "drift_deviation_pct": 20.0,
        "drift_profit_factor_floor": 0.8,
    }
    try:
        with open(RISK_RULES_PATH) as f:
            rules = yaml.safe_load(f) or {}
        anti_tilt = rules.get("anti_tilt", {})
        capital = rules.get("capital", {})
        drift = rules.get("model_drift", {}) if isinstance(rules.get("model_drift"), dict) else {}
        return {
            "loss_streak_warning": int(anti_tilt.get("consecutive_losses_warning", fallback["loss_streak_warning"])),
            "loss_streak_pause": int(anti_tilt.get("consecutive_losses_pause", fallback["loss_streak_pause"])),
            "max_daily_loss_pct": float(capital.get("max_daily_loss_pct", fallback["max_daily_loss_pct"])),
            "max_weekly_drawdown_pct": float(capital.get("max_weekly_drawdown_pct", fallback["max_weekly_drawdown_pct"])),
            "drift_deviation_pct": float(drift.get("recent_win_rate_deviation_pct", fallback["drift_deviation_pct"])),
            "drift_profit_factor_floor": float(drift.get("recent_profit_factor_floor", fallback["drift_profit_factor_floor"])),
        }
    except Exception:
        return fallback


_THRESHOLDS = _load_thresholds()


class PortfolioStrategistAgent(BaseAgent):
    def __init__(self, *, redis_client: RedisClient | None = None) -> None:
        super().__init__("A12", "Portfolio Strategist", redis_client=redis_client)

    async def invoke(self, state: AgentState) -> AgentState:
        symbol = state["symbol"]

        performance = await self._gather_performance()
        tilt_assessment = self._assess_tilt(performance)
        drift_check = self._check_model_drift(performance)

        dd_pct = performance.get("max_drawdown")
        dd_str = f"{dd_pct:.1f}%" if isinstance(dd_pct, (int, float)) else str(dd_pct)
        win_rate_pct = performance.get("win_rate")
        wr_str = f"{win_rate_pct:.1f}%" if isinstance(win_rate_pct, (int, float)) else str(win_rate_pct)

        context_for_llm = (
            f"=== PORTFOLIO REVIEW ===\n"
            f"Symbol just evaluated: {symbol}\n"
            f"Current verdict: {state.get('verdict', 'N/A')}\n"
            f"Conviction: {state.get('verdict_conviction', 0)}\n"
            f"Order placed: {json.dumps(state.get('order'), default=str)}\n\n"
            f"=== THRESHOLDS (from config/risk_rules.yaml — use these, not remembered values) ===\n"
            f"Anti-tilt warning after consecutive losses: {_THRESHOLDS['loss_streak_warning']}\n"
            f"Anti-tilt pause after consecutive losses: {_THRESHOLDS['loss_streak_pause']}\n"
            f"Daily loss budget: {_THRESHOLDS['max_daily_loss_pct']}%\n"
            f"Weekly drawdown budget: {_THRESHOLDS['max_weekly_drawdown_pct']}%\n"
            f"Drift: recent WR may deviate at most {_THRESHOLDS['drift_deviation_pct']}% "
            f"from overall; recent PF floor {_THRESHOLDS['drift_profit_factor_floor']}\n\n"
            f"=== PERFORMANCE METRICS ===\n"
            f"Data available: {performance.get('performance_data_available', False)}\n"
            f"Exposure data available: {performance.get('exposure_available', False)}\n"
            f"Total trades: {performance.get('total_trades', 0)}\n"
            f"Win rate: {wr_str}\n"
            f"Profit factor: {performance.get('profit_factor', 0):.2f}\n"
            f"Sharpe ratio: {performance.get('sharpe_ratio', 0):.2f}\n"
            f"Max drawdown: {dd_str}\n"
            f"Total PnL: ${performance.get('total_pnl', 0):.2f}\n"
            f"Avg win: ${performance.get('avg_win', 0):.2f}\n"
            f"Avg loss: ${performance.get('avg_loss', 0):.2f}\n"
            f"Consecutive losses: {performance.get('consecutive_losses', 0)}\n"
            f"Today's PnL: ${performance.get('today_pnl', 0):.2f}\n"
            f"Today's trades: {performance.get('today_trades', 0)}\n\n"
            f"=== TILT ASSESSMENT ===\n"
            f"Status: {tilt_assessment['status']}\n"
            f"Reasoning: {tilt_assessment['reasoning']}\n\n"
            f"=== MODEL DRIFT CHECK ===\n"
            f"Status: {drift_check['status']}\n"
            f"Details: {drift_check['details']}\n\n"
            f"=== RECENT TRADE ANALYSIS ===\n"
            f"{json.dumps(performance.get('recent_trades', [])[:5], default=str)}\n\n"
            f"NOTE: Your review is advisory — the central nexus-risk service is the "
            f"authority for the final decision and enforces the risk budgets above.\n"
            f"Any metric marked unavailable is INSUFFICIENT_DATA, not zero and not healthy.\n"
            f"Provide a portfolio review with:\n"
            f"1. Current performance assessment\n"
            f"2. Any strategy adjustments recommended\n"
            f"3. Risk parameter suggestions\n"
            f"4. Confidence in current approach (0-100)"
        )

        try:
            llm = self._get_llm(fast=True)
            prompt = self._load_prompt("portfolio_strategist")
            chain = prompt | llm
            response = await self._invoke_with_budget(chain, {"input": context_for_llm}, cycle_id=str(state.get("cycle_id", "")))
            review = response.content if hasattr(response, "content") else str(response)
        except Exception as exc:
            pf = performance.get("profit_factor")
            review = (
                f"[Auto-review]\n"
                f"Win rate: {wr_str}\n"
                f"PF: {f'{pf:.2f}' if isinstance(pf, (int, float)) else 'INSUFFICIENT_DATA'}\n"
                f"Tilt: {tilt_assessment['status']}\n"
                f"Drift: {drift_check['status']}"
            )
            state["errors"].append(f"A12: LLM call failed: {exc}")

        state["messages"].append({
            "agent_id": self.agent_id,
            "agent_name": self.name,
            "type": "portfolio_review",
            "content": review[:500],
            "performance": performance,
            "tilt": tilt_assessment,
            "drift": drift_check,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        await self._publish_message(
            f"Portfolio review: WR={wr_str}, "
            f"Tilt={tilt_assessment['status']}",
            metadata={
                "performance": performance,
                "tilt": tilt_assessment["status"],
                "drift": drift_check["status"],
            },
            state=state,
        )
        await self._log_reasoning(review, state=state)

        return state

    async def _gather_performance(self) -> dict[str, Any]:
        """Collect performance metrics from DuckDB and Redis.

        Unavailable sources are marked explicitly (performance_data_available /
        exposure_available) so callers never treat missing data as zeros.
        """
        performance: dict[str, Any] = {
            "total_trades": 0,
            "win_rate": None,
            "profit_factor": None,
            "sharpe_ratio": None,
            "max_drawdown": None,
            "total_pnl": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "consecutive_losses": 0,
            "today_pnl": None,
            "today_trades": 0,
            "recent_trades": [],
            "performance_data_available": False,
            "exposure_available": False,
        }

        try:
            trades = await query_duckdb(
                "SELECT * FROM trades ORDER BY closed_at DESC LIMIT 50"
            )
        except Exception as exc:
            trades = None
            logger.warning("portfolio_strategist.trade_history_unavailable", error=str(exc))
        if trades:
            performance["performance_data_available"] = True
            performance["recent_trades"] = trades[:10]
            performance["total_trades"] = len(trades)

            wins = [t for t in trades if t.get("pnl_usd", 0) > 0]
            losses = [t for t in trades if t.get("pnl_usd", 0) <= 0]

            if trades:
                performance["win_rate"] = (len(wins) / len(trades)) * 100

            total_wins = sum(t.get("pnl_usd", 0) for t in wins)
            total_losses = abs(sum(t.get("pnl_usd", 0) for t in losses))
            performance["total_pnl"] = total_wins - total_losses

            if total_losses > 0:
                performance["profit_factor"] = total_wins / total_losses
            elif total_wins > 0:
                performance["profit_factor"] = 999.0

            if wins:
                performance["avg_win"] = total_wins / len(wins)
            if losses:
                performance["avg_loss"] = total_losses / len(losses)

            consec = 0
            for t in trades:
                if t.get("pnl_usd", 0) <= 0:
                    consec += 1
                else:
                    break
            performance["consecutive_losses"] = consec

        try:
            exposure = await check_exposure()
        except Exception:
            exposure = {"available": False}
        # check_exposure() returns {"available": False, ...zeros} when the risk
        # service is unreachable — those zeros are NOT real exposure numbers.
        if exposure.get("available"):
            performance["exposure_available"] = True
            performance["max_drawdown"] = exposure.get("weekly_dd_pct")
            performance["today_pnl"] = exposure.get("daily_pnl")
            performance["consecutive_losses"] = max(
                performance["consecutive_losses"],
                exposure.get("consecutive_losses", 0),
            )
        else:
            logger.warning("portfolio_strategist.exposure_data_unavailable")

        return performance

    def _assess_tilt(self, performance: dict[str, Any]) -> dict[str, str]:
        consecutive = performance.get("consecutive_losses", 0)
        win_rate = performance.get("win_rate")
        max_dd = performance.get("max_drawdown")
        warning_at = _THRESHOLDS["loss_streak_warning"]
        pause_at = _THRESHOLDS["loss_streak_pause"]

        if consecutive >= pause_at:
            return {
                "status": "TILT",
                "reasoning": f"{pause_at}+ consecutive losses ({consecutive}). Trading should be paused.",
            }
        if consecutive >= warning_at:
            return {
                "status": "WARNING",
                "reasoning": f"{warning_at}+ consecutive losses ({consecutive}). Reduce position sizes.",
            }
        if isinstance(max_dd, (int, float)) and max_dd >= _THRESHOLDS["max_daily_loss_pct"] / 2:
            return {
                "status": "WARNING",
                "reasoning": f"Drawdown approaching limit ({max_dd:.1f}%). Trade cautiously.",
            }
        if (
            isinstance(win_rate, (int, float))
            and win_rate < 35
            and performance.get("total_trades", 0) > 10
        ):
            return {
                "status": "WARNING",
                "reasoning": f"Win rate below 35% ({win_rate:.1f}%). Review strategy.",
            }
        if not performance.get("performance_data_available") or not performance.get("exposure_available"):
            return {
                "status": "INSUFFICIENT_DATA",
                "reasoning": (
                    "Trade history or exposure data is unavailable — tilt cannot be "
                    "verified. Treat as unverified risk, not as NORMAL."
                ),
            }
        return {
            "status": "NORMAL",
            "reasoning": "No tilt indicators detected.",
        }

    def _check_model_drift(self, performance: dict[str, Any]) -> dict[str, str]:
        recent = performance.get("recent_trades", [])
        if len(recent) < 10:
            return {
                "status": "INSUFFICIENT_DATA",
                "details": f"Only {len(recent)} recent trades — need 10+ for drift analysis.",
            }

        recent_10_wr = sum(1 for t in recent[:10] if t.get("pnl_usd", 0) > 0) / 10 * 100
        overall_wr = performance.get("win_rate")
        if not isinstance(overall_wr, (int, float)):
            return {
                "status": "INSUFFICIENT_DATA",
                "details": "Overall win rate unavailable — cannot compare for drift.",
            }

        if abs(recent_10_wr - overall_wr) > _THRESHOLDS["drift_deviation_pct"]:
            return {
                "status": "DRIFT_DETECTED",
                "details": (
                    f"Recent 10-trade WR ({recent_10_wr:.0f}%) deviates significantly "
                    f"from overall ({overall_wr:.0f}%). Model may need recalibration."
                ),
            }

        recent_pf_wins = sum(t.get("pnl_usd", 0) for t in recent[:10] if t.get("pnl_usd", 0) > 0)
        recent_pf_losses = abs(sum(t.get("pnl_usd", 0) for t in recent[:10] if t.get("pnl_usd", 0) <= 0))
        recent_pf = recent_pf_wins / recent_pf_losses if recent_pf_losses > 0 else 999.0

        if recent_pf < _THRESHOLDS["drift_profit_factor_floor"]:
            return {
                "status": "DRIFT_WARNING",
                "details": f"Recent profit factor ({recent_pf:.2f}) is below threshold.",
            }

        return {
            "status": "STABLE",
            "details": "No significant model drift detected.",
        }
