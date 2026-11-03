from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

import pandas as pd


def _utc_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _finite(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _symbol_values(
    values: Mapping[str, float],
    name: str,
    *,
    minimum: float | None = None,
    strictly_positive: bool = False,
    drop_zero: bool = False,
) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for raw_symbol, raw_value in values.items():
        symbol = str(raw_symbol).strip().upper()
        if not symbol:
            raise ValueError(f"{name} symbols cannot be empty")
        if symbol in normalized:
            raise ValueError(f"{name} contains duplicate normalized symbol {symbol}")
        value = _finite(raw_value, f"{name}[{symbol}]")
        if strictly_positive and value <= 0:
            raise ValueError(f"{name}[{symbol}] must be positive")
        if minimum is not None and value < minimum:
            raise ValueError(f"{name}[{symbol}] must be at least {minimum}")
        if not drop_zero or value != 0.0:
            normalized[symbol] = value
    return normalized


def _required(mapping: Mapping[str, float], symbol: str, name: str) -> float:
    try:
        return mapping[symbol]
    except KeyError as error:
        raise ValueError(f"{name} is missing {symbol}") from error


def _account_value_multipliers(
    values: Mapping[str, float] | None,
) -> dict[str, float]:
    if values is None:
        return {}
    return _symbol_values(values, "account_value_multipliers", strictly_positive=True)


@dataclass(frozen=True)
class DailyLedgerEntry:
    """One close-to-close master-account accounting interval.

    Positions are master-account net quantities, not sleeve quantities. Price
    PnL is earned by ``previous_positions`` from the previous mid mark to the
    current mid mark; the net trade into ``target_positions`` then executes at
    the current mark. All PnL fields and NAV must use one account currency.

    ``broker_turnover`` is one-way broker quantity, ``sum(abs(delta_q))``. A
    reversal from ``+q`` to ``-q`` therefore contributes ``2 * abs(q)``.
    """

    timestamp: pd.Timestamp
    execution_mode: Literal["mid_plus_half_spread", "bid_ask"]
    previous_nav: float
    previous_positions: Mapping[str, float]
    target_positions: Mapping[str, float]
    net_trades: Mapping[str, float]
    price_pnl: float
    spread_cost: float
    slippage_cost: float
    financing: float
    cash_interest: float
    net_pnl: float
    nav: float
    simple_return: float
    broker_turnover: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", _utc_timestamp(self.timestamp))
        for name in ("previous_positions", "target_positions", "net_trades"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))


def _prepare_day(
    *,
    previous_nav: float,
    previous_positions: Mapping[str, float],
    target_positions: Mapping[str, float],
    previous_mid_prices: Mapping[str, float],
    mid_prices: Mapping[str, float],
    account_value_multipliers: Mapping[str, float] | None,
) -> tuple[
    float,
    dict[str, float],
    dict[str, float],
    dict[str, float],
    dict[str, float],
    dict[str, float],
    dict[str, float],
]:
    nav = _finite(previous_nav, "previous_nav")
    if nav <= 0:
        raise ValueError("previous_nav must be positive")

    previous = _symbol_values(
        previous_positions, "previous_positions", drop_zero=True
    )
    target = _symbol_values(target_positions, "target_positions", drop_zero=True)
    previous_mids = _symbol_values(
        previous_mid_prices, "previous_mid_prices", strictly_positive=True
    )
    mids = _symbol_values(mid_prices, "mid_prices", strictly_positive=True)
    multipliers = _account_value_multipliers(account_value_multipliers)

    symbols = sorted(set(previous) | set(target))
    trades: dict[str, float] = {}
    for symbol in symbols:
        delta = target.get(symbol, 0.0) - previous.get(symbol, 0.0)
        if delta != 0.0:
            trades[symbol] = delta
        _required(mids, symbol, "mid_prices")

    for symbol in previous:
        _required(previous_mids, symbol, "previous_mid_prices")

    return nav, previous, target, trades, previous_mids, mids, multipliers


def _multiplier(multipliers: Mapping[str, float], symbol: str) -> float:
    return multipliers.get(symbol, 1.0)


def _price_pnl(
    previous_positions: Mapping[str, float],
    previous_mids: Mapping[str, float],
    mids: Mapping[str, float],
    multipliers: Mapping[str, float],
) -> float:
    return math.fsum(
        quantity
        * (_required(mids, symbol, "mid_prices") - previous_mids[symbol])
        * _multiplier(multipliers, symbol)
        for symbol, quantity in previous_positions.items()
    )


def _slippage_cost(
    trades: Mapping[str, float],
    slippage_per_unit: Mapping[str, float] | None,
    multipliers: Mapping[str, float],
) -> float:
    slippage = _symbol_values(
        slippage_per_unit or {}, "slippage_per_unit", minimum=0.0
    )
    return math.fsum(
        abs(delta) * slippage.get(symbol, 0.0) * _multiplier(multipliers, symbol)
        for symbol, delta in trades.items()
    )


