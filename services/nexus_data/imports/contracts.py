"""Canonical market-data contracts for CSV, JSON, and MetaTrader 5 rows.

This module deliberately contains no file, network, database, or broker I/O.
Source adapters provide mappings converted by pure normalization functions.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping, TypedDict


class DataKind(StrEnum):
    OHLCV = "ohlcv"
    TICK = "tick"


class SourceFormat(StrEnum):
    CSV = "csv"
    JSON = "json"
    MT5 = "mt5"


class CsvOHLCVRow(TypedDict, total=False):
    symbol: str
    timeframe: str
    timestamp: str | int | float
    open: str | float
    high: str | float
    low: str | float
    close: str | float
    volume: str | float


class CsvTickRow(TypedDict, total=False):
    symbol: str
    timestamp: str | int | float
    bid: str | float
    ask: str | float
    last: str | float
    bid_size: str | float
    ask_size: str | float
    last_size: str | float
    volume: str | float


class JsonOHLCVObject(CsvOHLCVRow, total=False):
    """JSON OHLCV contract; nested/enveloped JSON is adapter-owned."""


class JsonTickObject(CsvTickRow, total=False):
    """JSON tick contract; nested/enveloped JSON is adapter-owned."""


class Mt5OHLCVRow(TypedDict, total=False):
    symbol: str
    timeframe: str
    time: int | float
    time_msc: int | float
    open: float
    high: float
    low: float
    close: float
    tick_volume: int | float
    real_volume: int | float


class Mt5TickRow(TypedDict, total=False):
    symbol: str
    time: int | float
    time_msc: int | float
    bid: float
    ask: float
    last: float
    volume: int | float
    volume_real: int | float


CANONICAL_OHLCV_FIELDS: tuple[str, ...] = (
    "symbol", "timeframe", "timestamp", "open", "high", "low", "close",
    "volume", "session", "provenance",
)
CANONICAL_TICK_FIELDS: tuple[str, ...] = (
    "symbol", "timestamp", "bid", "ask", "last", "bid_size", "ask_size",
    "last_size", "volume", "session", "provenance",
)


@dataclass(frozen=True, slots=True)
class Provenance:
    """Record-level lineage retained through normalization and quarantine."""

    source_name: str
    source_format: SourceFormat
    source_uri: str | None = None
    source_checksum: str | None = None
    source_version: str | None = None
    raw_record_key: str | None = None
    observed_at: datetime | None = None
    adapter_name: str | None = None
    adapter_version: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_name.strip():
            raise ValueError("source_name must not be empty")
        if self.observed_at is not None and self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class CanonicalOHLCV:
    """Canonical completed bar; timestamp is the bar-open timestamp in UTC."""

    symbol: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    session: str | None = None
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        _validate_identity(self.symbol, self.timeframe, self.timestamp)
        _validate_finite_prices((self.open, self.high, self.low, self.close))
        if self.high < self.low:
            raise ValueError("high must be greater than or equal to low")
        if self.high < max(self.open, self.close):
            raise ValueError("high must contain open and close")
        if self.low > min(self.open, self.close):
            raise ValueError("low must contain open and close")
        if not math.isfinite(self.volume) or self.volume < 0:
            raise ValueError("volume must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class CanonicalTick:
    """Canonical quote/trade tick with UTC event time."""

    symbol: str
    timestamp: datetime
    bid: float
    ask: float
    last: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    last_size: float | None = None
    volume: float | None = None
    session: str | None = None
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        _validate_identity(self.symbol, "tick", self.timestamp)
        _validate_finite_prices((self.bid, self.ask))
        if self.bid < 0 or self.ask < 0 or self.ask < self.bid:
            raise ValueError("tick requires non-negative ask >= bid")
        for name, value in (
            ("last", self.last), ("bid_size", self.bid_size),
            ("ask_size", self.ask_size), ("last_size", self.last_size),
            ("volume", self.volume),
        ):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError(f"{name} must be finite and non-negative")


def _validate_identity(symbol: str, timeframe: str, timestamp: datetime) -> None:
    if not symbol.strip():
        raise ValueError("symbol must not be empty")
    if not timeframe.strip():
        raise ValueError("timeframe must not be empty")
    if timestamp.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")


def _validate_finite_prices(values: tuple[float, ...]) -> None:
    if any(not math.isfinite(value) for value in values):
        raise ValueError("prices must be finite")


def canonical_record_key(record: CanonicalOHLCV | CanonicalTick) -> tuple[Any, ...]:
    """Return a stable exact-record key used by deduplication."""
    if isinstance(record, CanonicalOHLCV):
        return (DataKind.OHLCV, record.symbol, record.timeframe, record.timestamp)
    return (
        DataKind.TICK, record.symbol, record.timestamp, record.bid, record.ask,
        record.last, record.bid_size, record.ask_size, record.last_size,
        record.volume,
    )


def canonical_payload(record: CanonicalOHLCV | CanonicalTick) -> dict[str, Any]:
    """Create a JSON-friendly payload without serialization I/O."""
    payload: dict[str, Any] = {}
    for item in fields(record):
        value = getattr(record, item.name)
        if item.name == "timestamp":
            value = value.astimezone(timezone.utc).isoformat()
        if item.name == "provenance" and value is not None:
            value = {
                provenance_field.name: _json_value(getattr(value, provenance_field.name))
                for provenance_field in fields(value)
            }
        payload[item.name] = _json_value(value)
    return payload


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, StrEnum):
        return str(value)
    return value


OHLCV_FIELD_ALIASES: Mapping[SourceFormat, Mapping[str, tuple[str, ...]]] = {
    SourceFormat.CSV: {
        "symbol": ("symbol", "ticker", "instrument"),
        "timeframe": ("timeframe", "interval", "tf"),
        "timestamp": ("timestamp", "datetime", "date", "time"),
        "open": ("open", "o"), "high": ("high", "h"),
        "low": ("low", "l"), "close": ("close", "c"),
        "volume": ("volume", "vol", "tick_volume"),
    },
    SourceFormat.JSON: {
        "symbol": ("symbol", "ticker", "instrument"),
        "timeframe": ("timeframe", "interval", "tf"),
        "timestamp": ("timestamp", "datetime", "date", "time"),
        "open": ("open", "o"), "high": ("high", "h"),
        "low": ("low", "l"), "close": ("close", "c"),
        "volume": ("volume", "vol", "tick_volume", "real_volume"),
    },
    SourceFormat.MT5: {
        "symbol": ("symbol",), "timeframe": ("timeframe",),
        "timestamp": ("time_msc", "time", "timestamp"),
        "open": ("open",), "high": ("high",), "low": ("low",),
        "close": ("close",),
        "volume": ("tick_volume", "real_volume", "volume"),
    },
}

TICK_FIELD_ALIASES: Mapping[SourceFormat, Mapping[str, tuple[str, ...]]] = {
    SourceFormat.CSV: {
        "symbol": ("symbol", "ticker", "instrument"),
        "timestamp": ("timestamp", "datetime", "date", "time"),
        "bid": ("bid",), "ask": ("ask",),
        "last": ("last", "last_price", "price"),
        "bid_size": ("bid_size", "bid_volume"),
        "ask_size": ("ask_size", "ask_volume"),
        "last_size": ("last_size", "trade_size"),
        "volume": ("volume", "vol"),
    },
    SourceFormat.JSON: {
        "symbol": ("symbol", "ticker", "instrument"),
        "timestamp": ("timestamp", "datetime", "date", "time"),
        "bid": ("bid",), "ask": ("ask",),
        "last": ("last", "last_price", "price"),
        "bid_size": ("bid_size", "bid_volume"),
        "ask_size": ("ask_size", "ask_volume"),
        "last_size": ("last_size", "trade_size"),
        "volume": ("volume", "vol", "volume_real"),
    },
    SourceFormat.MT5: {
        "symbol": ("symbol",), "timestamp": ("time_msc", "time", "timestamp"),
        "bid": ("bid",), "ask": ("ask",), "last": ("last",),
        "bid_size": ("bid_size",), "ask_size": ("ask_size",),
        "last_size": ("last_size",), "volume": ("volume_real", "volume"),
    },
}
