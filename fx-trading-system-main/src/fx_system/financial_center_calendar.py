"""Financial-center holiday / half-day contract for ASIA-LDN filters.

Does not invent holidays. Formal ASIA-LDN holiday filtering requires a verified
manifest; otherwise the filter remains unapplied and the mode is research-only.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd

CENTER_COLUMNS: tuple[str, ...] = (
    "center",
    "session_date",
    "session_type",
    "source",
    "source_url",
    "retrieved_at_utc",
    "notes",
)
ALLOWED_CENTERS = frozenset({"Tokyo", "London"})
ALLOWED_SESSION_TYPES = frozenset({"closed", "half_day"})


class FinancialCenterCalendarError(ValueError):
    """Holiday calendar contract violation."""


@dataclass(frozen=True)
class FinancialCenterCalendar:
    rows: pd.DataFrame
    manifest_verified: bool
    centers: tuple[str, ...]

    def closed_or_half_days(self, center: str) -> set[pd.Timestamp]:
        key = center.strip()
        if key not in ALLOWED_CENTERS:
            raise FinancialCenterCalendarError(f"unsupported center {center!r}")
        selected = self.rows.loc[self.rows["center"] == key, "session_date"]
        return {pd.Timestamp(value).normalize() for value in selected}

    def to_audit(self) -> dict[str, Any]:
        return {
            "manifest_verified": self.manifest_verified,
            "centers": list(self.centers),
            "rows": int(len(self.rows)),
            "holiday_filter_eligible": bool(self.manifest_verified and len(self.rows)),
        }


def validate_financial_center_calendar(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        raise FinancialCenterCalendarError("financial center calendar is empty")
    result = frame.copy()
    missing = [column for column in CENTER_COLUMNS if column not in result.columns]
    if missing:
        raise FinancialCenterCalendarError(f"missing columns: {missing}")
    result["center"] = result["center"].astype(str)
    if not set(result["center"]).issubset(ALLOWED_CENTERS):
        raise FinancialCenterCalendarError(
            f"center must be one of {sorted(ALLOWED_CENTERS)}"
        )
    result["session_type"] = result["session_type"].astype(str)
    if not set(result["session_type"]).issubset(ALLOWED_SESSION_TYPES):
        raise FinancialCenterCalendarError(
            f"session_type must be one of {sorted(ALLOWED_SESSION_TYPES)}"
        )
    result["session_date"] = pd.to_datetime(
        result["session_date"], utc=True, errors="coerce"
    ).dt.normalize()
    if result["session_date"].isna().any():
        raise FinancialCenterCalendarError("session_date must be valid UTC dates")
    if result.duplicated(["center", "session_date"]).any():
        raise FinancialCenterCalendarError("duplicate center/session_date rows")
    return result.sort_values(["center", "session_date"]).reset_index(drop=True)


def _verify_manifest(csv_path: Path, frame: pd.DataFrame) -> bool:
    manifest_path = csv_path.with_suffix(".manifest.json")
    if not manifest_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    if manifest.get("schema_version") != 1:
        return False
    if manifest.get("dataset_kind") != "financial_center_calendar":
        return False
    if manifest.get("csv_sha256") != digest:
        raise FinancialCenterCalendarError("calendar CSV does not match manifest hash")
    centers = manifest.get("centers")
    if not isinstance(centers, list) or set(centers) != set(frame["center"].unique()):
        return False
    return True


def load_financial_center_calendar(path: str | Path) -> FinancialCenterCalendar:
    csv_path = Path(path)
    frame = validate_financial_center_calendar(pd.read_csv(csv_path))
    verified = _verify_manifest(csv_path, frame)
    return FinancialCenterCalendar(
        rows=frame,
        manifest_verified=verified,
        centers=tuple(sorted(frame["center"].unique())),
    )


def asia_ldn_holiday_filter_status(
    calendar: FinancialCenterCalendar | None,
    *,
    require_formal: bool = False,
) -> dict[str, Any]:
    """Return whether ASIA-LDN may apply a holiday filter."""
    if calendar is None:
        status: Literal["unapplied_missing_calendar", "formal_rejected"] = (
            "formal_rejected" if require_formal else "unapplied_missing_calendar"
        )
        if require_formal:
            raise FinancialCenterCalendarError(
                "formal ASIA-LDN requires a verified Tokyo/London holiday calendar"
            )
        return {
            "holiday_filter_applied": False,
            "status": status,
            "reason": "calendar not supplied",
        }
    if not calendar.manifest_verified:
        if require_formal:
            raise FinancialCenterCalendarError(
                "formal ASIA-LDN requires manifest-verified holiday calendar"
            )
        return {
            "holiday_filter_applied": False,
            "status": "unapplied_unverified_manifest",
            "reason": "manifest missing or incomplete",
            "audit": calendar.to_audit(),
        }
    required = {"Tokyo", "London"}
    if not required.issubset(set(calendar.centers)):
        if require_formal:
            raise FinancialCenterCalendarError(
                "formal ASIA-LDN holiday calendar must cover Tokyo and London"
            )
        return {
            "holiday_filter_applied": False,
            "status": "unapplied_incomplete_centers",
            "reason": f"centers={calendar.centers}",
            "audit": calendar.to_audit(),
        }
    return {
        "holiday_filter_applied": True,
        "status": "applied",
        "audit": calendar.to_audit(),
    }


def deferred_central_bank_adapters() -> dict[str, str]:
    """Machine-readable deferred status for incomplete CB policy adapters."""
    return {
        "BOE": "deferred_missing_official_adapter",
        "SNB": "deferred_missing_official_adapter",
        "BOC": "deferred_missing_official_adapter",
        "RBNZ": "deferred_missing_official_adapter",
        "macro_blackout_formal_status": "deferred_missing_data",
        "implemented_authorities": "FED,ECB,BOJ,RBA",
    }
