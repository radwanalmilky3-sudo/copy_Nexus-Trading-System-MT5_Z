"""Point-in-time eligibility checks with no data-source side effects."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from shared.strategy_contracts import (
    AntiLeakageAudit,
    AntiLeakageContract,
)


def _timestamp(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError(f"{field_name} must be an aware datetime or ISO string")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed


def audit_point_in_time_records(
    records: Iterable[Mapping[str, Any]],
    *,
    decision_time: datetime,
    contract: AntiLeakageContract,
    run_id: str = "unassigned",
) -> AntiLeakageAudit:
    """Audit records against a decision time without loading or mutating them.

    A record is eligible only when it was available no later than the decision
    timestamp.  Missing provenance, observation-after-availability, revised
    values, and malformed timestamps are violations.  The function deliberately
    returns a fail-closed audit instead of silently dropping bad records.
    """

    decision = _timestamp(decision_time, "decision_time")
    violations: list[str] = []
    checked = 0
    for index, record in enumerate(records):
        checked += 1
        prefix = f"record[{index}]"
        try:
            available = _timestamp(record[contract.available_time_field], "available_time")
        except (KeyError, TypeError, ValueError) as exc:
            violations.append(f"{prefix}:invalid_available_time:{exc}")
            continue
        if available > decision:
            violations.append(f"{prefix}:available_after_decision")

        observation_value = record.get(contract.observation_time_field)
        if observation_value is not None:
            try:
                observation = _timestamp(observation_value, "observation_time")
                if observation > available:
                    violations.append(f"{prefix}:observation_after_available")
            except ValueError as exc:
                violations.append(f"{prefix}:invalid_observation_time:{exc}")

        if contract.require_vintage_id and not str(record.get(contract.vintage_id_field, "")).strip():
            violations.append(f"{prefix}:missing_vintage_id")
        if contract.require_content_hash and not str(record.get(contract.content_hash_field, "")).strip():
            violations.append(f"{prefix}:missing_content_hash")
        if not contract.allow_revised_values and bool(record.get("is_revised", False)):
            violations.append(f"{prefix}:revised_value_not_allowed")

    return AntiLeakageAudit(
        audit_id=uuid4().hex,
        run_id=run_id,
        valid=not violations,
        checked_records=checked,
        violations=tuple(violations),
        checked_at=datetime.now(timezone.utc),
        decision_time=decision,
    )


__all__ = ["audit_point_in_time_records"]
