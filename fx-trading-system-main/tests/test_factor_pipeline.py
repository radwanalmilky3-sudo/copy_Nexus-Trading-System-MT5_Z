from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from conftest import make_bars

from fx_system.config import CostConfig, DataConfig, RiskConfig
from fx_system.data import SyntheticFXProvider
from fx_system.factor_config import FactorMiningConfig, FactorSettings
from fx_system.factor_research import (
    _add_economic_scores,
    _fold_boundaries,
    _holdout_boundary,
    factor_statistics,
    run_factor_mining,
)
from fx_system.factors import build_factor_panel, factor_catalog, factor_columns
from fx_system.labels import _label_symbol, build_directional_dataset
from fx_system.rates import FXRateGraph


def test_factor_catalog_is_implemented_and_uses_multiple_families() -> None:
    catalog = factor_catalog()
    assert len(catalog) >= 55
    assert set(catalog["family"]) >= {
        "momentum",
        "reversal",
        "volatility",
        "currency_graph",
        "relative_value",
        "cross_sectional",
    }
    assert catalog["name"].is_unique


def test_factor_panel_has_no_future_dependency() -> None:
    data = SyntheticFXProvider(seed=101).generate(
        ["EURUSD", "GBPUSD", "USDJPY", "EURGBP"], bars=180, interval="4h"
    )
    cutoff = data["EURUSD"].index[130]
    prefix = {symbol: frame.loc[:cutoff] for symbol, frame in data.items()}
    full_panel = build_factor_panel(data)
    prefix_panel = build_factor_panel(prefix)
    past = full_panel.loc[full_panel["_feature_time"] <= cutoff].reset_index(drop=True)
    pd.testing.assert_frame_equal(
        past[prefix_panel.columns],
        prefix_panel.reset_index(drop=True),
        check_exact=False,
        rtol=1e-12,
        atol=1e-12,
    )


def test_unknown_financing_is_a_scenario_not_silent_net_return() -> None:
    data = SyntheticFXProvider(seed=118).generate(
        ["EURUSD", "GBPUSD"], bars=20, interval="1d", price_mode="bid_ask"
    )
    data = {
        symbol: frame.drop(columns=["swap_long_pips", "swap_short_pips"])
        for symbol, frame in data.items()
    }
    timestamp = data["EURUSD"].index[10]
    predictions = pd.DataFrame(
        [
            {
                "_symbol": "EURUSD",
                "_feature_time": timestamp,
                "_entry_time": data["EURUSD"].index[11],
                "_atr": 0.01,
                "_direction": direction,
                "probability": probability,
            }
            for direction, probability in ((1, 0.8), (-1, 0.2))
        ]
    )
    config = FactorMiningConfig(
        data=DataConfig(
            provider="csv",
            symbols=["EURUSD", "GBPUSD"],
            interval="1d",
            price_mode="bid_ask",
        ),
        costs=CostConfig(),
        risk=RiskConfig(close_before_weekend=False),
        factor=FactorSettings(),
    )
    scored = _add_economic_scores(
        predictions,
        data,
        config,
        target_mean_r=1.0,
        non_target_mean_r=-1.0,
    )
    assert scored["financing_cost_known"].eq(False).all()
    assert scored["financing_source"].eq("zero_placeholder").all()
    assert scored["expected_gross_r"].notna().all()
    assert scored["expected_scenario_r"].notna().all()
    assert scored["expected_net_r"].isna().all()


def test_factor_significance_clusters_mirrored_rows_and_controls_fdr() -> None:
    generator = np.random.default_rng(105)
    timestamps = pd.date_range("2020-01-01", periods=240, freq="1D", tz="UTC")
    rows_per_time = 8
    repeated_times = np.repeat(timestamps, rows_per_time)
    time_regime = np.repeat(np.arange(len(timestamps)) % 2, rows_per_time)
    frame = pd.DataFrame(
        generator.normal(size=(len(repeated_times), len(factor_columns()))),
        columns=factor_columns(),
    )
    frame["_feature_time"] = repeated_times
    frame["_label"] = time_regime
    frame["momentum_1"] = time_regime
    statistics = factor_statistics(
        frame,
        FactorSettings(
            bootstrap_samples=1000,
            bootstrap_block_bars=10,
            factor_fdr_level=0.10,
        ),
    ).set_index("factor")
    strong = statistics.loc["momentum_1"]
    assert strong["effective_time_blocks"] == 24
    assert strong["bootstrap_p_value"] < 0.01
    assert strong["fdr_q_value"] < 0.10
    assert strong["by_fdr_q_value"] >= strong["fdr_q_value"]
    assert bool(strong["fdr_significant"])


