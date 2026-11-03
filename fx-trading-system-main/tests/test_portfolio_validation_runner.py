from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest

from fx_system.portfolio_ledger import MasterAccountLedger
from fx_system.portfolio_runner import PortfolioRunResult
from fx_system.portfolio_validation_runner import (
    run_portfolio_candidate_validation,
    write_portfolio_candidate_validation_artifacts,
)


def _ledger_run(index: pd.DatetimeIndex, daily_returns: np.ndarray) -> PortfolioRunResult:
    ledger = MasterAccountLedger(initial_nav=100.0)
    for timestamp, simple_return in zip(index, daily_returns, strict=True):
        ledger.book_mid_plus_half_spread(
            timestamp=timestamp,
            target_positions={},
            mid_prices={},
            half_spreads={},
            cash_interest=ledger.nav * float(simple_return),
        )
    return PortfolioRunResult(ledger=ledger, transitions=(), skipped_targets=())


def _candidate_runs() -> dict[str, PortfolioRunResult]:
    observations = 64
    index = pd.bdate_range("2020-01-02", periods=observations, tz="UTC")
    noise = np.sin(np.arange(observations) * 0.71) * 0.004
    return {
        "preregistered": _ledger_run(index, noise + 0.0020),
        "candidate_b": _ledger_run(index, noise * 0.8 + 0.0005),
        "candidate_c": _ledger_run(index, -noise * 0.4 - 0.0007),
    }


def test_bridge_uses_exact_cost_adjusted_ledger_returns_for_joint_diagnostics() -> None:
    candidates = _candidate_runs()

    result = run_portfolio_candidate_validation(
        candidates,
        candidate_set_is_complete=True,
        declared_candidate_names=tuple(candidates),
        selected_candidate="preregistered",
        total_trials_evaluated=3312,
    )

    expected = pd.DataFrame(
        {name: run.to_frame()["simple_return"] for name, run in candidates.items()}
    ).rename_axis("date")
    pdt.assert_frame_equal(result.daily_net_returns, expected)
    assert result.deflated_sharpe is not None
    assert result.deflated_sharpe.trial_count == 3312
    assert result.pbo.defined
    assert result.pbo.split_count == math.comb(16, 8)
    pdt.assert_frame_equal(result.spa_inputs.candidate_losses, -expected)
    assert result.manifest["selected_candidate_was_not_chosen_by_runner"] is True
    assert result.manifest["trading_approval"] is False
    assert result.ledger_audit["accounting_reconciled"].all()
    assert (result.ledger_audit["cash_interest"].abs() > 0).all()


def test_bridge_rejects_incomplete_candidate_attestation_or_missing_trial_disclosure() -> None:
    candidates = _candidate_runs()

    with pytest.raises(ValueError, match="complete candidate set"):
        run_portfolio_candidate_validation(
            candidates,
            candidate_set_is_complete=False,
            declared_candidate_names=tuple(candidates),
            selected_candidate="preregistered",
            total_trials_evaluated=3312,
        )
    with pytest.raises(ValueError, match="all inspected trials"):
        run_portfolio_candidate_validation(
            candidates,
            candidate_set_is_complete=True,
            declared_candidate_names=tuple(candidates),
            selected_candidate="preregistered",
            total_trials_evaluated=2,
        )
    with pytest.raises(ValueError, match="exactly match declared_candidate_names"):
        run_portfolio_candidate_validation(
            candidates,
            candidate_set_is_complete=True,
            declared_candidate_names=(*candidates, "omitted_candidate"),
            selected_candidate="preregistered",
            total_trials_evaluated=3312,
        )


def test_bridge_rejects_date_intersection_and_misaligned_spa_benchmark() -> None:
    candidates = _candidate_runs()
    first = candidates["candidate_b"].to_frame()["simple_return"].to_numpy()
    shifted_index = candidates["candidate_b"].to_frame().index.shift(1, freq="D")
    candidates["candidate_b"] = _ledger_run(shifted_index, first)

    with pytest.raises(ValueError, match="exact common date index"):
        run_portfolio_candidate_validation(
            candidates,
            candidate_set_is_complete=True,
            declared_candidate_names=tuple(candidates),
            selected_candidate="preregistered",
            total_trials_evaluated=3312,
        )

    aligned = _candidate_runs()
    index = aligned["preregistered"].to_frame().index
    benchmark = pd.Series(0.0, index=index.shift(1, freq="D"))
    with pytest.raises(ValueError, match="exactly the candidate matrix date index"):
        run_portfolio_candidate_validation(
            aligned,
            candidate_set_is_complete=True,
            declared_candidate_names=tuple(aligned),
            selected_candidate="preregistered",
            total_trials_evaluated=3312,
            benchmark_returns=benchmark,
        )


class _MissingCostColumnRun(PortfolioRunResult):
    def to_frame(self) -> pd.DataFrame:
        return super().to_frame().drop(columns="spread_cost")


class _UnreconciledRun(PortfolioRunResult):
    def to_frame(self) -> pd.DataFrame:
        frame = super().to_frame()
        frame.loc[frame.index[3], "net_pnl"] += 1.0
        return frame


@pytest.mark.parametrize(
    ("replacement_type", "message"),
    [
        (_MissingCostColumnRun, "missing columns"),
        (_UnreconciledRun, "net PnL components"),
    ],
)
def test_bridge_rejects_incomplete_or_unreconciled_ledger(
    replacement_type: type[PortfolioRunResult], message: str
) -> None:
    candidates = _candidate_runs()
    original = candidates["candidate_b"]
    candidates["candidate_b"] = replacement_type(
        ledger=original.ledger,
        transitions=original.transitions,
        skipped_targets=original.skipped_targets,
    )

    with pytest.raises(ValueError, match=message):
        run_portfolio_candidate_validation(
            candidates,
            candidate_set_is_complete=True,
            declared_candidate_names=tuple(candidates),
            selected_candidate="preregistered",
            total_trials_evaluated=3312,
        )


def test_writer_persists_validation_inputs_and_never_marks_approval(tmp_path: Path) -> None:
    result = run_portfolio_candidate_validation(
        (candidates := _candidate_runs()),
        candidate_set_is_complete=True,
        declared_candidate_names=tuple(candidates),
        selected_candidate="preregistered",
        total_trials_evaluated=3312,
    )

    output = write_portfolio_candidate_validation_artifacts(result, tmp_path / "validation")
    manifest = json.loads(
        (output / "portfolio_validation_manifest.json").read_text(encoding="utf-8")
    )

    assert manifest["trading_approval"] is False
    assert manifest["spa_executed"] is False
    assert manifest["deflated_sharpe"]["trial_count"] == 3312
    assert manifest["pbo"]["split_count"] == math.comb(16, 8)
    for name in (
        "daily_net_returns.csv",
        "ledger_accounting_audit.csv",
        "spa_benchmark_losses.csv",
        "spa_candidate_losses.csv",
        "pbo_splits.csv",
        "pbo_selection_counts.csv",
    ):
        path = output / name
        assert path.exists()
        with path.open("rb") as handle:
            assert manifest["artifacts"][name]["sha256"] == hashlib.file_digest(
                handle, "sha256"
            ).hexdigest()
        assert manifest["artifacts"][name]["rows"] > 0
