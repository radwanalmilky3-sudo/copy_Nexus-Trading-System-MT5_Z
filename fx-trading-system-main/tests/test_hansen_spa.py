from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest

from fx_system.hansen_spa import (
    _stationary_bootstrap_indices,
    hansen_spa_test,
)


def _index(observations: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2020-01-02", periods=observations, tz="UTC")


def _synthetic_noise(
    observations: int,
    *,
    seed: int,
    scale: float = 0.001,
) -> np.ndarray:
    innovations = np.random.default_rng(seed).normal(0.0, scale, observations)
    values = np.empty(observations)
    values[0] = innovations[0]
    for position in range(1, observations):
        values[position] = 0.45 * values[position - 1] + innovations[position]
    return values


def _run(
    candidates: pd.DataFrame,
    benchmark: pd.Series,
    *,
    seed: int = 731,
    reps: int = 399,
    batch_size: int = 17,
):
    return hansen_spa_test(
        candidates,
        benchmark_returns=benchmark,
        expected_block_length=6,
        reps=reps,
        seed=seed,
        batch_size=batch_size,
    )


def test_spa_uses_candidate_minus_benchmark_return_and_studentized_statistic() -> None:
    observations = 96
    index = _index(observations)
    benchmark = pd.Series(
        0.0001 + _synthetic_noise(observations, seed=1, scale=0.0002),
        index=index,
        name="cash_only_benchmark",
    )
    positive_differential = 0.0004 + _synthetic_noise(observations, seed=2)
    negative_differential = -0.0003 + _synthetic_noise(observations, seed=3)
    candidates = pd.DataFrame(
        {
            "positive": benchmark.to_numpy() + positive_differential,
            "negative": benchmark.to_numpy() + negative_differential,
        },
        index=index,
    )

    result = _run(candidates, benchmark)

    np.testing.assert_allclose(
        result.candidate_statistics["mean_excess_return"],
        [positive_differential.mean(), negative_differential.mean()],
    )
    expected_observed = max(
        0.0,
        float(
            result.candidate_statistics["studentized_mean_statistic"].max()
        ),
    )
    assert result.observed_statistic == pytest.approx(expected_observed)
    assert result.benchmark_name == "cash_only_benchmark"
    assert result.studentized is True
    assert result.primary_pvalue_type == "consistent"
    assert result.trading_approval is False
    assert result.consistent.monte_carlo_standard_error == pytest.approx(
        math.sqrt(
            result.consistent.p_value
            * (1.0 - result.consistent.p_value)
            / (result.reps + 1)
        )
    )


def test_stationary_population_lrv_reduces_to_lag_zero_for_block_one() -> None:
    observations = 32
    index = _index(observations)
    differential = _synthetic_noise(observations, seed=11)
    benchmark = pd.Series(0.0, index=index, name="explicit_zero_return_benchmark")
    candidates = pd.DataFrame({"candidate": differential}, index=index)

    result = hansen_spa_test(
        candidates,
        benchmark_returns=benchmark,
        expected_block_length=1,
        reps=49,
        seed=91,
        batch_size=8,
    )

    expected = np.mean((differential - differential.mean()) ** 2)
    actual = result.candidate_statistics.loc[
        "candidate", "stationary_bootstrap_long_run_variance"
    ]
    assert actual == pytest.approx(expected)


def test_studentized_spa_is_invariant_to_positive_per_candidate_scaling() -> None:
    observations = 96
    index = _index(observations)
    benchmark = pd.Series(0.0, index=index, name="explicit_zero_return_benchmark")
    base = pd.DataFrame(
        {
            "a": 0.00015 + _synthetic_noise(observations, seed=20),
            "b": -0.00010 + _synthetic_noise(observations, seed=21),
            "c": _synthetic_noise(observations, seed=22),
        },
        index=index,
    )
    scaled = base * pd.Series({"a": 17.0, "b": 0.25, "c": 4.0})

    original = _run(base, benchmark)
    transformed = _run(scaled, benchmark)

    assert transformed.observed_statistic == pytest.approx(original.observed_statistic)
    np.testing.assert_allclose(
        transformed.candidate_statistics["studentized_mean_statistic"],
        original.candidate_statistics["studentized_mean_statistic"],
    )
    for name in ("lower", "consistent", "upper"):
        original_pvalue = getattr(original, name)
        transformed_pvalue = getattr(transformed, name)
        assert transformed_pvalue.exceedances == original_pvalue.exceedances
        assert transformed_pvalue.p_value == original_pvalue.p_value


def test_max_zero_and_plus_one_are_fail_safe_for_uniformly_worse_candidate() -> None:
    observations = 96
    index = _index(observations)
    benchmark = pd.Series(0.0, index=index, name="explicit_zero_return_benchmark")
    candidates = pd.DataFrame(
        {"worse": -0.01 + _synthetic_noise(observations, seed=31, scale=0.0001)},
        index=index,
    )

    result = _run(candidates, benchmark, reps=199)

    assert result.observed_statistic == 0.0
    for pvalue in (result.lower, result.consistent, result.upper):
        assert pvalue.exceedances == 199
        assert pvalue.p_value == 1.0


def test_strong_synthetic_advantage_has_nonzero_plus_one_pvalue_and_reversal_does_not() -> None:
    observations = 128
    index = _index(observations)
    benchmark = pd.Series(0.0, index=index, name="explicit_zero_return_benchmark")
    differential = 0.004 + _synthetic_noise(observations, seed=41, scale=0.0002)

    positive = _run(
        pd.DataFrame({"synthetic_positive": differential}, index=index),
        benchmark,
        reps=499,
    )
    negative = _run(
        pd.DataFrame({"synthetic_negative": -differential}, index=index),
        benchmark,
        reps=499,
    )

    assert positive.consistent.p_value == pytest.approx(1 / 500)
    assert positive.consistent.p_value > 0.0
    assert negative.observed_statistic == 0.0
    assert negative.consistent.p_value == 1.0


def test_pvalue_order_seed_reproducibility_batch_independence_and_column_permutation() -> None:
    observations = 96
    index = _index(observations)
    benchmark = pd.Series(0.0, index=index, name="explicit_zero_return_benchmark")
    candidates = pd.DataFrame(
        {
            "candidate_a": 0.0002 + _synthetic_noise(observations, seed=50),
            "candidate_b": -0.0015 + _synthetic_noise(observations, seed=51),
            "candidate_c": _synthetic_noise(observations, seed=52),
        },
        index=index,
    )

    first = _run(candidates, benchmark, seed=4242, batch_size=7)
    repeated = _run(candidates, benchmark, seed=4242, batch_size=7)
    rebatched = _run(candidates, benchmark, seed=4242, batch_size=31)
    permuted = _run(
        candidates.loc[:, ["candidate_c", "candidate_a", "candidate_b"]],
        benchmark,
        seed=4242,
        batch_size=7,
    )

    assert first.lower.p_value <= first.consistent.p_value <= first.upper.p_value
    for name in ("lower", "consistent", "upper"):
        expected = getattr(first, name)
        assert getattr(repeated, name) == expected
        assert getattr(rebatched, name) == expected
        assert getattr(permuted, name) == expected
    pdt.assert_frame_equal(first.candidate_statistics, repeated.candidate_statistics)


def test_stationary_bootstrap_canary_is_deterministic_and_shares_rows() -> None:
    first = _stationary_bootstrap_indices(
        8,
        paths=3,
        expected_block_length=3,
        generator=np.random.default_rng(2026),
    )
    second = _stationary_bootstrap_indices(
        8,
        paths=3,
        expected_block_length=3,
        generator=np.random.default_rng(2026),
    )
    row = np.arange(8)
    panel = np.column_stack([row, row + 100, -2 * row])
    sampled = panel[first]

    np.testing.assert_array_equal(
        first,
        [
            [1, 2, 3, 7, 5, 6, 7, 0],
            [3, 2, 3, 5, 6, 7, 3, 4],
            [6, 7, 0, 7, 5, 6, 7, 4],
        ],
    )
    np.testing.assert_array_equal(first, second)
    np.testing.assert_array_equal(sampled[:, :, 0], first)
    np.testing.assert_array_equal(sampled[:, :, 1] - sampled[:, :, 0], 100)
    np.testing.assert_array_equal(sampled[:, :, 2], -2 * sampled[:, :, 0])


def test_spa_rejects_degenerate_differential_before_bootstrap() -> None:
    observations = 32
    index = _index(observations)
    benchmark = pd.Series(0.0, index=index, name="explicit_zero_return_benchmark")
    candidates = pd.DataFrame({"identical": np.zeros(observations)}, index=index)

    with pytest.raises(ValueError, match="zero or invalid variance"):
        hansen_spa_test(
            candidates,
            benchmark_returns=benchmark,
            expected_block_length=4,
            reps=99,
            seed=1,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("unnamed_benchmark", "explicit non-empty name"),
        ("shifted_benchmark", "exactly the candidate date index"),
        ("missing_candidate", "missing or infinite"),
        ("naive_index", "timezone-aware UTC"),
        ("too_long_block", "at least two expected bootstrap blocks"),
        ("zero_block", "expected_block_length must be positive"),
        ("zero_reps", "reps must be positive"),
        ("negative_seed", "seed must be non-negative"),
        ("zero_batch", "batch_size must be positive"),
    ],
)
def test_spa_fails_closed_on_invalid_contract(mutation: str, message: str) -> None:
    observations = 16
    index = _index(observations)
    candidates = pd.DataFrame(
        {"candidate": _synthetic_noise(observations, seed=70)}, index=index
    )
    benchmark = pd.Series(0.0, index=index, name="explicit_zero_return_benchmark")
    kwargs: dict[str, object] = {
        "benchmark_returns": benchmark,
        "expected_block_length": 4,
        "reps": 19,
        "seed": 5,
        "batch_size": 3,
    }
    if mutation == "unnamed_benchmark":
        kwargs["benchmark_returns"] = benchmark.rename(None)
    elif mutation == "shifted_benchmark":
        kwargs["benchmark_returns"] = benchmark.set_axis(index.shift(1, freq="D"))
    elif mutation == "missing_candidate":
        candidates.iloc[3, 0] = np.nan
    elif mutation == "naive_index":
        candidates.index = candidates.index.tz_localize(None)
        kwargs["benchmark_returns"] = benchmark.set_axis(benchmark.index.tz_localize(None))
    elif mutation == "too_long_block":
        kwargs["expected_block_length"] = 9
    elif mutation == "zero_block":
        kwargs["expected_block_length"] = 0
    elif mutation == "zero_reps":
        kwargs["reps"] = 0
    elif mutation == "negative_seed":
        kwargs["seed"] = -1
    elif mutation == "zero_batch":
        kwargs["batch_size"] = 0

    with pytest.raises(ValueError, match=message):
        hansen_spa_test(candidates, **kwargs)  # type: ignore[arg-type]
