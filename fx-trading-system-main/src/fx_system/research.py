from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd

from .analytics import calculate_metrics, robust_screen_score
from .config import SystemConfig
from .engine import BacktestEngine
from .ensemble import SignalEnsembler
from .models import BacktestResult
from .strategies import build_strategy


@dataclass
class ScreeningRun:
    name: str
    result: BacktestResult
    metrics: dict[str, object]


def generate_ensemble_signals(
    data: Mapping[str, pd.DataFrame], config: SystemConfig, selected: set[str] | None = None
):
    raw_signals = []
    weights: dict[str, float] = {}
    for item in config.strategies:
        if not item.enabled or (selected is not None and item.name not in selected):
            continue
        strategy = build_strategy(item.name, item.params)
        raw_signals.extend(strategy.generate(data))
        weights[item.name] = item.weight
    ensembler = SignalEnsembler(config.ensemble, weights)
    return ensembler.combine(raw_signals), raw_signals


def screen_strategies(
    data: Mapping[str, pd.DataFrame], config: SystemConfig, include_ensemble: bool = True
) -> list[ScreeningRun]:
    output: list[ScreeningRun] = []
    engine = BacktestEngine(config.risk, config.costs)
    for item in config.strategies:
        if not item.enabled:
            continue
        signals, _ = generate_ensemble_signals(data, config, {item.name})
        result = engine.run(data, signals, {"screen": item.name})
        metrics = calculate_metrics(result)
        metrics["screen_score"] = robust_screen_score(metrics)
        output.append(ScreeningRun(item.name, result, metrics))
    if include_ensemble:
        signals, _ = generate_ensemble_signals(data, config)
        result = engine.run(data, signals, {"screen": "ensemble"})
        metrics = calculate_metrics(result)
        metrics["screen_score"] = robust_screen_score(metrics)
        output.append(ScreeningRun("ensemble", result, metrics))
    return sorted(output, key=lambda item: float(item.metrics["screen_score"]), reverse=True)


def walk_forward(
    data: Mapping[str, pd.DataFrame],
    config: SystemConfig,
    train_bars: int = 1200,
    test_bars: int = 400,
    top_k: int = 2,
    warmup_bars: int = 250,
) -> list[dict[str, object]]:
    common_index = sorted(set.intersection(*(set(frame.index) for frame in data.values())))
    folds: list[dict[str, object]] = []
    offset = 0
    while offset + train_bars + test_bars <= len(common_index):
        train_start = common_index[offset]
        train_end = common_index[offset + train_bars - 1]
        test_start = common_index[offset + train_bars]
        test_end = common_index[offset + train_bars + test_bars - 1]
        train_data = {symbol: frame.loc[train_start:train_end] for symbol, frame in data.items()}
        ranked = screen_strategies(train_data, config, include_ensemble=False)
        selected = {run.name for run in ranked[:top_k]}
        warmup_start_index = max(0, offset + train_bars - warmup_bars)
        warmup_start = common_index[warmup_start_index]
        warm_data = {symbol: frame.loc[warmup_start:test_end] for symbol, frame in data.items()}
        test_data = {symbol: frame.loc[test_start:test_end] for symbol, frame in data.items()}
        signals, _ = generate_ensemble_signals(warm_data, config, selected)
        signals = [signal for signal in signals if test_start <= signal.timestamp <= test_end]
        result = BacktestEngine(config.risk, config.costs).run(
            test_data, signals, {"selected": sorted(selected)}
        )
        metrics = calculate_metrics(result)
        folds.append(
            {
                "fold": len(folds) + 1,
                "train_start": train_start.isoformat(),
                "train_end": train_end.isoformat(),
                "test_start": test_start.isoformat(),
                "test_end": test_end.isoformat(),
                "selected": sorted(selected),
                "training_ranking": [
                    {
                        "name": run.name,
                        "score": run.metrics["screen_score"],
                        "trades": run.metrics["trades"],
                        "sharpe": run.metrics["sharpe"],
                    }
                    for run in ranked
                ],
                "test_metrics": metrics,
            }
        )
        offset += test_bars
    return folds
