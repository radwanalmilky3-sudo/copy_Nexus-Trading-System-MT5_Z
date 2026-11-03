from __future__ import annotations

from collections.abc import Iterable

import pandas as pd
import pytest

from fx_system.config import CostConfig, RiskConfig


def make_bars(
    rows: Iterable[tuple[float, float, float, float]],
    *,
    start: str = "2025-01-06T00:00:00Z",
    frequency: str = "4h",
) -> pd.DataFrame:
    values = list(rows)
    index = pd.date_range(start, periods=len(values), freq=frequency)
    return pd.DataFrame(values, columns=["open", "high", "low", "close"], index=index).assign(
        volume=1000.0
    )


@pytest.fixture
def zero_costs() -> CostConfig:
    return CostConfig(
        default_spread_pips=0,
        slippage_pips=0,
        commission_per_million=0,
    )


@pytest.fixture
def permissive_risk() -> RiskConfig:
    return RiskConfig(
        initial_equity=100_000,
        risk_per_trade=0.003,
        max_portfolio_risk=0.02,
        max_open_positions=5,
        max_gross_leverage=5,
        max_currency_exposure=5,
        max_correlated_positions=5,
        max_drawdown=0.3,
        close_before_weekend=False,
    )
