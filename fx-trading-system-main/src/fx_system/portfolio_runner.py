from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd

from fx_system.portfolio import (
    CommonSessionCalendar,
    OverlappingSleevePortfolio,
    PortfolioTransition,
)
from fx_system.portfolio_ledger import DailyLedgerEntry, MasterAccountLedger


def _utc_session(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.normalize()


def _normalized_symbols(values: Mapping[str, float]) -> dict[str, float]:
    result: dict[str, float] = {}
    for raw_symbol, raw_value in values.items():
        symbol = str(raw_symbol).strip().upper()
        if not symbol:
            raise ValueError("target symbols cannot be empty")
        if symbol in result:
            raise ValueError(f"target contains duplicate normalized symbol {symbol}")
        value = float(raw_value)
        if not math.isfinite(value):
            raise ValueError(f"{symbol}: target weight must be finite")
        if value != 0.0:
            result[symbol] = value
    if math.fsum(abs(value) for value in result.values()) > 1.0 + 1e-12:
        raise ValueError("each sleeve target must have gross weight no greater than 1")
    return dict(sorted(result.items()))


def _normalize_targets(
    targets: Mapping[Any, Mapping[int, Mapping[str, float]]],
    calendar: CommonSessionCalendar,
    configured_horizons: set[int],
    rebalance_interval_sessions: int,
    anchor: Any | None,
) -> dict[pd.Timestamp, dict[int, dict[str, float]]]:
    normalized: dict[pd.Timestamp, dict[int, dict[str, float]]] = {}
    anchor_label = calendar.sessions[0] if anchor is None else _utc_session(anchor)
    anchor_location = calendar.location(anchor_label)
    for raw_session, raw_horizons in targets.items():
        session = _utc_session(raw_session)
        if session in normalized:
            raise ValueError(f"duplicate normalized target session: {session.date()}")
        location = calendar.location(session)
        if location < anchor_location or (
            location - anchor_location
        ) % rebalance_interval_sessions:
            raise ValueError(f"{session.date()}: target is not on an eligible rebalance session")

        horizons: dict[int, dict[str, float]] = {}
        for horizon, vector in raw_horizons.items():
            if horizon not in configured_horizons:
                raise ValueError(f"unconfigured horizon: {horizon}")
            horizons[horizon] = _normalized_symbols(vector)
        normalized[session] = dict(sorted(horizons.items()))
    return normalized


def _normalize_frame(
    frame: pd.DataFrame,
    *,
    name: str,
    calendar: CommonSessionCalendar,
    required_symbols: tuple[str, ...],
    strictly_positive: bool,
) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"{name} must be a pandas DataFrame")

    normalized = frame.copy()
    normalized.index = pd.DatetimeIndex([_utc_session(value) for value in normalized.index])
    if normalized.index.has_duplicates:
        raise ValueError(f"{name} contains duplicate normalized sessions")

    columns: list[str] = []
    for raw_column in normalized.columns:
        symbol = str(raw_column).strip().upper()
        if not symbol:
            raise ValueError(f"{name} symbols cannot be empty")
        columns.append(symbol)
    if len(columns) != len(set(columns)):
        raise ValueError(f"{name} contains duplicate normalized symbols")
    normalized.columns = columns

    missing_sessions = calendar.sessions.difference(normalized.index)
    if not missing_sessions.empty:
        dates = ", ".join(str(value.date()) for value in missing_sessions[:3])
        raise ValueError(f"{name} is missing common sessions: {dates}")
    missing_symbols = sorted(set(required_symbols).difference(normalized.columns))
    if missing_symbols:
        raise ValueError(f"{name} is missing symbols: {missing_symbols}")

    normalized = normalized.reindex(index=calendar.sessions, columns=list(required_symbols))
    if normalized.empty and required_symbols:
        raise ValueError(f"{name} cannot be empty")
    normalized = normalized.apply(pd.to_numeric, errors="coerce")
    if normalized.isna().any(axis=None):
        raise ValueError(f"{name} contains missing or non-numeric common observations")
    values = normalized.to_numpy(dtype=float)
    if not all(math.isfinite(float(value)) for value in values.ravel()):
        raise ValueError(f"{name} must contain only finite observations")
    if strictly_positive and (values <= 0).any():
        raise ValueError(f"{name} observations must be positive")
    if not strictly_positive and (values < 0).any():
        raise ValueError(f"{name} observations must be non-negative")
    return normalized


