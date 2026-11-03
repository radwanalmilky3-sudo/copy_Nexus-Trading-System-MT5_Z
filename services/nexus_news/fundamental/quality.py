from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class DataQualityEngine:
    version = "1.0.0"

    def assess(self, record: dict[str, Any], *, required: tuple[str, ...], max_age_sec: int | None = None) -> dict[str, Any]:
        missing = [k for k in required if record.get(k) in (None, "")]
        completeness = max(0.0, 100.0 * (1.0 - len(missing) / max(1, len(required))))
        age_sec: float | None = None
        freshness = 100.0
        ts = record.get("source_timestamp") or record.get("timestamp") or record.get("published_at")
        if ts and max_age_sec:
            try:
                d = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if d.tzinfo is None:
                    d = d.replace(tzinfo=timezone.utc)
                age_sec = max(0.0, (datetime.now(timezone.utc) - d.astimezone(timezone.utc)).total_seconds())
                freshness = max(0.0, min(100.0, 100.0 * (1.0 - age_sec / max_age_sec)))
            except Exception:
                freshness = 35.0
        origin = str(record.get("origin", "real")).lower()
        origin_factor = {"real": 1.0, "proxy": 0.55, "synthetic": 0.20, "test": 0.0}.get(origin, 0.35)
        quality = completeness * 0.55 + freshness * 0.30 + origin_factor * 100.0 * 0.15
        return {
            "quality_score": max(0.0, min(100.0, quality)),
            "completeness_score": completeness,
            "freshness_score": freshness,
            "age_sec": age_sec,
            "missing_fields": missing,
            "origin": origin,
            "version": self.version,
        }
