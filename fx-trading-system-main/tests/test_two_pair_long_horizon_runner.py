from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_runner():
    path = (
        Path(__file__).parents[1] / "scripts" / "run_two_pair_long_horizon_research.py"
    )
    spec = importlib.util.spec_from_file_location("run_two_pair_long_horizon_research", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_runner()


def test_two_pair_runner_requires_explicit_outcome_acknowledgement(capsys) -> None:
    assert runner.main([]) == 2
    assert "--open-return-labels" in capsys.readouterr().err


def test_two_pair_config_is_broker_neutral_time_series() -> None:
    config = runner.LongHorizonConfig.from_yaml(
        Path(__file__).parents[1] / "configs" / "long_horizon_two_pair_time_series.yaml"
    )
    assert config.data.symbols == ["EURUSD", "GBPUSD"]
    assert config.data.provider == "csv"
    assert config.research.research_mode == "time_series_panel"
    assert config.external.enabled is False

