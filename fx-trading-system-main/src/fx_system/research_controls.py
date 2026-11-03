from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from typing import Literal

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_numeric_dtype

JointDateRandomizationMethod = Literal["circular_shift", "permutation"]


class FutureInformationError(ValueError):
    """Raised when a research row uses information unavailable at decision time."""


def _validate_random_state(random_state: int) -> int:
    if isinstance(random_state, bool) or not isinstance(random_state, (int, np.integer)):
        raise ValueError("random_state must be an explicit non-negative integer")
    seed = int(random_state)
    if seed < 0:
        raise ValueError("random_state must be an explicit non-negative integer")
    return seed


def _validate_factor_panel(panel: pd.DataFrame, *, minimum_rows: int = 2) -> None:
    if not isinstance(panel, pd.DataFrame):
        raise TypeError("panel must be a pandas DataFrame")
    if len(panel) < minimum_rows:
        raise ValueError(f"panel must contain at least {minimum_rows} rows")
    if not isinstance(panel.index, pd.DatetimeIndex):
        raise ValueError("panel must use a DatetimeIndex containing the common dates")
    if panel.index.hasnans:
        raise ValueError("panel date index cannot contain missing values")
    if not panel.index.is_unique:
        raise ValueError("panel date index must be unique")
    if not panel.index.is_monotonic_increasing:
        raise ValueError("panel date index must be sorted in increasing order")
    if not len(panel.columns):
        raise ValueError("panel must contain at least one factor column")
    if panel.columns.has_duplicates:
        raise ValueError("panel factor columns must be unique")
    if not all(isinstance(column, str) and column for column in panel.columns):
        raise ValueError("panel factor columns must have non-empty string names")

    for column in panel.columns:
        values = panel[column]
        if is_bool_dtype(values.dtype) or not is_numeric_dtype(values.dtype):
            raise ValueError(f"factor column {column!r} must be numeric and non-boolean")
        numeric = values.to_numpy(dtype=float, na_value=np.nan)
        if np.isinf(numeric).any():
            raise ValueError(f"factor column {column!r} cannot contain infinite values")


def joint_date_mapping(
    observations: int,
    *,
    method: JointDateRandomizationMethod,
    random_state: int,
) -> np.ndarray:
    """Return one seeded date mapping to apply jointly to every panel column.

    The mapping is deliberately non-identity. A circular shift preserves the
    complete serial and cross-sectional row structure, while a permutation
    preserves complete rows but destroys their original date alignment.
    """
    if isinstance(observations, bool) or not isinstance(observations, (int, np.integer)):
        raise ValueError("observations must be an integer")
    observations = int(observations)
    if observations < 2:
        raise ValueError("observations must be at least two")
    if method not in {"circular_shift", "permutation"}:
        raise ValueError("method must be 'circular_shift' or 'permutation'")

    generator = np.random.default_rng(_validate_random_state(random_state))
    positions = np.arange(observations, dtype=np.int64)
    if method == "circular_shift":
        shift = int(generator.integers(1, observations))
        return (positions + shift) % observations

    mapping = generator.permutation(observations)
    if np.array_equal(mapping, positions):
        mapping = np.roll(mapping, 1)
    return mapping


def randomize_common_date_panel(
    panel: pd.DataFrame,
    *,
    method: JointDateRandomizationMethod,
    random_state: int,
) -> pd.DataFrame:
    """Randomize a common-date panel with exactly one shared row mapping.

    Values, including NaNs, move as complete rows. Consequently the
    contemporaneous missingness and cross-column dependence structure are not
    silently altered by independently shuffling instruments.
    """
    _validate_factor_panel(panel)
    mapping = joint_date_mapping(
        len(panel), method=method, random_state=random_state
    )
    randomized = panel.iloc[mapping].copy()
    randomized.index = panel.index.copy()
    randomized.index.name = panel.index.name
    randomized.attrs = panel.attrs.copy()
    return randomized


def _shadow_permutation(values: np.ndarray, generator: np.random.Generator) -> np.ndarray:
    mapping = generator.permutation(len(values))
    if len(values) > 1 and np.array_equal(mapping, np.arange(len(values))):
        mapping = np.roll(mapping, 1)
    return values[mapping]


