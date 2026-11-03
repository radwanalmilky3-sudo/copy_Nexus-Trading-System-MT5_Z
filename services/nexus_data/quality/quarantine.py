"""Quarantine envelopes; persistence is intentionally left to callers."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from ..imports.contracts import CanonicalOHLCV, CanonicalTick, Provenance, canonical_payload, canonical_record_key


class QuarantineReason(StrEnum):
    DUPLICATE = "duplicate"
    GAP = "gap"
    OUTLIER = "outlier"
    INVALID_TIMESTAMP = "invalid_timestamp"
    INVALID_RECORD = "invalid_record"
    CONTRACT_VIOLATION = "contract_violation"


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    quarantine_id: str
    dataset_id: str
    reason_code: QuarantineReason
    record_key: str
    payload: Mapping[str, Any]
    detail: str
    provenance: Provenance | None = None
    import_job_id: str | None = None
    quality_run_id: str | None = None
    resolution_status: str = "open"


def make_quarantine_record(
    *, dataset_id: str, record: CanonicalOHLCV | CanonicalTick,
    reason_code: QuarantineReason, detail: str,
    import_job_id: str | None = None, quality_run_id: str | None = None,
) -> QuarantineRecord:
    payload = canonical_payload(record)
    record_key = json.dumps(canonical_record_key(record), default=str, sort_keys=True)
    identity = json.dumps(
        {"dataset_id": dataset_id, "reason": reason_code.value, "key": record_key},
        sort_keys=True,
    ).encode("utf-8")
    return QuarantineRecord(
        quarantine_id=hashlib.sha256(identity).hexdigest()[:24],
        dataset_id=dataset_id, reason_code=reason_code, record_key=record_key,
        payload=payload, detail=detail, provenance=record.provenance,
        import_job_id=import_job_id, quality_run_id=quality_run_id,
    )
