"""Multiple-testing gates for honest research statistics (Phase 5ج).

False-discovery-rate (FDR) adjusted p-values ("q-values"):

* Benjamini, Y. and Hochberg, Y. (1995) "Controlling the False Discovery
  Rate: a Practical and Powerful Approach to Multiple Testing",
  Journal of the Royal Statistical Society B 57(1), 289-300.
  Valid under independence or positive regression dependence (PRDS).
* Benjamini, Y. and Yekutieli, D. (2001) "The Control of the False
  Discovery Rate in Multiple Testing under Dependency",
  Annals of Statistics 29(4), 1165-1188.
  Valid under arbitrary dependence via division by the m-th harmonic number.

The optional deflated-Sharpe helper follows the normal-approximation idea of
Bailey and Lopez de Prado (2014), "The Deflated Sharpe Ratio: Correcting for
Selection Bias, Backtest Overfitting, and Non-Normality" — kept deliberately
simple (inputs: observed Sharpe, number of trials, variance of Sharpe
estimates) and NOT a full DSR implementation (no skewness/kurtosis terms).

All functions are pure, side-effect free, and dependency-light (stdlib only).
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from statistics import NormalDist
from typing import Literal

FDRMethod = Literal["bh", "by"]

DEFAULT_FDR_THRESHOLD = 0.10

__all__ = [
    "DEFAULT_FDR_THRESHOLD",
    "FDRMethod",
    "benjamini_hochberg",
    "benjamini_yekutieli",
    "deflated_sharpe_ratio",
    "harmonic_number",
    "minimum_resamples_for_fdr",
]


def harmonic_number(terms: int) -> float:
    """H_m = sum_{i=1..m} 1/i  (the BY dependence factor is H_m)."""
    if terms < 0:
        raise ValueError("terms must be non-negative")
    return math.fsum(1.0 / rank for rank in range(1, terms + 1))


def _validate_p_values(p_values: Sequence[float]) -> list[float]:
    try:
        values = [float(p) for p in p_values]
    except (TypeError, ValueError) as exc:
        raise ValueError("p_values must be a sequence of floats") from exc
    for p in values:
        if not math.isfinite(p) or p < 0.0 or p > 1.0:
            raise ValueError(
                "p_values must contain only finite values in [0, 1]; "
                "NaN/inf/out-of-range inputs are rejected (fail-closed)"
            )
    return values


def _fdr_q_values(p_values: Sequence[float], *, dependency_correction: float) -> list[float]:
    """Step-up adjusted p-values: q_(i) = min_{j>=i} p_(j) * m * c / j, clipped to [0, 1].

    Ties are handled by a stable sort; tied hypotheses share the most
    favourable (highest-rank) adjustment, matching standard implementations.
    """
    values = _validate_p_values(p_values)
    m = len(values)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: values[i])
    adjusted = [0.0] * m
    running_min = 1.0
    for rank in range(m, 0, -1):
        p = values[order[rank - 1]]
        candidate = p * m * dependency_correction / rank
        running_min = min(running_min, candidate)
        adjusted[order[rank - 1]] = min(1.0, max(0.0, running_min))
    return adjusted


def benjamini_hochberg(p_values: Sequence[float]) -> list[float]:
    """BH (1995) q-values; controls FDR under independence / positive dependence."""
    return _fdr_q_values(p_values, dependency_correction=1.0)


def benjamini_yekutieli(p_values: Sequence[float]) -> list[float]:
    """BY (2001) q-values; controls FDR under arbitrary dependence (divides by H_m)."""
    m = len(_validate_p_values(p_values))
    correction = harmonic_number(m) if m else 1.0
    return _fdr_q_values(p_values, dependency_correction=correction)


def minimum_resamples_for_fdr(
    hypotheses: int,
    fdr_level: float,
    *,
    method: FDRMethod = "bh",
) -> int:
    """Smallest resample count whose plus-one p-value (1/(r+1)) can reach the
    first step-up threshold ``fdr_level / (m * c_m)``.

    Solving ``1/(r+1) * m * c_m <= fdr_level`` gives
    ``r = ceil(m * c_m / fdr_level) - 1`` (floored at 1).  With BH, c_m = 1;
    with BY, c_m = H_m.
    """
    if hypotheses < 1:
        raise ValueError("hypotheses must be positive")
    if not 0 < fdr_level <= 1:
        raise ValueError("fdr_level must be in (0, 1]")
    if method not in ("bh", "by"):
        raise ValueError("method must be 'bh' or 'by'")
    correction = harmonic_number(hypotheses) if method == "by" else 1.0
    return max(1, math.ceil(hypotheses * correction / fdr_level) - 1)


def deflated_sharpe_ratio(
    observed_sharpe: float,
    n_trials: int,
    sharpe_variance: float,
) -> float:
    """Simple normal-approximation Deflated Sharpe Ratio (optional helper).

    Returns ``P(SR* > E[max SR over n_trials])`` under the assumption that
    Sharpe estimates are iid normal with the given ``sharpe_variance``.
    The expected maximum of ``n_trials`` standard normals is approximated by
    the ``(1 - 1/n)`` quantile.  Full DSR (skewness/kurtosis corrected) is out
    of scope; this is a screening gate, not a publication-grade statistic.
    """
    if n_trials < 1:
        raise ValueError("n_trials must be positive")
    if not math.isfinite(observed_sharpe):
        raise ValueError("observed_sharpe must be finite")
    if not math.isfinite(sharpe_variance) or sharpe_variance <= 0.0:
        raise ValueError("sharpe_variance must be finite and positive")
    sd = math.sqrt(sharpe_variance)
    baseline = 0.0 if n_trials == 1 else sd * NormalDist().inv_cdf(1.0 - 1.0 / n_trials)
    return NormalDist().cdf((observed_sharpe - baseline) / sd)


def paired_sign_test_pvalue(wins: int, n: int) -> float:
    """Exact two-sided sign-test p-value for ``wins`` of ``n`` non-tied pairs.

    H0: the candidate wins each paired comparison with probability 0.5.
    p = 2 * min(P(X <= wins), P(X >= wins)), capped at 1.0.
    Returns 1.0 when ``n`` is 0 (no information — never significant).
    """
    if n < 0 or wins < 0:
        raise ValueError("wins and n must be non-negative")
    if wins > n:
        raise ValueError("wins cannot exceed n")
    if n == 0:
        return 1.0
    lower = sum(math.comb(n, k) for k in range(0, wins + 1)) / (2 ** n)
    upper = sum(math.comb(n, k) for k in range(wins, n + 1)) / (2 ** n)
    return min(1.0, 2.0 * min(lower, upper))
