from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import pandas as pd

_TOLERANCE = 1e-12


def _utc_session(value: Any) -> pd.Timestamp:
    """Return the UTC midnight label for a market session."""
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.normalize()


def _session_index(values: Iterable[Any]) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex(values)
    if index.empty:
        return pd.DatetimeIndex([], tz="UTC")
    if index.tz is None:
        index = index.tz_localize("UTC")
    else:
        index = index.tz_convert("UTC")
    return pd.DatetimeIndex(index.normalize().unique()).sort_values()


@dataclass(frozen=True)
class CommonSessionCalendar:
    """A deterministic, data-driven calendar shared by every traded symbol.

    Session labels are UTC dates. ``from_market_data`` includes a date only when
    every supplied symbol has at least one observation on that UTC date. Holding
    periods and expiries must therefore be counted on this single index rather
    than independently shifting each pair's price frame.
    """

    sessions: pd.DatetimeIndex
    symbols: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        normalized = _session_index(self.sessions)
        if normalized.empty:
            raise ValueError("common session calendar cannot be empty")
        object.__setattr__(self, "sessions", normalized)
        object.__setattr__(self, "symbols", tuple(sorted(set(self.symbols))))
        object.__setattr__(
            self,
            "_locations",
            MappingProxyType({timestamp: number for number, timestamp in enumerate(normalized)}),
        )

    @classmethod
    def from_market_data(
        cls,
        market_data: Mapping[str, pd.DataFrame | pd.Series | pd.DatetimeIndex | Sequence[Any]],
    ) -> CommonSessionCalendar:
        """Build the intersection of observed UTC session dates across symbols."""
        if not market_data:
            raise ValueError("market_data cannot be empty")

        common: pd.DatetimeIndex | None = None
        symbols: list[str] = []
        for symbol, source in sorted(market_data.items()):
            if not symbol:
                raise ValueError("market_data symbols cannot be empty")
            values = source.index if isinstance(source, (pd.DataFrame, pd.Series)) else source
            observed = _session_index(values)
            if observed.empty:
                raise ValueError(f"{symbol}: no observed sessions")
            common = observed if common is None else common.intersection(observed, sort=True)
            symbols.append(symbol)

        if common is None or common.empty:
            raise ValueError("symbols have no common observed sessions")
        return cls(common, tuple(symbols))

    def location(self, session: Any) -> int:
        label = _utc_session(session)
        try:
            return self._locations[label]  # type: ignore[attr-defined]
        except KeyError as error:
            raise ValueError(f"{label.date()}: not a common observed session") from error

    def advance(self, session: Any, session_count: int) -> pd.Timestamp:
        """Advance by an exact number of common sessions.

        The opening session is position zero, so a 21-session sleeve opened at
        ``sessions[0]`` expires at ``sessions[21]`` and is active on 21 session
        intervals: ``[sessions[0], sessions[21])``.
        """
        if not isinstance(session_count, int) or isinstance(session_count, bool):
            raise TypeError("session_count must be an integer")
        if session_count < 0:
            raise ValueError("session_count must be non-negative")
        start = self.location(session)
        destination = start + session_count
        if destination >= len(self.sessions):
            raise ValueError(
                f"insufficient common sessions to advance {session_count} sessions "
                f"from {self.sessions[start].date()}"
            )
        return self.sessions[destination]

    def rebalance_sessions(
        self,
        interval_sessions: int,
        *,
        anchor: Any | None = None,
    ) -> pd.DatetimeIndex:
        if not isinstance(interval_sessions, int) or isinstance(interval_sessions, bool):
            raise TypeError("interval_sessions must be an integer")
        if interval_sessions <= 0:
            raise ValueError("interval_sessions must be positive")
        start = 0 if anchor is None else self.location(anchor)
        return self.sessions[start::interval_sessions]


@dataclass(frozen=True)
class Sleeve:
    """One fixed-budget vintage of a horizon target."""

    horizon_sessions: int
    opened_session: pd.Timestamp
    expiry_session: pd.Timestamp
    slot_budget: float
    allocations: Mapping[str, float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "allocations", MappingProxyType(dict(self.allocations)))

    @property
    def gross_allocation(self) -> float:
        return math.fsum(abs(value) for value in self.allocations.values())


