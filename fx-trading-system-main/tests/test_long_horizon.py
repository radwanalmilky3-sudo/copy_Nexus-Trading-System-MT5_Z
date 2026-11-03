from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from fx_system.config import DataConfig
from fx_system.data import SyntheticFXProvider
from fx_system.long_horizon import (
    build_long_horizon_folds,
    build_long_horizon_labels,
    build_long_horizon_research,
    to_daily_market_data,
    write_long_horizon_artifacts,
)
from fx_system.long_horizon_config import (
    LongHorizonConfig,
    LongHorizonExternalConfig,
    LongHorizonSettings,
)
from fx_system.long_horizon_research import (
    _block_bootstrap_mean_p_value,
    _filter_oos_horizon_before_test_end,
    _one_factor_statistic,
    _regime_quintile_spread,
    run_long_horizon_screen,
    write_long_horizon_screen_artifacts,
)

SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "EURJPY"]


def _config(tmp_path=None, *, external_enabled=False) -> LongHorizonConfig:
    external = LongHorizonExternalConfig(enabled=external_enabled)
    if tmp_path is not None:
        external = external.model_copy(
            update={
                "raw_directory": tmp_path / "external_raw",
                "cftc_file": tmp_path / "currency_positioning.csv",
                "official_rates_file": tmp_path / "official_rate_observations.csv",
                "supplemental_file": tmp_path / "supplemental_observations.csv",
                "gscpi_vintages_file": tmp_path / "gscpi_vintages.csv",
            }
        )
    return LongHorizonConfig(
        data=DataConfig(
            provider="synthetic",
            symbols=SYMBOLS,
            interval="1d",
            price_mode="mid",
            start="2008-01-01",
            synthetic_bars=5000,
        ),
        external=external,
        research=LongHorizonSettings(
            train_years=5,
            test_years=1,
            step_years=1,
            minimum_history_years=3,
        ),
    )


def _synthetic_data(config: LongHorizonConfig):
    return SyntheticFXProvider(seed=17).generate(
        config.data.symbols,
        config.data.synthetic_bars,
        config.data.interval,
        config.data.start,
        config.data.price_mode,
    )


def test_long_horizon_config_isolated_from_weekly_holding_cap() -> None:
    config = _config()

    assert config.research.horizons == [21, 42, 63]
    assert config.research.maximum_horizon == 63
    assert not hasattr(config.research, "max_holding_hours")
    with pytest.raises(ValueError, match="252-21"):
        LongHorizonSettings(momentum_skip_days=20)


def test_two_pair_time_series_long_horizon_excludes_cross_sectional_families() -> None:
    settings = LongHorizonSettings(
        research_mode="time_series_panel",
        train_years=5,
        test_years=1,
        step_years=1,
        minimum_history_years=3,
    )
    config = LongHorizonConfig(
        data=DataConfig(
            provider="synthetic",
            symbols=["EURUSD", "GBPUSD"],
            interval="1d",
            price_mode="mid",
            start="2008-01-01",
            synthetic_bars=5000,
        ),
        external=LongHorizonExternalConfig(enabled=False),
        research=settings,
    )
    data = SyntheticFXProvider(seed=23).generate(
        config.data.symbols,
        config.data.synthetic_bars,
        "1d",
        config.data.start,
        "mid",
    )
    build = build_long_horizon_research(data, config)
    assert build.audit["research_mode"] == "time_series_panel"
    assert not set(build.catalog["family"]) & {
        "currency_graph",
        "cross_sectional",
        "value_trend",
    }
    # Price-only round contract: with external data disabled, the eligible catalog
    # must be exactly the 16 preregistered price/path factors (11 directional + 5
    # risk-state), giving 16 x 3 horizons = 48 hypotheses per fold.
    assert len(build.catalog) == 16
    assert set(build.catalog["name"]) == {
        "momentum_21d",
        "momentum_63d",
        "momentum_126d",
        "momentum_252d",
        "momentum_252d_skip_21d",
        "trend_tstat_63d",
        "trend_tstat_126d",
        "trend_tstat_252d",
        "ma_gap_63d",
        "ma_gap_126d",
        "ma_gap_252d",
        "realized_vol_21d",
        "realized_vol_63d",
        "realized_vol_126d",
        "vol_ratio_21_126",
        "global_fx_vol_21",
    }
    assert bool(build.catalog["price_only_eligible"].all())
    assert int(build.catalog["directional"].sum()) == 11
    assert int((~build.catalog["directional"]).sum()) == 5
    assert len(build.catalog) * len(settings.horizons) == 48
    statistic = _one_factor_statistic(
        build.dataset.loc[build.dataset["_rebalance_eligible"]],
        factor="momentum_63d",
        horizon=21,
        directional=True,
        settings=settings,
        seed_offset=0,
        run_bootstrap=False,
    )
    assert statistic["test_role"] == "within_symbol_time_series_directional_return"
    assert statistic["time_points"] > 20

    payload = config.model_dump()
    payload["research"]["research_mode"] = "cross_sectional"
    with pytest.raises(ValueError, match="cross-sectional"):
        LongHorizonConfig.model_validate(payload)