def _normalize_daily_values(
    values: pd.Series | Mapping[Any, float] | None,
    *,
    name: str,
    calendar: CommonSessionCalendar,
) -> pd.Series:
    if values is None:
        return pd.Series(0.0, index=calendar.sessions, dtype=float, name=name)
    series = values.copy() if isinstance(values, pd.Series) else pd.Series(dict(values))
    series.index = pd.DatetimeIndex([_utc_session(value) for value in series.index])
    if series.index.has_duplicates:
        raise ValueError(f"{name} contains duplicate normalized sessions")
    missing = calendar.sessions.difference(series.index)
    if not missing.empty:
        dates = ", ".join(str(value.date()) for value in missing[:3])
        raise ValueError(f"{name} is missing common sessions: {dates}")
    series = pd.to_numeric(series.reindex(calendar.sessions), errors="coerce")
    if series.isna().any() or not all(math.isfinite(float(value)) for value in series):
        raise ValueError(f"{name} must contain finite values for every common session")
    return series.astype(float)


def _normalize_static_multipliers(
    values: Mapping[str, float], required_symbols: tuple[str, ...]
) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for raw_symbol, raw_value in values.items():
        symbol = str(raw_symbol).strip().upper()
        if not symbol:
            raise ValueError("account_value_multipliers symbols cannot be empty")
        if symbol in normalized:
            raise ValueError(
                f"account_value_multipliers contains duplicate normalized symbol {symbol}"
            )
        value = float(raw_value)
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"account_value_multipliers[{symbol}] must be finite and positive")
        normalized[symbol] = value
    missing = sorted(set(required_symbols).difference(normalized))
    if missing:
        raise ValueError(f"account_value_multipliers is missing symbols: {missing}")
    return dict(sorted(normalized.items()))


@dataclass(frozen=True)
class SkippedSleeveTarget:
    """A non-empty target not opened because its full holding period is unavailable."""

    session: pd.Timestamp
    horizon_sessions: int
    reason: str = "insufficient_common_sessions_for_expiry"

    def __post_init__(self) -> None:
        object.__setattr__(self, "session", _utc_session(self.session))


@dataclass(frozen=True)
class PortfolioRunResult:
    """Synthetic end-to-end result with both transition and accounting audit trails."""

    ledger: MasterAccountLedger
    transitions: tuple[PortfolioTransition, ...]
    skipped_targets: tuple[SkippedSleeveTarget, ...]

    @property
    def entries(self) -> tuple[DailyLedgerEntry, ...]:
        return self.ledger.entries

    @property
    def final_nav(self) -> float:
        return self.ledger.nav

    def to_frame(self) -> pd.DataFrame:
        return self.ledger.to_frame()


