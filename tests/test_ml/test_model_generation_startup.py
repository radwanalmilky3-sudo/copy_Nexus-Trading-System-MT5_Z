from types import SimpleNamespace

import numpy as np
import pytest

from services.nexus_ml import main as ml_main
from services.nexus_ml.model_registry import ModelRegistry


def test_corrupt_active_pointer_does_not_load_unscoped_legacy_directory(tmp_path, monkeypatch):
    registry = ModelRegistry(tmp_path)
    registry.symbol_dir("XAUUSD", "M5").mkdir(parents=True)
    registry.active_manifest_path("XAUUSD", "M5").write_text("{broken")
    legacy_dir = tmp_path / "XAUUSD"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / "xgboost_direction.json").write_text("legacy model")
    loaded = []

    class FakeEnsemble:
        def __init__(self, model_dir):
            self.model_dir = str(model_dir)

        def load_all_models(self, **kwargs):
            loaded.append((self.model_dir, kwargs))
            return {}

    monkeypatch.setattr(ml_main, "_model_registry", registry)
    monkeypatch.setattr(ml_main, "MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(ml_main, "ModelEnsemble", FakeEnsemble)
    ml_main._ensembles.clear()

    result = ml_main._get_symbol_ensemble("XAUUSD")

    scoped_dir = str(tmp_path / "XAUUSD" / "timeframes" / "M5")
    assert result.model_dir == scoped_dir
    assert loaded == [(scoped_dir, {"strict": True, "expected_artifacts": []})]
    ml_main._ensembles.clear()


@pytest.mark.parametrize("mode", ["reject", "promote", "activation_failure"])
@pytest.mark.asyncio
async def test_candidate_outcome_preserves_or_switches_serving_bundle_atomically(tmp_path, monkeypatch, mode):
    registry = ModelRegistry(tmp_path)
    incumbent = object()
    ml_main._ensembles.clear()
    ml_main._ensembles[("XAUUSD", "M5")] = incumbent
    monkeypatch.setattr(ml_main, "_model_registry", registry)
    monkeypatch.setattr(ml_main, "_get_symbol_ensemble", lambda _symbol, _timeframe=None: incumbent)

    class FakeTrainer:
        def __init__(self, cfg):
            self.cfg = cfg
            self.saved_artifacts = []

        def train_all_models(self, *_args, **_kwargs):
            directory = __import__("pathlib").Path(self.cfg.model_dir)
            (directory / "xgboost_direction.json").write_text("candidate")
            (directory / "feature_names.json").write_text('["f"]')
            self.saved_artifacts = ["xgboost_direction.json", "feature_names.json"]
            folds = []
            for i in range(3):
                candidate = {"outer_val_accuracy": 0.8, "outer_val_log_loss": 0.4}
                baseline = {} if mode == "reject" else {
                    "outer_val_accuracy": 0.8, "outer_val_log_loss": 0.5,
                }
                folds.append(SimpleNamespace(
                    fold=i, validation_row_ids=[i * 3, i * 3 + 1],
                    metrics={"xgboost": candidate},
                    incumbent_metrics={"xgboost": baseline} if baseline else {},
                ))
            return folds

    class FakeEnsemble:
        def __init__(self, model_dir):
            self.model_dir = model_dir

        def load_all_models(self, **kwargs):
            assert kwargs["strict"] is True
            assert kwargs["expected_artifacts"] == ["xgboost_direction.json"]
            return {"xgboost": True}

    monkeypatch.setattr(ml_main, "WalkForwardTrainer", FakeTrainer)
    monkeypatch.setattr(ml_main, "ModelEnsemble", FakeEnsemble)
    if mode == "activation_failure":
        monkeypatch.setattr(registry, "activate", lambda *_args: (_ for _ in ()).throw(OSError("disk")))

    outcome, _ = await ml_main._train_symbol_candidate(
        "XAUUSD", "M5", (np.zeros((1, 1)), np.zeros(1), np.zeros(1), ["f"]),
        ml_main.WalkForwardConfig(), "test-task",
    )

    if mode == "promote":
        assert outcome["decision"] == "promoted"
        assert ml_main._ensembles[("XAUUSD", "M5")] is not incumbent
        assert registry.read_active("XAUUSD", "M5")["active_generation"] == outcome["generation"]
    else:
        expected_reason = "no_comparable_incumbent" if mode == "reject" else "candidate_validation_failed"
        assert outcome["reason"] == expected_reason
        assert ml_main._ensembles[("XAUUSD", "M5")] is incumbent
        assert registry.read_active("XAUUSD", "M5") is None
    ml_main._ensembles.clear()
