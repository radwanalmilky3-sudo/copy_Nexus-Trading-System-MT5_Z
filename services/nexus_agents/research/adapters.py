"""Pure adapters from source-neutral records into research contracts."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Protocol

from .contracts import BlackoutWindow, ResearchOnlyScope, ResearchSnapshot


class ResearchInputAdapter(Protocol):
    """Boundary for a caller-provided record; implementations must not fetch data."""

    def adapt(self, record: Mapping[str, Any]) -> ResearchSnapshot:
        ...


class MappingResearchAdapter:
    """Adapt an already-loaded mapping without I/O or trading dependencies."""

    def __init__(self, *, source: str = "mapping") -> None:
        self.source = source

    def adapt(self, record: Mapping[str, Any]) -> ResearchSnapshot:
        blackout_raw = record.get("blackout")
        blackout = None
        if blackout_raw is not None:
            blackout = BlackoutWindow(
                starts_at=_as_datetime(blackout_raw["starts_at"], "blackout.starts_at"),
                ends_at=_as_datetime(blackout_raw["ends_at"], "blackout.ends_at"),
                reason=str(blackout_raw["reason"]),
                source=str(blackout_raw.get("source", self.source)),
            )

        available_at = _as_datetime(record["available_at"], "available_at")
        vintage = _as_datetime(record["vintage"], "vintage")
        payload = record.get("payload", {})
        return ResearchSnapshot(
            payload=payload,
            available_at=available_at,
            vintage=vintage,
            scope=ResearchOnlyScope(),
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
