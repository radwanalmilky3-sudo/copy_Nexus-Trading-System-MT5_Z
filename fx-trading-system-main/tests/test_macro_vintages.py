from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import fx_system.macro_vintages as macro_vintages
from fx_system.macro_vintages import (
    CPI_SERIES_ID,
    IP_SERIES_ID,
    classify_rtdsm_vintage_eligibility,
    extract_rtdsm_asof_features,
    rtdsm_eligibility_audit,
)


def _vintage_rows(
    *,
    series_id: str,
    vintage_label: str,
    available_time: str,
    first_month: str,
    levels: list[float],
    quality: str,
) -> list[dict[str, object]]:
    observations = pd.date_range(first_month, periods=len(levels), freq="ME", tz="UTC")
    return [
        {
            "observation_time": observation,
            "vintage_label": vintage_label,
            "available_time": available_time,
            "series_id": series_id,
            "value": level,
            "quality": quality,
            "pit_eligible": True,
        }
        for observation, level in zip(observations, levels, strict=True)
    ]


def _complete_vintages() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    rows.extend(
        _vintage_rows(
            series_id=CPI_SERIES_ID,
            vintage_label="CPI20Q1",
            available_time="2020-02-02T05:00:00Z",
            first_month="2019-01-01",
            levels=list(100.0 * np.exp(np.arange(13) * 0.01)),
            quality="original_cpi_vintage",
        )
    )
    rows.extend(
        _vintage_rows(
            series_id=CPI_SERIES_ID,
            vintage_label="CPI20Q2",
            available_time="2020-05-16T04:00:00Z",
            first_month="2019-01-01",
            levels=list(50.0 * np.exp(np.arange(13) * 0.04)),
            quality="revised_cpi_vintage",
        )
    )
    rows.extend(
        _vintage_rows(
            series_id=IP_SERIES_ID,
            vintage_label="IPT20M2",
            available_time="2020-03-01T05:00:00Z",
            first_month="2019-07-01",
            levels=list(100.0 * np.exp(np.arange(7) * 0.02)),
            quality="original_ip_vintage",
        )
    )
    rows.extend(
        _vintage_rows(
            series_id=IP_SERIES_ID,
            vintage_label="IPT20M5",
            available_time="2020-06-01T04:00:00Z",
            first_month="2019-07-01",
            levels=list(70.0 * np.exp(np.arange(7) * 0.05)),
            quality="revised_ip_vintage",
        )
    )
    return pd.DataFrame(rows)


def test_asof_features_do_not_leak_later_revisions() -> None:
    vintages = _complete_vintages()

    result = extract_rtdsm_asof_features(
        vintages,
        ["2020-04-01T00:00:00Z", "2020-07-01T00:00:00Z"],
    )
    early = result[result["decision_time"] == pd.Timestamp("2020-04-01T00:00:00Z")]
    late = result[result["decision_time"] == pd.Timestamp("2020-07-01T00:00:00Z")]

    assert early.set_index("feature_name")["feature_value"].to_dict() == pytest.approx(
        {
            "us_cpi_12m_log_inflation": 12.0,
            "us_ip_6m_log_growth": 12.0,
        }
    )
    assert late.set_index("feature_name")["feature_value"].to_dict() == pytest.approx(
        {
            "us_cpi_12m_log_inflation": 48.0,
            "us_ip_6m_log_growth": 30.0,
        }
    )
    assert set(early["source_vintage_label"]) == {"CPI20Q1", "IPT20M2"}
    assert set(early["source_quality"]) == {
        "original_cpi_vintage",
        "original_ip_vintage",
    }
    assert set(late["source_vintage_label"]) == {"CPI20Q2", "IPT20M5"}
    assert (result["source_available_time"] <= result["decision_time"]).all()
    assert set(result["source_eligibility"]) == {"conservative_pit"}

    # Changing a future, not-yet-available vintage cannot change the early result.
    future_changed = vintages.copy()
    future_mask = future_changed["vintage_label"].isin(["CPI20Q2", "IPT20M5"])
    future_changed.loc[future_mask, "value"] *= np.linspace(1.0, 4.0, future_mask.sum())
    changed_early = extract_rtdsm_asof_features(
        future_changed, ["2020-04-01T00:00:00Z"]
    )
    pd.testing.assert_series_equal(
        early.set_index("feature_name")["feature_value"].sort_index(),
        changed_early.set_index("feature_name")["feature_value"].sort_index(),
        check_names=False,
    )


