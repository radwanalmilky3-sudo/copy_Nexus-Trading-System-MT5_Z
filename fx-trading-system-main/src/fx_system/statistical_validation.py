from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal

import numpy as np

FDRMethod = Literal["bh", "by"]


def _harmonic_number(terms: int) -> float:
    return math.fsum(1.0 / rank for rank in range(1, terms + 1))


def _fdr_q_values(
    p_values: Sequence[float] | np.ndarray,
    *,
    dependency_correction: float,
) -> np.ndarray:
    values = np.asarray(p_values, dtype=float)
    if values.ndim != 1:
        raise ValueError("p_values must be one-dimensional")
    if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
        raise ValueError("p_values must contain only finite values between zero and one")
    if not len(values):
        return np.array([], dtype=float)

    order = np.argsort(values, kind="stable")
    ranked = values[order]
    adjusted = (
        ranked
        * len(values)
        * dependency_correction
        / np.arange(1, len(values) + 1)
    )
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1].clip(0, 1)
    result = np.empty_like(adjusted)
    result[order] = adjusted
    return result


def benjamini_hochberg(p_values: Sequence[float] | np.ndarray) -> np.ndarray:
    """BH adjusted p-values, valid under independence or positive dependence."""
    return _fdr_q_values(p_values, dependency_correction=1.0)


def benjamini_yekutieli(p_values: Sequence[float] | np.ndarray) -> np.ndarray:
    """BY adjusted p-values for FDR control under arbitrary test dependence."""
    hypothesis_count = len(p_values)
    correction = _harmonic_number(hypothesis_count) if hypothesis_count else 1.0
    return _fdr_q_values(p_values, dependency_correction=correction)


def minimum_resamples_for_fdr(
    hypotheses: int,
    fdr_level: float,
    *,
    method: FDRMethod = "bh",
) -> int:
    """Minimum resamples whose plus-one p-value can reach the first FDR threshold."""
    if hypotheses < 1:
        raise ValueError("hypotheses must be positive")
    if not 0 < fdr_level <= 1:
        raise ValueError("fdr_level must be between zero and one")
    if method not in {"bh", "by"}:
        raise ValueError("method must be 'bh' or 'by'")
    dependency_correction = _harmonic_number(hypotheses) if method == "by" else 1.0
    return max(
        1,
        math.ceil(hypotheses * dependency_correction / fdr_level) - 1,
    )


def monte_carlo_p_value_standard_error(p_value: float, resamples: int) -> float:
    if not 0 <= p_value <= 1:
        raise ValueError("p_value must be between zero and one")
    if resamples < 1:
        raise ValueError("resamples must be positive")
    return math.sqrt(p_value * (1 - p_value) / (resamples + 1))


def _validate_joint_bootstrap_parameters(
    observations: int,
    resamples: int,
    block_length: int,
) -> None:
    if observations < 1:
        raise ValueError("observations must be positive")
    if resamples < 1:
        raise ValueError("resamples must be positive")
    if not 1 <= block_length <= observations:
        raise ValueError("block_length must be between one and observations")


def joint_circular_block_bootstrap_indices(
    observations: int,
    *,
    resamples: int,
    block_length: int,
    random_state: int | None = None,
) -> np.ndarray:
    """Draw fixed-length circular blocks as shared row indices for a panel.

    Each returned row is one bootstrap path. Applying that same path to every
    candidate/instrument column preserves their contemporaneous dependence.
    """
    _validate_joint_bootstrap_parameters(observations, resamples, block_length)
    generator = np.random.default_rng(random_state)
    blocks = math.ceil(observations / block_length)
    starts = generator.integers(0, observations, size=(resamples, blocks))
    offsets = np.arange(block_length)
    indices = (starts[:, :, None] + offsets[None, None, :]) % observations
    return indices.reshape(resamples, -1)[:, :observations]


def joint_stationary_bootstrap_indices(
    observations: int,
    *,
    resamples: int,
    expected_block_length: int,
    random_state: int | None = None,
) -> np.ndarray:
    """Draw stationary-bootstrap shared row indices for a common-date panel.

    Blocks restart with probability ``1 / expected_block_length`` and wrap at
    the panel boundary. Cross-column synchronization comes from applying each
    index path to the whole matrix, never resampling columns independently.
    """
    _validate_joint_bootstrap_parameters(
        observations, resamples, expected_block_length
    )
    generator = np.random.default_rng(random_state)
    indices = np.empty((resamples, observations), dtype=np.int64)
    indices[:, 0] = generator.integers(0, observations, size=resamples)
    if observations == 1:
        return indices

    restart = generator.random((resamples, observations - 1)) < (
        1.0 / expected_block_length
    )
    new_starts = generator.integers(
        0, observations, size=(resamples, observations - 1)
    )
    for position in range(1, observations):
        continued = (indices[:, position - 1] + 1) % observations
        indices[:, position] = np.where(
            restart[:, position - 1],
            new_starts[:, position - 1],
            continued,
        )
    return indices


def joint_resample_matrix(
    values: Sequence[Sequence[float]] | np.ndarray,
    indices: np.ndarray,
) -> np.ndarray:
    """Apply shared bootstrap row indices to a date-by-candidate panel."""
    matrix = np.asarray(values)
    paths = np.asarray(indices)
    if matrix.ndim != 2:
        raise ValueError("values must be a two-dimensional matrix")
    if paths.ndim != 2 or not np.issubdtype(paths.dtype, np.integer):
        raise ValueError("indices must be a two-dimensional integer array")
    if paths.size and (paths.min() < 0 or paths.max() >= len(matrix)):
        raise ValueError("indices contain a row outside values")
    return matrix[paths]
