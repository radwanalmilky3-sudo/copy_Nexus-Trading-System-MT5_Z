"""Pure quality checks for ordering, duplicates, gaps, and outliers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import Iterable

from ..imports.contracts import CanonicalOHLCV, CanonicalTick, canonical_record_key
from .quarantine import QuarantineReason, QuarantineRecord, make_quarantine_record


class Severity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class QualityIssue:
    code: str
    severity: Severity
    message: str
    record_key: str | None = None
    observed: float | int | str | None = None
    expected: float | int | str | None = None


@dataclass(frozen=True, slots=True)
class QualityCheck:
    name: str
    passed: bool
    rows_checked: int
    issue_count: int
    metrics: dict[str, float | int | str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ValidationFindings:
    dataset_id: str
    rows_checked: int
    checks: tuple[QualityCheck, ...]
    issues: tuple[QualityIssue, ...]
    quarantined: tuple[QuarantineRecord, ...]

    @property
    def valid(self) -> bool:
        return not any(issue.severity == Severity.ERROR for issue in self.issues)

    @property
    def status(self) -> str:
        if any(issue.severity == Severity.ERROR for issue in self.issues):
            return "failed"
        if self.issues:
            return "warning"
        return "passed"


@dataclass(frozen=True, slots=True)
class OutlierPolicy:
    max_abs_return: float = 0.20
    max_bar_range_pct: float = 0.25


def validate_ohlcv(
    records: Iterable[CanonicalOHLCV], *, dataset_id: str,
    expected_interval: timedelta, outlier_policy: OutlierPolicy = OutlierPolicy(),
    gap_tolerance: float = 1.0,
) -> ValidationFindings:
    rows = tuple(records)
    issues: list[QualityIssue] = []
    quarantined: list[QuarantineRecord] = []

    duplicate_issues: list[QualityIssue] = []
    seen: set[object] = set()
    for record in rows:
        key = canonical_record_key(record)
        if key in seen:
            issue = QualityIssue(
                code="duplicate_key", severity=Severity.ERROR,
                message=f"duplicate OHLCV key: {key}", record_key=str(key),
            )
            duplicate_issues.append(issue)
            quarantined.append(make_quarantine_record(
                dataset_id=dataset_id, record=record,
                reason_code=QuarantineReason.DUPLICATE, detail=issue.message,
            ))
        seen.add(key)
    issues.extend(duplicate_issues)

    order_issues = _ordering_issues(rows)
    issues.extend(order_issues)
    ordered = tuple(sorted(rows, key=lambda record: record.timestamp))

    gap_issues: list[QualityIssue] = []
    for previous, current in zip(ordered, ordered[1:]):
        delta = current.timestamp - previous.timestamp
        if delta > expected_interval * (1 + gap_tolerance):
            gap_issues.append(QualityIssue(
                code="time_gap", severity=Severity.WARNING,
                message=f"gap of {delta} between bars",
                record_key=str((current.symbol, current.timeframe, current.timestamp)),
                observed=delta.total_seconds(), expected=expected_interval.total_seconds(),
            ))
    issues.extend(gap_issues)

    outlier_issues: list[QualityIssue] = []
    for previous, current in zip(ordered, ordered[1:]):
        if previous.close == 0:
            continue
        return_pct = (current.close - previous.close) / previous.close
        range_pct = (current.high - current.low) / current.close if current.close else 0
        if abs(return_pct) > outlier_policy.max_abs_return or range_pct > outlier_policy.max_bar_range_pct:
            issue = QualityIssue(
                code="price_outlier", severity=Severity.ERROR,
                message="bar exceeds configured return or range threshold",
                record_key=str((current.symbol, current.timeframe, current.timestamp)),
                observed=max(abs(return_pct), range_pct),
                expected=max(outlier_policy.max_abs_return, outlier_policy.max_bar_range_pct),
            )
            outlier_issues.append(issue)
            quarantined.append(make_quarantine_record(
                dataset_id=dataset_id, record=current,
                reason_code=QuarantineReason.OUTLIER, detail=issue.message,
            ))
    issues.extend(outlier_issues)

    checks = (
        QualityCheck("duplicate_keys", not duplicate_issues, len(rows), len(duplicate_issues)),
        QualityCheck("monotonic_order", not order_issues, len(rows), len(order_issues)),
        QualityCheck("expected_interval_gaps", not gap_issues, len(rows), len(gap_issues)),
        QualityCheck("price_outliers", not outlier_issues, len(rows), len(outlier_issues)),
    )
    return ValidationFindings(dataset_id, len(rows), checks, tuple(issues), tuple(quarantined))


def validate_ticks(records: Iterable[CanonicalTick], *, dataset_id: str) -> ValidationFindings:
    rows = tuple(records)
    issues: list[QualityIssue] = []
    quarantined: list[QuarantineRecord] = []
    seen: set[object] = set()
    duplicate_issues: list[QualityIssue] = []
    for record in rows:
        key = canonical_record_key(record)
        if key in seen:
            issue = QualityIssue(
                code="duplicate_key", severity=Severity.ERROR,
                message=f"duplicate tick key: {key}", record_key=str(key),
            )
            duplicate_issues.append(issue)
            quarantined.append(make_quarantine_record(
                dataset_id=dataset_id, record=record,
                reason_code=QuarantineReason.DUPLICATE, detail=issue.message,
            ))
        seen.add(key)
    issues.extend(duplicate_issues)
    order_issues = _ordering_issues(rows)
    issues.extend(order_issues)
    checks = (
        QualityCheck("duplicate_keys", not duplicate_issues, len(rows), len(duplicate_issues)),
        QualityCheck("monotonic_order", not order_issues, len(rows), len(order_issues)),
    )
    return ValidationFindings(dataset_id, len(rows), checks, tuple(issues), tuple(quarantined))


def _ordering_issues(records: tuple[CanonicalOHLCV | CanonicalTick, ...]) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    for previous, current in zip(records, records[1:]):
        if current.timestamp < previous.timestamp:
            issues.append(QualityIssue(
                code="out_of_order", severity=Severity.ERROR,
                message="records are not ordered by timestamp",
                record_key=str(current.timestamp),
            ))
    return issues