def test_rtdsm_row_level_eligibility_separates_verified_and_conservative() -> None:
    vintages = _complete_vintages()
    vintages["availability_policy"] = np.where(
        vintages["series_id"].eq(CPI_SERIES_ID),
        "after_rtdsm_mid_quarter_vintage_date",
        "after_unresolved_ip_vintage_month",
    )
    first_ip = vintages["series_id"].eq(IP_SERIES_ID) & vintages["vintage_label"].eq(
        "IPT20M2"
    )
    vintages.loc[first_ip, "availability_policy"] = "after_verified_g17_release_date"

    classified = classify_rtdsm_vintage_eligibility(vintages)
    cpi = classified.loc[classified["series_id"].eq(CPI_SERIES_ID)]
    unresolved_ip = classified.loc[
        classified["vintage_label"].eq("IPT20M5")
    ]
    assert cpi["external_eligibility"].eq("verified_strict_pit").all()
    assert unresolved_ip["external_eligibility"].eq("conservative_pit").all()

    strict = extract_rtdsm_asof_features(
        vintages,
        ["2020-04-01T00:00:00Z"],
        eligibility_mode="verified_only",
    )
    assert set(strict["source_eligibility"]) == {"verified_strict_pit"}
    assert set(strict["source_vintage_label"]) == {"CPI20Q1", "IPT20M2"}

    audit = rtdsm_eligibility_audit(vintages)
    assert audit["counts_by_eligibility"] == {
        "conservative_pit": 7,
        "verified_strict_pit": 33,
    }
    assert audit["return_labels_opened"] is False


def test_verified_only_fails_when_one_required_series_has_no_strict_rows() -> None:
    vintages = _complete_vintages()
    vintages["availability_policy"] = np.where(
        vintages["series_id"].eq(CPI_SERIES_ID),
        "after_rtdsm_mid_quarter_vintage_date",
        "after_unresolved_ip_vintage_month",
    )
    with pytest.raises(ValueError, match="missing series"):
        extract_rtdsm_asof_features(
            vintages,
            ["2020-07-01T00:00:00Z"],
            eligibility_mode="verified_only",
        )


def test_unknown_rtdsm_availability_policy_fails_closed() -> None:
    vintages = _complete_vintages()
    vintages["availability_policy"] = "guessed_release_time"
    with pytest.raises(ValueError, match="unknown availability policies"):
        classify_rtdsm_vintage_eligibility(vintages)


def test_baseline_must_come_from_selected_vintage() -> None:
    vintages = _complete_vintages()
    is_latest_cpi = vintages["vintage_label"].eq("CPI20Q2")
    latest_observation = vintages.loc[is_latest_cpi, "observation_time"].max()
    vintages = vintages.loc[
        ~is_latest_cpi | vintages["observation_time"].eq(latest_observation)
    ]

    with pytest.raises(ValueError, match="lacks its exact 12-month baseline"):
        extract_rtdsm_asof_features(vintages, ["2020-07-01T00:00:00Z"])


