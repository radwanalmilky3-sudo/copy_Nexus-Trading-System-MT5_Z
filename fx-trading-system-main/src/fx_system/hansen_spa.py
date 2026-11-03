"""Transparent studentized Hansen SPA test for common-date portfolio returns.

This module implements the statistic and recentering rules in Hansen (2005)
directly.  It deliberately does not select a candidate or approve trading.
All candidates and the benchmark must already be frozen, cost-adjusted daily
net-return series on exactly the same UTC date index.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_numeric_dtype

from .portfolio_validation import validate_daily_net_return_matrix
from .statistical_validation import monte_carlo_p_value_standard_error

_MINIMUM_OBSERVATIONS = 8
_PVALUE_TYPES = ("lower", "consistent", "upper")


@dataclass(frozen=True)
class HansenSPAPValue:
    """One plus-one-corrected SPA bootstrap p-value."""

    p_value: float
    exceedances: int
    monte_carlo_standard_error: float


@dataclass(frozen=True)
class HansenSPAResult:
    """Studentized Hansen SPA result over a declared common-date family.

    ``consistent`` is Hansen's recommended sample-dependent p-value.  ``lower``
    and ``upper`` disclose the liberal and least-favourable recentering bounds.
    A rejection is a family-level diagnostic only: it does not identify a
    winning model and is not a trading approval.
    """

    observations: int
    candidate_names: tuple[str, ...]
    benchmark_name: str
    common_start: pd.Timestamp
    common_end: pd.Timestamp
    expected_block_length: int
    reps: int
    seed: int
    batch_size: int
    observed_statistic: float
    candidate_statistics: pd.DataFrame
    lower: HansenSPAPValue
    consistent: HansenSPAPValue
    upper: HansenSPAPValue
    bootstrap: str = "stationary"
    studentized: bool = True
    pvalue_correction: str = "plus_one_greater_than_or_equal"
    primary_pvalue_type: str = "consistent"
    trading_approval: bool = False


def _validate_positive_integer(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer")
    result = int(value)
    if result < 1:
        raise ValueError(f"{name} must be positive")
    return result


def _validate_benchmark(
    benchmark_returns: pd.Series,
    *,
    expected_index: pd.DatetimeIndex,
) -> pd.Series:
    if not isinstance(benchmark_returns, pd.Series):
        raise TypeError("benchmark_returns must be a pandas Series")
    if not isinstance(benchmark_returns.name, str) or not benchmark_returns.name.strip():
        raise ValueError("benchmark_returns must have an explicit non-empty name")
    if benchmark_returns.name != benchmark_returns.name.strip():
        raise ValueError("benchmark_returns name cannot have surrounding whitespace")
    if not benchmark_returns.index.equals(expected_index):
        raise ValueError("benchmark_returns must have exactly the candidate date index")
    if is_bool_dtype(benchmark_returns.dtype) or not is_numeric_dtype(
        benchmark_returns.dtype
    ):
        raise ValueError("benchmark_returns must be numeric and non-boolean")
    values = benchmark_returns.to_numpy(dtype=float, na_value=np.nan)
    if not np.isfinite(values).all():
        raise ValueError("benchmark_returns cannot contain missing or infinite values")
    return pd.Series(values, index=expected_index, name=benchmark_returns.name)


def _stationary_bootstrap_indices(
    observations: int,
    *,
    paths: int,
    expected_block_length: int,
    generator: np.random.Generator,
) -> np.ndarray:
    """Generate shared stationary-bootstrap row paths for one streaming batch.

    Each path consumes exactly ``2 * observations`` uniforms, so changing the
    processing batch size does not change the random paths for a fixed seed.
    """
    uniforms = generator.random((paths, observations, 2))
    indices = np.empty((paths, observations), dtype=np.int64)
    indices[:, 0] = np.floor(observations * uniforms[:, 0, 0]).astype(np.int64)
    restart_probability = 1.0 / expected_block_length
    for position in range(1, observations):
        continued = (indices[:, position - 1] + 1) % observations
        new_starts = np.floor(observations * uniforms[:, position, 0]).astype(
            np.int64
        )
        indices[:, position] = np.where(
            uniforms[:, position, 1] < restart_probability,
            new_starts,
            continued,
        )
    return indices


def _stationary_bootstrap_population_lrv(
    differentials: np.ndarray,
    *,
    expected_block_length: int,
) -> np.ndarray:
    """Estimate each differential's stationary-bootstrap population LRV."""
    observations = differentials.shape[0]
    demeaned = differentials - differentials.mean(axis=0)
    lag_zero = np.sum(demeaned**2, axis=0) / observations
    raw_scale = np.maximum(
        np.mean(differentials**2, axis=0),
        np.finfo(float).tiny,
    )
    raw_tolerance = np.finfo(float).eps * raw_scale * 64.0
    invalid_raw = np.flatnonzero(
        ~np.isfinite(lag_zero) | (lag_zero <= raw_tolerance)
    )
    if len(invalid_raw):
        raise ValueError(
            "candidate-benchmark differential has zero or invalid variance at "
            f"column positions {invalid_raw.tolist()}"
        )

    restart_probability = 1.0 / expected_block_length
    continuation_probability = 1.0 - restart_probability
    long_run_variances = lag_zero.copy()
    for lag in range(1, observations):
        weight = (
            (1.0 - lag / observations) * continuation_probability**lag
            + (lag / observations) * continuation_probability ** (observations - lag)
        )
        autocovariance = np.sum(
            demeaned[:-lag] * demeaned[lag:], axis=0
        ) / observations
        long_run_variances += 2.0 * weight * autocovariance

    lrv_tolerance = np.finfo(float).eps * lag_zero * 64.0
    invalid_lrv = np.flatnonzero(
        ~np.isfinite(long_run_variances) | (long_run_variances <= lrv_tolerance)
    )
    if len(invalid_lrv):
        raise ValueError(
            "candidate-benchmark differential has non-positive or invalid "
            f"stationary-bootstrap long-run variance at column positions "
            f"{invalid_lrv.tolist()}"
        )
    return long_run_variances


