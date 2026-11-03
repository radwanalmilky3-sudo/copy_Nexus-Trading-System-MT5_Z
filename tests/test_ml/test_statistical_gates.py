"""Phase 5ج — honest-statistics tests: FDR gates, trial registry, promotion hook."""
from __future__ import annotations

import math

import pytest

from services.nexus_ml.statistical_gates import (
    DEFAULT_FDR_THRESHOLD,
    benjamini_hochberg,
    benjamini_yekutieli,
    deflated_sharpe_ratio,
    harmonic_number,
    minimum_resamples_for_fdr,
)

# ── FDR q-values ─────────────────────────────────────────────────────────────

# Benjamini & Hochberg (1995) Table 1 example p-values (ascending).
BH95_P = [0.0001, 0.0081, 0.0390, 0.0415, 0.0485, 0.0846, 0.5929]
BH95_Q = [0.0007, 0.02835, 0.0679, 0.0679, 0.0679, 0.0987, 0.5929]


def test_bh_classic_example():
    q = benjamini_hochberg(BH95_P)
    assert len(q) == len(BH95_P)
    for got, expected in zip(q, BH95_Q):
        assert got == pytest.approx(expected, abs=1e-12)


def test_bh_uniform_step_up_yields_common_value():
    assert benjamini_hochberg([0.01, 0.02, 0.03, 0.04]) == pytest.approx([0.04] * 4)


def test_bh_preserves_original_order_and_ties():
    q = benjamini_hochberg([0.04, 0.01, 0.04, 0.02])
    assert q[1] == pytest.approx(0.04)
    assert q[3] == pytest.approx(0.04)
    assert q[0] == pytest.approx(q[2])
    assert q[0] <= q[3]


def test_by_more_conservative_than_bh():
    bh = benjamini_hochberg(BH95_P)
    by = benjamini_yekutieli(BH95_P)
    factor = harmonic_number(len(BH95_P))
    assert factor == pytest.approx(math.fsum(1.0 / i for i in range(1, 8)))
    for b, y in zip(bh, by):
        assert y >= b - 1e-15
    assert by[0] > bh[0]
    assert by == pytest.approx(
        [min(1.0, min(bh95 * factor for bh95 in BH95_Q[i:])) for i in range(len(BH95_Q))],
        abs=1e-9,
    )


def test_empty_nan_and_out_of_range_safety():
    assert benjamini_hochberg([]) == []
    assert benjamini_yekutieli([]) == []
    for bad in ([float("nan")], [float("inf")], [-0.01], [1.5], ["x"], None):
        with pytest.raises(ValueError):
            benjamini_hochberg(bad)
        with pytest.raises(ValueError):
            benjamini_yekutieli(bad)


def test_minimum_resamples_for_fdr():
    assert minimum_resamples_for_fdr(1, 0.10) == 9
    assert minimum_resamples_for_fdr(2, 0.10) == 19
    previous = 1
    for m in (1, 5, 10, 50):
        current = minimum_resamples_for_fdr(m, DEFAULT_FDR_THRESHOLD)
        assert current >= previous
        previous = current
    for m in (1, 10, 50):
        assert (
            minimum_resamples_for_fdr(m, 0.10, method="by")
            >= minimum_resamples_for_fdr(m, 0.10, method="bh")
        )
    with pytest.raises(ValueError):
        minimum_resamples_for_fdr(0, 0.10)
    with pytest.raises(ValueError):
        minimum_resamples_for_fdr(5, 0.0)
    with pytest.raises(ValueError):
        minimum_resamples_for_fdr(5, 0.10, method="nope")  # type: ignore[arg-type]


def test_deflated_sharpe_ratio_is_monotone_and_bounded():
    low = deflated_sharpe_ratio(0.5, 10, 1.0)
    high = deflated_sharpe_ratio(2.5, 10, 1.0)
    assert 0.0 <= low < high <= 1.0
    single = deflated_sharpe_ratio(1.0, 1, 1.0)
    assert single == pytest.approx(0.5 + 0.5 * math.erf(1.0 / math.sqrt(2.0)), abs=1e-12)
    with pytest.raises(ValueError):
        deflated_sharpe_ratio(1.0, 0, 1.0)
    with pytest.raises(ValueError):
        deflated_sharpe_ratio(1.0, 5, 0.0)
    with pytest.raises(ValueError):
        deflated_sharpe_ratio(float("nan"), 5, 1.0)


