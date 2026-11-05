"""ML router — proxy to nexus-ml service (both legacy /api/ml and new /api/traders endpoints)."""
from __future__ import annotations

import os
from typing import Any

import httpx

from ..http_client import new_client
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from ..data_client import DataServiceClient
from ..deps import get_data_service
from ..middleware.auth import CurrentUser
from .admin import _require

logger = structlog.get_logger(__name__)

from shared.rate_limit import rate_limit_scope

router = APIRouter(prefix="/api/ml", tags=["ml"])

ML_BASE = os.getenv("NEXUS_ML_URL", f"http://localhost:{os.getenv('NEXUS_ML_PORT', '8003')}")

# ── Shared proxy helper ─────────────────────────────────────────────────────

async def _proxy(method: str, path: str, body: Any = None, params: dict | None = None) -> Any:
    """Forward request to nexus-ml and return JSON."""
    url = f"{ML_BASE}{path}"
    internal_secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
    if not internal_secret:
        raise HTTPException(503, "NEXUS_INTERNAL_API_SECRET is not configured")
    headers = {"X-Nexus-Internal-Secret": internal_secret}
    async with new_client(timeout=30.0) as client:
        try:
            kwargs: dict[str, Any] = {}
            kwargs["headers"] = headers
            if body is not None:
                kwargs["json"] = body
            if params:
                kwargs["params"] = params
            resp = await client.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(exc.response.status_code, exc.response.text)
        except Exception as exc:
            logger.warning("ml.proxy_failed", path=path, error=str(exc))
            raise HTTPException(502, f"nexus-ml unreachable: {exc}")


# ── Legacy /api/ml endpoints ────────────────────────────────────────────────

@router.get("/status")
async def ml_status(actor: CurrentUser, db: DataServiceClient = Depends(get_data_service)):
    await _require(db, actor, "trading.view")
    return await _proxy("GET", "/api/ml/models/status")


@router.get("/predict/{symbol}")
async def ml_predict(symbol: str, actor: CurrentUser, db: DataServiceClient = Depends(get_data_service)):
    await _require(db, actor, "trading.view")
    return await _proxy("GET", f"/api/ml/predict/{symbol}")


# ── /api/ml/traders/* — proxy to nexus-ml /api/traders/* ────────────────────

@router.get("/traders/status")
async def traders_status(actor: CurrentUser, db: DataServiceClient = Depends(get_data_service)):
    await _require(db, actor, "trading.view")
    """All model statuses (ML, DL, RL)."""
    return await _proxy("GET", "/api/traders/status")


@router.get("/traders/predict/{symbol}")
async def traders_predict_all(symbol: str, actor: CurrentUser, db: DataServiceClient = Depends(get_data_service)):
    await _require(db, actor, "trading.view")
    """Get predictions from all models for a symbol."""
    return await _proxy("GET", f"/api/traders/predict/{symbol}")


@router.get("/traders/predict/{model_type}/{symbol}")
async def traders_predict_single(model_type: str, symbol: str, actor: CurrentUser, db: DataServiceClient = Depends(get_data_service)):
    await _require(db, actor, "trading.view")
    """Get prediction from a specific model."""
    return await _proxy("GET", f"/api/traders/predict/{model_type}/{symbol}")


@router.post("/traders/train", dependencies=[rate_limit_scope("ml")])
async def traders_train(
    request: Request,
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
):
    """Trigger training for specified model types."""
    await _require(db, actor, "trading.settings")
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    return await _proxy("POST", "/api/traders/train", body=body)


@router.get("/traders/comparison")
async def traders_comparison(actor: CurrentUser, db: DataServiceClient = Depends(get_data_service)):
    await _require(db, actor, "trading.view")
    """Model comparison leaderboard."""
    return await _proxy("GET", "/api/traders/comparison")


@router.get("/traders/performance/{model_type}")
async def traders_performance(model_type: str, actor: CurrentUser, db: DataServiceClient = Depends(get_data_service)):
    await _require(db, actor, "trading.view")
    return await _proxy("GET", f"/api/traders/performance/{model_type}")


@router.get("/traders/signals/recent/{model_type}")
async def traders_recent_signals(model_type: str, actor: CurrentUser, db: DataServiceClient = Depends(get_data_service)):
    await _require(db, actor, "trading.view")
    return await _proxy("GET", f"/api/traders/signals/recent/{model_type}")


@router.get("/traders/mode")
async def traders_mode(actor: CurrentUser, db: DataServiceClient = Depends(get_data_service)):
    """Current trading mode (SCALPING/SWING)."""
    await _require(db, actor, "trading.view")
    return await _proxy("GET", "/api/traders/mode")


@router.post("/traders/mode/switch", dependencies=[rate_limit_scope("ml")])
async def traders_mode_switch(
    request: Request,
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
):
    await _require(db, actor, "trading.settings")
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    return await _proxy("POST", "/api/traders/mode/switch", body=body)


@router.post("/traders/retrain/force", dependencies=[rate_limit_scope("ml")])
async def traders_retrain_force(
    request: Request,
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
):
    await _require(db, actor, "trading.settings")
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    return await _proxy("POST", "/api/traders/retrain/force", body=body)


@router.get("/traders/dynamic-params/{symbol}")
async def traders_dynamic_params(symbol: str, actor: CurrentUser, db: DataServiceClient = Depends(get_data_service)):
    await _require(db, actor, "trading.view")
    return await _proxy("GET", f"/api/traders/dynamic-params/{symbol}")


@router.get("/traders/autonomous/status")
async def traders_autonomous_status(actor: CurrentUser, db: DataServiceClient = Depends(get_data_service)):
    """Autonomous ML pipeline status."""
    await _require(db, actor, "trading.view")
    return await _proxy("GET", "/api/traders/autonomous/status")


@router.post("/traders/autonomous/toggle", dependencies=[rate_limit_scope("ml")])
async def traders_autonomous_toggle(
    request: Request,
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
):
    """Start/stop autonomous ML pipeline."""
    await _require(db, actor, "trading.execute")
    params = dict(request.query_params)
    return await _proxy("POST", "/api/traders/autonomous/toggle", params=params)


@router.get("/retrain/status")
async def retrain_status(actor: CurrentUser, db: DataServiceClient = Depends(get_data_service)):
    """Auto-retrain status: sample count, last run, next trigger."""
    await _require(db, actor, "trading.view")
    return await _proxy("GET", "/api/ml/retrain/status")


@router.post("/train", dependencies=[rate_limit_scope("ml")])
async def train_ensemble(
    request: Request,
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
):
    """Trigger walk-forward ensemble training."""
    await _require(db, actor, "trading.settings")
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    return await _proxy("POST", "/api/ml/train", body=body)