def _entry(
    *,
    timestamp: Any,
    execution_mode: Literal["mid_plus_half_spread", "bid_ask"],
    previous_nav: float,
    previous_positions: Mapping[str, float],
    target_positions: Mapping[str, float],
    trades: Mapping[str, float],
    price_pnl: float,
    spread_cost: float,
    slippage_cost: float,
    financing: float,
    cash_interest: float,
) -> DailyLedgerEntry:
    financing_value = _finite(financing, "financing")
    interest_value = _finite(cash_interest, "cash_interest")
    net_pnl = math.fsum(
        (price_pnl, -spread_cost, -slippage_cost, financing_value, interest_value)
    )
    nav = previous_nav + net_pnl
    return DailyLedgerEntry(
        timestamp=_utc_timestamp(timestamp),
        execution_mode=execution_mode,
        previous_nav=previous_nav,
        previous_positions=previous_positions,
        target_positions=target_positions,
        net_trades=trades,
        price_pnl=price_pnl,
        spread_cost=spread_cost,
        slippage_cost=slippage_cost,
        financing=financing_value,
        cash_interest=interest_value,
        net_pnl=net_pnl,
        nav=nav,
        simple_return=net_pnl / previous_nav,
        broker_turnover=math.fsum(abs(delta) for delta in trades.values()),
    )


def book_day_mid_plus_half_spread(
    *,
    timestamp: Any,
    previous_nav: float,
    previous_positions: Mapping[str, float],
    target_positions: Mapping[str, float],
    previous_mid_prices: Mapping[str, float],
    mid_prices: Mapping[str, float],
    half_spreads: Mapping[str, float],
    slippage_per_unit: Mapping[str, float] | None = None,
    financing: float = 0.0,
    cash_interest: float = 0.0,
    account_value_multipliers: Mapping[str, float] | None = None,
) -> DailyLedgerEntry:
    """Book a day from mid marks and one explicit half-spread per net trade.

    ``half_spreads`` and ``slippage_per_unit`` are adverse price distances.
    ``account_value_multipliers`` converts one unit of price PnL into the
    account currency. It defaults to one for inputs already denominated in the
    account currency.
    """
    (
        nav,
        previous,
        target,
        trades,
        previous_mids,
        mids,
        multipliers,
    ) = _prepare_day(
        previous_nav=previous_nav,
        previous_positions=previous_positions,
        target_positions=target_positions,
        previous_mid_prices=previous_mid_prices,
        mid_prices=mid_prices,
        account_value_multipliers=account_value_multipliers,
    )
    spreads = _symbol_values(half_spreads, "half_spreads", minimum=0.0)
    for symbol in trades:
        _required(spreads, symbol, "half_spreads")

    price_pnl = _price_pnl(previous, previous_mids, mids, multipliers)
    spread_cost = math.fsum(
        abs(delta) * spreads[symbol] * _multiplier(multipliers, symbol)
        for symbol, delta in trades.items()
    )
    slippage_cost = _slippage_cost(trades, slippage_per_unit, multipliers)
    return _entry(
        timestamp=timestamp,
        execution_mode="mid_plus_half_spread",
        previous_nav=nav,
        previous_positions=previous,
        target_positions=target,
        trades=trades,
        price_pnl=price_pnl,
        spread_cost=spread_cost,
        slippage_cost=slippage_cost,
        financing=financing,
        cash_interest=cash_interest,
    )


def book_day_bid_ask(
    *,
    timestamp: Any,
    previous_nav: float,
    previous_positions: Mapping[str, float],
    target_positions: Mapping[str, float],
    previous_mid_prices: Mapping[str, float],
    mid_prices: Mapping[str, float],
    bids: Mapping[str, float],
    asks: Mapping[str, float],
    slippage_per_unit: Mapping[str, float] | None = None,
    financing: float = 0.0,
    cash_interest: float = 0.0,
    account_value_multipliers: Mapping[str, float] | None = None,
) -> DailyLedgerEntry:
    """Book a day using executable ask for buys and bid for sells.

    Spread cost is extracted from those executable sides relative to the mid;
    no additional fixed spread is deducted. Quotes must satisfy
    ``bid <= mid <= ask`` for every traded symbol.
    """
    (
        nav,
        previous,
        target,
        trades,
        previous_mids,
        mids,
        multipliers,
    ) = _prepare_day(
        previous_nav=previous_nav,
        previous_positions=previous_positions,
        target_positions=target_positions,
        previous_mid_prices=previous_mid_prices,
        mid_prices=mid_prices,
        account_value_multipliers=account_value_multipliers,
    )
    bid_prices = _symbol_values(bids, "bids", strictly_positive=True)
    ask_prices = _symbol_values(asks, "asks", strictly_positive=True)

    spread_parts: list[float] = []
    for symbol, delta in trades.items():
        bid = _required(bid_prices, symbol, "bids")
        ask = _required(ask_prices, symbol, "asks")
        mid = mids[symbol]
        if bid > ask:
            raise ValueError(f"{symbol}: bid cannot exceed ask")
        if not bid <= mid <= ask:
            raise ValueError(f"{symbol}: mid must lie between bid and ask")
        executable_price = ask if delta > 0 else bid
        implicit_cost = delta * (executable_price - mid)
        spread_parts.append(implicit_cost * _multiplier(multipliers, symbol))

    price_pnl = _price_pnl(previous, previous_mids, mids, multipliers)
    spread_cost = math.fsum(spread_parts)
    slippage_cost = _slippage_cost(trades, slippage_per_unit, multipliers)
    return _entry(
        timestamp=timestamp,
        execution_mode="bid_ask",
        previous_nav=nav,
        previous_positions=previous,
        target_positions=target,
        trades=trades,
        price_pnl=price_pnl,
        spread_cost=spread_cost,
        slippage_cost=slippage_cost,
        financing=financing,
        cash_interest=cash_interest,
    )


