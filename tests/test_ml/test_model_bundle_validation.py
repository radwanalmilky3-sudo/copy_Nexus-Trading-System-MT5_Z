from types import SimpleNamespace

import pytest

from services.nexus_ml.ensemble import ModelEnsemble
from services.nexus_ml.training import WalkForwardConfig, WalkForwardTrainer


def test_strict_candidate_save_raises_on_any_model_persistence_failure(tmp_path):
    trainer = WalkForwardTrainer(WalkForwardConfig(model_dir=str(tmp_path)))
    trainer._xgb = SimpleNamespace(save=lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk")))

    # Legacy mode remains best-effort; candidate mode must fail closed.
    trainer._save_all()
    with pytest.raises(RuntimeError, match="xgboost"):
        trainer._save_all(strict=True)


def test_strict_ensemble_load_rejects_missing_declared_model_artifact(tmp_path):
    ensemble = ModelEnsemble(model_dir=tmp_path)
    (tmp_path / "feature_names.json").write_text('["close"]')

    with pytest.raises(RuntimeError, match="xgboost"):
        ensemble.load_all_models(strict=True, expected_artifacts=["xgboost_direction.json"])


def test_strict_ensemble_load_rejects_invalid_feature_schema(tmp_path):
    ensemble = ModelEnsemble(model_dir=tmp_path)
    (tmp_path / "feature_names.json").write_text("[]")
    artifact = tmp_path / "xgboost_direction.json"
    artifact.write_bytes(b"not empty")

    with pytest.raises(ValueError, match="feature"):
        ensemble.load_all_models(strict=True, expected_artifacts=[artifact.name])