# ── Trial registry round-trip ────────────────────────────────────────────────

@pytest.fixture()
def registry_db(tmp_path, monkeypatch):
    monkeypatch.delenv("NEXUS_DATA_URL", raising=False)
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "trials.duckdb"))
    monkeypatch.delenv("TRIAL_REGISTRY_DB", raising=False)
    from services.nexus_data import trial_registry
    return trial_registry


def test_registry_family_round_trip(registry_db):
    q_values = registry_db.record_family("fam-roundtrip", [0.001, 0.02, 0.5])
    assert q_values == pytest.approx([0.003, 0.03, 0.5])
    assert registry_db.has_disclosed_family("fam-roundtrip") is True
    rows = registry_db.get_family("fam-roundtrip")
    assert len(rows) == 3
    assert {row["method"] for row in rows} == {"bh"}
    assert {row["total_trials"] for row in rows} == {3}
    assert all(row["family_id"] == "fam-roundtrip" for row in rows)
    assert all(isinstance(row["trial_id"], str) and row["trial_id"] for row in rows)
    assert registry_db.best_family_q_value("fam-roundtrip") == pytest.approx(0.003)


def test_registry_by_method_is_more_conservative(registry_db):
    bh = registry_db.record_family("fam-bh", [0.01, 0.02, 0.03], method="bh")
    by = registry_db.record_family("fam-by", [0.01, 0.02, 0.03], method="by")
    assert all(y > b for b, y in zip(bh, by))
    assert registry_db.get_family("fam-by")[0]["method"] == "by"


def test_registry_single_trial_and_meta(registry_db):
    trial_id = registry_db.record_trial(
        family_id="fam-one", p_value=0.04, meta={"note": "unit"},
    )
    assert trial_id
    rows = registry_db.get_family("fam-one")
    assert len(rows) == 1
    assert rows[0]["p_value"] == pytest.approx(0.04)
    assert rows[0]["q_value"] == pytest.approx(0.04)
    assert "unit" in rows[0]["meta"]


def test_registry_missing_family_is_undisclosed(registry_db):
    assert registry_db.has_disclosed_family("never-recorded") is False
    assert registry_db.get_family("never-recorded") == []
    assert registry_db.best_family_q_value("never-recorded") is None
    assert registry_db.has_disclosed_family("") is False


# ── Promotion trial-universe gate ────────────────────────────────────────────

def fold_metrics(name="xgboost", *, accuracy=0.8, log_loss=0.5, target="direction"):
    return {
        name: [
            {"fold": fold, "row_ids": [fold * 10, fold * 10 + 1],
             "target": target, "accuracy": accuracy, "log_loss": log_loss}
            for fold in range(3)
        ]
    }


@pytest.fixture()
def forced_gate(tmp_path, monkeypatch):
    monkeypatch.delenv("NEXUS_DATA_URL", raising=False)
    monkeypatch.setenv("NEXUS_FDR_GATE", "1")
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "gate.duckdb"))
    monkeypatch.delenv("TRIAL_REGISTRY_DB", raising=False)
    from services.nexus_ml.model_promotion import evaluate_promotion, check_trial_universe
    return evaluate_promotion, check_trial_universe


def test_promotion_undisclosed_family_is_rejected(forced_gate):
    evaluate_promotion, check_trial_universe = forced_gate
    assert check_trial_universe(None) == "trial_universe_undisclosed"
    assert check_trial_universe("") == "trial_universe_undisclosed"
    assert check_trial_universe("ghost-family") == "trial_universe_undisclosed"
    for family_id in (None, "ghost-family"):
        decision = evaluate_promotion(
            fold_metrics(log_loss=0.4), fold_metrics(log_loss=0.5),
            trial_family_id=family_id,
        )
        assert decision.accepted is False
        assert decision.reason == "trial_universe_undisclosed"


def test_promotion_disclosed_family_with_small_q_passes_gate(forced_gate, registry_db):
    evaluate_promotion, check_trial_universe = forced_gate
    registry_db.record_family("fam-pass", [0.001, 0.02, 0.05])
    assert check_trial_universe("fam-pass") is None
    decision = evaluate_promotion(
        fold_metrics(log_loss=0.4), fold_metrics(log_loss=0.5),
        trial_family_id="fam-pass",
    )
    assert decision.accepted is True
    assert decision.reason == "accepted"