def test_intraday_conversion_uses_only_closed_utc_day_bars() -> None:
    index = pd.date_range("2025-01-01", periods=48, freq="h", tz="UTC")
    source = pd.DataFrame(
        {
            "open": np.arange(48, dtype=float) + 1,
            "high": np.arange(48, dtype=float) + 2,
            "low": np.arange(48, dtype=float) + 0.5,
            "close": np.arange(48, dtype=float) + 1.5,
            "volume": np.ones(48),
        },
        index=index,
    )

    daily = to_daily_market_data({"EURUSD": source})["EURUSD"]

    assert len(daily) == 2
    assert daily.iloc[0]["open"] == 1
    assert daily.iloc[0]["close"] == 24.5
    assert daily.iloc[0]["high"] == 25
    assert daily.iloc[0]["low"] == 0.5
    assert daily.iloc[0]["volume"] == 24


def test_long_horizon_panel_labels_and_folds_are_temporally_purged(tmp_path) -> None:
    config = _config(tmp_path)
    result = build_long_horizon_research(_synthetic_data(config), config)

    assert set(result.catalog["family"]) >= {
        "momentum",
        "trend",
        "value",
        "positioning",
        "risk",
    }
    assert len(result.panel) == len(result.dataset)
    assert not result.folds.empty
    complete = result.dataset["_label_end_time_63d"].notna()
    assert (
        result.dataset.loc[complete, "_entry_time"]
        > result.dataset.loc[complete, "_feature_time"]
    ).all()
    assert (
        result.dataset.loc[complete, "_label_end_time_63d"]
        > result.dataset.loc[complete, "_entry_time"]
    ).all()
    assert result.audit["label_temporal_order_valid"] is True
    assert result.audit["empirical_ready"] is False
    assert result.audit["complete_walk_forward_folds"] >= 3

    folds = build_long_horizon_folds(result.dataset, config.research)
    first = folds.iloc[0]
    train = result.dataset.loc[
        (result.dataset["_feature_time"] >= first["train_start"])
        & (result.dataset["_feature_time"] < first["train_end_exclusive"])
        & result.dataset["_label_end_time_63d"].notna()
        & (result.dataset["_label_end_time_63d"] < first["test_start"])
    ]
    assert len(train) == first["train_rows"]
    assert (train["_label_end_time_63d"] < first["test_start"]).all()


def test_factor_values_do_not_change_when_only_future_prices_change() -> None:
    config = _config()
    original = _synthetic_data(config)
    changed = {symbol: frame.copy() for symbol, frame in original.items()}
    cutoff = original["EURUSD"].index[900]
    for frame in changed.values():
        future = frame.index > cutoff
        frame.loc[future, ["open", "high", "low", "close"]] *= 1.25

    before = build_long_horizon_research(original, config).panel
    after = build_long_horizon_research(changed, config).panel
    columns = [
        "momentum_252d_skip_21d",
        "currency_relative_63d",
        "trend_tstat_126d",
        "realized_vol_21d",
    ]
    before = before.loc[before["_feature_time"] <= cutoff, ["_feature_time", "_symbol", *columns]]
    after = after.loc[after["_feature_time"] <= cutoff, ["_feature_time", "_symbol", *columns]]

    pd.testing.assert_frame_equal(before.reset_index(drop=True), after.reset_index(drop=True))


