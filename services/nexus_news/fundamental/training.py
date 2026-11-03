from __future__ import annotations

from datetime import datetime
from typing import Any

from .replay import HistoricalReplayGuard


class TrainingDatasetBuilder:
    version = "1.0.0"

    def __init__(self) -> None:
        self.guard = HistoricalReplayGuard()

    def build_row(self, decision_time: datetime, *, event: dict[str, Any], observations: list[dict[str, Any]], targets: dict[str, float]) -> dict[str, Any]:
        self.guard.assert_known_at(event, decision_time)
        safe_obs = self.guard.filter_known(observations, decision_time)
        latest = {str(o.get("series_code") or o.get("flow_type")): o for o in safe_obs}
        return {
            "timestamp": decision_time,
            "event_id": event.get("event_id"),
            "symbol": event.get("symbol", "XAUUSD"),
            "event_type": event.get("event_type"),
            "declared_impact": event.get("declared_impact"),
            "actual": event.get("actual"),
            "forecast": event.get("forecast"),
            "previous": event.get("previous"),
            "surprise_zscore": event.get("surprise_zscore"),
            "dxy": (latest.get("DXY") or {}).get("value"),
            "us2y": (latest.get("US2Y") or {}).get("value"),
            "us10y": (latest.get("US10Y") or {}).get("value"),
            "real_yield": (latest.get("REAL_YIELD_10Y") or {}).get("value"),
            "vix": (latest.get("VIX") or {}).get("value"),
            "target_return_5m": targets.get("5m"),
            "target_return_15m": targets.get("15m"),
            "target_return_60m": targets.get("60m"),
            "target_return_4h": targets.get("4h"),
            "leakage_guard_version": self.guard.version,
            "feature_version": self.version,
            "known_at_cutoff": decision_time,
        }
