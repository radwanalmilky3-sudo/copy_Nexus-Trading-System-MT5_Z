from __future__ import annotations

from typing import Any

from .base import Strategy
from .multicurrency import CointegrationSpread, CurrencyStrengthReversion
from .technical import FalseBreakoutReversal, RegimeMeanReversion, SessionBreakout, TrendPullback

STRATEGIES: dict[str, type[Strategy]] = {
    RegimeMeanReversion.name: RegimeMeanReversion,
    TrendPullback.name: TrendPullback,
    SessionBreakout.name: SessionBreakout,
    FalseBreakoutReversal.name: FalseBreakoutReversal,
    CurrencyStrengthReversion.name: CurrencyStrengthReversion,
    CointegrationSpread.name: CointegrationSpread,
}


def build_strategy(name: str, params: dict[str, Any] | None = None) -> Strategy:
    try:
        strategy_class = STRATEGIES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown strategy {name!r}; options: {sorted(STRATEGIES)}") from exc
    return strategy_class(**(params or {}))


__all__ = [
    "Strategy",
    "RegimeMeanReversion",
    "TrendPullback",
    "SessionBreakout",
    "FalseBreakoutReversal",
    "CurrencyStrengthReversion",
    "CointegrationSpread",
    "build_strategy",
]