def test_public_rate_factor_uses_only_available_official_observations(tmp_path) -> None:
    config = _config(tmp_path, external_enabled=True)
    rate_path = config.external.official_rates_file
    rate_path.parent.mkdir(parents=True, exist_ok=True)
    observations = []
    levels = {"EUR": 2.0, "USD": 3.0, "GBP": 4.0, "JPY": 0.1}
    for timestamp in pd.date_range("2008-01-01", "2021-12-01", freq="MS", tz="UTC"):
        timestamp = pd.Timestamp(timestamp)
        for currency, level in levels.items():
            observations.append(
                {
                    "observation_time": timestamp,
                    "available_time": timestamp + pd.Timedelta(1, unit="D"),
                    "currency": currency,
                    "series_id": f"{currency}_ON",
                    "rate_percent": level,
                    "series_role": "overnight_reference",
                    "quality": "official_current_vintage",
                }
            )
    pd.DataFrame(observations).to_csv(rate_path, index=False)

    result = build_long_horizon_research(_synthetic_data(config), config)
    panel = result.panel.set_index(["_feature_time", "_symbol"])

    assert pd.isna(
        panel.loc[
            (pd.Timestamp("2008-01-01", tz="UTC"), "EURUSD"),
            "overnight_rate_differential_public",
        ]
    )
    assert panel.loc[
        (pd.Timestamp("2008-01-02", tz="UTC"), "EURUSD"),
        "overnight_rate_differential_public",
    ] == pytest.approx(-0.01)
    assert panel.loc[
        (pd.Timestamp("2008-01-02", tz="UTC"), "GBPUSD"),
        "overnight_rate_differential_public",
    ] == pytest.approx(0.01)


def test_preregistered_supplemental_factors_use_available_current_and_vintage_data(
    tmp_path,
) -> None:
    config = _config(tmp_path, external_enabled=True)
    supplemental_path = config.external.supplemental_file
    supplemental_path.parent.mkdir(parents=True, exist_ok=True)
    observations = []
    series = [
        "GEPU_CURRENT",
        "GPR_GLOBAL",
        "WB_CRUDE_OIL_AVG",
        "WB_COMMODITY_BASE_METALS",
        "WB_COMMODITY_AGRICULTURE",
        "WB_COMMODITY_ENERGY",
    ]
    for number, timestamp in enumerate(
        pd.date_range("2008-01-31", "2026-06-30", freq="ME", tz="UTC")
    ):
        for offset, series_id in enumerate(series):
            lag = 60 if series_id in {"GEPU_CURRENT", "GPR_GLOBAL"} else 45
            observations.append(
                {
                    "observation_time": timestamp,
                    "available_time": timestamp + pd.Timedelta(lag, unit="D"),
                    "series_id": series_id,
                    "value": 100 + number + 5 * np.sin(number / 4 + offset),
                    "quality": "exploratory_current_vintage",
                }
            )
    supplemental = pd.DataFrame(observations)
    supplemental["observation_time"] = supplemental["observation_time"].map(
        lambda value: value.isoformat()
    )
    supplemental["available_time"] = supplemental["available_time"].map(
        lambda value: value.isoformat()
    )
    supplemental.loc[supplemental.index[-1], "available_time"] = (
        "2026-08-29T00:00:00.123456+00:00"
    )
    supplemental.to_csv(supplemental_path, index=False)

    vintage_rows = []
    for number, vintage in enumerate(
        pd.date_range("2022-01-06", "2026-07-06", freq="MS", tz="UTC")
    ):
        observation = vintage - pd.offsets.MonthEnd(1)
        vintage_rows.append(
            {
                "observation_time": observation,
                "available_time": vintage,
                "vintage_label": vintage.strftime("%b-%y"),
                "series_id": "GSCPI",
                "value": np.sin(number / 3),
                "quality": "verified_monthly_vintage_from_2022",
            }
        )
    pd.DataFrame(vintage_rows).to_csv(config.external.gscpi_vintages_file, index=False)

    result = build_long_horizon_research(_synthetic_data(config), config)
    panel = result.panel
    mature = panel.loc[panel["_feature_time"] >= pd.Timestamp("2015-01-01", tz="UTC")]

    assert mature["global_policy_uncertainty_risk"].notna().mean() > 0.9
    assert mature["global_geopolitical_risk_state"].notna().mean() > 0.9
    assert mature["commodity_currency_alignment_12m"].notna().mean() > 0.9
    pit = panel.loc[panel["_feature_time"] >= pd.Timestamp("2022-08-01", tz="UTC")]
    assert pit["gscpi_risk_state_pit"].notna().mean() > 0.8
    same_time = mature.groupby("_feature_time")["global_policy_uncertainty_risk"].nunique()
    assert same_time.max() == 1
    assert {
        "value_trend_agreement",
        "positioning_crowding_reversal",
        "commodity_currency_alignment_12m",
    }.issubset(result.catalog["name"])


