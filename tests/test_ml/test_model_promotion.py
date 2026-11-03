import pytest

from services.nexus_ml.model_promotion import (
    evaluate_promotion,
    metric_records_from_folds,
    preserve_unscored_anomaly,
)


def fold_metrics(name="xgboost", *, accuracy=0.8, log_loss=0.5, target="direction", offset=0):
    return {
        name: [
            {"fold": fold, "row_ids": [fold * 10 + offset, fold * 10 + offset + 1],
             "target": target, "accuracy": accuracy, "log_loss": log_loss}
            for fold in range(3)
        ]
    }


def test_requires_three_valid_folds():
    candidate = fold_metrics()["xgboost"][:2]
    incumbent = fold_metrics()["xgboost"][:2]
    decision = evaluate_promotion({"xgboost": candidate}, {"xgboost": incumbent})
    assert (decision.accepted, decision.reason, decision.fold_count) == (
        False, "insufficient_valid_folds", 2,
    )


def test_strictly_better_log_loss_and_tied_accuracy_is_accepted():
    decision = evaluate_promotion(fold_metrics(log_loss=0.4), fold_metrics(log_loss=0.5))
    assert decision.accepted is True
    assert decision.reason == "accepted"


@pytest.mark.parametrize(("candidate_loss", "candidate_accuracy", "reason"), [
    (0.5, 0.8, "log_loss_not_improved"),
    (0.4, 0.79, "accuracy_regressed"),
])
def test_candidate_fails_if_log_loss_or_accuracy_gate_fails(candidate_loss, candidate_accuracy, reason):
    decision = evaluate_promotion(
        fold_metrics(accuracy=candidate_accuracy, log_loss=candidate_loss),
        fold_metrics(accuracy=0.8, log_loss=0.5),
    )
    assert decision.accepted is False
    assert decision.reason == reason


def test_compares_only_matching_model_target_folds_and_row_ids():
    candidate = fold_metrics(name="lgbm_regime", target="regime")
    wrong_target = fold_metrics(name="lgbm_regime", target="direction")
    assert evaluate_promotion(candidate, wrong_target).reason == "validation_data_mismatch"
    wrong_rows = fold_metrics(name="lgbm_regime", target="regime", offset=1)
    assert evaluate_promotion(candidate, wrong_rows).reason == "validation_data_mismatch"
    no_baseline = evaluate_promotion(candidate, {})
    assert no_baseline.reason == "no_comparable_incumbent"
    assert no_baseline.fold_count == 3


def test_rejects_fold_set_mismatch_and_nonfinite_metrics():
    candidate = fold_metrics()
    incumbent = fold_metrics()
    incumbent["xgboost"][-1] = {**incumbent["xgboost"][-1], "fold": 5}
    assert evaluate_promotion(candidate, incumbent).reason == "fold_mismatch"

    bad = fold_metrics()
    bad["xgboost"][0]["log_loss"] = float("nan")
    assert evaluate_promotion(bad, fold_metrics()).reason == "invalid_metrics"


def test_rejects_missing_validation_row_identity():
    candidate = fold_metrics()
    incumbent = fold_metrics()
    candidate["xgboost"][0]["row_ids"] = []
    incumbent["xgboost"][0]["row_ids"] = []
    assert evaluate_promotion(candidate, incumbent).reason == "invalid_validation_identity"


def test_rejects_out_of_range_acceptance_metrics():
    candidate = fold_metrics(log_loss=-0.1)
    incumbent = fold_metrics(log_loss=0.5)
    assert evaluate_promotion(candidate, incumbent).reason == "invalid_metrics"


def test_metric_records_preserve_fold_rows_and_target_identity():
    class Fold:
        fold = 2
        validation_row_ids = [4, 5, 6]
        metrics = {"xgboost": {"outer_val_accuracy": 0.75, "outer_val_log_loss": 0.4}}
        incumbent_metrics = {"xgboost": {"outer_val_accuracy": 0.5, "outer_val_log_loss": 0.7}}

    assert metric_records_from_folds([Fold()], "direction")["xgboost"] == [{
        "fold": 2, "row_ids": [4, 5, 6], "target": "direction",
        "accuracy": 0.75, "log_loss": 0.4,
    }]
    assert metric_records_from_folds([Fold()], "direction", incumbent=True)["xgboost"][0]["log_loss"] == 0.7


def test_unscored_anomaly_is_not_introduced_or_replaced_without_schema_match(tmp_path):
    from pathlib import Path
    from types import SimpleNamespace

    candidate = tmp_path / "candidate"
    candidate.mkdir()
    candidate_artifact = candidate / "isolation_anomaly.joblib"
    candidate_artifact.write_bytes(b"new")
    incumbent_dir = tmp_path / "incumbent"
    incumbent_dir.mkdir()
    (incumbent_dir / candidate_artifact.name).write_bytes(b"old")
    incumbent = SimpleNamespace(
        anomaly=SimpleNamespace(is_fitted=True),
        feature_names=["close"], model_dir=str(incumbent_dir),
    )

    artifacts, reason = preserve_unscored_anomaly(
        candidate, [candidate_artifact.name], ["close"], incumbent,
    )
    assert reason is None
    assert artifacts == [candidate_artifact.name]
    assert candidate_artifact.read_bytes() == b"old"

    artifacts, reason = preserve_unscored_anomaly(
        candidate, [candidate_artifact.name], ["volume"], incumbent,
    )
    assert artifacts == [candidate_artifact.name]
    assert reason == "anomaly_schema_mismatch"

    no_incumbent = SimpleNamespace(anomaly=SimpleNamespace(is_fitted=False))
    artifacts, reason = preserve_unscored_anomaly(
        candidate, [candidate_artifact.name], ["close"], no_incumbent,
    )
    assert artifacts == []
    assert reason is None
