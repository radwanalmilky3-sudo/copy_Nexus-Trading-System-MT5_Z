"""Next-bar labels for feature history."""
from __future__ import annotations

from typing import Any


def label_next_bar_direction(
    frame: Any,
    *,
    close_column: str = "close",
    target_column: str = "target",
) -> Any:
    """Return rows labeled by the next close, omitting rows without a valid target."""
    if close_column not in frame.columns:
        raise ValueError(f"Missing close column: {close_column}")
    if target_column == close_column:
        raise ValueError("Target column must not overwrite the close column")

    next_close = frame[close_column].shift(-1)
    valid = next_close.notna() & frame[close_column].notna()
    labeled = frame.loc[valid].copy()
    next_values = next_close.loc[valid].to_numpy()
    current_values = labeled[close_column].to_numpy()
    labeled[target_column] = (next_values > current_values).astype(int)
    return labeled


def advance_pending_bar(
    pending: dict[str, Any] | None,
    current: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Resolve the previous feature row from this bar's close.

    Bar timestamps are UTC epoch milliseconds, allowing stable ordering and
    duplicate detection across process restarts.
    """
    timestamp = int(current["timestamp"])
    if pending is not None and timestamp <= int(pending["timestamp"]):
        return pending, None

    completed = None
    if pending is not None:
        completed = {
            "timestamp": int(pending["timestamp"]),
            "features": pending["features"],
            "ohlcv": pending["ohlcv"],
            "label": int(float(current["close"]) > float(pending["close"])),
        }
        if pending.get("timeframe") is not None:
            completed["timeframe"] = pending["timeframe"]
    next_pending = {
        "timestamp": timestamp,
        "close": float(current["close"]),
        "features": current["features"],
        "ohlcv": current["ohlcv"],
    }
    if current.get("timeframe") is not None:
        next_pending["timeframe"] = current["timeframe"]
    return next_pending, completed