def test_artifacts_record_exploratory_status_and_hashes(tmp_path) -> None:
    config = _config(tmp_path)
    data = _synthetic_data(config)
    result = build_long_horizon_research(data, config)

    output = write_long_horizon_artifacts(result, config, tmp_path / "artifacts")

    manifest = json.loads((output / "manifest.json").read_text())
    audit = json.loads((output / "data_audit.json").read_text())
    assert manifest["implementation_version"] == "long-horizon-v6"
    assert manifest["empirical_ready"] is False
    assert manifest["factor_count"] == len(result.catalog)
    assert audit["tier"] == "software_or_exploratory"
    assert (output / "research_dataset.csv.gz").stat().st_size > 0


def test_execution_readiness_requires_verified_source_manifests() -> None:
    base = _config()
    config = base.model_copy(
        update={
            "data": base.data.model_copy(
                update={"provider": "csv", "price_mode": "bid_ask"}
            )
        }
    )
    data = SyntheticFXProvider(seed=17).generate(
        config.data.symbols,
        config.data.synthetic_bars,
        config.data.interval,
        config.data.start,
        "bid_ask",
    )

    unverified = build_long_horizon_research(data, config)
    assert unverified.audit["empirical_ready"] is False
    assert unverified.audit["sources_are_execution_grade"] is False

    for frame in data.values():
        frame.attrs.update(
            {
                "source_provider": "dukascopy",
                "source_manifest_complete": True,
                "source_failed_hours": 0,
                "source_csv_hash_verified": True,
                "source_manifest_schema_version": 2,
            }
        )
    verified = build_long_horizon_research(data, config)
    assert verified.audit["empirical_ready"] is True
    assert verified.audit["all_source_manifests_complete"] is True
    assert verified.audit["all_csv_hashes_verified"] is True

    data["EURUSD"].attrs["source_csv_hash_verified"] = False
    modified = build_long_horizon_research(data, config)
    assert modified.audit["empirical_ready"] is False
    assert modified.audit["all_csv_hashes_verified"] is False


def test_bootstrap_block_days_are_converted_to_rebalance_observations() -> None:
    settings = LongHorizonSettings(
        bootstrap_samples=100,
        bootstrap_block_days=63,
        rebalance_interval_days=21,
    )
    values = pd.Series(np.linspace(-1, 1, 10))

    _, p_value, effective_blocks = _block_bootstrap_mean_p_value(values, settings, 0)

    assert 0 < p_value <= 1
    assert effective_blocks == 4


def test_short_regime_window_reports_undefined_quintile_spread() -> None:
    frame = pd.DataFrame(
        {
            "_feature_time": pd.date_range("2020-01-01", periods=25, freq="21D", tz="UTC"),
            "factor": np.linspace(-1, 1, 25),
            "outcome": np.linspace(0, 0.1, 25),
        }
    )

    assert np.isnan(_regime_quintile_spread(frame))