class MasterAccountLedger:
    """Small stateful wrapper over the two pure daily accounting functions."""

    def __init__(
        self,
        *,
        initial_nav: float,
        initial_positions: Mapping[str, float] | None = None,
        initial_mid_prices: Mapping[str, float] | None = None,
    ) -> None:
        self.initial_nav = _finite(initial_nav, "initial_nav")
        if self.initial_nav <= 0:
            raise ValueError("initial_nav must be positive")
        self._nav = self.initial_nav
        self._positions = _symbol_values(
            initial_positions or {}, "initial_positions", drop_zero=True
        )
        self._mid_prices = _symbol_values(
            initial_mid_prices or {}, "initial_mid_prices", strictly_positive=True
        )
        for symbol in self._positions:
            _required(self._mid_prices, symbol, "initial_mid_prices")
        self._entries: list[DailyLedgerEntry] = []

    @property
    def nav(self) -> float:
        return self._nav

    @property
    def positions(self) -> Mapping[str, float]:
        return MappingProxyType(dict(self._positions))

    @property
    def entries(self) -> tuple[DailyLedgerEntry, ...]:
        return tuple(self._entries)

    @property
    def compounded_return(self) -> float:
        return self.nav / self.initial_nav - 1.0

    def _append(self, entry: DailyLedgerEntry, mid_prices: Mapping[str, float]) -> None:
        if self._entries and entry.timestamp <= self._entries[-1].timestamp:
            raise ValueError("ledger timestamps must be strictly increasing")
        self._entries.append(entry)
        self._nav = entry.nav
        self._positions = dict(entry.target_positions)
        self._mid_prices.update(
            _symbol_values(mid_prices, "mid_prices", strictly_positive=True)
        )

    def book_mid_plus_half_spread(
        self,
        *,
        timestamp: Any,
        target_positions: Mapping[str, float],
        mid_prices: Mapping[str, float],
        half_spreads: Mapping[str, float],
        slippage_per_unit: Mapping[str, float] | None = None,
        financing: float = 0.0,
        cash_interest: float = 0.0,
        account_value_multipliers: Mapping[str, float] | None = None,
    ) -> DailyLedgerEntry:
        entry = book_day_mid_plus_half_spread(
            timestamp=timestamp,
            previous_nav=self._nav,
            previous_positions=self._positions,
            target_positions=target_positions,
            previous_mid_prices=self._mid_prices,
            mid_prices=mid_prices,
            half_spreads=half_spreads,
            slippage_per_unit=slippage_per_unit,
            financing=financing,
            cash_interest=cash_interest,
            account_value_multipliers=account_value_multipliers,
        )
        self._append(entry, mid_prices)
        return entry

    def book_bid_ask(
        self,
        *,
        timestamp: Any,
        target_positions: Mapping[str, float],
        mid_prices: Mapping[str, float],
        bids: Mapping[str, float],
        asks: Mapping[str, float],
        slippage_per_unit: Mapping[str, float] | None = None,
        financing: float = 0.0,
        cash_interest: float = 0.0,
        account_value_multipliers: Mapping[str, float] | None = None,
    ) -> DailyLedgerEntry:
        entry = book_day_bid_ask(
            timestamp=timestamp,
            previous_nav=self._nav,
            previous_positions=self._positions,
            target_positions=target_positions,
            previous_mid_prices=self._mid_prices,
            mid_prices=mid_prices,
            bids=bids,
            asks=asks,
            slippage_per_unit=slippage_per_unit,
            financing=financing,
            cash_interest=cash_interest,
            account_value_multipliers=account_value_multipliers,
        )
        self._append(entry, mid_prices)
        return entry

    def to_frame(self) -> pd.DataFrame:
        columns: Sequence[str] = (
            "execution_mode",
            "previous_nav",
            "price_pnl",
            "spread_cost",
            "slippage_cost",
            "financing",
            "cash_interest",
            "net_pnl",
            "nav",
            "simple_return",
            "broker_turnover",
        )
        rows = [
            {column: getattr(entry, column) for column in columns} | {"timestamp": entry.timestamp}
            for entry in self._entries
        ]
        if not rows:
            return pd.DataFrame(columns=columns).rename_axis("timestamp")
        return pd.DataFrame(rows).set_index("timestamp")
