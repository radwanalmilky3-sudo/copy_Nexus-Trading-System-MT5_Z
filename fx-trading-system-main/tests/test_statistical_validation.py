from __future__ import annotations

import numpy as np

from fx_system.statistical_validation import (
    benjamini_hochberg,
    benjamini_yekutieli,
    joint_circular_block_bootstrap_indices,
    joint_resample_matrix,
    joint_stationary_bootstrap_indices,
    minimum_resamples_for_fdr,
)


def test_by_is_a_more_conservative_dependency_sensitivity_than_bh() -> None:
    p_values = np.array([0.001, 0.01, 0.03, 0.20])

    bh = benjamini_hochberg(p_values)
    by = benjamini_yekutieli(p_values)

    np.testing.assert_allclose(bh, [0.004, 0.02, 0.04, 0.20])
    np.testing.assert_allclose(
        by,
        [0.008333333333, 0.041666666667, 0.083333333333, 0.416666666667],
    )
    assert (by >= bh).all()
    assert minimum_resamples_for_fdr(4, 0.10, method="by") > (
        minimum_resamples_for_fdr(4, 0.10, method="bh")
    )


def test_joint_circular_blocks_are_deterministic_and_synchronized_across_columns() -> None:
    row = np.arange(12)
    matrix = np.column_stack([row, row + 100, row * -3])

    first = joint_circular_block_bootstrap_indices(
        len(matrix), resamples=5, block_length=4, random_state=221
    )
    second = joint_circular_block_bootstrap_indices(
        len(matrix), resamples=5, block_length=4, random_state=221
    )
    sampled = joint_resample_matrix(matrix, first)

    np.testing.assert_array_equal(first, second)
    np.testing.assert_array_equal(sampled[:, :, 0], first)
    np.testing.assert_array_equal(sampled[:, :, 1] - sampled[:, :, 0], 100)
    np.testing.assert_array_equal(sampled[:, :, 2], sampled[:, :, 0] * -3)
    for block_start in range(0, len(matrix), 4):
        block = first[:, block_start : block_start + 4]
        np.testing.assert_array_equal(
            block,
            (block[:, :1] + np.arange(block.shape[1])) % len(matrix),
        )


def test_joint_stationary_bootstrap_seed_and_panel_synchronization() -> None:
    row = np.arange(30)
    matrix = np.column_stack([row, row + 1000])

    first = joint_stationary_bootstrap_indices(
        len(matrix),
        resamples=8,
        expected_block_length=6,
        random_state=991,
    )
    second = joint_stationary_bootstrap_indices(
        len(matrix),
        resamples=8,
        expected_block_length=6,
        random_state=991,
    )
    different_seed = joint_stationary_bootstrap_indices(
        len(matrix),
        resamples=8,
        expected_block_length=6,
        random_state=992,
    )
    sampled = joint_resample_matrix(matrix, first)

    np.testing.assert_array_equal(first, second)
    assert not np.array_equal(first, different_seed)
    np.testing.assert_array_equal(sampled[:, :, 0], first)
    np.testing.assert_array_equal(sampled[:, :, 1] - sampled[:, :, 0], 1000)
