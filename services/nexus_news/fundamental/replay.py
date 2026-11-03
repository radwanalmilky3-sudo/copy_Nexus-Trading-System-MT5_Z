from __future__ import annotations

from datetime import datetime
from typing import Any


class LeakageError(RuntimeError):
    pass


class HistoricalReplayGuard:
    version = "1.0.0"

    @staticmethod
    def assert_known_at(record: dict[str, Any], decision_time: datetime) -> None:
        raw = record.get("known_at") or record.get("received_at") or record.get("source_published_at")
        if not raw:
            raise LeakageError("record has no known_at/received_at timestamp")
        known = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if known.tzinfo is None and decision_time.tzinfo is not None:
            known = known.replace(tzinfo=decision_time.tzinfo)
        if known > decision_time:
            raise LeakageError(f"future data leakage: known_at={known.isoformat()} > decision={decision_time.isoformat()}")

    def filter_known(self, records: list[dict[str, Any]], decision_time: datetime) -> list[dict[str, Any]]:
        safe: list[dict[str, Any]] = []
        for r in records:
            try:
                self.assert_known_at(r, decision_time)
            except LeakageError:
                continue
            safe.append(r)
        return safe
