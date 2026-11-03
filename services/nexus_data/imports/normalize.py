"""Pure timestamp, session, and source-row normalization."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timezone, tzinfo
from typing import Any, Mapping

from .contracts import (
    CanonicalOHLCV, CanonicalTick, OHLCV_FIELD_ALIASES, Provenance,
    SourceFormat, TICK_FIELD_ALIASES,
)


class NormalizationError(ValueError):
    """Raised when a raw record cannot be represented canonically."""


@dataclass(frozen=True, slots=True)
class SessionWindow:
    """A recurring session window in the supplied timezone."""

    name: str
    start: time
    end: time
    weekdays: frozenset[int] = frozenset(range(7))


@dataclass(frozen=True, slots=True)
class SessionCalendar:
    timezone: tzinfo = timezone.utc
    windows: tuple[SessionWindow, ...] = ()
    off_hours_name: str = "OFF_HOURS"

    def session_for(self, timestamp: datetime) -> str:
        local = timestamp.astimezone(self.timezone)
        for window in self.windows:
            if local.weekday() not in window.weekdays:
                continue
            if _in_window(local.time(), window.start, window.end):
                return window.name
        return self.off_hours_name


@dataclass(frozen=True, slots=True)
class NormalizationPolicy:
    """Explicit defaults for deterministic source normalization."""

    assumed_timezone: tzinfo = timezone.utc
    session_calendar: SessionCalendar | None = None
    default_symbol: str | None = None
    default_timeframe: str | None = None
    uppercase_symbols: bool = True


DEFAULT_POLICY = NormalizationPolicy()


def normalize_timestamp(value: Any, *, assumed_timezone: tzinfo = timezone.utc) -> datetime:
    """Normalize ISO text or epoch seconds/milliseconds to UTC."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value)
        if not math.isfinite(numeric):
            raise NormalizationError("timestamp must be finite")
        divisor = 1000 if abs(numeric) >= 10_000_000_000 else 1
        try:
            parsed = datetime.fromtimestamp(numeric / divisor, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise NormalizationError("timestamp epoch is out of range") from exc
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise NormalizationError("timestamp must not be empty")
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise NormalizationError(f"unsupported timestamp: {value!r}") from exc
    else:
        raise NormalizationError(f"unsupported timestamp type: {type(value).__name__}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=assumed_timezone)
    return parsed.astimezone(timezone.utc)


def normalize_symbol(value: Any, *, uppercase: bool = True) -> str:
    symbol = str(value).strip()
    if not symbol:
        raise NormalizationError("symbol is required")
    return symbol.upper() if uppercase else symbol


def normalize_timeframe(value: Any) -> str:
    timeframe = str(value).strip().upper()
    if not timeframe:
        raise NormalizationError("timeframe is required")
    return timeframe


def normalize_ohlcv(
    values: Mapping[str, Any], *, source_format: SourceFormat,
    provenance: Provenance, policy: NormalizationPolicy = DEFAULT_POLICY,
) -> CanonicalOHLCV:
    """Convert one CSV/JSON/MT5 row into the canonical bar schema."""
    aliases = OHLCV_FIELD_ALIASES[source_format]
    symbol = _required(values, aliases["symbol"], policy.default_symbol)
    timeframe = _required(values, aliases["timeframe"], policy.default_timeframe)
    timestamp = normalize_timestamp(
        _required(values, aliases["timestamp"]),
        assumed_timezone=policy.assumed_timezone,
    )
    session = (
        policy.session_calendar.session_for(timestamp)
        if policy.session_calendar is not None else None
    )
    try:
        return CanonicalOHLCV(
            symbol=normalize_symbol(symbol, uppercase=policy.uppercase_symbols),
            timeframe=normalize_timeframe(timeframe), timestamp=timestamp,
            open=_number(values, aliases["open"]), high=_number(values, aliases["high"]),
            low=_number(values, aliases["low"]), close=_number(values, aliases["close"]),
            volume=_number(values, aliases["volume"], default=0.0),
            session=session, provenance=provenance,
        )
    except (TypeError, ValueError) as exc:
        raise NormalizationError(str(exc)) from exc


def normalize_tick(
    values: Mapping[str, Any], *, source_format: SourceFormat,
    provenance: Provenance, policy: NormalizationPolicy = DEFAULT_POLICY,
) -> CanonicalTick:
    """Convert one CSV/JSON/MT5 row into the canonical tick schema."""
    aliases = TICK_FIELD_ALIASES[source_format]
    symbol = _required(values, aliases["symbol"], policy.default_symbol)
    timestamp = normalize_timestamp(
        _required(values, aliases["timestamp"]),
        assumed_timezone=policy.assumed_timezone,
    )
    session = (
        policy.session_calendar.session_for(timestamp)
        if policy.session_calendar is not None else None
    )
    try:
        return CanonicalTick(
            symbol=normalize_symbol(symbol, uppercase=policy.uppercase_symbols),
            timestamp=timestamp, bid=_number(values, aliases["bid"]),
            ask=_number(values, aliases["ask"]), last=_optional_number(values, aliases["last"]),
            bid_size=_optional_number(values, aliases["bid_size"]),
            ask_size=_optional_number(values, aliases["ask_size"]),
            last_size=_optional_number(values, aliases["last_size"]),
            volume=_optional_number(values, aliases["volume"]),
            session=session, provenance=provenance,
        )
    except (TypeError, ValueError) as exc:
        raise NormalizationError(str(exc)) from exc


def _required(values: Mapping[str, Any], names: tuple[str, ...], fallback: Any = None) -> Any:
    for name in names:
        if name in values and values[name] not in (None, ""):
            return values[name]
    if fallback not in (None, ""):
        return fallback
    raise NormalizationError(f"missing required field; tried {names!r}")


def _number(values: Mapping[str, Any], names: tuple[str, ...], *, default: float | None = None) -> float:
    value = _required(values, names, default)
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise NormalizationError(f"field {names[0]!r} must be numeric") from exc
    if not math.isfinite(result):
        raise NormalizationError(f"field {names[0]!r} must be finite")
    return result


def _optional_number(values: Mapping[str, Any], names: tuple[str, ...]) -> float | None:
    if all(name not in values or values[name] in (None, "") for name in names):
        return None
    return _number(values, names)


def _in_window(value: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= value < end
    return value >= start or value < end
