from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any

import pandas as pd


class Side(IntEnum):
    SHORT = -1
    FLAT = 0
    LONG = 1


@dataclass(frozen=True)
class CurrencyPair:
    symbol: str
    base: str
    quote: str
    pip_size: float

    @classmethod
    def parse(cls, value: str) -> CurrencyPair:
        symbol = value.upper().replace("/", "").replace("_", "").replace("=X", "")
        if len(symbol) != 6 or not symbol.isalpha():
            raise ValueError(f"Invalid FX symbol: {value!r}; expected EURUSD or EUR/USD")
        base, quote = symbol[:3], symbol[3:]
        pip_size = 0.01 if quote == "JPY" else 0.0001
        return cls(symbol=symbol, base=base, quote=quote, pip_size=pip_size)


@dataclass(frozen=True)
class Signal:
    timestamp: pd.Timestamp
    symbol: str
    side: Side
    confidence: float
    strategy: str
    atr: float
    stop_atr: float
    target_atr: float
    max_holding_hours: int
    reason: str = ""
    group_id: str | None = None

    @property
    def reward_risk(self) -> float:
        return self.target_atr / self.stop_atr

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["timestamp"] = self.timestamp.isoformat()
        result["side"] = int(self.side)
        return result


@dataclass
class Position:
    position_id: str
    symbol: str
    strategy: str
    side: Side
    units: float
    entry_time: pd.Timestamp
    entry_mid: float
    entry_price: float
    stop_price: float
    target_price: float
    max_exit_time: pd.Timestamp
    initial_risk_account: float
    confidence: float
    group_id: str | None = None
    accrued_swap: float = 0.0


@dataclass(frozen=True)
class Trade:
    position_id: str
    symbol: str
    strategy: str
    side: Side
    units: float
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_mid: float
    exit_mid: float
    entry_price: float
    exit_price: float
    gross_pnl: float
    costs: float
    net_pnl: float
    initial_risk: float
    exit_reason: str
    group_id: str | None = None

    @property
    def r_multiple(self) -> float:
        return self.net_pnl / self.initial_risk if self.initial_risk else 0.0

    @property
    def holding_hours(self) -> float:
        return (self.exit_time - self.entry_time).total_seconds() / 3600

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["entry_time"] = self.entry_time.isoformat()
        result["exit_time"] = self.exit_time.isoformat()
        result["side"] = int(self.side)
        result["r_multiple"] = self.r_multiple
        result["holding_hours"] = self.holding_hours
        return result


@dataclass(frozen=True)
class EquityPoint:
    timestamp: pd.Timestamp
    cash: float
    unrealized_pnl: float
    equity: float
    open_positions: int
    gross_leverage: float
    drawdown: float


@dataclass
class BacktestResult:
    trades: list[Trade]
    equity: list[EquityPoint]
    rejected_signals: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def utc_timestamp(value: str | datetime | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")