def test_searchsorted_selection_matches_naive_available_time_filter() -> None:
    vintages = _complete_vintages()
    cpi_boundary = pd.Timestamp("2020-05-16T04:00:00Z")
    ip_boundary = pd.Timestamp("2020-06-01T04:00:00Z")
    decisions = pd.DatetimeIndex(
        [
            cpi_boundary - pd.Timedelta(1, unit="ns"),
            cpi_boundary,
            ip_boundary - pd.Timedelta(1, unit="ns"),
            ip_boundary,
        ]
    )

    result = extract_rtdsm_asof_features(vintages, decisions)
    actual = result.set_index(["decision_time", "series_id"])["source_vintage_label"]
    timestamped = vintages.assign(
        available_time=pd.to_datetime(vintages["available_time"], utc=True)
    )
    expected: dict[tuple[pd.Timestamp, str], str] = {}
    for decision in decisions:
        for series_id in (CPI_SERIES_ID, IP_SERIES_ID):
            candidates = timestamped.loc[
                (timestamped["series_id"] == series_id)
                & (timestamped["available_time"] <= decision)
            ]
            latest_available = candidates["available_time"].max()
            expected[(decision, series_id)] = str(
                candidates.loc[
                    candidates["available_time"] == latest_available,
                    "vintage_label",
                ].iloc[0]
            )

    assert actual.to_dict() == expected
    cpi = result.loc[result["series_id"] == CPI_SERIES_ID].set_index("decision_time")

    assert cpi.loc[
        cpi_boundary - pd.Timedelta(1, unit="ns"), "feature_value"
    ] == pytest.approx(12.0)
    assert cpi.loc[cpi_boundary, "feature_value"] == pytest.approx(48.0)


def test_thousands_of_decisions_reuse_precomputed_vintage_features(monkeypatch) -> None:
    vintages = _complete_vintages()
    decisions = pd.date_range("2020-07-01", periods=2_500, freq="D", tz="UTC")
    original = macro_vintages._within_vintage_feature
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(macro_vintages, "_within_vintage_feature", counted)
    result = macro_vintages.extract_rtdsm_asof_features(vintages, decisions)

    assert len(result) == 2 * len(decisions)
    assert result["decision_time"].nunique() == len(decisions)
    # There are four source vintages in the input.  A decision-by-decision
    # implementation would call this 5,000 times; grouping/caching may call it
    # no more than once per vintage and currently needs only the two selected.
    assert calls <= vintages["vintage_label"].nunique()


def test_duplicate_vintage_observation_key_fails_closed() -> None:
    vintages = _complete_vintages()

    with pytest.raises(ValueError, match="duplicate key"):
        extract_rtdsm_asof_features(
            pd.concat([vintages, vintages.iloc[[0]]], ignore_index=True),
            ["2020-04-01T00:00:00Z"],
        )


def test_future_observation_fails_closed() -> None:
    vintages = _complete_vintages()
    vintages.loc[0, "observation_time"] = "2021-01-31T00:00:00Z"

    with pytest.raises(ValueError, match="future observation"):
        extract_rtdsm_asof_features(vintages, ["2020-04-01T00:00:00Z"])


@pytest.mark.parametrize(
    ("column", "bad_value", "message"),
    [
        ("observation_time", None, "missing or invalid observation_time"),
        ("available_time", "not-a-time", "missing or invalid available_time"),
    ],
)
def test_missing_source_time_fails_closed(
    column: str, bad_value: object, message: str
) -> None:
    vintages = _complete_vintages()
    vintages.loc[0, column] = bad_value

    with pytest.raises(ValueError, match=message):
        extract_rtdsm_asof_features(vintages, ["2020-04-01T00:00:00Z"])


def test_missing_decision_time_and_pre_release_decision_fail_closed() -> None:
    vintages = _complete_vintages()

    with pytest.raises(ValueError, match="missing or invalid timestamp"):
        extract_rtdsm_asof_features(vintages, [None])
    with pytest.raises(ValueError, match="duplicate keys"):
        extract_rtdsm_asof_features(
            vintages,
            ["2020-04-01T00:00:00Z", "2020-04-01T00:00:00Z"],
        )
    with pytest.raises(ValueError, match="no US_CPI_SA_RTDSM vintage is available"):
        extract_rtdsm_asof_features(vintages, ["2020-01-01T00:00:00Z"])
