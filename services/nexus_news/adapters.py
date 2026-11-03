"""No-I/O adapters for turning loaded news records into research contracts."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from .contracts import NewsBlackout, ResearchNewsItem


class NewsResearchAdapter:
    """Convert caller-owned mappings; this adapter never imports or fetches data."""

    def adapt(self, record: Mapping[str, Any]) -> ResearchNewsItem:
        blackout_raw = record.get("blackout")
        blackout = None
        if blackout_raw is not None:
            blackout = NewsBlackout(
                starts_at=_as_datetime(blackout_raw["starts_at"], "blackout.starts_at"),
                ends_at=_as_datetime(blackout_raw["ends_at"], "blackout.ends_at"),
                reason=str(blackout_raw["reason"]),
                impact=str(blackout_raw.get("impact", "unknown")),
            )
        return ResearchNewsItem(
            payload=record.get("payload", {}),
            available_at=_as_datetime(record["available_at"], "available_at"),
            vintage=_as_datetime(record["vintage"], "vintage"),
            blackout=blackout,
        )


def _as_datetime(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO-8601 datetime") from exc
    raise TypeError(f"{field} must be a datetime or ISO-8601 string")