def generate_shadow_factors(
    factors: pd.DataFrame,
    *,
    random_state: int,
    prefix: str = "shadow__",
) -> pd.DataFrame:
    """Generate independently permuted factor controls with fixed NaN masks.

    Each shadow preserves its source factor's observed marginal distribution.
    Only finite cells are shuffled, so a factor is never made artificially
    available on a date where its source was missing.
    """
    _validate_factor_panel(factors)
    if not isinstance(prefix, str) or not prefix:
        raise ValueError("prefix must be a non-empty string")
    _validate_random_state(random_state)
    generator = np.random.default_rng(int(random_state))
    output = pd.DataFrame(index=factors.index.copy())
    for column in factors.columns:
        source = factors[column].to_numpy(dtype=float, na_value=np.nan)
        observed = ~np.isnan(source)
        shadow = np.full(len(source), np.nan, dtype=float)
        shadow[observed] = _shadow_permutation(source[observed], generator)
        output[f"{prefix}{column}"] = shadow
    output.index.name = factors.index.name
    output.attrs = {
        "negative_control": "independent_observed_value_permutation",
        "random_state": int(random_state),
    }
    return output


def generate_random_factors(
    template: pd.DataFrame,
    *,
    random_state: int,
    prefix: str = "random__",
) -> pd.DataFrame:
    """Generate seeded standard-normal controls using a template's NaN masks."""
    _validate_factor_panel(template)
    if not isinstance(prefix, str) or not prefix:
        raise ValueError("prefix must be a non-empty string")
    _validate_random_state(random_state)
    generator = np.random.default_rng(int(random_state))
    output = pd.DataFrame(index=template.index.copy())
    for column in template.columns:
        source = template[column].to_numpy(dtype=float, na_value=np.nan)
        observed = ~np.isnan(source)
        random_values = np.full(len(source), np.nan, dtype=float)
        random_values[observed] = generator.standard_normal(observed.sum())
        output[f"{prefix}{column}"] = random_values
    output.index.name = template.index.name
    output.attrs = {
        "negative_control": "independent_standard_normal",
        "random_state": int(random_state),
    }
    return output


def _normalized_required_times(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"availability audit is missing columns {sorted(missing)}")
    if frame.empty:
        raise ValueError("availability audit cannot attest an empty frame")

    result = frame.copy()
    for column in columns:
        normalized = pd.to_datetime(result[column], utc=True, errors="coerce")
        if normalized.isna().any():
            raise ValueError(
                f"availability audit contains missing or invalid {column!r} values"
            )
        result[column] = normalized
    return result


def validate_research_availability(
    frame: pd.DataFrame,
    *,
    observation_time_column: str = "observation_time",
    available_time_column: str = "available_time",
    decision_time_column: str = "decision_time",
) -> pd.DataFrame:
    """Fail closed unless every value was observable by its decision time.

    Both the economic observation timestamp and its actual availability
    timestamp are checked. This intentionally rejects future-information
    canaries even if a caller has accidentally assigned an earlier availability
    timestamp to a future observation.
    """
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas DataFrame")
    columns = (
        observation_time_column,
        available_time_column,
        decision_time_column,
    )
    if any(not isinstance(column, str) or not column for column in columns):
        raise ValueError("availability column names must be non-empty strings")
    if len(set(columns)) != len(columns):
        raise ValueError("availability column names must be distinct")

    result = _normalized_required_times(frame, columns)
    observation = result[observation_time_column]
    available = result[available_time_column]
    decision = result[decision_time_column]

    ordering_violations = observation > available
    if ordering_violations.any():
        raise FutureInformationError(
            "availability audit rejected "
            f"{int(ordering_violations.sum())} row(s) where observation_time is after "
            "available_time"
        )

    future_observations = observation > decision
    future_availability = available > decision
    if future_observations.any() or future_availability.any():
        raise FutureInformationError(
            "future information detected: "
            f"observation_time exceeds decision_time in {int(future_observations.sum())} "
            "row(s); available_time exceeds decision_time in "
            f"{int(future_availability.sum())} row(s)"
        )
    return result


def make_future_information_canary(
    decision_times: Sequence[object] | pd.Series | pd.Index,
    *,
    lead: timedelta = timedelta(days=1),
) -> pd.DataFrame:
    """Build a deliberately invalid future factor to test availability gates."""
    decision = pd.to_datetime(decision_times, utc=True, errors="coerce")
    if len(decision) == 0:
        raise ValueError("decision_times must contain at least one timestamp")
    if pd.isna(decision).any():
        raise ValueError("decision_times contain missing or invalid timestamps")
    if not isinstance(lead, timedelta):
        raise ValueError("lead must be a valid positive duration")
    lead_delta = pd.Timedelta(lead)
    if lead_delta <= pd.Timedelta(0):
        raise ValueError("lead must be a valid positive duration")

    decision_index = pd.DatetimeIndex(decision)
    future = decision_index + lead_delta
    return pd.DataFrame(
        {
            "factor": "future_information_canary",
            "decision_time": decision_index,
            "observation_time": future,
            "available_time": future,
            "value": np.arange(1, len(decision_index) + 1, dtype=float),
        }
    )
