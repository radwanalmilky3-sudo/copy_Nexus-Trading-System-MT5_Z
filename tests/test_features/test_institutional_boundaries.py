import math

import numpy as np
import pytest

from services.nexus_features import institutional_features as institutional


@pytest.mark.parametrize("breakpoints,expected_age", [([90, 100], 10), ([100], 999)])
def test_change_points_ignore_terminal_segment_boundary(monkeypatch, breakpoints, expected_age):
    class Detector:
        def __init__(self, **kwargs):
            pass

        def fit(self, prices):
            return self

        def predict(self, pen):
            return breakpoints

    monkeypatch.setattr(institutional, "_RUPTURES_OK", True)
    monkeypatch.setattr(institutional, "Pelt", Detector, raising=False)
    result = institutional.NexusInstitutionalFeatures().change_point_detection(np.arange(100))
    assert result["bars_since"] == expected_age
    assert result["disable_lstm"] is (expected_age < 15)


def test_flat_prices_do_not_invent_buy_pressure():
    result = institutional.NexusInstitutionalFeatures().tick_rule_imbalance(np.ones(100))
    assert result["tick_imbalance"] == 0
    assert result["directional_bias"] == "NEUTRAL"


def test_unchanged_ticks_carry_last_observed_direction():
    result = institutional.NexusInstitutionalFeatures().tick_rule_imbalance(
        np.array([3.0, 2.0, 2.0, 2.0]), window=4,
    )
    assert result["tick_imbalance"] == -1


def test_temporal_growth_uses_number_of_return_intervals():
    history = [100.0 * math.exp(0.002 * index) for index in range(30)]
    result = institutional.NexusInstitutionalFeatures().temporal_growth_rate(history)
    assert result["temporal_growth_g"] == pytest.approx(0.002)