def test_factor_screen_uses_training_only_fdr_and_non_overlapping_oos(tmp_path) -> None:
    config = _config(tmp_path)
    config = config.model_copy(
        update={
            "research": config.research.model_copy(
                update={"bootstrap_samples": 1300, "bootstrap_block_days": 21}
            )
        }
    )
    build = build_long_horizon_research(_synthetic_data(config), config)
    build.folds = build.folds.head(2).copy()

    screen = run_long_horizon_screen(build, config)

    expected = len(build.folds) * len(build.catalog) * len(config.research.horizons)
    assert len(screen.train_statistics) == expected
    assert len(screen.oos_statistics) == expected
    assert (screen.train_statistics["fdr_q_value"] >= 0).all()
    assert (screen.train_statistics["fdr_q_value"] <= 1).all()
    assert (
        screen.train_statistics["by_fdr_q_value"]
        >= screen.train_statistics["fdr_q_value"]
    ).all()
    # OOS statistics are materialized only for factor/horizons selected in
    # training (freeze contract); non-selected rows keep a not_evaluated
    # skeleton so the full audit rectangle is still disclosed without opening
    # outcomes the freeze forbids.
    evaluated = screen.oos_statistics.loc[screen.oos_statistics["oos_evaluated"]]
    assert set(evaluated["test_role"]) <= {
        "cross_sectional_directional_return",
        "time_series_absolute_return_regime",
    }
    not_evaluated = screen.oos_statistics.loc[~screen.oos_statistics["oos_evaluated"]]
    assert bool(not_evaluated["ic"].isna().all())
    # Regression (independent review Fix 3): every materialized OOS evaluation
    # must satisfy label_end_time_{horizon}d < test_end_exclusive (per horizon).
    for _, row in evaluated.iterrows():
        assert row["test_end_exclusive"] is not None
    assert screen.summary["hypotheses_per_fold"] == len(build.catalog) * 3
    assert screen.summary["observations_are_rebalance_eligible"] is True
    assert screen.summary["bootstrap_block_observations"] == 1
    assert screen.summary["minimum_bootstrap_samples_for_fdr_resolution"] == 1289
    assert (
        screen.summary["minimum_bootstrap_samples_for_by_fdr_resolution"]
        > screen.summary["minimum_bootstrap_samples_for_fdr_resolution"]
    )
    assert screen.summary["fdr_selection_method"] == "benjamini_hochberg"
    assert (
        screen.summary["selected_directional_train_hypotheses"]
        + screen.summary["selected_risk_state_train_hypotheses"]
        == screen.summary["selected_train_hypotheses"]
    )
    first, second = build.folds.iloc[0], build.folds.iloc[1]
    assert first["test_end_exclusive"] <= second["test_start"]
    assert screen.train_statistics["valid_rows"].max() <= max(
        first["train_rebalance_rows"], second["train_rebalance_rows"]
    )
    assert screen.oos_statistics["valid_rows"].max() <= max(
        first["test_rebalance_rows"], second["test_rebalance_rows"]
    )

    output = write_long_horizon_screen_artifacts(screen, tmp_path / "screen")
    summary = json.loads((output / "screen_summary.json").read_text())
    assert summary["total_train_hypotheses"] == expected
    assert (output / "oos_factor_statistics.csv").stat().st_size > 0


def _minimal_daily_frame(open_quote_times, close_quote_times):
    """Build a tiny OHLC daily frame with explicit boundary quote times."""
    n = len(open_quote_times)
    return pd.DataFrame(
        {
            "open": np.linspace(1.0, 1.0 + 0.001 * n, n),
            "high": np.linspace(1.0, 1.0 + 0.001 * n, n) + 0.0005,
            "low": np.linspace(1.0, 1.0 + 0.001 * n, n) - 0.0005,
            "close": np.linspace(1.0, 1.0 + 0.001 * n, n),
            "bid_open": np.linspace(1.0, 1.0 + 0.001 * n, n) - 0.0001,
            "bid_high": np.linspace(1.0, 1.0 + 0.001 * n, n),
            "bid_low": np.linspace(1.0, 1.0 + 0.001 * n, n) - 0.0002,
            "bid_close": np.linspace(1.0, 1.0 + 0.001 * n, n) - 0.0001,
            "ask_open": np.linspace(1.0, 1.0 + 0.001 * n, n) + 0.0001,
            "ask_high": np.linspace(1.0, 1.0 + 0.001 * n, n) + 0.0002,
            "ask_low": np.linspace(1.0, 1.0 + 0.001 * n, n),
            "ask_close": np.linspace(1.0, 1.0 + 0.001 * n, n) + 0.0001,
            "session_open_quote_time": pd.to_datetime(open_quote_times, utc=True),
            "session_close_quote_time": pd.to_datetime(close_quote_times, utc=True),
        },
        index=pd.DatetimeIndex(pd.to_datetime(open_quote_times, utc=True), name="timestamp"),
    )


