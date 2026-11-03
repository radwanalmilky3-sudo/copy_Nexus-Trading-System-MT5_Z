"""Deterministic walk-forward window construction without running a backtest."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from shared.strategy_contracts import OutOfSampleWindow, WalkForwardSpec


def _validate_timestamps(timestamps: Sequence[datetime]) -> tuple[datetime, ...]:
    values = tuple(timestamps)
    if any(value.tzinfo is None or value.utcoffset() is None for value in values):
        raise ValueError("walk-forward timestamps must be timezone-aware")
    if any(left >= right for left, right in zip(values, values[1:])):
        raise ValueError("walk-forward timestamps must be strictly increasing")
    return values


def build_walk_forward_windows(
    timestamps: Sequence[datetime],
    spec: WalkForwardSpec,
) -> tuple[OutOfSampleWindow, ...]:
    """Build train/validation/purge/embargo/test windows from an index.

    Selection uses only the train and optional validation ranges.  Test bars
    are separated by explicit purge and embargo bars and are marked OOS in the
    returned contract.  No signals, metrics, or market data are produced.
    """

    values = _validate_timestamps(timestamps)
    required = (
        spec.train_bars
        + spec.validation_bars
        + spec.purge_bars
        + spec.embargo_bars
        + spec.test_bars
    )
    if len(values) < required:
        return ()

    windows: list[OutOfSampleWindow] = []
    offset = 0
    fold = 1
    while offset + required <= len(values):
        train_start_index = 0 if spec.expanding_train else offset
        train_end_index = offset + spec.train_bars - 1
        validation_start_index = train_end_index + 1
        validation_end_index = validation_start_index + spec.validation_bars - 1
        purge_start_index = validation_end_index + 1
        purge_end_index = purge_start_index + spec.purge_bars - 1
        embargo_start_index = purge_end_index + 1
        embargo_end_index = embargo_start_index + spec.embargo_bars - 1
        test_start_index = embargo_end_index + 1
        test_end_index = test_start_index + spec.test_bars - 1

        windows.append(
            OutOfSampleWindow(
                fold=fold,
                train_start=values[train_start_index],
                train_end=values[train_end_index],
                validation_start=(
                    values[validation_start_index] if spec.validation_bars else None
                ),
                validation_end=(values[validation_end_index] if spec.validation_bars else None),
                purge_start=values[purge_start_index] if spec.purge_bars else None,
                purge_end=values[purge_end_index] if spec.purge_bars else None,
                embargo_start=values[embargo_start_index] if spec.embargo_bars else None,
                embargo_end=values[embargo_end_index] if spec.embargo_bars else None,
                test_start=values[test_start_index],
                test_end=values[test_end_index],
                warmup_start=values[max(0, test_start_index - spec.warmup_bars)],
            )
        )
        fold += 1
        offset += spec.step_bars

    return tuple(windows)


__all__ = ["build_walk_forward_windows"]
