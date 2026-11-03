from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from fx_system.portfolio_validation import (
    cscv_probability_of_backtest_overfitting,
    deflated_sharpe_ratio,
    prepare_spa_inputs,
    validate_daily_net_return_matrix,
)


def _daily_frame(values: dict[str, np.ndarray]) -> pd.DataFrame:
    observations = len(next(iter(values.values())))
    return pd.DataFrame(
        values,
        index=pd.date_range("2020-01-01", periods=observations, freq="D", tz="UTC"),
    )


def test_common_daily_matrix_rejects_missing_unsorted_and_non_numeric_data() -> None:
    valid = _daily_frame(
        {
            "candidate_a": np.array([0.01, -0.02, 0.03]),
            "candidate_b": np.array([0.00, 0.01, -0.01]),
        }
    )
    validated = validate_daily_net_return_matrix(valid)

    pd.testing.assert_frame_equal(validated, valid)
    with pytest.raises(ValueError, match="missing or infinite"):
        validate_daily_net_return_matrix(valid.assign(candidate_a=[0.01, np.nan, 0.03]))
    with pytest.raises(ValueError, match="sorted"):
        validate_daily_net_return_matrix(valid.iloc[::-1])
    with pytest.raises(ValueError, match="numeric"):
        validate_daily_net_return_matrix(valid.assign(candidate_a=["a", "b", "c"]))


def test_dsr_requires_complete_trial_universe_provenance() -> None:
    returns = _daily_frame({"survivor": np.tile([0.012, -0.008, 0.010, -0.004], 64)})

    with pytest.raises(ValueError, match="trial universe is undisclosed"):
        deflated_sharpe_ratio(returns, selected_candidate="survivor")
    with pytest.raises(ValueError, match="cannot be smaller"):
        deflated_sharpe_ratio(
            returns.assign(
                another=returns["survivor"] * 0.5,
                third=returns["survivor"] * -0.5,
            ),
            selected_candidate="survivor",
            total_trials_evaluated=2,
        )


def test_dsr_uses_daily_units_and_penalizes_a_larger_disclosed_search() -> None:
    selected = np.tile([0.014, -0.006, 0.011, -0.003, 0.008, -0.002], 80)
    returns = _daily_frame({"selected": selected})

    ten_trials = deflated_sharpe_ratio(
        returns,
        selected_candidate="selected",
        total_trials_evaluated=10,
    )
    thousand_trials = deflated_sharpe_ratio(
        returns,
        selected_candidate="selected",
        total_trials_evaluated=1000,
    )

    expected_daily_sharpe = float(np.mean(selected) / np.std(selected, ddof=1))
    assert ten_trials.observed_daily_sharpe == pytest.approx(expected_daily_sharpe)
    assert ten_trials.trial_std_daily_sharpe == pytest.approx(
        1 / math.sqrt(len(selected) - 1)
    )
    assert thousand_trials.expected_max_daily_sharpe > (
        ten_trials.expected_max_daily_sharpe
    )
    assert thousand_trials.probability < ten_trials.probability
    assert ten_trials.benchmark_source == "complete_trial_count_iid_zero_sharpe_null"


def test_dsr_can_parameterize_expected_maximum_from_complete_candidate_matrix() -> None:
    base = np.tile([0.012, -0.009, 0.007, -0.004, 0.003], 80)
    returns = _daily_frame(
        {
            "candidate_a": base + 0.0020,
            "candidate_b": base + 0.0010,
            "candidate_c": base - 0.0005,
        }
    )

    result = deflated_sharpe_ratio(
        returns,
        selected_candidate="candidate_a",
        candidate_set_is_complete=True,
    )

    sharpes = returns.mean().to_numpy() / returns.std(ddof=1).to_numpy()
    assert result.trial_count == 3
    assert result.trial_mean_daily_sharpe == pytest.approx(float(sharpes.mean()))
    assert result.trial_std_daily_sharpe == pytest.approx(float(sharpes.std(ddof=1)))
    assert result.benchmark_source == "complete_candidate_matrix"


def test_cscv_pbo_is_zero_for_a_stable_winner_on_every_contiguous_split() -> None:
    observations = 64
    base = np.sin(np.arange(observations) * 0.71) * 0.01
    returns = _daily_frame(
        {
            "stable_best": base + 0.004,
            "middle": base + 0.001,
            "worst": base - 0.002,
        }
    )

    result = cscv_probability_of_backtest_overfitting(returns)

    assert result.defined
    assert result.reason is None
    assert result.pbo == 0.0
    assert result.block_count == 16
    assert result.block_sizes == (4,) * 16
    assert result.split_count == math.comb(16, 8)
    assert dict(result.selection_counts) == {
        "stable_best": math.comb(16, 8),
        "middle": 0,
        "worst": 0,
    }
    assert min(result.logits) > 0


def test_cscv_detects_candidates_that_only_win_inside_their_own_block() -> None:
    observations = 160
    candidate_count = 16
    common_noise = np.sin(np.arange(observations) * 0.37) * 0.001
    values = np.tile(common_noise[:, None], (1, candidate_count))
    for candidate in range(candidate_count):
        values[:, candidate] += (
            np.cos(np.arange(observations) * (0.11 + candidate * 0.001)) * 1e-7
        )
        start = candidate * 10
        values[start : start + 10, candidate] += 0.03 + candidate * 0.00001
    returns = _daily_frame(
        {f"block_{column:02d}": values[:, column] for column in range(candidate_count)}
    )

    result = cscv_probability_of_backtest_overfitting(returns)

    assert result.defined
    assert result.pbo is not None and result.pbo > 0.98
    assert result.split_count == math.comb(16, 8)
    assert np.mean(np.asarray(result.logits) <= 0) == pytest.approx(result.pbo)


def test_cscv_returns_explicit_undefined_for_insufficient_or_degenerate_panel() -> None:
    too_short = _daily_frame(
        {
            "a": np.linspace(-0.01, 0.01, 31),
            "b": np.linspace(0.01, -0.01, 31),
        }
    )
    degenerate = _daily_frame(
        {
            "a": np.ones(64) * 0.001,
            "b": np.linspace(-0.01, 0.01, 64),
        }
    )

    short_result = cscv_probability_of_backtest_overfitting(too_short)
    degenerate_result = cscv_probability_of_backtest_overfitting(degenerate)

    assert not short_result.defined
    assert short_result.pbo is None
    assert "at least 32" in (short_result.reason or "")
    assert not degenerate_result.defined
    assert "zero or invalid" in (degenerate_result.reason or "")


def test_spa_adapter_preserves_common_index_and_converts_returns_to_losses() -> None:
    returns = _daily_frame(
        {
            "a": np.array([0.01, -0.02, 0.03, 0.00]),
            "b": np.array([-0.01, 0.00, 0.02, 0.01]),
        }
    )
    benchmark = pd.Series(
        [0.001, 0.002, -0.001, 0.000], index=returns.index, name="cash"
    )

    prepared = prepare_spa_inputs(returns, benchmark_returns=benchmark)

    pd.testing.assert_index_equal(prepared.benchmark_losses.index, returns.index)
    pd.testing.assert_index_equal(prepared.candidate_losses.index, returns.index)
    np.testing.assert_allclose(prepared.benchmark_losses, -benchmark)
    np.testing.assert_allclose(prepared.candidate_losses, -returns)

    shifted_benchmark = benchmark.copy()
    shifted_benchmark.index = shifted_benchmark.index.shift(1, freq="D")
    with pytest.raises(ValueError, match="exactly"):
        prepare_spa_inputs(returns, benchmark_returns=shifted_benchmark)
