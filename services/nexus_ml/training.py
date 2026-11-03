"""
Walk-forward training pipeline.

Orchestrates training of every model in the ensemble using a rolling
train/validation window so that forward-looking bias is eliminated.
All experiments are logged to MLflow for reproducibility.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import accuracy_score, f1_score, log_loss

from .models.xgboost_direction import XGBoostDirectionModel
from .models.lightgbm_regime import LightGBMRegimeModel
from .models.lstm_sequence import LSTMSequenceModel
from .models.isolation_anomaly import AnomalyDetector
from .models.random_forest_features import FeatureImportanceModel

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardConfig:
    """Parameters governing the walk-forward schedule."""

    train_months: int = 6
    val_months: int = 1
    step_months: int = 1
    min_train_samples: int = 2000
    min_val_samples: int = 300
    model_dir: str = "./models_store"
    mlflow_experiment: str = "nexus_ml_walk_forward"
    seq_len: int = 20
    strict_persistence: bool = False


@dataclass
class FoldResult:
    fold: int
    train_start: str
    train_end: str
    val_start: str
    val_end: str
    metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    validation_row_ids: list[int] = field(default_factory=list)
    incumbent_metrics: dict[str, dict[str, float]] = field(default_factory=dict)


class WalkForwardTrainer:
    """Coordinates walk-forward training for every model."""

    def __init__(self, config: WalkForwardConfig | None = None) -> None:
        self.cfg = config or WalkForwardConfig()
        self.model_dir = Path(self.cfg.model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self._fold_results: list[FoldResult] = []
        self.saved_artifacts: list[str] = []

    # ── Public entry point ────────────────────────────────────────────────

    def train_all_models(
        self,
        X: np.ndarray,
        y: np.ndarray,
        timestamps: np.ndarray,
        feature_names: list[str] | None = None,
        sequences: np.ndarray | None = None,
        incumbent: Any | None = None,
    ) -> list[FoldResult]:
        """Full walk-forward pass over the dataset.

        Parameters
        ----------
        X          : (N, n_features)  flat feature matrix.
        y          : (N,)  binary labels (1=UP, 0=DOWN).
        timestamps : (N,)  datetime64 array aligned with X.
        feature_names : column names for X.
        sequences  : optional (N, seq_len, n_features) for LSTM.
        """
        self._fold_results.clear()
        folds = self._generate_folds(timestamps)

        mlflow_available = self._setup_mlflow()

        for fold_idx, (train_mask, val_mask) in enumerate(folds):
            X_train, y_train = X[train_mask], y[train_mask]
            X_val, y_val = X[val_mask], y[val_mask]
            t_train, t_val = timestamps[train_mask], timestamps[val_mask]

            if len(X_train) < self.cfg.min_train_samples:
                logger.warning("Fold %d skipped — only %d train samples", fold_idx, len(X_train))
                continue
            if len(X_val) < self.cfg.min_val_samples:
                logger.warning("Fold %d skipped — only %d val samples", fold_idx, len(X_val))
                continue

            fold_result = FoldResult(
                fold=fold_idx,
                train_start=str(t_train[0]),
                train_end=str(t_train[-1]),
                val_start=str(t_val[0]),
                val_end=str(t_val[-1]),
                validation_row_ids=np.flatnonzero(val_mask).astype(int).tolist(),
            )

            run_ctx = self._mlflow_run(fold_idx) if mlflow_available else _NullContext()
            with run_ctx:
                fold_result.metrics["xgboost"] = self._train_xgboost(
                    X_train, y_train, feature_names,
                )
                fold_result.metrics["xgboost"].update(
                    self._score_outer_classifier(self._xgb, X_val, y_val),
                )
                if incumbent is not None and getattr(incumbent.xgb, "is_fitted", False):
                    fold_result.incumbent_metrics["xgboost"] = self._score_outer_classifier(
                        incumbent.xgb, X_val, y_val,
                    )
                fold_result.metrics["lgbm_regime"] = self._train_lgbm(
                    X_train, y_train, feature_names,
                )
                regime_val = LightGBMRegimeModel.label_regimes(
                    self._extract_atr_percentile(X_val, feature_names),
                )
                fold_result.metrics["lgbm_regime"].update(
                    self._score_outer_classifier(self._lgbm, X_val, regime_val),
                )
                if incumbent is not None and getattr(incumbent.lgbm, "is_fitted", False):
                    fold_result.incumbent_metrics["lgbm_regime"] = self._score_outer_classifier(
                        incumbent.lgbm, X_val, regime_val,
                    )
                fold_result.metrics["rf_importance"] = self._train_rf(
                    X_train, y_train, feature_names,
                )
                fold_result.metrics["rf_importance"].update(
                    self._score_outer_classifier(self._rf, X_val, y_val),
                )
                if incumbent is not None and getattr(incumbent.rf, "is_fitted", False):
                    fold_result.incumbent_metrics["rf_importance"] = self._score_outer_classifier(
                        incumbent.rf, X_val, y_val,
                    )
                fold_result.metrics["anomaly"] = self._train_anomaly(
                    X_train, feature_names,
                )
                anomaly_scores = self._anomaly.detect_batch(X_val)
                fold_result.metrics["anomaly"].update({
                    "outer_val_mean_score": float(np.mean(anomaly_scores)),
                    "outer_val_std_score": float(np.std(anomaly_scores)),
                    "outer_val_anomaly_rate": float(np.mean(anomaly_scores < self._anomaly.threshold)),
                })

                if sequences is not None:
                    seq_train = sequences[train_mask]
                    fold_result.metrics["lstm"] = self._train_lstm(
                        seq_train, y_train,
                    )
                    fold_result.metrics["lstm"].update(
                        self._score_outer_lstm(self._lstm, sequences[val_mask], y_val),
                    )
                    if incumbent is not None and getattr(incumbent.lstm, "is_fitted", False):
                        fold_result.incumbent_metrics["lstm"] = self._score_outer_lstm(
                            incumbent.lstm, sequences[val_mask], y_val,
                        )

                if mlflow_available:
                    self._log_fold_metrics(fold_idx, fold_result.metrics)

            self._fold_results.append(fold_result)
            logger.info("Fold %d complete — metrics: %s", fold_idx, fold_result.metrics)

        self._save_all(strict=self.cfg.strict_persistence)
        self.saved_artifacts = [
            filename for attr, filename in self._saver_specs()
            if getattr(self, attr, None) is not None
        ]
        if feature_names:
            # Persisted separately because individual model.save()/.load()
            # round-trips only the fitted estimator, not this Python-level
            # attribute — the live ensemble needs it to align inference
            # features to the exact column order training used.
            import json as _json
            try:
                (self.model_dir / "feature_names.json").write_text(_json.dumps(feature_names))
            except Exception as exc:
                if self.cfg.strict_persistence:
                    raise RuntimeError("Failed to save feature_names.json") from exc
                logger.error("Failed to save feature_names.json", exc_info=True)
            else:
                self.saved_artifacts.append("feature_names.json")
        elif self.cfg.strict_persistence:
            raise RuntimeError("Candidate model requires a non-empty feature schema")
        return list(self._fold_results)

    # ── Individual model trainers ─────────────────────────────────────────

    def _train_xgboost(
        self, X: np.ndarray, y: np.ndarray, names: list[str] | None,
    ) -> dict[str, float]:
        model = XGBoostDirectionModel()
        metrics = model.train(X, y, feature_names=names)
        self._xgb = model
        return metrics

    def _train_lgbm(
        self, X: np.ndarray, y: np.ndarray, names: list[str] | None,
    ) -> dict[str, float]:
        from .models.lightgbm_regime import LightGBMRegimeModel

        regime_labels = LightGBMRegimeModel.label_regimes(
            self._extract_atr_percentile(X, names),
        )
        model = LightGBMRegimeModel()
        metrics = model.train(X, regime_labels, feature_names=names)
        self._lgbm = model
        return metrics

    def _train_lstm(
        self, sequences: np.ndarray, y: np.ndarray,
    ) -> dict[str, float]:
        model = LSTMSequenceModel({"seq_len": self.cfg.seq_len})
        metrics = model.train(sequences, y)
        self._lstm = model
        return metrics

    def _train_anomaly(
        self, X: np.ndarray, names: list[str] | None,
    ) -> dict[str, float]:
        model = AnomalyDetector()
        stats = model.train(X, feature_names=names)
        self._anomaly = model
        return stats

    def _train_rf(
        self, X: np.ndarray, y: np.ndarray, names: list[str] | None,
    ) -> dict[str, float]:
        model = FeatureImportanceModel()
        metrics = model.train(X, y, feature_names=names)
        self._rf = model
        return metrics

    @staticmethod
    def _score_outer_classifier(
        model: Any,
        X_val: np.ndarray,
        y_val: np.ndarray,
    ) -> dict[str, float]:
        """Score a fitted classifier only on the untouched outer fold."""
        estimator = model.model
        y_pred = estimator.predict(X_val)
        scores = {
            "outer_val_accuracy": float(accuracy_score(y_val, y_pred)),
            "outer_val_f1_weighted": float(f1_score(
                y_val, y_pred, average="weighted", zero_division=0,
            )),
        }
        classes_attr = getattr(estimator, "classes_", None)
        if classes_attr is None:
            n_classes = getattr(estimator, "_n_classes", None)
            classes_attr = np.arange(int(n_classes)) if n_classes else None
        classes = np.asarray(classes_attr) if classes_attr is not None else np.asarray([])
        if hasattr(estimator, "predict_proba") and len(classes) and set(np.unique(y_val)).issubset(set(classes)):
            scores["outer_val_log_loss"] = float(log_loss(
                y_val, estimator.predict_proba(X_val), labels=classes,
            ))
        return scores

    @staticmethod
    def _score_outer_lstm(
        model: Any,
        X_val: np.ndarray,
        y_val: np.ndarray,
    ) -> dict[str, float]:
        predictions = model.predict_batch(X_val)
        y_pred = np.asarray([direction for direction, _ in predictions])
        p_up = np.asarray([
            confidence if direction == 1 else 1.0 - confidence
            for direction, confidence in predictions
        ])
        return {
            "outer_val_accuracy": float(accuracy_score(y_val, y_pred)),
            "outer_val_f1_weighted": float(f1_score(
                y_val, y_pred, average="weighted", zero_division=0,
            )),
            "outer_val_log_loss": float(log_loss(y_val, p_up, labels=[0, 1])),
        }

    # ── Walk-forward fold generation ──────────────────────────────────────

    def _generate_folds(
        self, timestamps: np.ndarray,
    ) -> list[tuple[np.ndarray, np.ndarray]]:
        row_timestamps = np.array(timestamps, dtype="datetime64[s]")
        month_timestamps = row_timestamps.astype("datetime64[M]")
        unique_months = np.unique(month_timestamps)

        folds: list[tuple[np.ndarray, np.ndarray]] = []
        train_len = self.cfg.train_months
        val_len = self.cfg.val_months
        step = self.cfg.step_months

        i = 0
        while i + train_len + val_len <= len(unique_months):
            train_months_range = unique_months[i : i + train_len]
            val_months_range = unique_months[i + train_len : i + train_len + val_len]

            train_mask = np.isin(month_timestamps, train_months_range)
            val_mask = np.isin(month_timestamps, val_months_range)

            # Labels are resolved from the *next* bar's close. The final
            # training bar can therefore carry a target from the first
            # validation bar; purge every row at that final training time.
            if np.any(train_mask):
                last_train_timestamp = np.max(row_timestamps[train_mask])
                train_mask &= row_timestamps != last_train_timestamp

            folds.append((train_mask, val_mask))
            i += step

        logger.info("Generated %d walk-forward folds", len(folds))
        return folds

    @staticmethod
    def _extract_atr_percentile(
        X: np.ndarray, names: list[str] | None,
    ) -> np.ndarray:
        """Pull atr_percentile column if present, else synthesise from data."""
        if names and "atr_percentile" in names:
            idx = names.index("atr_percentile")
            return X[:, idx]
        col_std = np.std(X, axis=0)
        proxy_col = int(np.argmax(col_std))
        vals = X[:, proxy_col]
        from scipy.stats import rankdata
        return rankdata(vals) / len(vals)

    # ── Persistence ───────────────────────────────────────────────────────

    @staticmethod
    def _saver_specs() -> list[tuple[str, str]]:
        return [
            ("_xgb", "xgboost_direction.json"),
            ("_lgbm", "lgbm_regime.txt"),
            ("_lstm", "lstm_sequence.pt"),
            ("_anomaly", "isolation_anomaly.joblib"),
            ("_rf", "rf_features.joblib"),
        ]

    def _save_all(self, strict: bool = False) -> None:
        failures: list[str] = []
        savers = self._saver_specs()
        for attr, filename in savers:
            model = getattr(self, attr, None)
            if model is not None:
                try:
                    model.save(self.model_dir / filename, mlflow_run=False)
                except Exception:
                    logger.error("Failed to save %s", attr, exc_info=True)
                    failures.append(attr)
        if strict and failures:
            display_names = {
                "_xgb": "xgboost", "_lgbm": "lgbm_regime", "_lstm": "lstm",
                "_anomaly": "anomaly", "_rf": "rf_importance",
            }
            raise RuntimeError(
                f"Failed to save candidate models: {', '.join(display_names[name] for name in failures)}"
            )

    # ── MLflow helpers ────────────────────────────────────────────────────

    def _setup_mlflow(self) -> bool:
        try:
            import mlflow
            mlflow.set_experiment(self.cfg.mlflow_experiment)
            return True
        except Exception:
            logger.warning("MLflow unavailable — metrics will not be tracked remotely")
            return False

    def _mlflow_run(self, fold_idx: int) -> Any:
        import mlflow
        return mlflow.start_run(
            run_name=f"walk_forward_fold_{fold_idx}",
            nested=True,
        )

    @staticmethod
    def _log_fold_metrics(fold_idx: int, metrics: dict[str, dict[str, float]]) -> None:
        try:
            import mlflow
            for model_name, model_metrics in metrics.items():
                for k, v in model_metrics.items():
                    mlflow.log_metric(f"{model_name}_{k}", v, step=fold_idx)
        except Exception:
            pass

    # ── Results ───────────────────────────────────────────────────────────

    @property
    def fold_results(self) -> list[FoldResult]:
        return list(self._fold_results)


class _NullContext:
    """No-op context manager when MLflow is unavailable."""

    def __enter__(self) -> "_NullContext":
        return self

    def __exit__(self, *exc: object) -> None:
        pass