def test_currency_graph_residual_detects_inconsistent_cross() -> None:
    index = pd.date_range("2025-01-01", periods=100, freq="1D", tz="UTC")
    eurusd = pd.Series(1.10 * np.exp(np.linspace(0, 0.02, len(index))), index=index)
    gbpusd = pd.Series(1.25 * np.exp(np.linspace(0, -0.01, len(index))), index=index)
    eurgbp = eurusd / gbpusd
    eurgbp.iloc[-1] *= 1.02

    def ohlc(close: pd.Series) -> pd.DataFrame:
        open_ = close.shift(1).fillna(close.iloc[0])
        return pd.DataFrame(
            {
                "open": open_,
                "high": pd.concat([open_, close], axis=1).max(axis=1) * 1.001,
                "low": pd.concat([open_, close], axis=1).min(axis=1) * 0.999,
                "close": close,
                "volume": 0.0,
            },
            index=index,
        )

    panel = build_factor_panel(
        {"EURUSD": ohlc(eurusd), "GBPUSD": ohlc(gbpusd), "EURGBP": ohlc(eurgbp)}
    )
    last = panel.loc[panel["_feature_time"] == index[-1]]
    assert last["pair_residual_1"].abs().max() > 1e-3


def test_currency_graph_disables_residual_without_a_cycle() -> None:
    data = SyntheticFXProvider(seed=104).generate(
        ["EURUSD", "GBPUSD", "USDJPY"], bars=100, interval="1d"
    )
    panel = build_factor_panel(data)
    assert panel["pair_residual_1"].isna().all()
    assert panel["currency_relative_1"].isna().all()


def test_triple_barrier_enters_next_bar_and_stop_wins_ambiguous_bar() -> None:
    bars = make_bars(
        [
            (1.0, 1.001, 0.999, 1.0),
            (1.0, 1.02, 0.98, 1.0),
            (1.0, 1.001, 0.999, 1.0),
            (1.0, 1.001, 0.999, 1.0),
        ]
    )
    labels = _label_symbol(
        bars,
        pd.Series(0.01, index=bars.index),
        direction=1,
        settings=FactorSettings(max_holding_hours=8),
    )
    first = labels.iloc[0]
    assert first["_feature_time"] == bars.index[0]
    assert first["_entry_time"] == bars.index[1]
    assert first["_event"] == "stop"
    assert first["_label"] == 0
    assert first["_realized_r"] == -1
    assert labels["_feature_time"].max() < bars.index[-2]


def test_triple_barrier_times_out_at_deadline_open_before_barriers() -> None:
    bars = make_bars(
        [
            (1.0, 1.001, 0.999, 1.0),
            (1.0, 1.001, 0.999, 1.0),
            (1.002, 1.02, 0.999, 1.015),
            (1.015, 1.016, 1.014, 1.015),
        ]
    )
    labels = _label_symbol(
        bars,
        pd.Series(0.01, index=bars.index),
        direction=1,
        settings=FactorSettings(max_holding_hours=4),
    )
    first = labels.iloc[0]
    assert first["_event"] == "timeout"
    assert first["_label_end_time"] == bars.index[2]
    assert first["_realized_r"] == pytest.approx(0.002 / 0.011)


def test_open_phase_fx_rates_never_use_current_close() -> None:
    primary = make_bars([(1.0, 1.1, 0.9, 1.0), (2.0, 10.0, 1.0, 9.0)])
    asynchronous = make_bars([(150.0, 151.0, 149.0, 150.5)], frequency="8h")
    graph = FXRateGraph({"EURUSD": primary, "USDJPY": asynchronous})
    prices = graph.prices_at_open(primary.index[1])
    assert prices["EURUSD"] == 2.0
    assert prices["USDJPY"] == 150.5


