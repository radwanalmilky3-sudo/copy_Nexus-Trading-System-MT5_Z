from types import SimpleNamespace

import numpy as np
import pytest

from services.nexus_ml.training import WalkForwardConfig, WalkForwardTrainer


class FixedBinaryEstimator:
    classes_ = np.array([0, 1])

    def predict(self, X):
        return np.zeros(len(X), dtype=int)

    def predict_proba(self, X):
        return np.tile([0.8, 0.2], (len(X), 1))


class FixedAnomalyModel:
    threshold = -0.3

    def detect_batch(self, X):
        return np.full(len(X), 0.1)


def test_fold_reports_separate_metrics_on_untouched_outer_validation_rows(tmp_path, monkeypatch):
    trainer = WalkForwardTrainer(WalkForwardConfig(
        train_months=2,
        val_months=1,
        step_months=1,
        min_train_samples=2,
        min_val_samples=2,
        model_dir=str(tmp_path),
    ))
    monkeypatch.setattr(trainer, "_setup_mlflow", lambda: False)
    monkeypatch.setattr(trainer, "_save_all", lambda **_kwargs: None)
    fit_rows = {}

    def fake_fit(slot):
        def fit(X, y, _names):
            fit_rows[slot] = (X.copy(), y.copy())
            setattr(trainer, slot, SimpleNamespace(model=FixedBinaryEstimator()))
            return {"accuracy": 1.0, "f1": 1.0}
        return fit

    monkeypatch.setattr(trainer, "_train_xgboost", fake_fit("_xgb"))
    monkeypatch.setattr(trainer, "_train_lgbm", fake_fit("_lgbm"))
    monkeypatch.setattr(trainer, "_train_rf", fake_fit("_rf"))
    monkeypatch.setattr(
        trainer,
        "_train_anomaly",
        lambda X, _names: (setattr(trainer, "_anomaly", FixedAnomalyModel()) or {"n_samples": float(len(X))}),
    )

    X = np.array([[0.0], [0.1], [0.2], [0.3], [1.0], [1.1], [1.2], [1.3]])
    y = np.array([0, 0, 1, 1, 0, 1, 0, 1])
    timestamps = np.array([
        "2026-01-01", "2026-01-15", "2026-02-01", "2026-02-15",
        "2026-03-01", "2026-03-15", "2026-03-20", "2026-03-25",
    ], dtype="datetime64[s]")

    folds = trainer.train_all_models(X, y, timestamps, feature_names=["f"])

    assert len(folds) == 1
    result = folds[0].metrics["xgboost"]
    assert result["accuracy"] == 1.0  # training metric fixture
    assert result["outer_val_accuracy"] == 0.5
    assert result["outer_val_f1_weighted"] == 1 / 3
    assert result["outer_val_log_loss"] == pytest.approx(0.9162907319)
    # The last Feb bar's next-bar label is resolved from Mar 1, the first
    # validation bar, so it must be purged from training.
    assert fit_rows["_xgb"][0].tolist() == X[:3].tolist()
    assert fit_rows["_xgb"][1].tolist() == y[:3].tolist()


def test_walk_forward_purges_final_training_bar_whose_label_crosses_validation_boundary(tmp_path):
    trainer = WalkForwardTrainer(WalkForwardConfig(
        train_months=2, val_months=1, step_months=1,
        model_dir=str(tmp_path),
    ))
    timestamps = np.array([
        "2026-01-15", "2026-02-01", "2026-02-28T23:55:00",
        "2026-03-01", "2026-03-05",
    ], dtype="datetime64[s]")

    (train_mask, validation_mask), = trainer._generate_folds(timestamps)

    assert np.flatnonzero(train_mask).tolist() == [0, 1]
    assert np.flatnonzero(validation_mask).tolist() == [3, 4]


def test_fold_records_original_validation_row_ids_for_incumbent_comparison(tmp_path, monkeypatch):
    trainer = WalkForwardTrainer(WalkForwardConfig(
        train_months=2, val_months=1, step_months=1,
        min_train_samples=2, min_val_samples=2, model_dir=str(tmp_path),
    ))
    monkeypatch.setattr(trainer, "_setup_mlflow", lambda: False)
    monkeypatch.setattr(trainer, "_save_all", lambda **_kwargs: None)
    monkeypatch.setattr(trainer, "_train_xgboost", lambda *_: (setattr(trainer, "_xgb", SimpleNamespace(model=FixedBinaryEstimator())) or {}))
    monkeypatch.setattr(trainer, "_train_lgbm", lambda *_: (setattr(trainer, "_lgbm", SimpleNamespace(model=FixedBinaryEstimator())) or {}))
    monkeypatch.setattr(trainer, "_train_rf", lambda *_: (setattr(trainer, "_rf", SimpleNamespace(model=FixedBinaryEstimator())) or {}))
    monkeypatch.setattr(trainer, "_train_anomaly", lambda *_: (setattr(trainer, "_anomaly", FixedAnomalyModel()) or {}))

    timestamps = np.array(["2026-01-01", "2026-01-15", "2026-02-01", "2026-02-15",
                          "2026-03-01", "2026-03-15", "2026-03-20", "2026-03-25"], dtype="datetime64[s]")
    results = trainer.train_all_models(
        np.arange(8, dtype=float).reshape(-1, 1), np.array([0, 1] * 4), timestamps,
        feature_names=["f"],
    )

    assert results[0].validation_row_ids == [4, 5, 6, 7]


def test_outer_classifier_scoring_supports_loaded_booster_without_classes_property():
    estimator = SimpleNamespace(
        _n_classes=4,
        predict=lambda X: np.zeros(len(X), dtype=int),
        predict_proba=lambda X: np.tile([0.7, 0.1, 0.1, 0.1], (len(X), 1)),
    )
    model = SimpleNamespace(model=estimator)

    result = WalkForwardTrainer._score_outer_classifier(
        model, np.zeros((2, 1)), np.array([0, 1]),
    )

    assert result["outer_val_accuracy"] == 0.5
    assert result["outer_val_log_loss"] > 0
