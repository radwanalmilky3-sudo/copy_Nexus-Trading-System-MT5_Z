"""
Config router — read/write system settings, agent configs, and risk rules.

Persistence contract (2026-10-16 audit):
  * ``GET /risk`` proxies the authoritative runtime settings owned by the
    nexus-risk service (``nexus:runtime:settings``). An unreachable risk
    service returns 502/503 instead of stale YAML defaults.
  * ``PUT`` endpoints validate input and keep a display-only in-process
    snapshot for the gateway UI. They do NOT change runtime trading policy,
    are not reloaded by other services, and do NOT persist across restarts.
    Runtime risk knobs live behind ``/api/risk/settings``; process
    trading-mode / auto-trade live behind ``/api/system``. Responses carry
    explicit ``persistence``/``runtime_effective`` markers so clients never
    mistake a display save for a policy sync.
  * Only non-hardcoded legacy risk fields may be updated (e.g.
    ``daily_trade_limit``), and only in the tightening direction. Hardcoded
    safety limits (``max_daily_loss_pct``, ``max_weekly_drawdown_pct``)
    require a code change.
  * ``PUT /settings`` rejects unknown fields with 422 — ``SettingsSchema``
    ignores extras, so accepting them silently would let the dashboard
    believe a runtime key (``trading_mode_type``, ``max_daily_trades``, … —
    owned by ``POST /api/intelligence/settings``) was stored when it was
    discarded. All ``PUT`` handlers validate on a copy so a rejected update
    never corrupts the in-memory snapshot served by ``GET``.
"""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from shared.config_loader import (
    AgentConfigSchema,
    ConfigLoader,
    RiskRulesSchema,
    SettingsSchema,
)

from ..data_client import DataServiceClient
from ..deps import get_config, get_data_service
from ..middleware.auth import CurrentUser
from . import risk as risk_router
from .admin import _require

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/config", tags=["config"])

HARDCODED_RISK_FIELDS = frozenset({
    "max_daily_loss_pct",
    "max_weekly_drawdown_pct",
    "max_open_positions",
})

# Legacy risk rules are intentionally conservative.  This endpoint does not
# write the runtime-settings key; it may only tighten fields owned by the
# legacy risk schema.  The direction matters because some limits are safer
# when lower, while gates/penalties are safer when higher.
ALLOWED_RISK_FIELDS = frozenset({
    "max_risk_per_trade_pct", "max_correlation_exposure", "min_rr_ratio",
    "max_spread_pips", "min_conviction", "position_size_cap_lots",
    "daily_trade_limit", "cooldown_after_loss_sec",
})
TIGHTENING_DIRECTION = {
    "max_risk_per_trade_pct": "lower",
    "max_correlation_exposure": "lower",
    "min_rr_ratio": "higher",
    "max_spread_pips": "lower",
    "min_conviction": "higher",
    "position_size_cap_lots": "lower",
    "daily_trade_limit": "lower",
    "cooldown_after_loss_sec": "higher",
}


# ── Request models ───────────────────────────────────────────────────────────

class UpdateSettingsRequest(BaseModel):
    settings: dict[str, Any]


class UpdateAgentConfigRequest(BaseModel):
    enabled: bool | None = None
    temperature: float | None = None
    parameters: dict[str, Any] | None = None


class UpdateRiskRulesRequest(BaseModel):
    rules: dict[str, Any]


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/settings")
async def get_settings(
    actor: CurrentUser,
    cfg: ConfigLoader = Depends(get_config),
    db: DataServiceClient = Depends(get_data_service),
) -> dict[str, Any]:
    await _require(db, actor, "trading.settings")
    cached = cfg.get("settings")
    if cached:
        return cached
    return cfg.load_settings()


@router.put("/settings")
async def update_settings(
    body: UpdateSettingsRequest,
    actor: CurrentUser,
    cfg: ConfigLoader = Depends(get_config),
    db: DataServiceClient = Depends(get_data_service),
) -> dict[str, Any]:
    await _require(db, actor, "trading.settings")
    # ``SettingsSchema`` ignores extra keys; silently accepting them would
    # let the client believe a value was stored when it was discarded.
    unknown = set(body.settings) - set(SettingsSchema.model_fields)
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Unsupported settings fields: {sorted(unknown)}; runtime trading "
            "knobs belong to POST /api/intelligence/settings (Redis "
            "nexus:runtime:settings)",
        )
    # Copy before merging: mutating the cached snapshot in place would leave
    # invalid values behind when validation below fails.
    current = dict(cfg.get("settings") or cfg.load_settings())
    current.update(body.settings)
    try:
        validated = SettingsSchema(**current)
    except Exception as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))

    dumped = validated.model_dump()
    cfg._cache["settings"] = dumped  # noqa: SLF001
    await logger.ainfo("config.settings.updated", changes=list(body.settings.keys()))
    return {
        **dumped,
        "persistence": "display_only",
        "runtime_effective": False,
        "runtime_sources": {
            "trading_mode": "/api/system/mode",
            "auto_trade_enabled": "/api/system/mode",
        },
        "message": (
            "Validated display snapshot kept in gateway memory only; "
            "trading_mode/auto_trade_enabled follow /api/system/mode."
        ),
    }


