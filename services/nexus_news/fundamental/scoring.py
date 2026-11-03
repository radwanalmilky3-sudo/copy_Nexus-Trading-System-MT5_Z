from __future__ import annotations

import math
from statistics import mean
from typing import Iterable

from shared.fundamental import GoldDirection


def clamp(value: float, lo: float = -100.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(value)))


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def direction_from_score(score: float, *, neutral_band: float = 12.0) -> GoldDirection:
    if score > neutral_band:
        return GoldDirection.BULLISH
    if score < -neutral_band:
        return GoldDirection.BEARISH
    return GoldDirection.NEUTRAL


def sigmoid_probability(score: float, scale: float = 26.0) -> float:
    """Convert [-100, 100] score into a bounded directional probability."""
    x = max(-8.0, min(8.0, float(score) / max(scale, 1e-6)))
    return 1.0 / (1.0 + math.exp(-x))


def average(values: Iterable[float], default: float = 0.0) -> float:
    vals = [float(v) for v in values]
    return mean(vals) if vals else default


def confidence_from_components(
    *,
    coverage: float,
    quality: float,
    freshness: float,
    reliability: float,
    agreement: float,
    conflict: float,
) -> float:
    base = (
        coverage * 0.20
        + quality * 0.20
        + freshness * 0.15
        + reliability * 0.20
        + agreement * 0.25
    )
    penalty = conflict * 0.45
    return max(0.0, min(100.0, base - penalty))


def conflict_from_scores(scores: list[float]) -> tuple[float, float]:
    """Return (agreement, conflict) in [0,100] without confusing offsetting with neutrality."""
    valid = [float(x) for x in scores]
    if not valid:
        return 0.0, 100.0
    pos = sum(abs(x) for x in valid if x > 12)
    neg = sum(abs(x) for x in valid if x < -12)
    magnitude = pos + neg
    if magnitude <= 1e-9:
        return 50.0, 0.0
    minority = min(pos, neg)
    conflict = 100.0 * (2.0 * minority / magnitude)
    agreement = max(0.0, 100.0 - conflict)
    return agreement, conflict


def independence_factor(group_size: int) -> float:
    """Diminishing evidence for multiple signals from the same causal chain."""
    if group_size <= 1:
        return 1.0
    # 2 correlated signals ~= 1.55 independent; 5 ~= 2.34, not 5.
    return max(0.35, min(1.0, math.log2(group_size + 1) / group_size))
