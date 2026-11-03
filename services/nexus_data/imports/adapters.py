"""I/O-free source adapter interfaces for historical and live data."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator, Iterable, Protocol

from .contracts import CanonicalOHLCV, CanonicalTick


@dataclass(frozen=True, slots=True)
class HistoricalRequest:
    symbol: str
    start: datetime
    end: datetime
    timeframe: str | None = None
    limit: int | None = None


@dataclass(frozen=True, slots=True)
class LiveRequest:
    symbols: tuple[str, ...]
    timeframe: str | None = None


class HistoricalSourceAdapter(Protocol):
    """Interface implemented by a historical source without prescribing I/O."""

    @property
    def source_name(self) -> str: ...

    def fetch_ohlcv(self, request: HistoricalRequest) -> Iterable[CanonicalOHLCV]: ...

    def fetch_ticks(self, request: HistoricalRequest) -> Iterable[CanonicalTick]: ...


class LiveSourceAdapter(Protocol):
    """Interface implemented by a live source without owning its transport."""

    @property
    def source_name(self) -> str: ...

    def stream_ohlcv(self, request: LiveRequest) -> AsyncIterator[CanonicalOHLCV]: ...

    def stream_ticks(self, request: LiveRequest) -> AsyncIterator[CanonicalTick]: ...