@router.get("/agents")
async def get_agent_configs(
    actor: CurrentUser,
    cfg: ConfigLoader = Depends(get_config),
    db: DataServiceClient = Depends(get_data_service),
) -> dict[str, Any]:
    await _require(db, actor, "trading.settings")
    cached = cfg.get("agents")
    if cached:
        return cached
    return cfg.load_agents()


@router.put("/agents/{agent_id}")
async def update_agent_config(
    agent_id: str,
    body: UpdateAgentConfigRequest,
    actor: CurrentUser,
    cfg: ConfigLoader = Depends(get_config),
    db: DataServiceClient = Depends(get_data_service),
) -> dict[str, Any]:
    await _require(db, actor, "trading.settings")
    agents = cfg.get("agents") or cfg.load_agents()
    if agent_id not in agents:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Agent {agent_id} not found")

    current = dict(agents[agent_id])
    updates = body.model_dump(exclude_none=True)
    current.update(updates)

    try:
        validated = AgentConfigSchema(**current)
    except Exception as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))

    agents[agent_id] = validated.model_dump()
    cfg._cache["agents"] = agents  # noqa: SLF001
    await logger.ainfo("config.agent.updated", agent_id=agent_id)
    return {
        **agents[agent_id],
        "persistence": "display_only",
        "runtime_effective": False,
        "message": (
            "Agent display configuration only; agent behavior is driven by "
            "config/agents.yaml at service startup."
        ),
    }


@router.get("/risk")
async def get_risk_rules(
    actor: CurrentUser,
    db: DataServiceClient = Depends(get_data_service),
) -> dict[str, Any]:
    """Authoritative runtime risk settings from the nexus-risk service.

    Replaces the former read of YAML defaults / display cache, which
    misreported the live policy. Unreachable nexus-risk fails closed with
    502/503 instead of serving a stale snapshot.
    """
    await _require(db, actor, "risk.view")
    payload = await risk_router._risk_proxy("GET", "/api/risk/settings")
    if not isinstance(payload, dict):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "nexus-risk returned an invalid runtime settings payload",
        )
    return {
        **payload,
        "source": "nexus-risk:runtime",
        "persistence": "runtime",
        "runtime_effective": True,
    }


@router.put("/risk")
async def update_risk_rules(
    body: UpdateRiskRulesRequest,
    actor: CurrentUser,
    cfg: ConfigLoader = Depends(get_config),
    db: DataServiceClient = Depends(get_data_service),
) -> dict[str, Any]:
    """Tighten-only legacy risk display snapshot (never writes runtime keys).

    Runtime risk policy is owned by nexus-risk; update it via
    ``POST /api/risk/settings``. This endpoint validates, may only tighten
    legacy fields, and keeps an in-memory display snapshot.
    """
    await _require(db, actor, "risk.modify")
    if not body.rules:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "risk rules update cannot be empty")
    # Hardcoded fields are rejected first so the documented 403 actually
    # surfaces (they are intentionally disjoint from ALLOWED_RISK_FIELDS,
    # which would otherwise mask them with a 422).
    forbidden = set(body.rules.keys()) & HARDCODED_RISK_FIELDS
    if forbidden:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Cannot modify hardcoded risk fields: {sorted(forbidden)}",
        )
    unknown = set(body.rules) - ALLOWED_RISK_FIELDS
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unsupported risk fields: {sorted(unknown)}")

    current = cfg.get("risk")
    if not current:
        try:
            current = cfg.load_risk_rules()
        except FileNotFoundError:
            current = RiskRulesSchema().model_dump()

    # Validate on a copy: a field that passes the numeric/direction checks but
    # fails schema coercion (e.g. ``daily_trade_limit: 10.5``) must not leave
    # the live snapshot half-updated.
    current = dict(current)
    for key, proposed in body.rules.items():
        try:
            old = float(current[key])
            new = float(proposed)
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Invalid numeric risk field: {key}") from exc
        direction = TIGHTENING_DIRECTION[key]
        if (direction == "lower" and new > old) or (direction == "higher" and new < old):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Update would loosen risk field: {key}")

    current.update(body.rules)
    try:
        validated = RiskRulesSchema(**current)
    except Exception as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))

    dumped = validated.model_dump()
    cfg._cache["risk"] = dumped  # noqa: SLF001
    await logger.ainfo("config.risk.updated", changes=list(body.rules.keys()))
    return {
        **dumped,
        "persistence": "display_only",
        "runtime_effective": False,
        "runtime_settings_api": "/api/risk/settings",
        "message": (
            "Legacy display snapshot only; runtime risk policy is owned by "
            "nexus-risk (POST /api/risk/settings)."
        ),
    }
