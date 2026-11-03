from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fx_system.structured_external_features import (
    FORMAL_REGIME_FEATURES,
    build_gscpi_release_features,
    build_structured_external_regime_panel,
    extract_gscpi_asof_features,
    normalize_gscpi_vintages,
)


def _gscpi_vintages() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for release_number, available in enumerate(
        pd.date_range("2022-01-06T15:00:00Z", periods=8, freq="31D")
    ):
        observations = pd.date_range("2021-10-31", periods=3, freq="ME", tz="UTC")
        for observation_number, observation in enumerate(observations):
            rows.append(
                {
                    "observation_time": observation,
                    "available_time": available,
                    "vintage_label": f"V{release_number:02d}",
                    "series_id": "GSCPI",
                    "value": release_number + observation_number / 10,
                    "provider": "new_york_fed",
                    "quality": "verified_monthly_vintage_from_2022",
                }
            )
    return pd.DataFrame(rows)


def _rtdsm_vintages() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    specifications = (
        (
            "US_CPI_SA_RTDSM",
            "CPI22Q2",
            "2022-07-01T00:00:00Z",
            "2021-05-01",
            13,
            0.01,
            "after_rtdsm_mid_quarter_vintage_date",
        ),
        (
            "US_IP_TOTAL_SA_RTDSM",
            "IPT22M6",
            "2022-07-01T00:00:00Z",
            "2021-11-01",
            7,
            0.02,
            "after_verified_g17_release_date",
        ),
        (
            "US_CPI_SA_RTDSM",
            "CPI22Q3",
            "2022-09-01T00:00:00Z",
            "2021-05-01",
            13,
            0.03,
            "after_rtdsm_mid_quarter_vintage_date",
        ),
        (
            "US_IP_TOTAL_SA_RTDSM",
            "IPT22M8",
            "2022-09-01T00:00:00Z",
            "2021-11-01",
            7,
            0.04,
            "after_verified_g17_release_date",
        ),
    )
    for series_id, label, available, first_month, periods, growth, policy in specifications:
        observations = pd.date_range(first_month, periods=periods, freq="ME", tz="UTC")
        levels = 100.0 * np.exp(np.arange(periods) * growth)
        for observation, level in zip(observations, levels, strict=True):
            rows.append(
                {
                    "observation_time": observation,
                    "vintage_label": label,
                    "available_time": available,
                    "series_id": series_id,
                    "value": level,
                    "quality": "verified_fixture_vintage",
                    "pit_eligible": True,
                    "availability_policy": policy,
                }
            )
    return pd.DataFrame(rows)


def test_gscpi_release_features_use_only_each_vintages_latest_observation() -> None:
    releases = build_gscpi_release_features(_gscpi_vintages())
    assert len(releases) == 8
    assert releases["gscpi_level"].tolist() == pytest.approx(
        [number + 0.2 for number in range(8)]
    )
    assert releases["gscpi_change_6_vintages"].iloc[:6].isna().all()
    assert releases["gscpi_change_6_vintages"].iloc[6:].tolist() == pytest.approx(
        [6.0, 6.0]
    )


def test_gscpi_asof_selection_is_backward_stale_aware_and_prefix_invariant() -> None:
    vintages = _gscpi_vintages()
    releases = build_gscpi_release_features(vintages)
    boundary = releases.loc[6, "source_available_time"]
    decisions = [boundary - pd.Timedelta(1, unit="ns"), boundary]
    before = extract_gscpi_asof_features(vintages, decisions)
    assert before.loc[0, "source_vintage_label"] == "V05"
    assert pd.isna(before.loc[0, "gscpi_risk_state_pit"])
    assert before.loc[1, "source_vintage_label"] == "V06"
    assert before.loc[1, "gscpi_risk_state_pit"] == pytest.approx(12.2)
    assert (before["source_available_time"] <= before["decision_time"]).all()

    changed = vintages.copy()
    changed.loc[changed["vintage_label"].eq("V07"), "value"] += 1000
    changed_before = extract_gscpi_asof_features(changed, [boundary])
    pd.testing.assert_series_equal(
        before.loc[1, ["gscpi_level", "gscpi_change_6_vintages"]],
        changed_before.loc[0, ["gscpi_level", "gscpi_change_6_vintages"]],
        check_names=False,
    )

    stale = extract_gscpi_asof_features(
        vintages,
        [releases.iloc[-1]["source_available_time"] + pd.Timedelta(76, unit="D")],
    )
    assert stale.loc[0, "source_eligibility"] == "verified_strict_pit"
    assert stale.loc[0, "feature_status"] == "stale"
    assert pd.notna(stale.loc[0, "source_available_time"])
    assert pd.isna(stale.loc[0, "gscpi_level"])


