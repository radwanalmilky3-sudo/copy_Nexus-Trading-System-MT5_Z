from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fx_system.intraday_validation import (
    generate_joint_sign_negative_controls,
    prepare_intraday_return_panel,
    run_intraday_validation,
)


def _series(values: np.ndarray, *, start: str = "2020-01-01") -> pd.Series:
    return pd.Series(
        values,
        index=pd.date_range(start, periods=len(values), freq="D", tz="UTC"),
    )


def _stable_candidates(observations: int = 96) -> dict[str, pd.Series]:
    base = np.sin(np.arange(observations) * 0.73) * 0.005
    return {
        "fix_w": _series(base + 0.004),
        "asia_london": _series(base + 0.002),
        "local_session": _series(base - 0.001),
    }


def test_prepare_intraday_panel_reports_union_coverage_and_uses_strict_intersection() -> None:
    candidates = _stable_candidates(60)
    candidates["asia_london"] = candidates["asia_london"].drop(
        candidates["asia_london"].index[[3, 17, 31]]
    )

    panel = prepare_intraday_return_panel(
        candidates,
        candidate_set_is_complete=True,
        minimum_common_observations=40,
    )

    assert panel.union_date_count == 60
    assert panel.common_date_count == 57
    assert len(panel.returns) == 57
    asia = panel.coverage.loc[panel.coverage["candidate"] == "asia_london"].iloc[0]
    assert asia["observed_dates"] == 57
    assert asia["missing_dates"] == 3
    assert panel.returns.attrs["missing_returns_filled"] is False


def test_prepare_intraday_panel_fails_closed_on_undisclosed_or_thin_family() -> None:
    candidates = _stable_candidates(20)

    with pytest.raises(ValueError, match="complete candidate set"):
        prepare_intraday_return_panel(
            candidates,
            candidate_set_is_complete=False,
            minimum_common_observations=10,
        )
    with pytest.raises(ValueError, match="only 20 common"):
        prepare_intraday_return_panel(
            candidates,
            candidate_set_is_complete=True,
            minimum_common_observations=40,
        )


def test_joint_sign_controls_preserve_magnitudes_and_cross_candidate_sign_path() -> None:
    panel = prepare_intraday_return_panel(
        _stable_candidates(48),
        candidate_set_is_complete=True,
        minimum_common_observations=40,
    )

    controls = generate_joint_sign_negative_controls(
        panel.returns, random_state=1729
    )

    np.testing.assert_allclose(
        np.abs(controls.to_numpy()), np.abs(panel.returns.to_numpy())
    )
    ratios = controls.to_numpy() / panel.returns.to_numpy()
    np.testing.assert_allclose(ratios, np.repeat(ratios[:, :1], ratios.shape[1], axis=1))
    assert set(np.unique(ratios)) == {-1.0, 1.0}
    assert controls.attrs["cross_candidate_date_mapping_shared"] is True


def test_intraday_validation_is_reproducible_joint_and_never_reports_zero_p() -> None:
    panel = prepare_intraday_return_panel(
        _stable_candidates(),
        candidate_set_is_complete=True,
        minimum_common_observations=40,
    )

    first = run_intraday_validation(
        panel,
        resamples=999,
        expected_block_length=5,
        fdr_level=0.10,
        random_state=1729,
        total_trials_evaluated=3315,
    )
    second = run_intraday_validation(
        panel,
        resamples=999,
        expected_block_length=5,
        fdr_level=0.10,
        random_state=1729,
        total_trials_evaluated=3315,
    )

    pd.testing.assert_frame_equal(first.candidate_statistics, second.candidate_statistics)
    pd.testing.assert_frame_equal(
        first.negative_control_statistics, second.negative_control_statistics
    )
    stats = first.candidate_statistics.set_index("candidate")
    assert (stats["empirical_p_value"] >= 1 / 1000).all()
    assert (stats["by_q_value"] >= stats["bh_q_value"]).all()
    assert bool(stats.loc["fix_w", "bh_selected"])
    assert first.manifest["negative_control_pass"]
    assert first.manifest["future_information_canary_rejected"]
    assert first.manifest["empirical_p_value_formula"] == (
        "(exceedances + 1) / (resamples + 1)"
    )
    assert first.deflated_sharpe is not None
    assert first.deflated_sharpe.trial_count == 3315
    assert first.pbo.defined and first.pbo.pbo == 0.0
    np.testing.assert_allclose(
        first.spa_inputs.candidate_losses.to_numpy(), -panel.returns.to_numpy()
    )


def test_intraday_validation_enforces_bootstrap_fdr_resolution() -> None:
    panel = prepare_intraday_return_panel(
        _stable_candidates(48),
        candidate_set_is_complete=True,
        minimum_common_observations=40,
    )

    with pytest.raises(ValueError, match="cannot resolve"):
        run_intraday_validation(
            panel,
            resamples=28,
            expected_block_length=5,
            fdr_level=0.10,
            random_state=1,
            total_trials_evaluated=3315,
        )
