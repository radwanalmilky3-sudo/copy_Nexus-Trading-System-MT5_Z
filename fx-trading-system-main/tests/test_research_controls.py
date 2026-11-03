from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from fx_system.research_controls import (
    FutureInformationError,
    generate_random_factors,
    generate_shadow_factors,
    joint_date_mapping,
    make_future_information_canary,
    randomize_common_date_panel,
    validate_research_availability,
)


def _factor_panel() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "eurusd": [0.0, 1.0, np.nan, 3.0, 4.0, 5.0, 6.0, 7.0],
            "usdjpy": [100.0, 101.0, np.nan, 103.0, np.nan, 105.0, 106.0, 107.0],
        },
        index=pd.date_range("2020-01-01", periods=8, tz="UTC", name="date"),
    )


@pytest.mark.parametrize("method", ["circular_shift", "permutation"])
def test_common_date_randomization_is_seeded_and_uses_one_mapping(method: str) -> None:
    panel = _factor_panel()
    mapping = joint_date_mapping(len(panel), method=method, random_state=1729)

    first = randomize_common_date_panel(panel, method=method, random_state=1729)
    second = randomize_common_date_panel(panel, method=method, random_state=1729)
    expected = panel.iloc[mapping].copy()
    expected.index = panel.index

    pd.testing.assert_frame_equal(first, second)
    pd.testing.assert_frame_equal(first, expected)
    assert not np.array_equal(mapping, np.arange(len(panel)))
    np.testing.assert_array_equal(first.isna(), panel.iloc[mapping].set_axis(panel.index).isna())


def test_circular_mapping_is_one_nonzero_rotation_and_permutation_is_complete() -> None:
    circular = joint_date_mapping(20, method="circular_shift", random_state=12)
    permutation = joint_date_mapping(20, method="permutation", random_state=12)

    assert len(set((circular - np.arange(20)) % 20)) == 1
    assert int((circular[0] - 0) % 20) != 0
    np.testing.assert_array_equal(np.sort(permutation), np.arange(20))


def test_shadow_and_random_controls_are_reproducible_and_keep_nan_masks() -> None:
    panel = _factor_panel()

    shadows = generate_shadow_factors(panel, random_state=2027)
    same_shadows = generate_shadow_factors(panel, random_state=2027)
    randoms = generate_random_factors(panel, random_state=2027)
    same_randoms = generate_random_factors(panel, random_state=2027)

    pd.testing.assert_frame_equal(shadows, same_shadows)
    pd.testing.assert_frame_equal(randoms, same_randoms)
    for source_column in panel:
        shadow_column = f"shadow__{source_column}"
        random_column = f"random__{source_column}"
        np.testing.assert_array_equal(shadows[shadow_column].isna(), panel[source_column].isna())
        np.testing.assert_array_equal(randoms[random_column].isna(), panel[source_column].isna())
        np.testing.assert_allclose(
            np.sort(shadows[shadow_column].dropna()),
            np.sort(panel[source_column].dropna()),
        )

    assert not generate_random_factors(panel, random_state=2028).equals(randoms)


@pytest.mark.parametrize(
    ("bad_panel", "message"),
    [
        (pd.DataFrame({"x": [1.0, 2.0]}), "DatetimeIndex"),
        (
            pd.DataFrame(
                {"x": [1.0, 2.0]},
                index=pd.to_datetime(["2020-01-01", "2020-01-01"], utc=True),
            ),
            "unique",
        ),
        (
            pd.DataFrame(
                {"x": [1.0, np.inf]},
                index=pd.date_range("2020-01-01", periods=2, tz="UTC"),
            ),
            "infinite",
        ),
    ],
)
def test_randomization_controls_fail_closed_on_invalid_panels(
    bad_panel: pd.DataFrame, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        randomize_common_date_panel(
            bad_panel, method="permutation", random_state=1
        )

    with pytest.raises(ValueError, match="random_state"):
        joint_date_mapping(10, method="permutation", random_state=-1)


def test_availability_audit_normalizes_valid_rows_and_rejects_each_future_path() -> None:
    valid = pd.DataFrame(
        {
            "observation_time": ["2020-01-01", "2020-01-02"],
            "available_time": ["2020-01-02", "2020-01-03"],
            "decision_time": ["2020-01-03", "2020-01-03"],
            "value": [1.0, 2.0],
        }
    )
    audited = validate_research_availability(valid)
    assert str(audited["decision_time"].dtype) == "datetime64[ns, UTC]"

    future_observation = valid.iloc[[0]].copy()
    future_observation["observation_time"] = "2020-01-04"
    future_observation["available_time"] = "2020-01-04"
    with pytest.raises(FutureInformationError, match="observation_time exceeds"):
        validate_research_availability(future_observation)

    future_available = valid.iloc[[0]].copy()
    future_available["available_time"] = "2020-01-04"
    with pytest.raises(FutureInformationError, match="available_time exceeds"):
        validate_research_availability(future_available)


def test_future_information_canary_cannot_pass_availability_audit() -> None:
    canary = make_future_information_canary(
        pd.date_range("2025-01-01", periods=3, tz="UTC"), lead=timedelta(hours=2)
    )

    with pytest.raises(FutureInformationError, match="future information detected"):
        validate_research_availability(canary)


@pytest.mark.parametrize(
    "frame",
    [
        pd.DataFrame(
            {
                "observation_time": ["not-a-time"],
                "available_time": ["2020-01-01"],
                "decision_time": ["2020-01-02"],
            }
        ),
        pd.DataFrame(
            {
                "observation_time": ["2020-01-01"],
                "available_time": ["2020-01-01"],
            }
        ),
        pd.DataFrame(
            columns=["observation_time", "available_time", "decision_time"]
        ),
    ],
)
def test_availability_audit_fails_closed_on_unverifiable_data(frame: pd.DataFrame) -> None:
    with pytest.raises(ValueError):
        validate_research_availability(frame)