def test_gscpi_contract_fails_closed_on_quality_time_and_duplicate_errors() -> None:
    bad_quality = _gscpi_vintages()
    bad_quality.loc[0, "quality"] = "current_vintage"
    with pytest.raises(ValueError, match="not verified"):
        normalize_gscpi_vintages(bad_quality)

    future = _gscpi_vintages()
    future.loc[0, "observation_time"] = future.loc[0, "available_time"]
    with pytest.raises(ValueError, match="must precede"):
        normalize_gscpi_vintages(future)

    duplicate = pd.concat([_gscpi_vintages(), _gscpi_vintages().iloc[[0]]])
    with pytest.raises(ValueError, match="duplicate key"):
        normalize_gscpi_vintages(duplicate)


def test_gscpi_require_complete_rejects_pre_history_and_short_vintage_chain() -> None:
    with pytest.raises(ValueError, match="unavailable or lacks six"):
        extract_gscpi_asof_features(
            _gscpi_vintages(),
            ["2022-02-01T00:00:00Z"],
            require_complete=True,
        )


def test_unified_regime_panel_preserves_strict_lineage_and_future_invariance() -> None:
    gscpi = _gscpi_vintages()
    rtdsm = _rtdsm_vintages()
    releases = build_gscpi_release_features(gscpi)
    decision = releases.loc[6, "source_available_time"]

    panel = build_structured_external_regime_panel(gscpi, rtdsm, [decision])
    assert list(panel.values.columns) == ["decision_time", *FORMAL_REGIME_FEATURES]
    assert panel.values.loc[0, "gscpi_risk_state_pit"] == pytest.approx(12.2)
    assert panel.values.loc[0, "us_cpi_12m_log_inflation"] == pytest.approx(12.0)
    assert panel.values.loc[0, "us_ip_6m_log_growth"] == pytest.approx(12.0)
    assert len(panel.lineage) == 3
    assert panel.lineage["feature_status"].eq("ready").all()
    assert panel.lineage["source_eligibility"].eq("verified_strict_pit").all()
    assert (
        panel.lineage["source_available_time"] <= panel.lineage["decision_time"]
    ).all()

    changed_gscpi = gscpi.copy()
    changed_gscpi.loc[changed_gscpi["vintage_label"].eq("V07"), "value"] += 1000
    changed_rtdsm = rtdsm.copy()
    changed_rtdsm.loc[
        changed_rtdsm["vintage_label"].isin(["CPI22Q3", "IPT22M8"]), "value"
    ] *= 10
    changed = build_structured_external_regime_panel(
        changed_gscpi, changed_rtdsm, [decision]
    )
    pd.testing.assert_frame_equal(panel.values, changed.values)
    pd.testing.assert_series_equal(
        panel.lineage.set_index("feature_name")["source_vintage_label"],
        changed.lineage.set_index("feature_name")["source_vintage_label"],
    )


def test_unified_regime_panel_fails_closed_when_a_formal_feature_is_missing() -> None:
    with pytest.raises(ValueError, match="panel is incomplete"):
        build_structured_external_regime_panel(
            _gscpi_vintages(),
            _rtdsm_vintages(),
            ["2022-07-02T00:00:00Z"],
            require_complete=True,
        )