def test_label_build_halts_when_entry_not_after_feature() -> None:
    # Regression (independent review Fix 2): _entry_time <= _feature_time must
    # raise BEFORE any forward return is computed. entry is the NEXT session's
    # open quote time (shift -1). Make session 1's open quote not strictly
    # after session 0's feature time, so row 0's entry <= its feature time.
    base = pd.to_datetime(
        ["2020-01-02 01:00", "2020-01-02 00:30", "2020-01-04 01:00", "2020-01-05 01:00"]
    ).tz_localize("UTC")
    close_q = base + pd.Timedelta(hours=8)
    daily = {"EURUSD": _minimal_daily_frame(base, close_q)}
    panel = pd.DataFrame({"_symbol": "EURUSD", "_feature_time": base})
    settings = LongHorizonSettings(
        train_years=3, test_years=1, step_years=1, minimum_history_years=3
    )
    with pytest.raises(ValueError, match="strictly after _feature_time"):
        build_long_horizon_labels(panel, daily, settings)


def test_label_build_halts_when_label_end_not_after_entry() -> None:
    # Regression (independent review Fix 2): _label_end <= _entry_time must
    # raise BEFORE that horizon's return is computed. Exercise the per-horizon
    # fail-closed gate directly with a horizon whose exit (next session close)
    # is not strictly after the entry.
    from fx_system.long_horizon import _enforce_label_end_after_entry

    feature = pd.Series(
        pd.to_datetime(
            ["2020-01-02 01:00", "2020-01-03 01:00", "2020-01-04 01:00"]
        ).tz_localize("UTC")
    )
    entry = feature + pd.Timedelta(hours=2)
    # exit (label end) for horizon=1 equals row1's close; make it <= row0 entry.
    exit_time = pd.Series(
        [
            entry.iloc[0],  # row0 exit == row0 entry -> violation
            entry.iloc[1] + pd.Timedelta(hours=1),
            pd.NaT,
        ]
    )
    with pytest.raises(ValueError, match="strictly after _entry_time"):
        _enforce_label_end_after_entry("EURUSD", entry, exit_time, horizon=1)


def test_build_long_horizon_labels_halts_on_label_end_not_after_entry(
    monkeypatch,
) -> None:
    # Build-level lock: build_long_horizon_labels must call the label-end gate
    # before computing returns. Construct a daily frame where the next close
    # (horizon=1 label end) is not strictly after the next open (entry).
    # Monkeypatch np.log so any premature return math raises AssertionError;
    # the expected failure is still the temporal-order ValueError.
    opens = pd.to_datetime(
        [
            "2020-01-02 01:00",
            "2020-01-03 01:00",
            "2020-01-04 01:00",
            "2020-01-05 01:00",
        ]
    ).tz_localize("UTC")
    # Entry for row0 is open of row1 (01:00 on 01-03). Make close of row1
    # equal that same timestamp so label_end_1d == entry for row0.
    closes = pd.to_datetime(
        [
            "2020-01-02 09:00",
            "2020-01-03 01:00",  # == next open of previous row -> violation
            "2020-01-04 09:00",
            "2020-01-05 09:00",
        ]
    ).tz_localize("UTC")
    daily = {"EURUSD": _minimal_daily_frame(opens, closes)}
    panel = pd.DataFrame({"_symbol": "EURUSD", "_feature_time": opens})
    settings = LongHorizonSettings(
        train_years=3,
        test_years=1,
        step_years=1,
        minimum_history_years=3,
        horizons=(1,),
    )

    def _forbid_log(*_args, **_kwargs):  # pragma: no cover - failure path
        raise AssertionError("return computed before temporal gate")

    monkeypatch.setattr(np, "log", _forbid_log)
    with pytest.raises(ValueError, match="strictly after _entry_time"):
        build_long_horizon_labels(panel, daily, settings)


def test_filter_oos_horizon_before_test_end_boundary_cases() -> None:
    # Direct unit test of the per-horizon spill helper. Must keep only rows
    # whose label end is strictly before test_end_exclusive; equal/later/NaT
    # are excluded. Assert on the time column itself, not summary metadata.
    test_end = pd.Timestamp("2020-06-01 00:00:00+00:00")
    frame = pd.DataFrame(
        {
            "_label_end_time_21d": pd.to_datetime(
                [
                    "2020-05-31 23:59:59+00:00",  # strict before -> keep
                    "2020-06-01 00:00:00+00:00",  # equal -> drop
                    "2020-06-01 00:00:01+00:00",  # later -> drop
                    pd.NaT,  # missing -> drop
                ],
                utc=True,
            ),
            "marker": ["keep", "eq", "late", "nat"],
        }
    )
    filtered = _filter_oos_horizon_before_test_end(
        frame, horizon=21, test_end_exclusive=test_end
    )
    assert list(filtered["marker"]) == ["keep"]
    assert filtered["_label_end_time_21d"].notna().all()
    assert (filtered["_label_end_time_21d"] < test_end).all()


