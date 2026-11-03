"""Helpers for normalizing OHLCV rows at feature-service boundaries."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _timestamp_value(bar: dict[str, Any]) -> float | None:
    value = bar.get("timestamp", bar.get("time"))
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return float(value)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def chronological_bars(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort oldest-first only when every row has a parseable timestamp.

    Without complete timestamp information, preserve the provider's input order
    rather than guessing which row is newest.
    """
    timestamps = [_timestamp_value(bar) for bar in bars]
    if any(timestamp is None for timestamp in timestamps):
        return list(bars)

    indexed = enumerate(zip(bars, timestamps))
    return [bar for _, (bar, _) in sorted(indexed, key=lambda item: (item[1][1], item[0]))]