def run_portfolio(
    *,
    calendar: CommonSessionCalendar,
    horizon_budgets: Mapping[int, float],
    targets_by_rebalance: Mapping[Any, Mapping[int, Mapping[str, float]]],
    mid_prices: pd.DataFrame,
    initial_nav: float = 1.0,
    rebalance_interval_sessions: int = 21,
    capital_limit: float = 1.0,
    anchor: Any | None = None,
    half_spreads: pd.DataFrame | None = None,
    bids: pd.DataFrame | None = None,
    asks: pd.DataFrame | None = None,
    slippage_per_unit: pd.DataFrame | None = None,
    financing: pd.Series | Mapping[Any, float] | None = None,
    cash_interest: pd.Series | Mapping[Any, float] | None = None,
    account_value_multipliers: Mapping[str, float] | pd.DataFrame | None = None,
) -> PortfolioRunResult:
    """Run overlapping targets through one daily, cost-adjusted master ledger.

    Every common session is booked, including flat cash-only sessions. Sleeve
    allocations are aggregated before the ledger sees a target, so spread is
    charged exactly once on the master account's net position change. Targets
    whose expiry would fall beyond ``calendar`` are skipped rather than opened.

    Supply either ``bids`` and ``asks`` together, or optional ``half_spreads``.
    When no execution quotes/spreads are supplied, trades execute at mid with
    zero spread cost. ``slippage_per_unit`` is an adverse price distance charged
    only on the master account's net quantity change. A daily multiplier frame
    can translate price, spread, and slippage PnL into the account currency; a
    static symbol mapping remains supported. All supplied daily inputs must
    explicitly cover every common session and required symbol. Financing and
    cash interest are already account-currency daily PnL amounts.
    """
    if (bids is None) != (asks is None):
        raise ValueError("bids and asks must be supplied together")
    if bids is not None and half_spreads is not None:
        raise ValueError("half_spreads cannot be combined with executable bids and asks")

    portfolio = OverlappingSleevePortfolio(
        calendar,
        horizon_budgets,
        rebalance_interval_sessions=rebalance_interval_sessions,
        capital_limit=capital_limit,
        anchor=anchor,
    )
    targets = _normalize_targets(
        targets_by_rebalance,
        calendar,
        set(portfolio.horizon_budgets),
        rebalance_interval_sessions,
        anchor,
    )
    target_symbols = {
        symbol
        for horizons in targets.values()
        for vector in horizons.values()
        for symbol in vector
    }
    required_symbols = tuple(
        sorted(target_symbols | {str(symbol).strip().upper() for symbol in calendar.symbols})
    )

    mids = _normalize_frame(
        mid_prices,
        name="mid_prices",
        calendar=calendar,
        required_symbols=required_symbols,
        strictly_positive=True,
    )
    spreads = None
    bid_prices = None
    ask_prices = None
    if half_spreads is not None:
        spreads = _normalize_frame(
            half_spreads,
            name="half_spreads",
            calendar=calendar,
            required_symbols=required_symbols,
            strictly_positive=False,
        )
    elif bids is not None and asks is not None:
        bid_prices = _normalize_frame(
            bids,
            name="bids",
            calendar=calendar,
            required_symbols=required_symbols,
            strictly_positive=True,
        )
        ask_prices = _normalize_frame(
            asks,
            name="asks",
            calendar=calendar,
            required_symbols=required_symbols,
            strictly_positive=True,
        )

    slippage = None
    if slippage_per_unit is not None:
        slippage = _normalize_frame(
            slippage_per_unit,
            name="slippage_per_unit",
            calendar=calendar,
            required_symbols=required_symbols,
            strictly_positive=False,
        )

    daily_multipliers = None
    static_multipliers = None
    if isinstance(account_value_multipliers, pd.DataFrame):
        daily_multipliers = _normalize_frame(
            account_value_multipliers,
            name="account_value_multipliers",
            calendar=calendar,
            required_symbols=required_symbols,
            strictly_positive=True,
        )
    elif account_value_multipliers is not None:
        static_multipliers = _normalize_static_multipliers(
            account_value_multipliers, required_symbols
        )

    daily_financing = _normalize_daily_values(financing, name="financing", calendar=calendar)
    daily_cash_interest = _normalize_daily_values(
        cash_interest, name="cash_interest", calendar=calendar
    )

    ledger = MasterAccountLedger(initial_nav=initial_nav)
    transitions: list[PortfolioTransition] = []
    skipped: list[SkippedSleeveTarget] = []
    rebalance_sessions = set(
        portfolio.calendar.rebalance_sessions(
            rebalance_interval_sessions, anchor=portfolio.anchor
        )
    )

    for session in calendar.sessions:
        if session in rebalance_sessions:
            opening_targets: dict[int, dict[str, float]] = {}
            location = calendar.location(session)
            for horizon, vector in targets.get(session, {}).items():
                if vector and location + horizon >= len(calendar.sessions):
                    skipped.append(SkippedSleeveTarget(session, horizon))
                else:
                    opening_targets[horizon] = vector
            transitions.append(portfolio.rebalance(session, opening_targets))

        mid_row = mids.loc[session].to_dict()
        common = {
            "timestamp": session,
            "target_positions": portfolio.target,
            "mid_prices": mid_row,
            "financing": float(daily_financing.loc[session]),
            "cash_interest": float(daily_cash_interest.loc[session]),
            "slippage_per_unit": (
                slippage.loc[session].to_dict() if slippage is not None else None
            ),
            "account_value_multipliers": (
                daily_multipliers.loc[session].to_dict()
                if daily_multipliers is not None
                else static_multipliers
            ),
        }
        if bid_prices is not None and ask_prices is not None:
            ledger.book_bid_ask(
                **common,
                bids=bid_prices.loc[session].to_dict(),
                asks=ask_prices.loc[session].to_dict(),
            )
        else:
            ledger.book_mid_plus_half_spread(
                **common,
                half_spreads=(
                    spreads.loc[session].to_dict()
                    if spreads is not None
                    else {symbol: 0.0 for symbol in required_symbols}
                ),
            )

    return PortfolioRunResult(
        ledger=ledger,
        transitions=tuple(transitions),
        skipped_targets=tuple(skipped),
    )
