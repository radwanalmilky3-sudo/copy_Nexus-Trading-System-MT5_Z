"""Explicit two-stage next-open/same-session-close FX account ledger.

The core in this module starts after target construction and quantity sizing.
It accepts complete synthetic-or-frozen quantity, quote, conversion, financing,
slippage and cash-interest inputs.  It does not infer missing costs, choose
strategies, convert weights to quantities, or approve trading.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_numeric_dtype

_TIMESTAMP_COLUMNS = (
    "rollover_timestamp",
    "open_timestamp",
    "close_timestamp",
)


def _close_enough(actual: float, expected: float) -> bool:
    return math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)


def _immutable_positions(values: Mapping[str, float]) -> Mapping[str, float]:
    return MappingProxyType(dict(values))


@dataclass(frozen=True)
class TwoStageTrade:
    """One net broker trade after cross-component quantity netting."""

    session: pd.Timestamp
    timestamp: pd.Timestamp
    phase: Literal["open", "close"]
    symbol: str
    previous_quantity: float
    target_quantity: float
    delta_quantity: float
    side: Literal["buy", "sell"]
    bid: float
    ask: float
    mid: float
    quoted_execution_price: float
    adverse_slippage_per_unit: float
    effective_execution_price: float
    account_value_multiplier: float
    spread_cost: float
    slippage_cost: float

    def __post_init__(self) -> None:
        for field in ("session", "timestamp"):
            timestamp = pd.Timestamp(getattr(self, field))
            if timestamp.tzinfo is None:
                raise ValueError(f"trade {field} must be timezone-aware")
            object.__setattr__(self, field, timestamp.tz_convert("UTC"))
        numeric_values = (
            self.previous_quantity,
            self.target_quantity,
            self.delta_quantity,
            self.bid,
            self.ask,
            self.mid,
            self.quoted_execution_price,
            self.adverse_slippage_per_unit,
            self.effective_execution_price,
            self.account_value_multiplier,
            self.spread_cost,
            self.slippage_cost,
        )
        if not all(math.isfinite(value) for value in numeric_values):
            raise ValueError("trade values must be finite")
        if self.delta_quantity == 0:
            raise ValueError("a trade delta cannot be zero")
        if not _close_enough(
            self.previous_quantity + self.delta_quantity,
            self.target_quantity,
        ):
            raise ValueError("trade quantities do not reconcile")
        if self.adverse_slippage_per_unit < 0:
            raise ValueError("trade adverse slippage cannot be negative")
        if self.account_value_multiplier <= 0:
            raise ValueError("trade account-value multiplier must be positive")
        expected_side = "buy" if self.delta_quantity > 0 else "sell"
        if self.side != expected_side:
            raise ValueError("trade side does not match delta quantity")
        if not 0 < self.bid <= self.ask:
            raise ValueError("trade contains crossed or non-positive quotes")
        expected_mid = self.bid + (self.ask - self.bid) / 2.0
        if not _close_enough(self.mid, expected_mid):
            raise ValueError("trade mid does not reconcile to bid and ask")
        expected_quote = self.ask if self.side == "buy" else self.bid
        if not _close_enough(self.quoted_execution_price, expected_quote):
            raise ValueError("trade did not use the executable bid/ask side")
        expected_effective = (
            expected_quote + self.adverse_slippage_per_unit
            if self.side == "buy"
            else expected_quote - self.adverse_slippage_per_unit
        )
        if expected_effective <= 0 or not _close_enough(
            self.effective_execution_price, expected_effective
        ):
            raise ValueError("trade effective price does not reconcile to slippage")
        expected_spread = (
            abs(self.delta_quantity)
            * abs(expected_quote - self.mid)
            * self.account_value_multiplier
        )
        expected_slippage = (
            abs(self.delta_quantity)
            * self.adverse_slippage_per_unit
            * self.account_value_multiplier
        )
        if not _close_enough(self.spread_cost, expected_spread):
            raise ValueError("trade spread cost does not reconcile")
        if not _close_enough(self.slippage_cost, expected_slippage):
            raise ValueError("trade slippage cost does not reconcile")


@dataclass(frozen=True)
class SessionSymbolAudit:
    """Per-symbol position, PnL, financing and execution audit for one session."""

    session: pd.Timestamp
    symbol: str
    previous_close_quantity: float
    previous_close_mid: float
    open_bid: float
    open_ask: float
    open_mid: float
    open_account_value_multiplier: float
    long_financing_per_unit: float
    short_financing_per_unit: float
    overnight_price_pnl: float
    financing: float
    open_target_quantity: float
    open_trade_quantity: float
    open_spread_cost: float
    open_slippage_cost: float
    close_bid: float
    close_ask: float
    close_mid: float
    close_account_value_multiplier: float
    intraday_price_pnl: float
    close_target_quantity: float
    close_trade_quantity: float
    close_spread_cost: float
    close_slippage_cost: float


@dataclass(frozen=True)
class TargetQuantityAudit:
    """One component quantity before master-account netting."""

    session: pd.Timestamp
    phase: Literal["open", "close"]
    component: str
    symbol: str
    target_quantity: float


@dataclass(frozen=True)
class TwoStageSessionLedger:
    """Segmented accounting for one rollover/open/close session."""

    session: pd.Timestamp
    previous_close_timestamp: pd.Timestamp
    rollover_timestamp: pd.Timestamp
    open_timestamp: pd.Timestamp
    close_timestamp: pd.Timestamp
    previous_nav: float
    previous_close_positions: Mapping[str, float]
    overnight_price_pnl: float
    financing: float
    cash_interest: float
    nav_before_open_execution: float
    open_target_positions: Mapping[str, float]
    open_spread_cost: float
    open_slippage_cost: float
    nav_after_open_execution: float
    intraday_price_pnl: float
    nav_before_close_execution: float
    close_target_positions: Mapping[str, float]
    close_spread_cost: float
    close_slippage_cost: float
    net_pnl: float
    nav: float
    simple_return: float
    open_broker_turnover: float
    close_broker_turnover: float
    accounting_reconciled: bool = True

    def __post_init__(self) -> None:
        numeric_fields = (
            "previous_nav",
            "overnight_price_pnl",
            "financing",
            "cash_interest",
            "nav_before_open_execution",
            "open_spread_cost",
            "open_slippage_cost",
            "nav_after_open_execution",
            "intraday_price_pnl",
            "nav_before_close_execution",
            "close_spread_cost",
            "close_slippage_cost",
            "net_pnl",
            "nav",
            "simple_return",
            "open_broker_turnover",
            "close_broker_turnover",
        )
        if not all(math.isfinite(getattr(self, field)) for field in numeric_fields):
            raise ValueError("session ledger values must be finite")
        for field in (
            "session",
            "previous_close_timestamp",
            "rollover_timestamp",
            "open_timestamp",
            "close_timestamp",
        ):
            timestamp = pd.Timestamp(getattr(self, field))
            if timestamp.tzinfo is None:
                raise ValueError(f"{field} must be timezone-aware")
            object.__setattr__(self, field, timestamp.tz_convert("UTC"))
        if not (
            self.previous_close_timestamp
            < self.rollover_timestamp
            <= self.open_timestamp
            < self.close_timestamp
        ):
            raise ValueError(
                "session event order must be previous close < rollover <= open < close"
            )
        for field in (
            "previous_close_positions",
            "open_target_positions",
            "close_target_positions",
        ):
            object.__setattr__(self, field, _immutable_positions(getattr(self, field)))
        expected_before_open = math.fsum(
            (
                self.previous_nav,
                self.overnight_price_pnl,
                self.financing,
                self.cash_interest,
            )
        )
        expected_after_open = math.fsum(
            (
                expected_before_open,
                -self.open_spread_cost,
                -self.open_slippage_cost,
            )
        )
        expected_before_close = expected_after_open + self.intraday_price_pnl
        expected_net_pnl = math.fsum(
            (
                self.overnight_price_pnl,
                self.financing,
                self.cash_interest,
                -self.open_spread_cost,
                -self.open_slippage_cost,
                self.intraday_price_pnl,
                -self.close_spread_cost,
                -self.close_slippage_cost,
            )
        )
        checks = {
            "nav before open execution": (
                self.nav_before_open_execution,
                expected_before_open,
            ),
            "nav after open execution": (
                self.nav_after_open_execution,
                expected_after_open,
            ),
            "nav before close execution": (
                self.nav_before_close_execution,
                expected_before_close,
            ),
            "net PnL": (self.net_pnl, expected_net_pnl),
            "ending NAV": (self.nav, self.previous_nav + expected_net_pnl),
            "simple return": (self.simple_return, expected_net_pnl / self.previous_nav),
        }
        for label, (actual, expected) in checks.items():
            if not _close_enough(actual, expected):
                raise ValueError(f"session ledger fails {label} reconciliation")
        if min(
            self.previous_nav,
            self.nav_before_open_execution,
            self.nav_after_open_execution,
            self.nav_before_close_execution,
            self.nav,
        ) <= 0:
            raise ValueError("master-account NAV must remain positive at every segment")
        if min(
            self.open_spread_cost,
            self.open_slippage_cost,
            self.close_spread_cost,
            self.close_slippage_cost,
            self.open_broker_turnover,
            self.close_broker_turnover,
        ) < 0:
            raise ValueError("execution costs and turnover cannot be negative")
        if self.accounting_reconciled is not True:
            raise ValueError("accounting_reconciled cannot be overridden")


@dataclass(frozen=True)
class LongHorizonExecutionResult:
    """Immutable audit result; never a claim of formal net-return readiness."""

    initial_nav: float
    final_nav: float
    entries: tuple[TwoStageSessionLedger, ...]
    trades: tuple[TwoStageTrade, ...]
    symbol_audit: tuple[SessionSymbolAudit, ...]
    target_quantity_audit: tuple[TargetQuantityAudit, ...]
    trading_approval: bool = False
    formal_net_returns_ready: bool = False
    account_pnl_settlement_assumption: str = (
        "account_currency_cash_settlement_or_mark_reset_at_each_boundary"
    )
    external_dependencies_remaining: tuple[str, ...] = (
        "weight_to_quantity_conversion",
        "sleeve_and_cross_candidate_budgeting",
        "verified_target_broker_financing_source",
        "calibrated_real_slippage_model",
        "multi_currency_unrealized_pnl_cost_basis_and_broker_settlement",
        "broker_commission_and_other_fees",
        "per_symbol_quote_timestamp_and_staleness",
    )

    def __post_init__(self) -> None:
        if not self.entries:
            raise ValueError("execution result must contain at least one session")
        if not _close_enough(self.entries[0].previous_nav, self.initial_nav):
            raise ValueError("first session does not start from initial_nav")
        previous = self.entries[0]
        for current in self.entries[1:]:
            if not _close_enough(current.previous_nav, previous.nav):
                raise ValueError("session NAV chain is broken")
            if current.previous_close_timestamp != previous.close_timestamp:
                raise ValueError("session close/open timestamp chain is broken")
            if dict(current.previous_close_positions) != dict(
                previous.close_target_positions
            ):
                raise ValueError("session position chain is broken")
            previous = current
        if not _close_enough(self.final_nav, self.entries[-1].nav):
            raise ValueError("final_nav does not match final session")
        if self.trading_approval or self.formal_net_returns_ready:
            raise ValueError("execution core cannot approve trading or formal readiness")
        expected_assumption = (
            "account_currency_cash_settlement_or_mark_reset_at_each_boundary"
        )
        if self.account_pnl_settlement_assumption != expected_assumption:
            raise ValueError("account PnL settlement assumption cannot be overridden")
        required_blockers = {
            "multi_currency_unrealized_pnl_cost_basis_and_broker_settlement",
            "broker_commission_and_other_fees",
            "per_symbol_quote_timestamp_and_staleness",
        }
        if not required_blockers.issubset(self.external_dependencies_remaining):
            raise ValueError("mandatory external execution blockers cannot be removed")

    def ledger_frame(self) -> pd.DataFrame:
        rows = []
        for entry in self.entries:
            rows.append(
                {
                    "session": entry.session,
                    "previous_close_timestamp": entry.previous_close_timestamp,
                    "rollover_timestamp": entry.rollover_timestamp,
                    "open_timestamp": entry.open_timestamp,
                    "close_timestamp": entry.close_timestamp,
                    "previous_nav": entry.previous_nav,
                    "overnight_price_pnl": entry.overnight_price_pnl,
                    "financing": entry.financing,
                    "cash_interest": entry.cash_interest,
                    "nav_before_open_execution": entry.nav_before_open_execution,
                    "open_spread_cost": entry.open_spread_cost,
                    "open_slippage_cost": entry.open_slippage_cost,
                    "nav_after_open_execution": entry.nav_after_open_execution,
                    "intraday_price_pnl": entry.intraday_price_pnl,
                    "nav_before_close_execution": entry.nav_before_close_execution,
                    "close_spread_cost": entry.close_spread_cost,
                    "close_slippage_cost": entry.close_slippage_cost,
                    "net_pnl": entry.net_pnl,
                    "nav": entry.nav,
                    "simple_return": entry.simple_return,
                    "open_broker_turnover": entry.open_broker_turnover,
                    "close_broker_turnover": entry.close_broker_turnover,
                    "accounting_reconciled": entry.accounting_reconciled,
                }
            )
        return pd.DataFrame(rows).set_index("session")

    def trades_frame(self) -> pd.DataFrame:
        return pd.DataFrame([vars(trade) for trade in self.trades])

    def positions_frame(self) -> pd.DataFrame:
        return pd.DataFrame([vars(row) for row in self.symbol_audit])

    def target_quantities_frame(self) -> pd.DataFrame:
        return pd.DataFrame([vars(row) for row in self.target_quantity_audit])


def _validate_session_index(index: object) -> pd.DatetimeIndex:
    if not isinstance(index, pd.DatetimeIndex):
        raise ValueError("session_timestamps must use a DatetimeIndex")
    if index.tz is None or str(index.tz).upper() != "UTC":
        raise ValueError("session labels must use a timezone-aware UTC index")
    if index.hasnans or not index.is_unique or not index.is_monotonic_increasing:
        raise ValueError("session labels must be valid, unique, and sorted")
    if len(index) < 1:
        raise ValueError("session_timestamps cannot be empty")
    return index.copy()


def _validate_event_timestamps(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("session_timestamps must be a pandas DataFrame")
    sessions = _validate_session_index(frame.index)
    if set(frame.columns) != set(_TIMESTAMP_COLUMNS) or len(frame.columns) != len(
        _TIMESTAMP_COLUMNS
    ):
        raise ValueError(
            f"session_timestamps columns must be exactly {list(_TIMESTAMP_COLUMNS)}"
        )
    normalized = pd.DataFrame(index=sessions)
    for column in _TIMESTAMP_COLUMNS:
        values: list[pd.Timestamp] = []
        for raw_value in frame[column]:
            timestamp = pd.Timestamp(raw_value)
            if timestamp.tzinfo is None:
                raise ValueError(f"{column} values must be timezone-aware")
            values.append(timestamp.tz_convert("UTC"))
        normalized[column] = values
    for session, row in normalized.iterrows():
        rollover = row["rollover_timestamp"]
        new_york_rollover = rollover.tz_convert("America/New_York")
        if (
            new_york_rollover.hour != 17
            or new_york_rollover.minute
            or new_york_rollover.second
            or new_york_rollover.microsecond
        ):
            raise ValueError(
                f"{session}: rollover must convert to exactly 17:00 "
                "America/New_York on that date"
            )
        if not rollover <= row["open_timestamp"] < row["close_timestamp"]:
            raise ValueError(f"{session}: require rollover <= open < close")
    return normalized


def _validate_symbols(columns: object, *, name: str) -> tuple[str, ...]:
    symbols: list[str] = []
    for value in columns:  # type: ignore[union-attr]
        if not isinstance(value, str) or not value:
            raise ValueError(f"{name} symbols must be non-empty strings")
        if value != value.strip() or value != value.upper():
            raise ValueError(f"{name} symbols must be stripped uppercase identifiers")
        symbols.append(value)
    if not symbols or len(symbols) != len(set(symbols)):
        raise ValueError(f"{name} symbols must be non-empty and unique")
    return tuple(symbols)


def _validate_numeric_frame(
    frame: pd.DataFrame,
    *,
    name: str,
    sessions: pd.DatetimeIndex,
    symbols: tuple[str, ...],
    lower_bound: float | None = None,
    strictly_positive: bool = False,
) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"{name} must be a pandas DataFrame")
    if not frame.index.equals(sessions):
        raise ValueError(f"{name} must have exactly the common session index")
    actual_symbols = _validate_symbols(frame.columns, name=name)
    if set(actual_symbols) != set(symbols) or len(actual_symbols) != len(symbols):
        raise ValueError(f"{name} must have exactly the common symbol columns")
    output = pd.DataFrame(index=sessions)
    for symbol in symbols:
        series = frame[symbol]
        if is_bool_dtype(series.dtype) or not is_numeric_dtype(series.dtype):
            raise ValueError(f"{name}[{symbol}] must be numeric and non-boolean")
        values = series.to_numpy(dtype=float, na_value=np.nan)
        if not np.isfinite(values).all():
            raise ValueError(f"{name}[{symbol}] contains missing or infinite values")
        if strictly_positive and np.any(values <= 0):
            raise ValueError(f"{name}[{symbol}] must be positive")
        if lower_bound is not None and np.any(values < lower_bound):
            raise ValueError(f"{name}[{symbol}] must be at least {lower_bound}")
        output[symbol] = values
    return output


def _validate_numeric_series(
    series: pd.Series,
    *,
    name: str,
    expected_index: pd.Index,
) -> pd.Series:
    if not isinstance(series, pd.Series):
        raise TypeError(f"{name} must be a pandas Series")
    if not series.index.equals(expected_index):
        raise ValueError(f"{name} must have exactly the required index")
    if is_bool_dtype(series.dtype) or not is_numeric_dtype(series.dtype):
        raise ValueError(f"{name} must be numeric and non-boolean")
    values = series.to_numpy(dtype=float, na_value=np.nan)
    if not np.isfinite(values).all():
        raise ValueError(f"{name} contains missing or infinite values")
    return pd.Series(values, index=expected_index, name=series.name)


def _validate_initial_quotes(
    bids: pd.Series,
    asks: pd.Series,
    *,
    symbols: tuple[str, ...],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    symbol_index = pd.Index(symbols)
    bid_series = _validate_numeric_series(
        bids, name="initial_close_bid_prices", expected_index=symbol_index
    )
    ask_series = _validate_numeric_series(
        asks, name="initial_close_ask_prices", expected_index=symbol_index
    )
    bid_values = bid_series.to_numpy()
    ask_values = ask_series.to_numpy()
    if np.any(bid_values <= 0) or np.any(ask_values <= 0):
        raise ValueError("initial close quotes must be positive")
    if np.any(bid_values > ask_values):
        raise ValueError("initial close quotes cannot be crossed")
    mids = bid_values + (ask_values - bid_values) / 2.0
    return bid_values, ask_values, mids


def _validate_targets(
    panels: Mapping[str, pd.DataFrame],
    *,
    name: str,
    sessions: pd.DatetimeIndex,
    symbols: tuple[str, ...],
) -> tuple[dict[str, pd.DataFrame], np.ndarray]:
    if not isinstance(panels, Mapping) or not panels:
        raise ValueError(f"{name} must be a non-empty component mapping")
    validated: dict[str, pd.DataFrame] = {}
    for component, panel in panels.items():
        if not isinstance(component, str) or not component or component != component.strip():
            raise ValueError(f"{name} component names must be non-empty and stripped")
        validated[component] = _validate_numeric_frame(
            panel,
            name=f"{name}[{component}]",
            sessions=sessions,
            symbols=symbols,
        )
    ordered = {component: validated[component] for component in sorted(validated)}
    with np.errstate(over="ignore", invalid="ignore"):
        net = np.sum(
            np.stack([panel.to_numpy(dtype=float) for panel in ordered.values()]),
            axis=0,
        )
    if not np.isfinite(net).all():
        raise ValueError(f"{name} component netting produced a non-finite quantity")
    return ordered, net


def _make_trades(
    *,
    session: pd.Timestamp,
    timestamp: pd.Timestamp,
    phase: Literal["open", "close"],
    symbols: tuple[str, ...],
    previous: np.ndarray,
    target: np.ndarray,
    bids: np.ndarray,
    asks: np.ndarray,
    slippage: np.ndarray,
    multipliers: np.ndarray,
) -> tuple[list[TwoStageTrade], np.ndarray, np.ndarray, np.ndarray]:
    deltas = target - previous
    spread_costs = np.zeros(len(symbols))
    slippage_costs = np.zeros(len(symbols))
    trades: list[TwoStageTrade] = []
    for location, symbol in enumerate(symbols):
        delta = float(deltas[location])
        if delta == 0.0:
            continue
        bid = float(bids[location])
        ask = float(asks[location])
        mid = bid + (ask - bid) / 2.0
        adverse_slippage = float(slippage[location])
        multiplier = float(multipliers[location])
        side: Literal["buy", "sell"] = "buy" if delta > 0 else "sell"
        quoted_price = ask if side == "buy" else bid
        effective_price = (
            quoted_price + adverse_slippage
            if side == "buy"
            else quoted_price - adverse_slippage
        )
        if effective_price <= 0:
            raise ValueError(f"{session} {phase} {symbol}: slippage makes price non-positive")
        spread_cost = abs(delta) * abs(quoted_price - mid) * multiplier
        slippage_cost = abs(delta) * adverse_slippage * multiplier
        spread_costs[location] = spread_cost
        slippage_costs[location] = slippage_cost
        trades.append(
            TwoStageTrade(
                session=session,
                timestamp=timestamp,
                phase=phase,
                symbol=symbol,
                previous_quantity=float(previous[location]),
                target_quantity=float(target[location]),
                delta_quantity=delta,
                side=side,
                bid=bid,
                ask=ask,
                mid=mid,
                quoted_execution_price=quoted_price,
                adverse_slippage_per_unit=adverse_slippage,
                effective_execution_price=effective_price,
                account_value_multiplier=multiplier,
                spread_cost=spread_cost,
                slippage_cost=slippage_cost,
            )
        )
    return trades, deltas, spread_costs, slippage_costs


def run_long_horizon_execution(
    *,
    session_timestamps: pd.DataFrame,
    open_target_quantities: Mapping[str, pd.DataFrame],
    close_target_quantities: Mapping[str, pd.DataFrame],
    open_bid_prices: pd.DataFrame,
    open_ask_prices: pd.DataFrame,
    close_bid_prices: pd.DataFrame,
    close_ask_prices: pd.DataFrame,
    open_account_value_multipliers: pd.DataFrame,
    close_account_value_multipliers: pd.DataFrame,
    long_financing_per_unit: pd.DataFrame,
    short_financing_per_unit: pd.DataFrame,
    open_adverse_slippage_per_unit: pd.DataFrame,
    close_adverse_slippage_per_unit: pd.DataFrame,
    cash_interest: pd.Series,
    initial_nav: float,
    initial_positions: pd.Series,
    initial_close_timestamp: pd.Timestamp,
    initial_close_bid_prices: pd.Series,
    initial_close_ask_prices: pd.Series,
) -> LongHorizonExecutionResult:
    """Book explicit close-to-open, rollover, open and close account events.

    Financing rates are signed account-currency amounts per absolute unit:
    ``long_financing_per_unit`` applies to positive old positions and
    ``short_financing_per_unit`` to negative old positions.  Cash interest is
    an already-computed signed account-currency amount.  No input defaults to
    zero when omitted.

    Price PnL uses the multiplier at the ending boundary.  This is valid only
    under an explicit account-currency cash-settlement or mark-reset assumption
    at every boundary.  A broker's multi-currency unrealized cost basis, actual
    settlement rules, commissions and per-symbol quote timestamps remain
    external blockers and are disclosed on the result.
    """
    timestamps = _validate_event_timestamps(session_timestamps)
    sessions = timestamps.index
    if not isinstance(open_bid_prices, pd.DataFrame):
        raise TypeError("open_bid_prices must be a pandas DataFrame")
    if not open_bid_prices.index.equals(sessions):
        raise ValueError("open_bid_prices must have exactly the common session index")
    symbols = _validate_symbols(open_bid_prices.columns, name="open_bid_prices")

    frame_specs = (
        ("open_bid_prices", open_bid_prices, None, True),
        ("open_ask_prices", open_ask_prices, None, True),
        ("close_bid_prices", close_bid_prices, None, True),
        ("close_ask_prices", close_ask_prices, None, True),
        (
            "open_account_value_multipliers",
            open_account_value_multipliers,
            None,
            True,
        ),
        (
            "close_account_value_multipliers",
            close_account_value_multipliers,
            None,
            True,
        ),
        ("long_financing_per_unit", long_financing_per_unit, None, False),
        ("short_financing_per_unit", short_financing_per_unit, None, False),
        (
            "open_adverse_slippage_per_unit",
            open_adverse_slippage_per_unit,
            0.0,
            False,
        ),
        (
            "close_adverse_slippage_per_unit",
            close_adverse_slippage_per_unit,
            0.0,
            False,
        ),
    )
    frames: dict[str, pd.DataFrame] = {}
    for name, frame, lower_bound, strictly_positive in frame_specs:
        frames[name] = _validate_numeric_frame(
            frame,
            name=name,
            sessions=sessions,
            symbols=symbols,
            lower_bound=lower_bound,
            strictly_positive=strictly_positive,
        )
    open_bids = frames["open_bid_prices"]
    open_asks = frames["open_ask_prices"]
    close_bids = frames["close_bid_prices"]
    close_asks = frames["close_ask_prices"]
    if (open_bids.to_numpy() > open_asks.to_numpy()).any():
        raise ValueError("open quotes cannot be crossed")
    if (close_bids.to_numpy() > close_asks.to_numpy()).any():
        raise ValueError("close quotes cannot be crossed")

    open_components, open_targets = _validate_targets(
        open_target_quantities,
        name="open_target_quantities",
        sessions=sessions,
        symbols=symbols,
    )
    close_components, close_targets = _validate_targets(
        close_target_quantities,
        name="close_target_quantities",
        sessions=sessions,
        symbols=symbols,
    )
    if set(open_components) != set(close_components):
        raise ValueError("open and close target component names must match exactly")

    daily_cash_interest = _validate_numeric_series(
        cash_interest,
        name="cash_interest",
        expected_index=sessions,
    )
    symbol_index = pd.Index(symbols)
    starting_positions = _validate_numeric_series(
        initial_positions,
        name="initial_positions",
        expected_index=symbol_index,
    ).to_numpy()
    _, _, previous_close_mids = _validate_initial_quotes(
        initial_close_bid_prices,
        initial_close_ask_prices,
        symbols=symbols,
    )
    previous_close_timestamp = pd.Timestamp(initial_close_timestamp)
    if previous_close_timestamp.tzinfo is None:
        raise ValueError("initial_close_timestamp must be timezone-aware")
    previous_close_timestamp = previous_close_timestamp.tz_convert("UTC")
    nav = float(initial_nav)
    if not math.isfinite(nav) or nav <= 0:
        raise ValueError("initial_nav must be finite and positive")
    if previous_close_timestamp >= timestamps.iloc[0]["rollover_timestamp"]:
        raise ValueError("initial close must precede the first rollover")

    all_trades: list[TwoStageTrade] = []
    ledgers: list[TwoStageSessionLedger] = []
    symbol_audits: list[SessionSymbolAudit] = []
    target_audits: list[TargetQuantityAudit] = []
    positions = starting_positions.astype(float, copy=True)
    for row_number, session in enumerate(sessions):
        event_row = timestamps.loc[session]
        rollover_timestamp = event_row["rollover_timestamp"]
        open_timestamp = event_row["open_timestamp"]
        close_timestamp = event_row["close_timestamp"]
        if previous_close_timestamp >= rollover_timestamp:
            raise ValueError(
                f"{session}: previous close must strictly precede rollover"
            )

        open_bid = open_bids.loc[session].to_numpy(dtype=float)
        open_ask = open_asks.loc[session].to_numpy(dtype=float)
        close_bid = close_bids.loc[session].to_numpy(dtype=float)
        close_ask = close_asks.loc[session].to_numpy(dtype=float)
        open_mid = open_bid + (open_ask - open_bid) / 2.0
        close_mid = close_bid + (close_ask - close_bid) / 2.0
        open_multiplier = frames["open_account_value_multipliers"].loc[
            session
        ].to_numpy(dtype=float)
        close_multiplier = frames["close_account_value_multipliers"].loc[
            session
        ].to_numpy(dtype=float)
        long_financing = frames["long_financing_per_unit"].loc[session].to_numpy(
            dtype=float
        )
        short_financing = frames["short_financing_per_unit"].loc[
            session
        ].to_numpy(dtype=float)
        open_slippage = frames["open_adverse_slippage_per_unit"].loc[
            session
        ].to_numpy(dtype=float)
        close_slippage = frames["close_adverse_slippage_per_unit"].loc[
            session
        ].to_numpy(dtype=float)

        previous_positions = positions.copy()
        overnight_parts = (
            previous_positions * (open_mid - previous_close_mids) * open_multiplier
        )
        financing_parts = np.where(
            previous_positions > 0,
            previous_positions * long_financing,
            np.where(
                previous_positions < 0,
                np.abs(previous_positions) * short_financing,
                0.0,
            ),
        )
        overnight_pnl = math.fsum(float(value) for value in overnight_parts)
        financing = math.fsum(float(value) for value in financing_parts)
        interest = float(daily_cash_interest.loc[session])
        nav_before_open = math.fsum((nav, overnight_pnl, financing, interest))

        open_target = open_targets[row_number].copy()
        open_trades, open_deltas, open_spreads, open_slippages = _make_trades(
            session=session,
            timestamp=open_timestamp,
            phase="open",
            symbols=symbols,
            previous=previous_positions,
            target=open_target,
            bids=open_bid,
            asks=open_ask,
            slippage=open_slippage,
            multipliers=open_multiplier,
        )
        open_spread_cost = math.fsum(float(value) for value in open_spreads)
        open_slippage_cost = math.fsum(float(value) for value in open_slippages)
        nav_after_open = math.fsum(
            (nav_before_open, -open_spread_cost, -open_slippage_cost)
        )

        intraday_parts = open_target * (close_mid - open_mid) * close_multiplier
        intraday_pnl = math.fsum(float(value) for value in intraday_parts)
        nav_before_close = nav_after_open + intraday_pnl

        close_target = close_targets[row_number].copy()
        close_trades, close_deltas, close_spreads, close_slippages = _make_trades(
            session=session,
            timestamp=close_timestamp,
            phase="close",
            symbols=symbols,
            previous=open_target,
            target=close_target,
            bids=close_bid,
            asks=close_ask,
            slippage=close_slippage,
            multipliers=close_multiplier,
        )
        close_spread_cost = math.fsum(float(value) for value in close_spreads)
        close_slippage_cost = math.fsum(float(value) for value in close_slippages)
        net_pnl = math.fsum(
            (
                overnight_pnl,
                financing,
                interest,
                -open_spread_cost,
                -open_slippage_cost,
                intraday_pnl,
                -close_spread_cost,
                -close_slippage_cost,
            )
        )
        final_session_nav = nav + net_pnl
        positions_before = {
            symbol: float(previous_positions[location])
            for location, symbol in enumerate(symbols)
        }
        positions_open = {
            symbol: float(open_target[location])
            for location, symbol in enumerate(symbols)
        }
        positions_close = {
            symbol: float(close_target[location])
            for location, symbol in enumerate(symbols)
        }
        ledger = TwoStageSessionLedger(
            session=session,
            previous_close_timestamp=previous_close_timestamp,
            rollover_timestamp=rollover_timestamp,
            open_timestamp=open_timestamp,
            close_timestamp=close_timestamp,
            previous_nav=nav,
            previous_close_positions=positions_before,
            overnight_price_pnl=overnight_pnl,
            financing=financing,
            cash_interest=interest,
            nav_before_open_execution=nav_before_open,
            open_target_positions=positions_open,
            open_spread_cost=open_spread_cost,
            open_slippage_cost=open_slippage_cost,
            nav_after_open_execution=nav_after_open,
            intraday_price_pnl=intraday_pnl,
            nav_before_close_execution=nav_before_close,
            close_target_positions=positions_close,
            close_spread_cost=close_spread_cost,
            close_slippage_cost=close_slippage_cost,
            net_pnl=net_pnl,
            nav=final_session_nav,
            simple_return=net_pnl / nav,
            open_broker_turnover=math.fsum(abs(float(value)) for value in open_deltas),
            close_broker_turnover=math.fsum(abs(float(value)) for value in close_deltas),
        )
        ledgers.append(ledger)
        all_trades.extend(open_trades)
        all_trades.extend(close_trades)

        for location, symbol in enumerate(symbols):
            symbol_audits.append(
                SessionSymbolAudit(
                    session=session,
                    symbol=symbol,
                    previous_close_quantity=float(previous_positions[location]),
                    previous_close_mid=float(previous_close_mids[location]),
                    open_bid=float(open_bid[location]),
                    open_ask=float(open_ask[location]),
                    open_mid=float(open_mid[location]),
                    open_account_value_multiplier=float(open_multiplier[location]),
                    long_financing_per_unit=float(long_financing[location]),
                    short_financing_per_unit=float(short_financing[location]),
                    overnight_price_pnl=float(overnight_parts[location]),
                    financing=float(financing_parts[location]),
                    open_target_quantity=float(open_target[location]),
                    open_trade_quantity=float(open_deltas[location]),
                    open_spread_cost=float(open_spreads[location]),
                    open_slippage_cost=float(open_slippages[location]),
                    close_bid=float(close_bid[location]),
                    close_ask=float(close_ask[location]),
                    close_mid=float(close_mid[location]),
                    close_account_value_multiplier=float(close_multiplier[location]),
                    intraday_price_pnl=float(intraday_parts[location]),
                    close_target_quantity=float(close_target[location]),
                    close_trade_quantity=float(close_deltas[location]),
                    close_spread_cost=float(close_spreads[location]),
                    close_slippage_cost=float(close_slippages[location]),
                )
            )
        for phase, components in (
            ("open", open_components),
            ("close", close_components),
        ):
            for component, panel in components.items():
                for symbol in symbols:
                    target_audits.append(
                        TargetQuantityAudit(
                            session=session,
                            phase=phase,
                            component=component,
                            symbol=symbol,
                            target_quantity=float(panel.loc[session, symbol]),
                        )
                    )

        nav = final_session_nav
        positions = close_target
        previous_close_mids = close_mid
        previous_close_timestamp = close_timestamp

    return LongHorizonExecutionResult(
        initial_nav=float(initial_nav),
        final_nav=nav,
        entries=tuple(ledgers),
        trades=tuple(all_trades),
        symbol_audit=tuple(symbol_audits),
        target_quantity_audit=tuple(target_audits),
    )


__all__ = [
    "LongHorizonExecutionResult",
    "SessionSymbolAudit",
    "TargetQuantityAudit",
    "TwoStageSessionLedger",
    "TwoStageTrade",
    "run_long_horizon_execution",
]
