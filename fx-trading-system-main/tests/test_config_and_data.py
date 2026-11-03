from __future__ import annotations

import pandas as pd
import pytest

from fx_system.config import DataConfig, RiskConfig, SystemConfig
from fx_system.data import (
    SyntheticFXProvider,
    drop_incomplete_bars,
    load_from_config,
    save_csv_directory,
    validate_bars,
)
from fx_system.models import CurrencyPair


def test_currency_pair_normalizes_and_knows_jpy_pip() -> None:
    assert CurrencyPair.parse("eur/usd").symbol == "EURUSD"
    assert CurrencyPair.parse("USD_JPY").pip_size == 0.01
    with pytest.raises(ValueError):
        CurrencyPair.parse("EUR")


def test_risk_config_enforces_requested_hard_limits() -> None:
    with pytest.raises(ValueError):
        RiskConfig(max_holding_hours=169)
    with pytest.raises(ValueError):
        RiskConfig(max_reward_risk=1.01)


def test_default_config_contains_major_pairs_and_linked_strategies() -> None:
    config = SystemConfig.from_yaml("configs/default.yaml")
    assert set(config.data.symbols) >= {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD"}
    names = {item.name for item in config.strategies}
    assert "currency_strength_reversion" in names
    assert "cointegration_spread" in names


def test_validate_bars_rejects_impossible_ohlc() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": ["2025-01-01", "2025-01-02"],
            "open": [1, 1],
            "high": [0.9, 1.1],
            "low": [0.8, 0.9],
            "close": [1, 1],
        }
    )
    with pytest.raises(ValueError, match="invalid OHLC"):
        validate_bars(frame, "EURUSD")


def test_validate_bars_can_explicitly_drop_bad_provider_rows() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": ["2025-01-01", "2025-01-02", "2025-01-03"],
            "open": [1, 1, 1],
            "high": [1.1, 0.9, 1.1],
            "low": [0.9, 0.8, 0.9],
            "close": [1, 1, 1],
        }
    )
    with pytest.warns(RuntimeWarning, match="dropping 1"):
        cleaned = validate_bars(frame, "EURUSD", invalid_ohlc="drop")
    assert len(cleaned) == 2


def test_synthetic_crosses_are_currency_graph_consistent() -> None:
    data = SyntheticFXProvider(seed=7).generate(
        ["EURUSD", "USDJPY", "EURJPY"], bars=200, interval="4h"
    )
    implied = data["EURUSD"]["close"] * data["USDJPY"]["close"]
    relative_error = (implied / data["EURJPY"]["close"] - 1).abs().max()
    assert relative_error < 1e-12


def test_live_provider_drops_still_forming_bar() -> None:
    index = pd.date_range("2026-01-01", periods=3, freq="4h", tz="UTC")
    frame = pd.DataFrame({"close": [1.0, 1.1, 1.2]}, index=index)
    filtered = drop_incomplete_bars(frame, "4h", pd.Timestamp("2026-01-01T09:00:00Z"))
    assert list(filtered.index) == list(index[:2])


def test_csv_provider_honors_exclusive_research_end_date(tmp_path) -> None:
    data = SyntheticFXProvider(seed=8).generate(["EURUSD"], bars=20, interval="1d")
    save_csv_directory(data, tmp_path)
    config = DataConfig(
        provider="csv",
        directory=tmp_path,
        symbols=["EURUSD"],
        interval="1d",
        start="2020-01-03",
        end="2020-01-15",
    )
    loaded = load_from_config(config)["EURUSD"]
    assert loaded.index.min() >= pd.Timestamp("2020-01-03", tz="UTC")
    assert loaded.index.max() < pd.Timestamp("2020-01-15", tz="UTC")


def test_csv_provider_rejects_manifest_hash_mismatch(tmp_path) -> None:
    data = SyntheticFXProvider(seed=9).generate(["EURUSD"], bars=20, interval="1d")
    save_csv_directory(data, tmp_path)
    path = tmp_path / "EURUSD.csv"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    config = DataConfig(
        provider="csv",
        directory=tmp_path,
        symbols=["EURUSD"],
        interval="1d",
        start="2020-01-01",
    )
    with pytest.raises(ValueError, match="SHA-256"):
        load_from_config(config)