def test_directional_dataset_has_symmetric_long_short_rows() -> None:
    data = SyntheticFXProvider(seed=102).generate(["EURUSD", "USDJPY"], bars=150, interval="4h")
    panel = build_factor_panel(data)
    dataset = build_directional_dataset(
        panel, data, FactorSettings(max_holding_hours=24, minimum_train_samples=500)
    )
    counts = dataset.groupby(["_feature_time", "_symbol"])["_direction"].nunique()
    assert counts.min() == 2
    assert set(dataset["_direction"]) == {-1, 1}
    assert set(factor_columns()).issubset(dataset.columns)


def test_fold_boundaries_have_embargo() -> None:
    timestamps = list(pd.date_range("2015-01-01", periods=700, freq="1D", tz="UTC"))
    settings = FactorSettings(
        train_bars=300,
        test_bars=100,
        step_bars=100,
        embargo_bars=5,
        minimum_train_samples=500,
    )
    folds = _fold_boundaries(timestamps, settings)
    assert len(folds) == 3
    assert (folds[0][2] - folds[0][1]).days == 6


def test_untouched_holdout_is_after_development_windows() -> None:
    timestamps = list(pd.date_range("2015-01-01", periods=1000, freq="1D", tz="UTC"))
    settings = FactorSettings(
        train_bars=300,
        test_bars=100,
        step_bars=100,
        embargo_bars=5,
        holdout_bars=100,
        minimum_train_samples=500,
    )
    holdout = _holdout_boundary(timestamps, settings)
    assert holdout is not None
    development = [
        boundary for boundary in _fold_boundaries(timestamps, settings) if boundary[3] < holdout[2]
    ]
    assert development
    assert development[-1][3] < holdout[2]


def test_factor_config_rejects_overlapping_folds_and_weekend_mismatch() -> None:
    with pytest.raises(ValueError, match="overlapping OOS"):
        FactorSettings(train_bars=300, test_bars=100, step_bars=50)
    with pytest.raises(ValueError, match="close_before_weekend=false"):
        FactorMiningConfig(
            data=DataConfig(symbols=["EURUSD"]),
            risk=RiskConfig(close_before_weekend=True),
            factor=FactorSettings(train_bars=300, test_bars=100, step_bars=100),
        )


def test_small_factor_mining_pipeline_runs_out_of_sample() -> None:
    symbols = ["EURUSD", "GBPUSD", "USDJPY", "EURGBP", "EURJPY"]
    data = SyntheticFXProvider(seed=103).generate(symbols, bars=500, interval="1d")
    settings = FactorSettings(
        train_bars=250,
        test_bars=75,
        step_bars=75,
        embargo_bars=5,
        minimum_train_samples=1500,
        minimum_calibration_samples=300,
        max_features=12,
    )
    config = FactorMiningConfig(
        data=DataConfig(provider="synthetic", symbols=symbols, interval="1d", synthetic_bars=500),
        costs=CostConfig(),
        risk=RiskConfig(close_before_weekend=False),
        factor=settings,
    )
    mining = run_factor_mining(data, config)
    assert len(mining.folds) == 3
    assert mining.summary["folds"] == 3
    for fold in mining.folds:
        assert fold.train_end < fold.test_start
        assert fold.model_metrics["rows"] > 0
        assert 0 <= fold.model_metrics["roc_auc"] <= 1
        assert fold.selected_features
        assert fold.model_metrics["rows"] == settings.test_bars * len(symbols) * 2
        assert fold.model_metrics["calibration_rows"] >= settings.minimum_calibration_samples
        assert {"estimated_swap_r", "estimated_cost_r", "expected_net_r"}.issubset(
            fold.predictions.columns
        )

    strict_settings = settings.model_copy(
        update={
            "bootstrap_samples": 100,
            "factor_fdr_level": 0.001,
            "require_fdr_significance": True,
        }
    )
    strict_config = config.model_copy(update={"factor": strict_settings})
    with pytest.raises(ValueError, match="first Benjamini-Hochberg threshold"):
        run_factor_mining(data, strict_config)