def test_evaluated_oos_respects_per_horizon_spill_gate(tmp_path, monkeypatch) -> None:
    # Integration: wrap the spill helper and the OOS statistic path. Assert
    # (1) the helper is actually invoked, (2) every filtered frame's label_end
    # is strictly before that call's test_end_exclusive, (3) every frame passed
    # to _one_factor_statistic with run_bootstrap=False obeys the same contract.
    # Empty capture must fail — otherwise deleting the filter can still pass.
    import fx_system.long_horizon_research as research_mod

    config = _config(tmp_path)
    # Force at least one train selection so the OOS path is exercised; this
    # test locks the spill filter, not the selection thresholds.
    config = config.model_copy(
        update={
            "research": config.research.model_copy(
                update={
                    "bootstrap_samples": 1300,
                    "bootstrap_block_days": 21,
                    "minimum_absolute_train_ic": 0.0,
                    "minimum_factor_coverage": 0.0,
                    "factor_fdr_level": 1.0,
                }
            )
        }
    )
    build = build_long_horizon_research(_synthetic_data(config), config)
    build.folds = build.folds.head(2).copy()

    filtered_captures: list[tuple[pd.DataFrame, int, pd.Timestamp]] = []
    statistic_captures: list[tuple[pd.DataFrame, int]] = []
    original_filter = research_mod._filter_oos_horizon_before_test_end
    original_statistic = research_mod._one_factor_statistic

    def _wrap_filter(test, horizon, test_end_exclusive):
        out = original_filter(test, horizon, test_end_exclusive)
        end = pd.Timestamp(test_end_exclusive)
        filtered_captures.append((out.copy(), int(horizon), end))
        col = f"_label_end_time_{horizon}d"
        if not out.empty:
            label_end = pd.to_datetime(out[col], utc=True, errors="coerce")
            assert label_end.notna().all()
            assert (label_end < end).all()
        return out

    def _wrap_statistic(
        frame,
        *,
        factor,
        horizon,
        directional,
        settings,
        seed_offset,
        run_bootstrap,
    ):
        if not run_bootstrap:
            statistic_captures.append((frame.copy(), int(horizon)))
        return original_statistic(
            frame,
            factor=factor,
            horizon=horizon,
            directional=directional,
            settings=settings,
            seed_offset=seed_offset,
            run_bootstrap=run_bootstrap,
        )

    monkeypatch.setattr(
        research_mod, "_filter_oos_horizon_before_test_end", _wrap_filter
    )
    monkeypatch.setattr(research_mod, "_one_factor_statistic", _wrap_statistic)
    screen = run_long_horizon_screen(build, config)
    evaluated = screen.oos_statistics.loc[screen.oos_statistics["oos_evaluated"]]
    assert not evaluated.empty, "synthetic screen must evaluate at least one OOS row"
    assert filtered_captures, "spill helper must be invoked for OOS horizons"
    assert statistic_captures, "OOS path must call _one_factor_statistic at least once"

    for frame, horizon, test_end in filtered_captures:
        col = f"_label_end_time_{horizon}d"
        if frame.empty:
            continue
        label_end = pd.to_datetime(frame[col], utc=True, errors="coerce")
        assert label_end.notna().all()
        assert (label_end < test_end).all()

    # Frames that enter the statistic function must already be filtered.
    for frame, horizon in statistic_captures:
        col = f"_label_end_time_{horizon}d"
        if frame.empty:
            continue
        label_end = pd.to_datetime(frame[col], utc=True, errors="coerce")
        assert label_end.notna().all()
        fold_ends = [
            pd.Timestamp(fr["test_end_exclusive"])
            for _, fr in build.folds.iterrows()
        ]
        keeping = [end for end in fold_ends if (label_end < end).all()]
        assert keeping, (
            f"OOS statistic input for horizon={horizon} spills every fold end"
        )
        again = original_filter(
            frame, horizon=horizon, test_end_exclusive=keeping[0]
        )
        assert len(again) == len(frame)
