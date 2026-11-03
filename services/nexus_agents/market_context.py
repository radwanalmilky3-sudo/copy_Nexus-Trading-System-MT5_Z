"""Pure helpers for shaping external market context without agent initialization."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


def classify_vix(data: Mapping[str, Any] | None) -> tuple[float | None, str]:
    """Return a validated VIX value and regime, preserving unavailable data."""
    if not isinstance(data, Mapping):
        return None, "unknown"

    raw_value = data.get("close")
    if raw_value is None:
        raw_value = data.get("last")
    if isinstance(raw_value, bool):
        return None, "unknown"

    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None, "unknown"

    if not math.isfinite(value) or value <= 0:
        return None, "unknown"
    if value < 15:
        return value, "low_vol"
    if value <= 25:
        return value, "normal"
    return value, "high_vol"
