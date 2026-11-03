from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from shared.fundamental import GoldDirection, GoldImpactResult


def _dir(ret: float, band: float = 0.00025) -> str:
    if ret > band:
        return GoldDirection.BULLISH.value
    if ret < -band:
        return GoldDirection.BEARISH.value
    return GoldDirection.NEUTRAL.value


class OutcomeEvaluator:
    version = "1.0.0"

    def evaluate(self, prediction: GoldImpactResult, prices: dict[str, float]) -> dict[str, Any]:
        p0 = float(prices.get("event", 0.0) or 0.0)
        if p0 <= 0:
            raise ValueError("event price required")
        out: dict[str, Any] = {
            "prediction_id": prediction.prediction_id,
            "price_at_event": p0,
            "evaluated_at": datetime.now(timezone.utc),
        }
        expected = prediction.direction.value
        for label, key in (("1m", "1m"), ("5m", "5m"), ("15m", "15m"), ("60m", "60m"), ("4h", "4h")):
            p = prices.get(key)
            if p is None:
                continue
            ret = float(p) / p0 - 1.0
            actual = _dir(ret)
            out[f"return_{label}"] = ret
            out[f"actual_direction_{label}"] = actual
            out[f"correct_{label}"] = expected == actual or (expected == GoldDirection.CONFLICTED.value and actual == GoldDirection.NEUTRAL.value)
        corrects = [v for k, v in out.items() if k.startswith("correct_")]
        out["lesson_ar"] = (
            "كان اتجاه النموذج متسقًا مع غالبية النوافذ المقاسة."
            if corrects and sum(bool(x) for x in corrects) >= len(corrects) / 2
            else "لم يتأكد اتجاه النموذج في أغلب النوافذ؛ يجب مراجعة الأوزان والتعارض والتأكيد السوقي."
        )
        return out
