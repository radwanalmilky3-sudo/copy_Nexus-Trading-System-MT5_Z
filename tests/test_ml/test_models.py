"""Tests for nexus_ml service — model definitions and ensemble."""
from __future__ import annotations

from pathlib import Path

import pytest


ML_SVC = Path(__file__).resolve().parents[2] / "services" / "nexus_ml"


class _UnexpectedUnpickle:
    def __reduce__(self):
        return (print, ("unsafe-deserialization-marker",))


class TestMLServiceFiles:
    REQUIRED = [
        "__init__.py", "main.py", "backtester.py",
        "ensemble.py", "training.py",
    ]

    @pytest.mark.parametrize("filename", REQUIRED)
    def test_file_exists(self, filename: str):
        assert (ML_SVC / filename).exists(), f"Missing ML file: {filename}"


class TestMLModelFiles:
    MODELS_DIR = ML_SVC / "models"

    REQUIRED_MODELS = [
        "__init__.py",
        "xgboost_direction.py",
        "lightgbm_regime.py",
        "random_forest_features.py",
        "lstm_sequence.py",
        "finbert_sentiment.py",
        "isolation_anomaly.py",
    ]

    @pytest.mark.parametrize("filename", REQUIRED_MODELS)
    def test_model_exists(self, filename: str):
        assert (self.MODELS_DIR / filename).exists(), f"Missing ML model: {filename}"


class TestEnsembleImport:
    def test_importable(self):
        import importlib
        mod = importlib.import_module("services.nexus_ml.ensemble")
        assert mod is not None


class TestLSTMCheckpointSafety:
    def test_rejects_checkpoint_objects_that_can_run_code(self, tmp_path, capsys):
        import pickle

        import torch

        from services.nexus_ml.models.lstm_sequence import LSTMSequenceModel

        checkpoint = tmp_path / "untrusted.pt"
        torch.save({"unexpected": _UnexpectedUnpickle()}, checkpoint)

        with pytest.raises(pickle.UnpicklingError):
            LSTMSequenceModel().load(checkpoint)

        assert "unsafe-deserialization-marker" not in capsys.readouterr().out

    def test_loads_a_normal_state_dict_checkpoint(self, tmp_path):
        import numpy as np

        from services.nexus_ml.models.lstm_sequence import (
            LSTMSequenceModel,
            _LSTMAttentionNet,
        )

        hparams = {
            "seq_len": 20,
            "hidden_size": 4,
            "num_layers": 1,
            "num_heads": 2,
            "dropout": 0.0,
            "fc_hidden": 3,
        }
        original = LSTMSequenceModel(hparams)
        original._input_size = 2
        original._net = _LSTMAttentionNet(
            input_size=2,
            hidden_size=4,
            num_layers=1,
            num_heads=2,
            dropout=0.0,
            fc_hidden=3,
        )
        original._is_fitted = True
        checkpoint = tmp_path / "safe.pt"
        original.save(checkpoint, mlflow_run=False)

        restored = LSTMSequenceModel()
        restored.load(checkpoint)

        direction, confidence = restored.predict(np.zeros((20, 2), dtype=np.float32))
        assert direction in (0, 1)
        assert 0.0 <= confidence <= 1.0


def test_rule_based_lifecycle_can_recommend_trailing_stop_above_1_2_atr():
    from services.nexus_ml.traders.rl_lifecycle import PositionState, RLLifecycleAgent

    state = PositionState(
        ticket=1,
        symbol="XAUUSD",
        side="BUY",
        entry_price=100.0,
        current_price=102.0,
        sl_price=99.0,
        tp_price=105.0,
        lot_size=0.1,
        open_time="2026-10-14T00:00:00+00:00",
        bars_held=1,
        atr=1.0,
        regime="RANGING",
        mtf_alignment_score=0.0,
        spread_pips=1.0,
        signal_quality=80.0,
        rsi=55.0,
        adx=20.0,
        macd_hist=0.1,
        pip_value=1.0,
    )

    action, _ = RLLifecycleAgent.rule_based_decide(state)

    assert action == "TRAIL_SL_1ATR"