def _recentring_means(
    means: np.ndarray,
    long_run_variances: np.ndarray,
    observations: int,
) -> dict[str, np.ndarray]:
    consistency_threshold = -np.sqrt(
        (long_run_variances / observations)
        * 2.0
        * math.log(math.log(observations))
    )
    return {
        "lower": np.maximum(0.0, means),
        "consistent": np.where(means >= consistency_threshold, means, 0.0),
        "upper": means.copy(),
    }


def hansen_spa_test(
    candidate_net_returns: pd.DataFrame,
    *,
    benchmark_returns: pd.Series,
    expected_block_length: int = 63,
    reps: int = 50_000,
    seed: int,
    batch_size: int = 128,
) -> HansenSPAResult:
    """Run a studentized Hansen SPA test without selecting a candidate.

    The loss differential is ``candidate_return - benchmark_return`` since
    losses are the negatives of returns.  Stationary-bootstrap paths are drawn
    jointly across the full candidate row, and processed in batches so a
    ``reps * observations * candidates`` tensor is never resident in memory.
    Final p-values use ``(exceedances + 1) / (reps + 1)`` with ``>=`` ties.
    """
    matrix = validate_daily_net_return_matrix(
        candidate_net_returns,
        minimum_rows=_MINIMUM_OBSERVATIONS,
    )
    if matrix.index.tz is None or str(matrix.index.tz).upper() != "UTC":
        raise ValueError("candidate_net_returns must use a timezone-aware UTC index")
    block_length = _validate_positive_integer(
        expected_block_length, name="expected_block_length"
    )
    bootstrap_reps = _validate_positive_integer(reps, name="reps")
    processing_batch_size = _validate_positive_integer(batch_size, name="batch_size")
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
        raise ValueError("seed must be an integer")
    random_seed = int(seed)
    if random_seed < 0:
        raise ValueError("seed must be non-negative")
    if len(matrix) < 2 * block_length:
        raise ValueError(
            "candidate_net_returns must contain at least two expected bootstrap blocks"
        )
    benchmark = _validate_benchmark(
        benchmark_returns,
        expected_index=matrix.index,
    )

    differentials = matrix.to_numpy(dtype=float) - benchmark.to_numpy(dtype=float)[:, None]
    means = differentials.mean(axis=0)
    long_run_variances = _stationary_bootstrap_population_lrv(
        differentials,
        expected_block_length=block_length,
    )
    long_run_standard_deviations = np.sqrt(long_run_variances)
    root_observations = math.sqrt(len(matrix))
    standardized_means = root_observations * means / long_run_standard_deviations
    observed_statistic = float(max(0.0, float(np.max(standardized_means))))
    recentering = _recentring_means(means, long_run_variances, len(matrix))

    exceedances = {name: 0 for name in _PVALUE_TYPES}
    generator = np.random.default_rng(random_seed)
    completed = 0
    while completed < bootstrap_reps:
        current_batch = min(processing_batch_size, bootstrap_reps - completed)
        indices = _stationary_bootstrap_indices(
            len(matrix),
            paths=current_batch,
            expected_block_length=block_length,
            generator=generator,
        )
        resampled_means = differentials[indices].mean(axis=1)
        for name in _PVALUE_TYPES:
            centered = resampled_means - recentering[name][None, :]
            statistics = np.maximum(
                0.0,
                np.max(
                    root_observations
                    * centered
                    / long_run_standard_deviations[None, :],
                    axis=1,
                ),
            )
            exceedances[name] += int(np.count_nonzero(statistics >= observed_statistic))
        completed += current_batch

    pvalue_results: dict[str, HansenSPAPValue] = {}
    for name in _PVALUE_TYPES:
        p_value = (exceedances[name] + 1.0) / (bootstrap_reps + 1.0)
        pvalue_results[name] = HansenSPAPValue(
            p_value=float(p_value),
            exceedances=exceedances[name],
            monte_carlo_standard_error=monte_carlo_p_value_standard_error(
                float(p_value), bootstrap_reps
            ),
        )
    ordered_pvalues = np.array(
        [pvalue_results[name].p_value for name in _PVALUE_TYPES]
    )
    if np.any(np.diff(ordered_pvalues) < -np.finfo(float).eps * 8.0):
        raise RuntimeError(
            "SPA recentering invariant failed: expected lower <= consistent <= upper"
        )

    candidate_statistics = pd.DataFrame(
        {
            "mean_excess_return": means,
            "stationary_bootstrap_long_run_variance": long_run_variances,
            "stationary_bootstrap_long_run_standard_deviation": (
                long_run_standard_deviations
            ),
            "studentized_mean_statistic": standardized_means,
        },
        index=pd.Index(matrix.columns, name="candidate"),
    )
    return HansenSPAResult(
        observations=len(matrix),
        candidate_names=tuple(matrix.columns),
        benchmark_name=benchmark.name,
        common_start=matrix.index[0],
        common_end=matrix.index[-1],
        expected_block_length=block_length,
        reps=bootstrap_reps,
        seed=random_seed,
        batch_size=processing_batch_size,
        observed_statistic=observed_statistic,
        candidate_statistics=candidate_statistics,
        lower=pvalue_results["lower"],
        consistent=pvalue_results["consistent"],
        upper=pvalue_results["upper"],
    )


__all__ = ["HansenSPAPValue", "HansenSPAResult", "hansen_spa_test"]
