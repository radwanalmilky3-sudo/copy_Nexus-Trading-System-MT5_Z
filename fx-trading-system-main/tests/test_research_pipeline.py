from __future__ import annotations

from fx_system.config import SystemConfig
from fx_system.data import SyntheticFXProvider
from fx_system.research import screen_strategies, walk_forward


def compact_config() -> SystemConfig:
    config = SystemConfig.from_yaml("configs/demo.yaml")
    keep = {"regime_mean_reversion", "false_breakout_reversal"}
    config.strategies = [item for item in config.strategies if item.name in keep]
    return config


def test_screening_compares_candidates_under_one_engine() -> None:
    config = compact_config()
    data = SyntheticFXProvider(seed=22).generate(config.data.symbols, bars=350, interval="4h")
    runs = screen_strategies(data, config)
    assert {run.name for run in runs} == {
        "regime_mean_reversion",
        "false_breakout_reversal",
        "ensemble",
    }
    assert all("screen_score" in run.metrics for run in runs)


def test_walk_forward_selects_only_on_past_window() -> None:
    config = compact_config()
    data = SyntheticFXProvider(seed=23).generate(config.data.symbols, bars=500, interval="4h")
    folds = walk_forward(
        data,
        config,
        train_bars=250,
        test_bars=100,
        top_k=1,
        warmup_bars=100,
    )
    assert len(folds) == 2
    for fold in folds:
        assert fold["train_end"] < fold["test_start"]
        assert len(fold["selected"]) == 1
        assert "test_metrics" in fold