def test_promotion_disclosed_family_with_large_q_is_rejected(forced_gate, registry_db):
    evaluate_promotion, check_trial_universe = forced_gate
    registry_db.record_family("fam-fail", [0.5, 0.6])
    assert check_trial_universe("fam-fail") == "fdr_threshold_exceeded"
    decision = evaluate_promotion(
        fold_metrics(log_loss=0.4), fold_metrics(log_loss=0.5),
        trial_family_id="fam-fail",
    )
    assert decision.accepted is False
    assert decision.reason == "fdr_threshold_exceeded"


def test_promotion_q_threshold_is_configurable(forced_gate, registry_db):
    _, check_trial_universe = forced_gate
    registry_db.record_family("fam-mid", [0.2, 0.2])
    assert check_trial_universe("fam-mid", fdr_threshold=0.10) == "fdr_threshold_exceeded"
    assert check_trial_universe("fam-mid", fdr_threshold=0.30) is None


def test_legacy_pytest_path_stays_accepted_without_trials(monkeypatch):
    monkeypatch.delenv("NEXUS_FDR_GATE", raising=False)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_ml/test_model_promotion.py::legacy")
    from services.nexus_ml.model_promotion import evaluate_promotion
    decision = evaluate_promotion(fold_metrics(log_loss=0.4), fold_metrics(log_loss=0.5))
    assert decision.accepted is True
    assert decision.reason == "accepted"


def test_existing_fold_gates_run_before_trial_gate(forced_gate):
    evaluate_promotion, _ = forced_gate
    decision = evaluate_promotion(
        fold_metrics(accuracy=0.7, log_loss=0.4), fold_metrics(accuracy=0.8, log_loss=0.5),
        trial_family_id=None,
    )
    assert decision.accepted is False
    assert decision.reason == "accuracy_regressed"


# ── Paired sign test + promotion-family disclosure (ml/main wiring) ──────────

def test_paired_sign_test_pvalue_known_values():
    from services.nexus_ml.statistical_gates import paired_sign_test_pvalue
    assert paired_sign_test_pvalue(0, 0) == 1.0
    assert paired_sign_test_pvalue(3, 3) == pytest.approx(2 / 8)
    assert paired_sign_test_pvalue(5, 5) == pytest.approx(2 / 32)
    assert paired_sign_test_pvalue(0, 5) == pytest.approx(2 / 32)
    # 2*(C(4,2)+C(4,3)+C(4,4))/16 = 1.375 → capped at 1.0
    assert paired_sign_test_pvalue(2, 4) == 1.0
    for bad in ((-1, 3), (4, 3)):
        with pytest.raises(ValueError):
            paired_sign_test_pvalue(*bad)


def test_disclose_promotion_family_records_and_gates(forced_gate, registry_db):
    evaluate_promotion, check_trial_universe = forced_gate
    from services.nexus_ml.model_promotion import disclose_promotion_family
    cand = fold_metrics(log_loss=0.4)
    inc = fold_metrics(log_loss=0.5)
    family = disclose_promotion_family(cand, inc, "disclose-ok")
    assert family == "disclose-ok"
    assert registry_db.has_disclosed_family("disclose-ok") is True
    # 3/3 wins → exact sign p = 0.25 → q = 0.25: disclosed but above the
    # default 0.10 FDR, so the gate rejects honestly at the default threshold.
    assert check_trial_universe(family) == "fdr_threshold_exceeded"
    decision = evaluate_promotion(
        cand, inc, trial_family_id=family, fdr_threshold=0.30,
    )
    assert decision.accepted is True


def test_disclose_promotion_family_fails_closed(registry_db, monkeypatch):
    from services.nexus_ml import model_promotion
    # Nothing to disclose → None (caller passes it through → rejected).
    assert model_promotion.disclose_promotion_family({}, {}, "empty") is None
    # Registry failure → None (fail-closed, never a fabricated disclosure).
    def _boom(*_args, **_kwargs):
        raise OSError("registry unavailable")
    monkeypatch.setattr(registry_db, "record_family", _boom)
    assert (
        model_promotion.disclose_promotion_family(
            fold_metrics(log_loss=0.4), fold_metrics(log_loss=0.5), "broken",
        )
        is None
    )
