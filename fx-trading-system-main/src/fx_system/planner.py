from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta

import numpy as np
import pandas as pd

from .config import SystemConfig
from .models import Position, Side
from .rates import FXRateGraph
from .research import generate_ensemble_signals
from .risk import PortfolioRiskManager


@dataclass(frozen=True)
class PaperOrderProposal:
    proposal_id: str
    signal_timestamp: str
    expires_at: str
    symbol: str
    units: int
    side: str
    reference_price: float
    stop_loss: float
    take_profit: float
    max_holding_hours: int
    strategy: str
    confidence: float
    group_id: str | None


def create_paper_plan(
    data: Mapping[str, pd.DataFrame],
    config: SystemConfig,
    equity: float | None = None,
    include_unapproved: bool = False,
) -> list[PaperOrderProposal]:
    """Create a no-side-effect order plan from signals on each symbol's latest closed bar."""
    approved = {
        item.name
        for item in config.strategies
        if item.enabled and (item.paper_enabled or include_unapproved)
    }
    if not approved:
        return []
    signals, _ = generate_ensemble_signals(data, config, approved)
    latest = {symbol: frame.index[-1] for symbol, frame in data.items()}
    actionable = [signal for signal in signals if signal.timestamp == latest[signal.symbol]]
    actionable.sort(key=lambda signal: signal.confidence, reverse=True)
    rate_graph = FXRateGraph(data)
    closes = pd.concat({symbol: frame["close"] for symbol, frame in data.items()}, axis=1)
    returns = np.log(closes.astype(float)).diff()
    manager = PortfolioRiskManager(config.risk, rate_graph, returns)
    positions: dict[str, Position] = {}
    proposals: list[PaperOrderProposal] = []
    account_equity = equity or config.risk.initial_equity
    interval_hours = {"1h": 1, "4h": 4, "1d": 24}[config.data.interval]
    groups: dict[str, list] = defaultdict(list)
    order: list[str] = []
    for sequence, signal in enumerate(actionable):
        key = signal.group_id or f"single-{sequence}"
        if key not in groups:
            order.append(key)
        groups[key].append(signal)
    for key in order:
        group = groups[key]
        start_count = len(proposals)
        opened: list[str] = []
        failed = False
        for signal in group:
            timestamp = signal.timestamp
            reference = float(data[signal.symbol].loc[timestamp, "close"])
            decision = manager.evaluate(
                signal,
                reference,
                account_equity,
                positions,
                timestamp,
                drawdown=0.0,
                daily_return=0.0,
            )
            if not decision.approved:
                failed = True
                continue
            stop_distance = signal.atr * signal.stop_atr
            target_distance = min(
                signal.atr * signal.target_atr,
                stop_distance * config.risk.max_reward_risk,
            )
            proposal = PaperOrderProposal(
                proposal_id=hashlib.sha256(
                    (
                        f"{timestamp.isoformat()}|{signal.symbol}|{int(signal.side)}|"
                        f"{signal.strategy}|{signal.group_id or ''}"
                    ).encode()
                ).hexdigest()[:32],
                signal_timestamp=timestamp.isoformat(),
                expires_at=(timestamp + timedelta(hours=2 * interval_hours)).isoformat(),
                symbol=signal.symbol,
                units=int(decision.units) * int(signal.side),
                side="buy" if signal.side == Side.LONG else "sell",
                reference_price=reference,
                stop_loss=reference - int(signal.side) * stop_distance,
                take_profit=reference + int(signal.side) * target_distance,
                max_holding_hours=min(signal.max_holding_hours, config.risk.max_holding_hours),
                strategy=signal.strategy,
                confidence=signal.confidence,
                group_id=signal.group_id,
            )
            proposals.append(proposal)
            positions[signal.symbol] = Position(
                position_id="paper-plan",
                symbol=signal.symbol,
                strategy=signal.strategy,
                side=signal.side,
                units=decision.units,
                entry_time=timestamp,
                entry_mid=reference,
                entry_price=reference,
                stop_price=proposal.stop_loss,
                target_price=proposal.take_profit,
                max_exit_time=timestamp + timedelta(hours=proposal.max_holding_hours),
                initial_risk_account=decision.initial_risk,
                confidence=signal.confidence,
                group_id=signal.group_id,
            )
            opened.append(signal.symbol)
        if failed and len(group) > 1:
            del proposals[start_count:]
            for symbol in opened:
                positions.pop(symbol, None)
    return proposals
