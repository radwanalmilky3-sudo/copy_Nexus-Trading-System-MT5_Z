"""Intelligence route honesty contracts (Agent 4 independent acceptance).

Truth contract: unknown ≠ 0 ≠ NEUTRAL.
- /models-by-regime must never emit a zeroed `overall` record synthesized from
  a missing/empty/partial metrics blob (fabricated 0-trade history).
- /genai-brief must never emit a fabricated `bias: NEUTRAL` when no brief was
  generated (the dashboard treats any bias as a confirmed outlook unless the
  `error` marker is present — see GenAIBrief.tsx payload.error guard).
"""
from __future__ import annotations

import json

import pytest

from services.nexus_api.routers import intelligence


def _redis_returning(mapping: dict[str, str | None]):
    async def _redis_get(key: str):
        return mapping.get(key)

    return _redis_get


# ── /models-by-regime ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_models_by_regime_empty_store_is_unknown_not_zeroed(monkeypatch):
    monkeypatch.setattr(intelligence, "_redis_get", _redis_returning({}))

    result = await intelligence.get_models_by_regime()

    assert result["available"] is False
    assert result["overall"] is None
    assert result["by_regime"] == {}
    # No synthesized headline numbers for the UI to misrender as a record.
    assert "win_rate" not in result
    assert "total_trades" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("blob", ["{}", "[]", '"not-a-metrics-blob"'])
async def test_models_by_regime_unshaped_metrics_is_unknown_not_zeroed(monkeypatch, blob):
    """Present-but-empty or wrong-shaped metrics must not fabricate overall=0."""
    monkeypatch.setattr(
        intelligence,
        "_redis_get",
        _redis_returning({"nexus:trade_memory:metrics": blob}),
    )

    result = await intelligence.get_models_by_regime()

    assert result["available"] is False
    assert result["overall"] is None


@pytest.mark.asyncio
async def test_models_by_regime_partial_metrics_nulls_missing_fields_not_zero(monkeypatch):
    """A missing key is UNKNOWN (None), only stored values are reported."""
    monkeypatch.setattr(
        intelligence,
        "_redis_get",
        _redis_returning({"nexus:trade_memory:metrics": json.dumps({"total_trades": 10})}),
    )

    result = await intelligence.get_models_by_regime()

    overall = result["overall"]
    assert result["available"] is True
    assert overall["total_trades"] == 10
    assert overall["win_rate"] is None
    assert overall["total_wins"] is None
    assert overall["total_losses"] is None
    assert overall["avg_pnl_pips"] is None


@pytest.mark.asyncio
async def test_models_by_regime_explicit_zero_still_passes_through(monkeypatch):
    """A genuinely stored 0 is known data and must survive as 0."""
    monkeypatch.setattr(
        intelligence,
        "_redis_get",
        _redis_returning({
            "nexus:trade_memory:metrics": json.dumps({
                "total_trades": 0,
                "overall_win_rate": 0.0,
                "by_regime": {},
            })
        }),
    )

    result = await intelligence.get_models_by_regime()

    assert result["available"] is True
    assert result["overall"]["total_trades"] == 0
    assert result["overall"]["win_rate"] == 0.0


@pytest.mark.asyncio
async def test_models_by_regime_real_metrics_pass_through_unchanged(monkeypatch):
    metrics = {
        "total_trades": 42,
        "total_wins": 23,
        "total_losses": 19,
        "overall_win_rate": 0.547619,
        "avg_pnl_pips": 1.35,
        "recent_streak": {"type": "win", "count": 3},
        "by_regime": {"RANGING": {"trades": 20, "wins": 12, "losses": 8,
                                  "win_rate": 0.6, "avg_pnl": 1.1}},
        "by_session": {"LONDON": {"trades": 30, "wins": 16, "losses": 14,
                                  "win_rate": 0.533, "avg_pnl": 0.9}},
    }
    monkeypatch.setattr(
        intelligence,
        "_redis_get",
        _redis_returning({"nexus:trade_memory:metrics": json.dumps(metrics)}),
    )

    result = await intelligence.get_models_by_regime()

    assert result["available"] is True
    assert result["overall"]["win_rate"] == metrics["overall_win_rate"]
    assert result["overall"]["recent_streak"] == metrics["recent_streak"]
    assert result["by_regime"] == metrics["by_regime"]
    assert result["by_session"] == metrics["by_session"]


@pytest.mark.asyncio
async def test_models_by_regime_corrupt_json_fails_closed(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(
        intelligence,
        "_redis_get",
        _redis_returning({"nexus:trade_memory:metrics": "{corrupt"}),
    )

    with pytest.raises(HTTPException) as exc:
        await intelligence.get_models_by_regime()
    assert exc.value.status_code == 503


# ── /genai-brief ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_genai_brief_missing_is_unknown_not_neutral(monkeypatch):
    """No generated brief must not answer bias=NEUTRAL (unknown ≠ NEUTRAL)."""
    monkeypatch.setattr(intelligence, "_redis_get", _redis_returning({}))

    result = await intelligence.get_genai_brief()

    assert result["bias"] is None
    assert result["bias"] != "NEUTRAL"
    assert result["available"] is False
    assert result["reason"] == "not_generated"
    # The dashboard keep-last-good guard keys on payload.error (GenAIBrief.tsx).
    assert result["error"] == "not_generated"
    assert result["summary"] is None


@pytest.mark.asyncio
async def test_genai_brief_stored_bias_passes_through_untouched(monkeypatch):
    brief = {
        "bias": "BULLISH",
        "summary": "brief de muestra",
        "key_drivers": ["driver-1"],
        "confidence": 71,
        "updated_at": "2026-10-21T06:00:00Z",
    }
    monkeypatch.setattr(
        intelligence,
        "_redis_get",
        _redis_returning({"nexus:genai:daily_bias": json.dumps(brief)}),
    )

    result = await intelligence.get_genai_brief()

    assert result == brief
    assert "error" not in result


@pytest.mark.asyncio
async def test_genai_brief_neutral_stored_value_is_preserved_as_real(monkeypatch):
    """A *stored* NEUTRAL is observed data and must still pass through."""
    brief = {"bias": "NEUTRAL", "summary": "almacenado", "updated_at": "2026-10-21T06:00:00Z"}
    monkeypatch.setattr(
        intelligence,
        "_redis_get",
        _redis_returning({"nexus:genai:daily_bias": json.dumps(brief)}),
    )

    result = await intelligence.get_genai_brief()

    assert result == brief


@pytest.mark.asyncio
async def test_genai_brief_corrupt_json_fails_closed(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(
        intelligence,
        "_redis_get",
        _redis_returning({"nexus:genai:daily_bias": "{corrupt"}),
    )

    with pytest.raises(HTTPException) as exc:
        await intelligence.get_genai_brief()
    assert exc.value.status_code == 503
