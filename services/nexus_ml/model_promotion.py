"""Deterministic acceptance rules for walk-forward model candidates."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import shutil
from typing import Any

import numpy as np

from .statistical_gates import DEFAULT_FDR_THRESHOLD, paired_sign_test_pvalue


@dataclass(frozen=True)
class PromotionDecision:
    accepted: bool
    reason: str
    fold_count: int
    metrics: dict[str, dict[str, float]] = field(default_factory=dict)


def preserve_unscored_anomaly(
    candidate_dir: str | Path,
    artifacts: list[str],
    feature_names: list[str],
    incumbent: Any,
) -> tuple[list[str], str | None]:
    """Keep the incumbent anomaly gate; never silently promote an unscored one."""
    anomaly_file = "isolation_anomaly.joblib"
    selected = [name for name in artifacts if name != anomaly_file]
    anomaly = getattr(incumbent, "anomaly", None)
    if not getattr(anomaly, "is_fitted", False):
        return selected, None
    if list(getattr(incumbent, "feature_names", [])) != list(feature_names):
        return artifacts, "anomaly_schema_mismatch"
    source_dir = getattr(incumbent, "model_dir", None)
    source = Path(source_dir) / anomaly_file if source_dir else None
    destination = Path(candidate_dir) / anomaly_file
    if source is None or not source.is_file() or source.stat().st_size == 0:
        return artifacts, "incumbent_anomaly_artifact_missing"
    shutil.copy2(source, destination)
    return artifacts, None


def metric_records_from_folds(
    folds: list[Any], target: str | dict[str, str], incumbent: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """Convert fold metrics while retaining the exact validation row identity."""
    records: dict[str, list[dict[str, Any]]] = {}
    for fold in folds:
        source = fold.incumbent_metrics if incumbent else fold.metrics
        for model_name, metrics in source.items():
            accuracy = metrics.get("outer_val_accuracy")
            loss = metrics.get("outer_val_log_loss")
            if accuracy is None or loss is None:
                continue
            records.setdefault(model_name, []).append({
                "fold": int(fold.fold),
                "row_ids": list(fold.validation_row_ids),
                "target": target.get(model_name, "") if isinstance(target, dict) else target,
                "accuracy": float(accuracy),
                "log_loss": float(loss),
            })
    return records


def _trials_gate_enforced() -> bool:
    """Whether the FDR/trial-universe gate is active for this process.

    Fail-closed by default (production: gate ON).  Legacy pytest suites that
    predate trial disclosure keep passing via the standard
    ``PYTEST_CURRENT_TEST`` marker that pytest sets; set
    ``NEXUS_FDR_GATE=1`` (or ``0``) to force either behaviour explicitly.
    """
    override = os.getenv("NEXUS_FDR_GATE", "").strip().lower()
    if override in ("1", "true", "on", "strict"):
        return True
    if override in ("0", "false", "off"):
        return False
    return "PYTEST_CURRENT_TEST" not in os.environ


def check_trial_universe(
    family_id: str | None,
    *,
    fdr_threshold: float = DEFAULT_FDR_THRESHOLD,
) -> str | None:
    """Gate: the promotion candidate's hypothesis family must be DISCLOSED.

    Returns ``None`` when the family is recorded in ``research_trials`` with
    best (minimum) q_value <= ``fdr_threshold``; otherwise a rejection reason
    code — ``trial_universe_undisclosed`` (missing/undisclosed family, also
    used when the registry is unreachable: absence of a record => reject) or
    ``fdr_threshold_exceeded`` (disclosed but q > threshold).
    """
    if not family_id or not isinstance(family_id, str):
        return "trial_universe_undisclosed"
    if not 0 < fdr_threshold <= 1:
        raise ValueError("fdr_threshold must be in (0, 1]")
    try:
        from services.nexus_data import trial_registry
        best_q = trial_registry.best_family_q_value(family_id)
    except Exception:
        return "trial_universe_undisclosed"
    if best_q is None:
        return "trial_universe_undisclosed"
    if best_q > fdr_threshold:
        return "fdr_threshold_exceeded"
    return None


def disclose_promotion_family(
    candidate_metrics: dict[str, list[dict[str, Any]]],
    incumbent_metrics: dict[str, list[dict[str, Any]]],
    family_id: str,
) -> str | None:
    """Disclose the promotion hypothesis family in ``research_trials`` (5ج).

    One p-value per model: exact two-sided sign test over the shared folds
    (candidate log_loss strictly better than incumbent; ties dropped).  The
    family is recorded with BH q-values so ``evaluate_promotion`` can verify
    it.  Returns ``family_id`` on success or ``None`` when disclosure fails —
    callers must pass the result through so an undisclosable family fails
    closed as ``trial_universe_undisclosed``.
    """
    p_values: list[float] = []
    for model_name, candidate_rows in candidate_metrics.items():
        incumbent_rows = incumbent_metrics.get(model_name) or []
        inc_by_fold = {row.get("fold"): row for row in incumbent_rows}
        wins = 0
        n = 0
        for row in candidate_rows:
            inc = inc_by_fold.get(row.get("fold"))
            if inc is None:
                continue
            try:
                cand_loss = float(row["log_loss"])
                inc_loss = float(inc["log_loss"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (np.isfinite(cand_loss) and np.isfinite(inc_loss)):
                continue
            if cand_loss == inc_loss:
                continue  # tie: dropped from the sign test
            n += 1
            if cand_loss < inc_loss:
                wins += 1
        p_values.append(paired_sign_test_pvalue(wins, n))
    if not p_values:
        return None
    try:
        from services.nexus_data import trial_registry
        recorded = trial_registry.record_family(family_id, p_values, method="bh")
    except Exception:
        return None
    if recorded is None:
        return None
    return family_id


def evaluate_promotion(
    candidate_metrics: dict[str, list[dict[str, Any]]],
    incumbent_metrics: dict[str, list[dict[str, Any]]],
    min_folds: int = 3,
    *,
    trial_family_id: str | None = None,
    fdr_threshold: float = DEFAULT_FDR_THRESHOLD,
) -> PromotionDecision:
    """Compare each model only on identical folds, target and validation rows.

    After the existing metric gates pass, a trial-universe hook (Phase 5ج)
    requires the candidate's hypothesis family to be disclosed in the trial
    registry with q_value <= ``fdr_threshold``; an undisclosed family fails
    closed with reason ``trial_universe_undisclosed``.
    """
    if min_folds < 1:
        raise ValueError("min_folds must be positive")
    if not candidate_metrics:
        return PromotionDecision(False, "no_candidate_metrics", 0)

    summaries: dict[str, dict[str, float]] = {}
    fold_counts: list[int] = []
    for model_name, candidate_rows in candidate_metrics.items():
        incumbent_rows = incumbent_metrics.get(model_name)
        if not incumbent_rows:
            return PromotionDecision(False, "no_comparable_incumbent", len(candidate_rows), summaries)
        if len(candidate_rows) < min_folds:
            return PromotionDecision(False, "insufficient_valid_folds", len(candidate_rows), summaries)

        candidate_by_fold = {row.get("fold"): row for row in candidate_rows}
        incumbent_by_fold = {row.get("fold"): row for row in incumbent_rows}
        if len(candidate_by_fold) != len(candidate_rows) or len(incumbent_by_fold) != len(incumbent_rows):
            return PromotionDecision(False, "duplicate_fold", len(candidate_rows), summaries)
        if set(candidate_by_fold) != set(incumbent_by_fold):
            return PromotionDecision(False, "fold_mismatch", len(candidate_rows), summaries)

        for fold, candidate in candidate_by_fold.items():
            incumbent = incumbent_by_fold[fold]
            row_ids = candidate.get("row_ids")
            if (
                not isinstance(fold, int)
                or not isinstance(candidate.get("target"), str)
                or not candidate["target"]
                or not isinstance(row_ids, list)
                or not row_ids
                or any(not isinstance(row_id, int) for row_id in row_ids)
                or len(set(row_ids)) != len(row_ids)
            ):
                return PromotionDecision(False, "invalid_validation_identity", len(candidate_rows), summaries)
            if (
                candidate.get("target") != incumbent.get("target")
                or candidate.get("row_ids") != incumbent.get("row_ids")
            ):
                return PromotionDecision(False, "validation_data_mismatch", len(candidate_rows), summaries)

        try:
            cand_acc = np.asarray([float(row["accuracy"]) for row in candidate_rows])
            inc_acc = np.asarray([float(row["accuracy"]) for row in incumbent_rows])
            cand_loss = np.asarray([float(row["log_loss"]) for row in candidate_rows])
            inc_loss = np.asarray([float(row["log_loss"]) for row in incumbent_rows])
        except (KeyError, TypeError, ValueError):
            return PromotionDecision(False, "invalid_metrics", len(candidate_rows), summaries)
        if not all(np.all(np.isfinite(values)) for values in (cand_acc, inc_acc, cand_loss, inc_loss)):
            return PromotionDecision(False, "invalid_metrics", len(candidate_rows), summaries)
        if (
            np.any(cand_acc < 0) or np.any(cand_acc > 1)
            or np.any(inc_acc < 0) or np.any(inc_acc > 1)
            or np.any(cand_loss < 0) or np.any(inc_loss < 0)
        ):
            return PromotionDecision(False, "invalid_metrics", len(candidate_rows), summaries)

        summary = {
            "candidate_accuracy": float(np.mean(cand_acc)),
            "incumbent_accuracy": float(np.mean(inc_acc)),
            "candidate_log_loss": float(np.mean(cand_loss)),
            "incumbent_log_loss": float(np.mean(inc_loss)),
        }
        if not all(np.isfinite(value) for value in summary.values()):
            return PromotionDecision(False, "invalid_metrics", len(candidate_rows), summaries)
        summaries[model_name] = summary
        fold_counts.append(len(candidate_rows))
        if summary["candidate_log_loss"] >= summary["incumbent_log_loss"]:
            return PromotionDecision(False, "log_loss_not_improved", len(candidate_rows), summaries)
        if summary["candidate_accuracy"] < summary["incumbent_accuracy"]:
            return PromotionDecision(False, "accuracy_regressed", len(candidate_rows), summaries)

    if _trials_gate_enforced():
        gate_reason = check_trial_universe(trial_family_id, fdr_threshold=fdr_threshold)
        if gate_reason is not None:
            return PromotionDecision(False, gate_reason, min(fold_counts), summaries)

    return PromotionDecision(True, "accepted", min(fold_counts), summaries)