@dataclass(frozen=True)
class PortfolioTransition:
    """One master-account rebalance after sleeve netting.

    ``net_trade`` is the sole executable order vector. Transaction costs should
    be charged once against this vector. In particular, a downstream simulator
    using executable bid/ask returns must not add another spread charge.
    """

    session: pd.Timestamp
    previous_target: Mapping[str, float]
    target: Mapping[str, float]
    net_trade: Mapping[str, float]
    opened_sleeves: tuple[Sleeve, ...]
    expired_sleeves: tuple[Sleeve, ...]
    active_sleeves: tuple[Sleeve, ...]

    def __post_init__(self) -> None:
        for name in ("previous_target", "target", "net_trade"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    @property
    def one_way_turnover(self) -> float:
        """Absolute master-account position change; a full reversal is 2x."""
        return math.fsum(abs(value) for value in self.net_trade.values())

    @property
    def gross_target(self) -> float:
        return math.fsum(abs(value) for value in self.target.values())

    @property
    def committed_sleeve_gross(self) -> float:
        """Gross capital before cross-sleeve netting, used for budget audits."""
        return math.fsum(sleeve.gross_allocation for sleeve in self.active_sleeves)


def _clean_vector(values: Mapping[str, float]) -> dict[str, float]:
    cleaned: dict[str, float] = {}
    for raw_symbol, raw_value in values.items():
        symbol = str(raw_symbol).strip().upper()
        if not symbol:
            raise ValueError("target symbols cannot be empty")
        value = float(raw_value)
        if not math.isfinite(value):
            raise ValueError(f"{symbol}: target weight must be finite")
        if abs(value) > _TOLERANCE:
            cleaned[symbol] = value
    if math.fsum(abs(value) for value in cleaned.values()) > 1.0 + _TOLERANCE:
        raise ValueError("each sleeve target must have gross weight no greater than 1")
    return dict(sorted(cleaned.items()))


def _sum_vectors(vectors: Iterable[Mapping[str, float]]) -> dict[str, float]:
    vectors = tuple(vectors)
    symbols = sorted({symbol for vector in vectors for symbol in vector})
    result: dict[str, float] = {}
    for symbol in symbols:
        value = math.fsum(vector.get(symbol, 0.0) for vector in vectors)
        if abs(value) > _TOLERANCE:
            result[symbol] = value
    return result


class OverlappingSleevePortfolio:
    """Allocate overlapping slow-horizon vintages without warm-up leverage.

    A horizon of ``H`` common sessions and rebalance interval ``R`` requires
    ``H % R == 0`` and has ``H / R`` slots. Every new vintage receives exactly
    ``horizon_budget / slot_count`` capacity. During warm-up, unused future
    slots remain unused rather than being redistributed to active sleeves.
    """

    def __init__(
        self,
        calendar: CommonSessionCalendar,
        horizon_budgets: Mapping[int, float],
        *,
        rebalance_interval_sessions: int = 21,
        capital_limit: float = 1.0,
        anchor: Any | None = None,
    ) -> None:
        if not isinstance(rebalance_interval_sessions, int) or isinstance(
            rebalance_interval_sessions, bool
        ):
            raise TypeError("rebalance_interval_sessions must be an integer")
        if rebalance_interval_sessions <= 0:
            raise ValueError("rebalance_interval_sessions must be positive")
        if not math.isfinite(capital_limit) or capital_limit <= 0:
            raise ValueError("capital_limit must be finite and positive")
        if not horizon_budgets:
            raise ValueError("horizon_budgets cannot be empty")

        budgets: dict[int, float] = {}
        for horizon, raw_budget in horizon_budgets.items():
            if not isinstance(horizon, int) or isinstance(horizon, bool) or horizon <= 0:
                raise ValueError("horizon sessions must be positive integers")
            if horizon % rebalance_interval_sessions:
                raise ValueError(
                    f"horizon {horizon} must be an exact multiple of rebalance interval "
                    f"{rebalance_interval_sessions} (H % R must equal zero)"
                )
            budget = float(raw_budget)
            if not math.isfinite(budget) or budget <= 0:
                raise ValueError(f"horizon {horizon}: budget must be finite and positive")
            budgets[horizon] = budget
        if math.fsum(budgets.values()) > capital_limit + _TOLERANCE:
            raise ValueError("sum of horizon budgets exceeds capital_limit")

        self.calendar = calendar
        self.horizon_budgets = dict(sorted(budgets.items()))
        self.rebalance_interval_sessions = rebalance_interval_sessions
        self.capital_limit = float(capital_limit)
        self.anchor = calendar.sessions[0] if anchor is None else calendar.sessions[
            calendar.location(anchor)
        ]
        self._anchor_location = calendar.location(self.anchor)
        self._active_sleeves: list[Sleeve] = []
        self._target: dict[str, float] = {}
        self._last_session_location: int | None = None

    @property
    def active_sleeves(self) -> tuple[Sleeve, ...]:
        return tuple(self._active_sleeves)

    @property
    def target(self) -> Mapping[str, float]:
        return MappingProxyType(dict(self._target))

    def slot_count(self, horizon_sessions: int) -> int:
        try:
            self.horizon_budgets[horizon_sessions]
        except KeyError as error:
            raise ValueError(f"unconfigured horizon: {horizon_sessions}") from error
        return horizon_sessions // self.rebalance_interval_sessions

    def slot_budget(self, horizon_sessions: int) -> float:
        return self.horizon_budgets[horizon_sessions] / self.slot_count(horizon_sessions)

    def _validate_rebalance_session(self, session: Any) -> tuple[pd.Timestamp, int]:
        label = _utc_session(session)
        location = self.calendar.location(label)
        if location < self._anchor_location or (
            location - self._anchor_location
        ) % self.rebalance_interval_sessions:
            raise ValueError(f"{label.date()}: not an eligible rebalance session")
        if self._last_session_location is not None and location <= self._last_session_location:
            raise ValueError("rebalance sessions must be processed once in increasing order")
        return label, location

    def rebalance(
        self,
        session: Any,
        targets_by_horizon: Mapping[int, Mapping[str, float]],
    ) -> PortfolioTransition:
        """Expire, open, aggregate, then emit one net master-account trade.

        Target vectors are signed portfolio weights with gross weight at most
        one. Horizons omitted from ``targets_by_horizon`` simply do not open a
        new vintage on this rebalance.
        """
        label, location = self._validate_rebalance_session(session)
        unknown = set(targets_by_horizon).difference(self.horizon_budgets)
        if unknown:
            raise ValueError(f"unconfigured horizons: {sorted(unknown)}")

        # Validate all new sleeves before mutating state, including availability
        # of their complete expiry session.
        opened: list[Sleeve] = []
        for horizon in sorted(targets_by_horizon):
            weights = _clean_vector(targets_by_horizon[horizon])
            if not weights:
                continue
            expiry = self.calendar.advance(label, horizon)
            slot_budget = self.slot_budget(horizon)
            allocations = {
                symbol: weight * slot_budget for symbol, weight in weights.items()
            }
            opened.append(
                Sleeve(
                    horizon_sessions=horizon,
                    opened_session=label,
                    expiry_session=expiry,
                    slot_budget=slot_budget,
                    allocations=allocations,
                )
            )

        expired = [sleeve for sleeve in self._active_sleeves if sleeve.expiry_session <= label]
        retained = [sleeve for sleeve in self._active_sleeves if sleeve.expiry_session > label]
        proposed = [*retained, *opened]
        self._assert_capital_conservation(proposed)

        previous = dict(self._target)
        target = _sum_vectors(sleeve.allocations for sleeve in proposed)
        net_trade = _sum_vectors((target, {symbol: -value for symbol, value in previous.items()}))

        self._active_sleeves = proposed
        self._target = target
        self._last_session_location = location
        return PortfolioTransition(
            session=label,
            previous_target=previous,
            target=target,
            net_trade=net_trade,
            opened_sleeves=tuple(opened),
            expired_sleeves=tuple(expired),
            active_sleeves=tuple(proposed),
        )

    def _assert_capital_conservation(self, sleeves: Sequence[Sleeve]) -> None:
        by_horizon: dict[int, list[Sleeve]] = {}
        for sleeve in sleeves:
            by_horizon.setdefault(sleeve.horizon_sessions, []).append(sleeve)
        for horizon, horizon_sleeves in by_horizon.items():
            slots = self.slot_count(horizon)
            if len(horizon_sleeves) > slots:
                raise RuntimeError(f"horizon {horizon}: active sleeves exceed slot count")
            committed = math.fsum(sleeve.gross_allocation for sleeve in horizon_sleeves)
            if committed > self.horizon_budgets[horizon] + _TOLERANCE:
                raise RuntimeError(f"horizon {horizon}: sleeve allocations exceed budget")
        total = math.fsum(sleeve.gross_allocation for sleeve in sleeves)
        if total > self.capital_limit + _TOLERANCE:
            raise RuntimeError("active sleeve allocations exceed capital_limit")
