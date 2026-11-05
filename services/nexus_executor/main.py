"""
Nexus Executor — FastAPI service (port 8007).

Provides REST endpoints for order execution, position management, and
a background Redis Stream consumer that processes approved risk decisions.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import math
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from shared.config_loader import ConfigLoader
from shared.constants import RedisStream, ServiceName, SUPPORTED_TIMEFRAMES
from shared.events import (
    OrderEvent,
    PositionUpdateEvent,
    TradeCloseEvent,
    parse_event,
)
from shared.asset_specs import price_to_pips
from shared.nexus_trades import (
    normalize_nexus_comment,
    partition_positions,
    strategy_from_comment,
)
from shared.redis_client import RedisClient
from shared.safety import GuardCode, evaluate_executor_guard, live_mode_enabled, record_guard_decision, trading_mode
from shared.security_headers import SecurityHeadersMiddleware

from .broker_adapter import (
    AccountInfo,
    BrokerAdapter,
    OrderRequest,
    OrderResponse,
    OrderSide,
    OrderStatus,
    OrderType,
)
from .ccxt_executor import CCXTExecutor
from .ea_queue import mirror_close, mirror_modify, mirror_open
from .ibkr_executor import IBKRExecutor
from .mt5_executor import MT5Executor
from .paper_executor import PaperExecutor
from .smart_routing import SmartRouter

from shared import setup_logger as _setup_logger
_setup_logger("nexus-executor")
log = structlog.get_logger(__name__)

# ── Globals ───────────────────────────────────────────────────────────────────

redis = RedisClient()
config = ConfigLoader()
smart_router = SmartRouter()

SERVICE_NAME = os.getenv("NEXUS_SERVICE_NAME", ServiceName.EXECUTOR)
SERVICE_PORT = int(os.getenv("NEXUS_SERVICE_PORT", "9007"))
DEFAULT_BROKER = os.getenv("NEXUS_DEFAULT_BROKER", os.getenv("DEFAULT_BROKER", "mt5"))
CONSUMER_GROUP = "nexus-executor-group"
CONSUMER_NAME = "nexus-executor-1"
DEDUP_TTL_SEC = int(os.getenv("NEXUS_ORDER_DEDUP_TTL_SEC", "60"))

# Approvals minted by central risk expire in ~30s; refuse to execute when the
# remaining signed lifetime is below this margin so broker latency can never
# push a fill past the approved expiry.
APPROVAL_MIN_TTL_SEC = float(os.getenv("NEXUS_RISK_APPROVAL_MIN_TTL_SEC", "3"))
# A proposal is claimed atomically before the broker call; the claim outlives
# any redelivery window so an uncertain fill can never be re-sent.
PROPOSAL_CLAIM_TTL_SEC = int(os.getenv("NEXUS_PROPOSAL_CLAIM_TTL_SEC", "900"))


def _ensure_approval_signing_secret() -> str:
    """Effective approval-verification key — migration-safe read.

    Prefers the dedicated NEXUS_RISK_APPROVAL_SECRET distributed only to
    nexus-risk (sign) and nexus-executor (verify). When it is unset (ad-hoc
    or manual start; run.py and preflight refuse to boot without it) fall back
    once to the legacy NEXUS_INTERNAL_API_SECRET so an in-flight upgrade keeps
    verifying. Verification fails closed when neither key is configured.
    """
    dedicated = os.getenv("NEXUS_RISK_APPROVAL_SECRET", "").strip()
    if dedicated:
        return dedicated
    legacy = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
    if legacy:
        os.environ["NEXUS_RISK_APPROVAL_SECRET"] = legacy
        log.warning(
            "executor.approval_secret.legacy_fallback_active",
            msg=(
                "NEXUS_RISK_APPROVAL_SECRET is unset; approval verification is "
                "falling back to the shared internal secret. Configure the "
                "dedicated approval key before live trading."
            ),
        )
    return os.getenv("NEXUS_RISK_APPROVAL_SECRET", "").strip()


# ── Order Deduplication ───────────────────────────────────────────────────────

async def _mark_order_executed(symbol: str, side: str) -> None:
    """Record that an order was just placed so the other execution path skips it."""
    key = f"nexus:recent_orders:{symbol.upper()}:{side.upper()}"
    await redis.r.set(key, "1", ex=DEDUP_TTL_SEC)


async def _fetch_last_price(symbol: str, side: str) -> float:
    """Best-effort last price when a position vanishes without a fill quote."""
    import httpx

    data_url = os.getenv("NEXUS_DATA_URL", "http://127.0.0.1:9001")
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                f"{data_url}/api/data/ticks/{symbol}",
                params={"count": 1, "source": "cache"},
            )
            if resp.status_code == 200:
                ticks = resp.json()
                if ticks:
                    t = ticks[0]
                    return float(t.get("bid" if side == "BUY" else "ask", 0) or t.get("last", 0))
    except Exception:
        pass
    return 0.0


async def _is_duplicate_order(symbol: str, side: str) -> bool:
    """Return True if this symbol+direction was already executed recently."""
    key = f"nexus:recent_orders:{symbol.upper()}:{side.upper()}"
    return await redis.r.exists(key) > 0


# ── Anti-stacking: one signal = one open position per symbol+direction ───────
# The 60s dedup above only stops bursts; without this check the system can
# re-add to the same bet every TTL window (June 9-11: clusters of 6-7
# identical positions). Capped at the broker level so EVERY execution path
# (REST, stream consumer, agents) is covered.

MAX_PER_DIRECTION = int(os.getenv("NEXUS_MAX_PER_DIRECTION", "1"))
TRADE_META_TTL_SEC = int(os.getenv("NEXUS_TRADE_META_TTL_SEC", str(7 * 24 * 3600)))


def _symbol_names(symbol: str) -> set[str]:
    """All spellings of a symbol: logical + broker alias (MT5_SYMBOL_ALIASES)."""
    logical = symbol.upper().replace("/", "")
    names = {logical}
    for part in os.getenv("MT5_SYMBOL_ALIASES", "").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        k = key.strip().upper().replace("/", "")
        v = value.strip().upper()
        if logical in (k, v):
            names.update({k, v})
    return names


async def _open_same_direction_count(symbol: str, side: str) -> int:
    """Count open Nexus positions on this symbol+direction (alias-aware)."""
    names = _symbol_names(symbol)
    broker = await _get_broker()
    positions = await broker.get_positions()
    nexus_pos, _ = partition_positions(positions)
    return sum(
        1
        for p in nexus_pos
        if str(p.get("symbol", "")).upper() in names
        and str(p.get("side", "")).upper() == side.upper()
    )


async def _stacking_blocked(symbol: str, side: str) -> bool:
    """True when MAX_PER_DIRECTION Nexus positions already exist same-direction.

    Fails closed if the broker position snapshot is unavailable. Redis dedup
    does not establish that an exposure is absent.
    """
    try:
        return await _open_same_direction_count(symbol, side) >= MAX_PER_DIRECTION
    except Exception:
        log.exception("executor.stacking_check_failed", symbol=symbol, side=side)
        return True


# ── Account-state fail-closed precondition ───────────────────────────────────

class AccountStateUnavailableError(RuntimeError):
    """Authoritative broker account snapshot missing/invalid — reject exposure."""


async def _require_account_snapshot() -> AccountInfo:
    """Fetch the live account snapshot; raise when it cannot authorize exposure.

    A zero/NaN balance or equity (every adapter returns an empty AccountInfo
    on failure) never authorizes a new order — no silent fall back to a
    last-known or zero balance.
    """
    broker = await _get_broker()
    account = await broker.get_account_info()
    balance = float(getattr(account, "balance", 0) or 0)
    equity = float(getattr(account, "equity", 0) or 0)
    margin = float(getattr(account, "margin", 0) or 0)
    free_margin = float(getattr(account, "free_margin", 0) or 0)
    if not math.isfinite(balance) or not math.isfinite(equity) or equity <= 0:
        raise AccountStateUnavailableError(
            "broker account snapshot unavailable or invalid (balance/equity)"
        )
    if margin > 0 and (not math.isfinite(free_margin) or free_margin <= 0):
        raise AccountStateUnavailableError(
            "broker free margin unavailable or exhausted"
        )
    return account


async def _claim_proposal_once(proposal_id: str) -> bool:
    """True when this proposal has not been claimed for execution yet.

    Claimed atomically before the broker call so a redelivered or duplicated
    approval can never place a second order while the first outcome is
    uncertain. Redis unavailability falls through (the guard has already
    failed closed on safety state) and the symbol+side dedup remains as
    defense in depth.
    """
    if not proposal_id:
        return True
    try:
        return bool(await redis.r.set(
            f"nexus:executor:proposal_claim:{proposal_id}",
            "1",
            ex=PROPOSAL_CLAIM_TTL_SEC,
            nx=True,
        ))
    except Exception:
        log.warning(
            "executor.proposal_claim_unavailable",
            proposal_id=proposal_id,
            exc_info=True,
        )
        return True


def _approval_expiry_within_margin(expires_at: Any) -> bool:
    """True when the signed approval is missing/too close to its expiry."""
    try:
        expiry = int(expires_at)
    except (TypeError, ValueError):
        return True  # malformed expiry fails closed
    return expiry - time.time() < APPROVAL_MIN_TTL_SEC


async def _enforce_fill_bounds(
    broker: BrokerAdapter,
    result: OrderResponse,
    *,
    symbol: str,
    approved_size: float,
    reference_price: float,
    slippage: int,
) -> str:
    """Fail closed when a fill breaks the signed approval bounds.

    Filled size ABOVE the risk-approved lots, or a fill whose price slipped
    beyond the signed slippage bound, is flattened immediately; if the
    flatten fails, the global kill switch is armed. Fills BELOW the approved
    size are accepted (reduced exposure) and logged.
    """
    if not result.is_success():
        return ""
    violations: list[str] = []
    filled = float(result.size or 0)
    if math.isfinite(filled) and approved_size > 0 and filled > approved_size + 1e-9:
        violations.append(f"filled size {filled} exceeds risk-approved {approved_size}")
    fill_price = float(result.fill_price or 0)
    if reference_price > 0 and fill_price > 0:
        deviation_pips = abs(price_to_pips(symbol, fill_price - reference_price))
        if math.isfinite(deviation_pips) and deviation_pips > float(slippage):
            violations.append(
                f"fill slippage {deviation_pips:.2f} pips exceeds approved {slippage}"
            )
    if math.isfinite(filled) and approved_size > 0 and 0 < filled < approved_size - 1e-9:
        log.warning(
            "executor.order.partial_fill_below_approved",
            order_id=result.order_id,
            symbol=symbol,
            filled=filled,
            approved=approved_size,
        )
    if not violations:
        return ""
    reason = "; ".join(violations)
    log.critical(
        "executor.fill_bounds_violation",
        order_id=result.order_id,
        symbol=symbol,
        reason=reason,
    )
    close_ok = False
    try:
        close_result = await broker.close_position(result.order_id)
        close_ok = bool(close_result.is_success())
    except Exception:
        log.exception(
            "executor.fill_bounds_violation.close_failed",
            order_id=result.order_id,
        )
    if not close_ok:
        try:
            await redis.cache_set(
                "system:kill_switch",
                {
                    "reason": "executor_fill_bounds_violation",
                    "order_id": result.order_id,
                    "symbol": symbol,
                },
                ttl_sec=1800,
            )
        except Exception:
            log.exception(
                "executor.fill_bounds_violation.kill_switch_failed",
                order_id=result.order_id,
            )
    return reason


# ── Last-line lot cap at the broker gateway ──────────────────────────────────
# The risk service sizes its own proposals, but manual/dashboard orders and any
# future path land here with an arbitrary ``size`` (a 1.0-lot order slipped
# through on June 10 and lost $410 in one trade). Clamp against the same
# risk_rules.yaml capital caps so no order can exceed them.

def _lot_caps() -> tuple[float, float]:
    """(hard_ceiling_lots, equity_divisor) from risk_rules.yaml → capital."""
    try:
        capital = config._load_yaml("risk_rules.yaml").get("capital", {})
        return (
            float(capital.get("lot_cap_hard_ceiling", 0.50)),
            float(capital.get("lot_cap_equity_divisor", 40_000)),
        )
    except Exception:
        return 0.50, 40_000.0


def _fixed_lots_map() -> dict[str, float]:
    """Per-symbol fixed lot overrides from NEXUS_FIXED_LOTS.

    Format: ``SYMBOL=lots;SYMBOL=lots`` (e.g. ``BTCUSD=0.02``). The
    equity-derived cap is calibrated for gold-sized instruments; a symbol whose
    per-lot risk is much smaller (BTC's M5 ATR is ~$31, so 0.02 lots risks
    <1% of a small account) would otherwise be clamped below its intended size.
    """
    out: dict[str, float] = {}
    for part in os.getenv("NEXUS_FIXED_LOTS", "").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        try:
            out[key.strip().upper().replace("/", "")] = float(value)
        except ValueError:
            continue
    return out


async def _clamp_lot_size(size: float, symbol: str = "") -> float:
    hard_ceiling, divisor = _lot_caps()

    # A per-symbol fixed lot bypasses the equity heuristic as an upper bound,
    # but must never replace or increase the size approved by central risk.
    fixed = _fixed_lots_map().get(symbol.strip().upper().replace("/", "")) if symbol else None
    if fixed is not None:
        lots = max(0.0, min(size, fixed, hard_ceiling))
        if abs(lots - size) > 1e-9:
            log.info("executor.lot_size_fixed", symbol=symbol, requested=size, fixed=lots)
        return lots

    cap = hard_ceiling
    try:
        broker = await _get_broker()
        account = await broker.get_account_info()
        if account.equity > 0:
            cap = min(cap, max(0.01, round(account.equity / divisor, 2)))
    except Exception:
        pass
    if size > cap:
        log.warning("executor.lot_size_clamped", requested=size, cap=cap)
        return cap
    return size


# ── Trade metadata (strategy/conviction/session) for close-time telemetry ────

_strategy_from_comment = strategy_from_comment


async def _current_regime() -> str:
    """Read the live regime from the regime publisher (nexus_ml) as fallback."""
    try:
        raw = await redis.r.get("nexus:regime:current")
        if raw:
            if isinstance(raw, bytes):
                raw = raw.decode()
            return str(json.loads(raw).get("regime", "") or "")
    except Exception:
        pass
    return ""


async def _store_trade_meta(order_id: str, meta: dict[str, Any]) -> None:
    """Persist signal context at order time so close events can be enriched."""
    if not order_id:
        return
    try:
        # Regime at entry is what matters for learning — fall back to the
        # live regime publisher when the order didn't carry one.
        if not meta.get("regime"):
            meta["regime"] = await _current_regime()
        await redis.r.set(
            f"nexus:trade_meta:{order_id}",
            json.dumps(meta, default=str),
            ex=TRADE_META_TTL_SEC,
        )
    except Exception:
        log.exception("executor.trade_meta_store_failed", order_id=order_id)


async def _save_entry_ctx(
    order_id: str,
    symbol: str,
    side: str,
    fill_price: float,
    sl: float | None,
    tp: float | None,
    timeframe: str | None = None,
) -> None:
    """Snapshot only an explicitly identified timeframe for outcome training."""
    selected_timeframe = str(timeframe or "").strip().upper()
    if not order_id or selected_timeframe not in SUPPORTED_TIMEFRAMES:
        return
    try:
        feat_raw = await redis.r.get(f"nexus:features:{symbol.upper()}:{selected_timeframe}")
        if not feat_raw:
            return
        feat_data = json.loads(feat_raw) if isinstance(feat_raw, (str, bytes)) else {}
        declared_timeframe = feat_data.get("timeframe") if isinstance(feat_data, dict) else None
        if declared_timeframe and str(declared_timeframe).strip().upper() != selected_timeframe:
            log.warning(
                "executor.entry_ctx_timeframe_mismatch",
                symbol=symbol,
                requested_timeframe=selected_timeframe,
                cached_timeframe=declared_timeframe,
            )
            return
        features = feat_data.get("features", feat_data) if isinstance(feat_data, dict) else {}
        ctx = {
            "features": features,
            "symbol": symbol,
            "side": side,
            "entry": fill_price,
            "sl": sl,
            "tp": tp,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "timeframe": selected_timeframe,
        }
        await redis.r.set(
            f"nexus:trade:entry_ctx:{order_id}",
            json.dumps(ctx, default=str),
            ex=48 * 3600,
        )
    except Exception:
        log.debug("executor.entry_ctx_save_failed", order_id=order_id)


async def _load_trade_meta(order_id: str) -> dict[str, Any]:
    try:
        raw = await redis.r.get(f"nexus:trade_meta:{order_id}")
        if not raw:
            return {}
        if isinstance(raw, bytes):
            raw = raw.decode()
        return json.loads(raw)
    except Exception:
        return {}


def _planned_rr(entry: float, sl: float, tp: float) -> float:
    """Reward:risk planned at entry; 0 when SL/TP were not set."""
    risk = abs(entry - sl)
    if entry <= 0 or sl <= 0 or tp <= 0 or risk <= 0:
        return 0.0
    return round(abs(tp - entry) / risk, 2)


def _positive_float_or_none(value: Any) -> float | None:
    try:
        v = float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v <= 0:
        return None
    return v


def _derive_sl_tp_from_signal_risk(
    side: str,
    entry: float,
    atr: Any,
    stop_atr: Any,
    target_atr: Any,
    sl: float,
    tp: float,
) -> tuple[float, float]:
    """Derive SL/TP from ATR multiples when the signal carries risk fields.

    Applies only when ``atr > 0`` and the corresponding multiple is a positive
    number: SL = entry −/+ atr×stop_atr, TP = entry ∓ atr×target_atr (BUY
    places SL below/TP above, SELL inverts). When a multiple is None (or
    atr/entry missing or ≤ 0) that component keeps the caller's value — no
    plain-ATR default multipliers are applied on this path because none are
    documented here. With all risk fields None the caller's SL/TP pass
    through unchanged (current code path).
    """
    atr_v = _positive_float_or_none(atr)
    if atr_v is None or entry <= 0:
        return sl, tp
    stop_mult = _positive_float_or_none(stop_atr)
    target_mult = _positive_float_or_none(target_atr)
    if stop_mult is None and target_mult is None:
        return sl, tp
    is_buy = str(side).strip().upper() == "BUY"
    if stop_mult is not None:
        sl = entry - atr_v * stop_mult if is_buy else entry + atr_v * stop_mult
    if target_mult is not None:
        tp = entry + atr_v * target_mult if is_buy else entry - atr_v * target_mult
    return sl, tp


_broker: BrokerAdapter | None = None
_broker_connected = False


# ── Broker Factory ────────────────────────────────────────────────────────────

def _create_broker(broker_type: str) -> BrokerAdapter:
    if broker_type == "paper":
        return PaperExecutor()
    if broker_type == "mt5":
        return MT5Executor()
    elif broker_type == "ibkr":
        return IBKRExecutor()
    elif broker_type in ("ccxt", "binance", "bybit", "okx"):
        exchange_id = broker_type if broker_type != "ccxt" else "binance"
        return CCXTExecutor(exchange_id=exchange_id)
    else:
        log.warning("executor.unknown_broker", broker=broker_type, fallback="mt5")
        return MT5Executor()


async def _get_broker() -> BrokerAdapter:
    global _broker, _broker_connected
    effective_broker = DEFAULT_BROKER if live_mode_enabled() else "paper"
    if _broker is None:
        _broker = _create_broker(effective_broker)
    if not _broker_connected:
        try:
            _broker_connected = await _broker.connect()
            log.info("executor.broker_connected", broker=effective_broker)
        except Exception as exc:
            log.error("executor.broker_connect_failed", error=str(exc))
    return _broker


# ── Request / Response Models ─────────────────────────────────────────────────

class SendOrderRequest(BaseModel):
    symbol: str
    side: str
    timeframe: str = ""
    order_type: str = "MARKET"
    size: float = 0.01
    price: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    slippage: int = 10
    comment: str = "nexus:manual"
    use_smart_routing: bool = True
    bid: float = 0.0
    ask: float = 0.0
    current_spread: float = 0.0
    # Signal context — persisted at order time so close telemetry is complete.
    strategy: str = ""
    conviction: float = 0.0
    session: str = ""
    atr: float = 0.0
    regime: str = ""
    # Optional signal risk fields — derive ATR-based SL/TP when all present.
    stop_atr: float | None = None
    target_atr: float | None = None
    max_holding_hours: float | None = None
    group_id: str | None = None
    reason: str = ""
    # Mandatory central-risk proof for every new exposure path.
    proposal_id: str = ""
    risk_approval_expires_at: int = 0
    risk_approval_signature: str = ""
    signal_timestamp: float = 0.0
    risk_approved_entry: float = 0.0
    risk_approval_payload: dict[str, Any] = Field(default_factory=dict)


class ModifyPositionRequest(BaseModel):
    sl: float | None = None
    tp: float | None = None


class OrderResponseModel(BaseModel):
    order_id: str = ""
    symbol: str = ""
    side: str = ""
    order_type: str = ""
    requested_price: float = 0.0
    fill_price: float = 0.0
    size: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    status: str = "PENDING"
    error: str = ""
    broker: str = ""
    routing: dict[str, Any] = Field(default_factory=dict)


# ── Background Stream Consumer ────────────────────────────────────────────────

async def _execution_stream_consumer() -> None:
    """Consume approved risk decisions and execute orders."""
    await redis.connect()
    log.info("executor.stream_consumer.started")

    async for delivery in redis.subscribe_deliveries(
        RedisStream.RISK_DECISION,
        CONSUMER_GROUP,
        CONSUMER_NAME,
    ):
        event = delivery.event
        try:
            decision = getattr(event, "decision", "")
            if decision != "APPROVE":
                log.debug("executor.skipping_rejected", decision=decision)
                await delivery.ack()
                continue

            # Idempotency: claim the delivery before any broker-affecting
            # work so a redelivered APPROVE can never double-place an order
            # while the first outcome is uncertain. Redis unavailability
            # falls through; the proposal claim below still guards the send.
            _message_id = str(getattr(delivery, "message_id", "") or "")
            if _message_id:
                try:
                    first_delivery = await redis.mark_processed(
                        RedisStream.RISK_DECISION, CONSUMER_GROUP, _message_id,
                    )
                except Exception:
                    log.debug(
                        "executor.stream.idem_claim_failed",
                        message_id=_message_id,
                        exc_info=True,
                    )
                    first_delivery = True
                if not first_delivery:
                    log.info(
                        "executor.stream_consumer.duplicate_delivery_skipped",
                        message_id=_message_id,
                    )
                    await delivery.ack()
                    continue

            event_data = event.data if isinstance(event.data, dict) else {}
            symbol = str(event_data.get("symbol", getattr(event, "symbol", "")) or "").strip().upper()
            side = str(event_data.get("side", event_data.get("direction", "BUY")) or "").strip().upper()
            size = float(getattr(event, "approved_size", 0.01))
            entry = float(event_data.get("entry", event_data.get("price", 0)) or 0)
            sl = float(event_data.get("sl", 0) or 0)
            tp = float(event_data.get("tp", event_data.get("tp1", 0)) or 0)
            # Optional signal risk fields: derive ATR-based SL/TP when the
            # decision carries atr/stop_atr/target_atr. Absent fields → the
            # pre-existing sl/tp pass through unchanged. The derived values are
            # bound by the signed-approval guard below, so any drift from what
            # central risk signed fails closed.
            sl, tp = _derive_sl_tp_from_signal_risk(
                side, entry,
                event_data.get("atr"),
                event_data.get("stop_atr"),
                event_data.get("target_atr"),
                sl, tp,
            )
            order_type = str(event_data.get("order_type", "MARKET") or "MARKET").strip().upper()
            execution_price = float(event_data.get("price", entry) or 0)
            slippage = int(event_data.get("slippage", 10) or 10)

            if not symbol or size <= 0:
                log.warning(
                    "executor.skipping_incomplete_decision",
                    symbol=symbol,
                    size=size,
                    has_data=bool(event_data),
                )
                await delivery.ack()
                continue

            # ── Final deterministic guard — shared by ALL execution paths ─
            proposal_id = str(event_data.get("proposal_id", getattr(event, "proposal_id", "")) or "")
            expiry = int(event_data.get("risk_approval_expires_at", 0) or 0)
            signal_timestamp = float(event_data.get("signal_timestamp", 0) or 0)
            execution_payload = {
                "version": 1,
                "proposal_id": proposal_id,
                "expires_at": expiry,
                "symbol": str(symbol),
                "side": str(side),
                "order_type": order_type,
                "entry": entry,
                "price": execution_price,
                "sl": sl,
                "tp": tp,
                "size": size,
                "signal_timestamp": signal_timestamp,
                "slippage": slippage,
            }
            # Expiry safety margin: never start broker work that could fill
            # after the signed approval lifetime (checked at execution time).
            if expiry > 0 and _approval_expiry_within_margin(expiry):
                log.warning(
                    "executor.stream.approval_expiry_within_margin",
                    symbol=symbol,
                    side=side,
                    expires_at=expiry,
                )
                await delivery.ack()
                continue
            guard = await evaluate_executor_guard(
                redis,
                approval_payload=event_data.get("risk_approval_payload"),
                execution_payload=execution_payload,
                approval_signature_value=str(event_data.get("risk_approval_signature", "") or ""),
                require_risk_approval=True,
            )
            await record_guard_decision(
                redis, guard,
                signal_id=str(event_data.get("proposal_id", getattr(event, "proposal_id", "")) or ""),
                requested_action=f"{side} {symbol}",
                executor_guard_version="1.0.0",
            )
            if not guard.allowed:
                log.warning(
                    "executor.stream.final_guard_blocked",
                    symbol=symbol, side=side, code=guard.code.value, reason=guard.reason,
                )
                await delivery.ack()
                continue

            # ── Dedup: skip if this symbol+direction was already executed ─
            if await _is_duplicate_order(symbol, side):
                log.info(
                    "executor.stream_consumer.dedup_skip",
                    symbol=symbol,
                    side=side,
                    reason="order already executed recently via REST or other path",
                )
                await delivery.ack()
                continue

            # ── Anti-stacking: never pile onto an already-open direction ──
            if await _stacking_blocked(symbol, side):
                log.info(
                    "executor.stream_consumer.stacking_block",
                    symbol=symbol,
                    side=side,
                    max_per_direction=MAX_PER_DIRECTION,
                )
                await delivery.ack()
                continue

            strategy = str(event_data.get("strategy", event_data.get("source", "risk")))
            comment = normalize_nexus_comment(
                str(event_data.get("comment", "")),
                strategy=strategy,
            )
            clamped_size = await _clamp_lot_size(size, symbol)
            if abs(clamped_size - size) > 1e-9:
                # Post-approval size mutation is rejected, not silently resized:
                # the signed approval binds the exact executed size.
                log.error(
                    "executor.stream.post_approval_size_mutation_blocked",
                    symbol=symbol,
                    side=side,
                    approved_size=size,
                    clamped_size=clamped_size,
                )
                await delivery.ack()
                continue
            size = clamped_size

            if live_mode_enabled():
                try:
                    await _require_account_snapshot()
                except Exception as exc:
                    log.error(
                        "executor.stream.account_state_unavailable",
                        symbol=symbol,
                        side=side,
                        error=str(exc),
                    )
                    await delivery.ack()
                    continue

            if not await _claim_proposal_once(proposal_id):
                log.warning(
                    "executor.stream.duplicate_proposal_claim",
                    symbol=symbol,
                    side=side,
                    proposal_id=proposal_id,
                )
                await delivery.ack()
                continue

            order_req = OrderRequest(
                symbol=symbol,
                side=OrderSide.BUY if side.upper() == "BUY" else OrderSide.SELL,
                order_type=OrderType(order_type),
                size=size,
                price=execution_price,
                sl=sl,
                tp=tp,
                slippage=slippage,
                comment=comment,
            )

            broker = await _get_broker()
            result = await broker.send_order(order_req)

            if result.is_success():
                fill_violation = await _enforce_fill_bounds(
                    broker,
                    result,
                    symbol=symbol,
                    approved_size=size,
                    reference_price=execution_price if execution_price > 0 else entry,
                    slippage=slippage,
                )
                if fill_violation:
                    log.error(
                        "executor.stream.fill_bounds_violation_blocked",
                        symbol=symbol,
                        side=side,
                        order_id=result.order_id,
                        error=fill_violation,
                    )
                    await delivery.ack()
                    continue
                await _mark_order_executed(symbol, side)
                await _store_trade_meta(result.order_id, {
                    "strategy": _strategy_from_comment(comment) or strategy,
                    "conviction": float(event_data.get("conviction", 0) or 0),
                    "session": str(event_data.get("session", "") or ""),
                    "atr": float(event_data.get("atr", 0) or 0),
                    "regime": str(event_data.get("regime", "") or ""),
                    "entry": result.fill_price,
                    "sl": sl,
                    "tp": tp,
                    "size": result.size,
                    "rr_planned": _planned_rr(result.fill_price, sl, tp),
                    "comment": comment,
                })
                await _save_entry_ctx(
                    result.order_id, symbol, side, result.fill_price, sl, tp,
                    timeframe=str(event_data.get("timeframe", "") or ""),
                )

            order_event = OrderEvent(
                source=SERVICE_NAME,
                correlation_id=event.correlation_id,
                order_id=result.order_id,
                symbol=result.symbol,
                side=result.side,
                order_type=result.order_type,
                price=result.fill_price,
                size=result.size,
                status=result.status.value,
            )
            await redis.publish_event(RedisStream.ORDER_STREAM, order_event)

            if result.is_success():
                pos_event = PositionUpdateEvent(
                    source=SERVICE_NAME,
                    correlation_id=event.correlation_id,
                    position_id=result.order_id,
                    symbol=result.symbol,
                    current_price=result.fill_price,
                    status="open",
                )
                await redis.publish_event(RedisStream.POSITION_UPDATE, pos_event)

            await delivery.ack()

        except Exception:
            log.exception("executor.stream_consumer.error")


# ── Position Monitor (detect SL/TP closes by broker) ─────────────────────────

_tracked_positions: dict[str, dict[str, Any]] = {}

POSITION_POLL_SEC = int(os.getenv("NEXUS_POSITION_POLL_SEC", "5"))


async def _position_monitor() -> None:
    """Poll broker positions and detect when a position disappears (SL/TP hit).

    MT5 (and most brokers) close positions server-side when SL/TP is reached.
    The position simply vanishes from ``get_positions()``.  This monitor
    detects the removal and publishes a ``TradeCloseEvent`` so the data
    pipeline can persist the trade to history and the dashboard shows it.
    """
    await asyncio.sleep(8)
    log.info("executor.position_monitor.started", poll_sec=POSITION_POLL_SEC)

    while True:
        try:
            broker = await _get_broker()
            live_positions = await broker.get_positions()
            live_ids = {str(p["id"]) for p in live_positions}

            for pid, tracked in list(_tracked_positions.items()):
                if pid not in live_ids:
                    log.info(
                        "executor.position_monitor.closed_detected",
                        position_id=pid,
                        symbol=tracked.get("symbol", ""),
                    )
                    entry_price = float(tracked.get("entry_price", 0))
                    pnl_usd = float(tracked.get("pnl_usd", 0))
                    side = tracked.get("side", "BUY")
                    symbol = tracked.get("symbol", "")

                    exit_price = float(tracked.get("current_price", 0) or tracked.get("exit_price", 0))
                    if exit_price <= 0:
                        exit_price = await _fetch_last_price(symbol, side)

                    pnl_pips = 0.0
                    if entry_price > 0 and exit_price > 0:
                        diff = exit_price - entry_price
                        if side == "SELL":
                            diff = -diff
                        pnl_pips = round(price_to_pips(symbol, diff), 1)

                    meta = await _load_trade_meta(pid)
                    comment = normalize_nexus_comment(str(tracked.get("comment", "")))
                    close_event = TradeCloseEvent(
                        source=SERVICE_NAME,
                        trade_id=pid,
                        symbol=symbol,
                        side=side,
                        entry_price=entry_price,
                        exit_price=exit_price,
                        pnl_pips=pnl_pips,
                        pnl_usd=pnl_usd,
                        rr_ratio=float(meta.get("rr_planned", 0) or 0),
                        reason="sl_tp_hit",
                        opened_at=str(tracked.get("opened_at", "")),
                        session=str(meta.get("session") or tracked.get("session", "")),
                        conviction=float(
                            meta.get("conviction") or tracked.get("conviction", 0) or 0
                        ),
                        size=float(tracked.get("size", 0)),
                        atr=float(meta.get("atr", 0) or 0),
                        regime=str(meta.get("regime", "") or ""),
                        data={
                            "source": comment,
                            "strategy": str(
                                meta.get("strategy") or _strategy_from_comment(comment)
                            ),
                        },
                    )
                    await redis.publish_event(RedisStream.TRADE_CLOSE, close_event)
                    del _tracked_positions[pid]

            for p in live_positions:
                _tracked_positions[str(p["id"])] = p

            # ── Trailing SL ──────────────────────────────────────────────
            # Move SL to breakeven once profit >= 1.5× SL distance.
            # Trail further once profit >= 2.5× SL distance.
            for p in live_positions:
                try:
                    pid = str(p["id"])
                    side = str(p.get("side", "BUY"))
                    entry_price = float(p.get("entry_price", 0) or 0)
                    current_price = float(p.get("current_price", 0) or 0)
                    current_sl = float(p.get("sl", 0) or 0)

                    if entry_price <= 0 or current_price <= 0 or current_sl <= 0:
                        continue

                    sl_dist = abs(entry_price - current_sl)
                    if sl_dist < 1e-6:
                        continue

                    new_sl: float | None = None

                    if side == "BUY":
                        profit_dist = current_price - entry_price
                        if profit_dist >= sl_dist * 2.5:
                            # Trail: keep SL at current_price minus half the original SL distance
                            trail = current_price - sl_dist * 0.5
                            if trail > current_sl + 1e-6:
                                new_sl = round(trail, 5)
                        elif profit_dist >= sl_dist * 1.5:
                            # Breakeven: move SL just above entry
                            be = entry_price + sl_dist * 0.1
                            if be > current_sl + 1e-6:
                                new_sl = round(be, 5)
                    else:  # SELL
                        profit_dist = entry_price - current_price
                        if profit_dist >= sl_dist * 2.5:
                            trail = current_price + sl_dist * 0.5
                            if trail < current_sl - 1e-6:
                                new_sl = round(trail, 5)
                        elif profit_dist >= sl_dist * 1.5:
                            be = entry_price - sl_dist * 0.1
                            if be < current_sl - 1e-6:
                                new_sl = round(be, 5)

                    if new_sl is not None:
                        result = await broker.modify_order(pid, sl=new_sl)
                        if result.is_success():
                            log.info(
                                "executor.trailing_sl.updated",
                                pid=pid, side=side,
                                old_sl=current_sl, new_sl=new_sl,
                                profit_dist=round(profit_dist, 5),
                            )
                            _tracked_positions[pid]["sl"] = new_sl
                except Exception:
                    log.debug("executor.trailing_sl.error", exc_info=True)

        except asyncio.CancelledError:
            break
        except Exception:
            log.exception("executor.position_monitor.error")

        await asyncio.sleep(POSITION_POLL_SEC)


# ── RL Lifecycle Action Executor ─────────────────────────────────────────────
# Reads RL recommendations from Redis and executes them on the broker.
# Only acts on non-HOLD actions to avoid excessive broker calls.

LIFECYCLE_POLL_SEC = int(os.getenv("NEXUS_LIFECYCLE_POLL_SEC", "30"))
_executed_lifecycle: dict[str, str] = {}  # ticket → last executed action


async def _lifecycle_action_executor() -> None:
    """Poll Redis for RL lifecycle recommendations and execute on broker."""
    await asyncio.sleep(15)  # let position monitor start first
    log.info("executor.lifecycle.started", poll_sec=LIFECYCLE_POLL_SEC)

    while True:
        try:
            # Only run if kill switch is off
            kill_switch = await redis.cache_get("system:kill_switch")
            if kill_switch:
                await asyncio.sleep(LIFECYCLE_POLL_SEC)
                continue

            raw = await redis.r.get("nexus:rl:lifecycle:all")
            if not raw:
                await asyncio.sleep(LIFECYCLE_POLL_SEC)
                continue

            import json as _json
            actions = _json.loads(raw)
            broker = await _get_broker()

            for action_data in actions:
                try:
                    ticket = str(action_data.get("ticket", ""))
                    action = str(action_data.get("action", "HOLD"))
                    confidence = float(action_data.get("confidence", 0.0))

                    # Skip HOLD or low-confidence
                    if action == "HOLD" or confidence < 0.55:
                        continue

                    # Skip if we already acted on this ticket with this action
                    prev = _executed_lifecycle.get(ticket)
                    if prev == action:
                        continue

                    symbol = str(action_data.get("symbol", ""))
                    side = str(action_data.get("side", "BUY"))
                    entry_price = float(action_data.get("entry_price", 0.0))
                    current_price = float(action_data.get("current_price", entry_price))
                    lot_size = float(action_data.get("lot_size", 0.01))

                    if action == "CLOSE_NOW":
                        result = await broker.close_position(ticket)
                        if result.is_success():
                            log.info("executor.lifecycle.close_now",
                                     ticket=ticket, symbol=symbol, confidence=confidence)
                            _executed_lifecycle[ticket] = action
                        else:
                            log.warning("executor.lifecycle.close_now_failed",
                                        ticket=ticket, error=result.error)

                    elif action == "MOVE_SL_BREAKEVEN":
                        # Set SL just at entry price (+10% of SL distance on favorable side)
                        pip_value = 0.01 if "XAU" in symbol else 0.0001
                        sl_buffer = 5 * pip_value  # 5 pip buffer past entry
                        new_sl = (entry_price + sl_buffer) if side == "BUY" else (entry_price - sl_buffer)
                        result = await broker.modify_order(ticket, sl=round(new_sl, 5))
                        if result.is_success():
                            log.info("executor.lifecycle.breakeven",
                                     ticket=ticket, new_sl=new_sl, confidence=confidence)
                            _executed_lifecycle[ticket] = action

                    elif action == "TAKE_PARTIAL_50PCT":
                        partial_size = round(lot_size * 0.5, 2)
                        if partial_size >= 0.01:
                            result = await broker.close_position(ticket, size=partial_size)
                            if result.is_success():
                                log.info("executor.lifecycle.partial_50",
                                         ticket=ticket, partial_lots=partial_size, confidence=confidence)
                                _executed_lifecycle[ticket] = action

                    elif action == "TRAIL_SL_1ATR":
                        # Get ATR from Redis features
                        try:
                            feat_raw = await redis.r.get(f"nexus:features:{symbol}:M5")
                            atr = 5.0
                            if feat_raw:
                                feat_data = _json.loads(feat_raw)
                                feats = feat_data.get("features", feat_data)
                                atr = float(feats.get("atr_14", feats.get("atr", 5.0)))
                            # Trail 1 ATR from current price
                            pip_value = 0.01 if "XAU" in symbol else 0.0001
                            trail_sl = (current_price - atr) if side == "BUY" else (current_price + atr)
                            result = await broker.modify_order(ticket, sl=round(trail_sl, 5))
                            if result.is_success():
                                log.info("executor.lifecycle.trail_1atr",
                                         ticket=ticket, trail_sl=trail_sl, atr=atr, confidence=confidence)
                                _executed_lifecycle[ticket] = action
                        except Exception:
                            log.debug("executor.lifecycle.trail_atr_error", ticket=ticket, exc_info=True)

                except Exception:
                    log.debug("executor.lifecycle.action_error", exc_info=True)

        except asyncio.CancelledError:
            break
        except Exception:
            log.exception("executor.lifecycle.error")

        await asyncio.sleep(LIFECYCLE_POLL_SEC)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Migration-safe approval-verification secret (dedicated key, legacy fallback).
    _ensure_approval_signing_secret()
    await redis.connect()
    log.info(
        "executor.service.started",
        port=SERVICE_PORT,
        broker=DEFAULT_BROKER if live_mode_enabled() else "paper",
        trading_mode=trading_mode(),
        real_broker_execution_enabled=live_mode_enabled(),
    )
    consumer_task = asyncio.create_task(_execution_stream_consumer())
    monitor_task = asyncio.create_task(_position_monitor())
    lifecycle_task = asyncio.create_task(_lifecycle_action_executor())
    try:
        yield
    finally:
        lifecycle_task.cancel()
        monitor_task.cancel()
        consumer_task.cancel()
        for t in (lifecycle_task, monitor_task, consumer_task):
            try:
                await t
            except asyncio.CancelledError:
                pass
        if _broker:
            await _broker.disconnect()
        await redis.disconnect()
        log.info("executor.service.stopped")


# ── FastAPI App ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Nexus Executor",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(SecurityHeadersMiddleware)


def _verify_internal_service_secret(provided_secret: str | None) -> None:
    internal_secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
    if not internal_secret:
        raise HTTPException(503, "NEXUS_INTERNAL_API_SECRET is not configured")
    if not provided_secret or not hmac.compare_digest(internal_secret, provided_secret):
        raise HTTPException(403, "invalid internal service credential")


@app.get("/health")
async def health():
    redis_ok = await redis.health_check()
    return {
        "service": SERVICE_NAME,
        "status": "healthy" if redis_ok else "degraded",
        "redis": redis_ok,
        "broker": DEFAULT_BROKER if live_mode_enabled() else "paper",
        "trading_mode": trading_mode(),
        "real_broker_execution_enabled": live_mode_enabled(),
        "broker_connected": _broker_connected,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/executor/order", response_model=OrderResponseModel)
async def send_order(
    req: SendOrderRequest,
    x_nexus_internal_secret: str | None = Header(default=None),
):
    _verify_internal_service_secret(x_nexus_internal_secret)
    try:
        symbol = req.symbol.strip().upper()
        side = req.side.strip().upper()
        order_type_name = req.order_type.strip().upper() if req.order_type else "MARKET"
        # Optional signal risk fields: derive ATR-based SL/TP when present.
        # Absent fields → req.sl/req.tp pass through unchanged. The derived
        # values are bound by the signed-approval guard below, so any drift
        # from what central risk signed fails closed.
        entry_ref = req.risk_approved_entry if req.risk_approved_entry > 0 else req.price
        sl_val, tp_val = _derive_sl_tp_from_signal_risk(
            side, entry_ref, req.atr, req.stop_atr, req.target_atr, req.sl, req.tp,
        )
        execution_payload = {
            "version": 1,
            "proposal_id": req.proposal_id,
            "expires_at": req.risk_approval_expires_at,
            "symbol": symbol,
            "side": side,
            "order_type": order_type_name,
            "entry": req.risk_approved_entry,
            "price": req.price,
            "sl": sl_val,
            "tp": tp_val,
            "size": req.size,
            "signal_timestamp": req.signal_timestamp,
            "slippage": req.slippage,
        }
        # Expiry safety margin: never start broker work that could fill after
        # the signed approval lifetime (checked at execution time).
        if (
            req.risk_approval_expires_at > 0
            and _approval_expiry_within_margin(req.risk_approval_expires_at)
        ):
            return OrderResponseModel(
                symbol=symbol, side=side,
                status="GUARD_BLOCKED_RISK_APPROVAL_EXPIRED",
                error=(
                    "Risk approval expires within the execution safety margin; "
                    "request a new risk approval."
                ),
                broker="none",
            )
        guard = await evaluate_executor_guard(
            redis,
            approval_payload=req.risk_approval_payload,
            execution_payload=execution_payload,
            approval_signature_value=req.risk_approval_signature,
            require_risk_approval=True,
        )
        await record_guard_decision(
            redis, guard, signal_id=req.proposal_id,
            requested_action=f"{side} {symbol}",
            executor_guard_version="1.0.0",
        )
        if not guard.allowed:
            log.warning(
                "executor.final_guard_blocked",
                symbol=symbol, side=side, code=guard.code.value, reason=guard.reason,
            )
            return OrderResponseModel(
                symbol=symbol, side=side,
                status=f"GUARD_BLOCKED_{guard.code.value}",
                error=guard.reason_ar,
                broker="none",
            )

        if await _is_duplicate_order(symbol, side):
            log.info(
                "executor.rest.dedup_skip",
                symbol=symbol,
                side=side,
            )
            return OrderResponseModel(
                symbol=symbol,
                side=side,
                status="DEDUP_SKIPPED",
                error="Duplicate order: same symbol+direction executed recently",
            )

        if await _stacking_blocked(symbol, side):
            log.info(
                "executor.rest.stacking_block",
                symbol=symbol,
                side=side,
                max_per_direction=MAX_PER_DIRECTION,
            )
            return OrderResponseModel(
                symbol=symbol,
                side=side,
                status="STACKING_BLOCKED",
                error=(
                    f"Open Nexus position already exists for {symbol} {side} "
                    f"(max {MAX_PER_DIRECTION} per direction)"
                ),
            )

        order_side = OrderSide.BUY if side == "BUY" else OrderSide.SELL
        order_type = OrderType(order_type_name)

        clamped_size = await _clamp_lot_size(req.size, symbol)
        if abs(clamped_size - req.size) > 1e-9:
            # Post-approval size mutation is rejected, not silently resized:
            # the signed approval binds the exact executed size.
            log.error(
                "executor.rest.post_approval_size_mutation_blocked",
                symbol=symbol,
                side=side,
                approved_size=req.size,
                clamped_size=clamped_size,
            )
            return OrderResponseModel(
                symbol=symbol,
                side=side,
                status="GUARD_BLOCKED_RISK_APPROVAL_MISSING",
                error=(
                    "Executor lot cap would change the risk-approved size; "
                    "request a new risk approval for the executable size."
                ),
                broker="none",
            )

        if live_mode_enabled():
            try:
                await _require_account_snapshot()
            except Exception as exc:
                log.error(
                    "executor.rest.account_state_unavailable",
                    symbol=symbol,
                    side=side,
                    error=str(exc),
                )
                return OrderResponseModel(
                    symbol=symbol,
                    side=side,
                    status="ACCOUNT_STATE_UNAVAILABLE",
                    error=(
                        "Authoritative broker account snapshot unavailable; "
                        "order rejected (fail-closed)."
                    ),
                    broker="none",
                )

        order = OrderRequest(
            symbol=symbol,
            side=order_side,
            order_type=order_type,
            size=clamped_size,
            price=req.price,
            sl=sl_val,
            tp=tp_val,
            slippage=req.slippage,
            comment=normalize_nexus_comment(req.comment, strategy="executor"),
        )

        routing_info: dict[str, Any] = {}
        if req.use_smart_routing and req.bid > 0 and req.ask > 0:
            decision = smart_router.route_order(
                order,
                bid=req.bid,
                ask=req.ask,
                current_spread=req.current_spread,
            )
            if (
                decision.order_type != order.order_type
                or (decision.adjusted and decision.price != order.price)
            ):
                log.warning(
                    "executor.smart_route_changed_approved_terms",
                    symbol=symbol,
                    approved_order_type=order.order_type.value,
                    proposed_order_type=decision.order_type.value,
                )
                return OrderResponseModel(
                    symbol=symbol,
                    side=side,
                    status="GUARD_BLOCKED_RISK_APPROVAL_MISSING",
                    error="Smart routing changed risk-approved order terms; request a new risk approval.",
                    broker="none",
                    routing={
                        "reason": decision.reason,
                        "adjusted": decision.adjusted,
                        "liquidity_ok": decision.liquidity_ok,
                    },
                )
            order.order_type = decision.order_type
            if decision.adjusted:
                order.price = decision.price
            routing_info = {
                "order_type": decision.order_type.value,
                "price": decision.price,
                "reason": decision.reason,
                "liquidity_ok": decision.liquidity_ok,
                "adjusted": decision.adjusted,
            }

        if not await _claim_proposal_once(req.proposal_id):
            log.warning(
                "executor.rest.duplicate_proposal_claim",
                symbol=symbol,
                side=side,
                proposal_id=req.proposal_id,
            )
            return OrderResponseModel(
                symbol=symbol,
                side=side,
                status="DUPLICATE_PROPOSAL",
                error=(
                    "Proposal already claimed for execution; a duplicate "
                    "order was blocked (fail-closed)."
                ),
                broker="none",
            )

        broker = await _get_broker()
        result = await broker.send_order(order)

        if result.is_success():
            fill_violation = await _enforce_fill_bounds(
                broker,
                result,
                symbol=symbol,
                approved_size=req.size,
                reference_price=req.price if req.price > 0 else req.risk_approved_entry,
                slippage=req.slippage,
            )
            if fill_violation:
                log.error(
                    "executor.rest.fill_bounds_violation_blocked",
                    symbol=symbol,
                    side=side,
                    order_id=result.order_id,
                    error=fill_violation,
                )
                return OrderResponseModel(
                    order_id=result.order_id,
                    symbol=result.symbol,
                    side=result.side,
                    status="REJECTED_FILL_OUT_OF_BOUNDS",
                    error=fill_violation,
                    broker=result.broker,
                )
            await _mark_order_executed(symbol, side)
            await _store_trade_meta(result.order_id, {
                "strategy": req.strategy or _strategy_from_comment(order.comment),
                "conviction": req.conviction,
                "session": req.session,
                "atr": req.atr,
                "regime": req.regime,
                "entry": result.fill_price,
                "sl": sl_val,
                "tp": tp_val,
                "size": result.size,
                "rr_planned": _planned_rr(result.fill_price, sl_val, tp_val),
                "comment": order.comment,
            })
            await _save_entry_ctx(
                result.order_id, symbol, side, result.fill_price, sl_val, tp_val,
                timeframe=req.timeframe,
            )
            order_event = OrderEvent(
                source=SERVICE_NAME,
                order_id=result.order_id,
                symbol=result.symbol,
                side=result.side,
                order_type=result.order_type,
                price=result.fill_price,
                size=result.size,
                status=result.status.value,
            )
            await redis.publish_event(RedisStream.ORDER_STREAM, order_event)
            # EA bridge (item 4): mirror the executed order to MT5 terminals.
            await mirror_open(
                symbol=result.symbol,
                side=result.side.value if hasattr(result.side, "value") else str(result.side),
                order_type=order.order_type.value,
                size=result.size,
                price=result.fill_price,
                sl=result.sl,
                tp=result.tp,
                slippage=req.slippage,
                comment=order.comment,
            )

        return OrderResponseModel(
            order_id=result.order_id,
            symbol=result.symbol,
            side=result.side,
            order_type=result.order_type,
            requested_price=result.requested_price,
            fill_price=result.fill_price,
            size=result.size,
            sl=result.sl,
            tp=result.tp,
            status=result.status.value,
            error=result.error,
            broker=result.broker,
            routing=routing_info,
        )
    except Exception as exc:
        log.exception("executor.send_order.error")
        raise HTTPException(status_code=500, detail=str(exc))


@app.delete("/api/executor/position/{position_id}")
async def close_position(
    position_id: str,
    size: float | None = None,
    x_nexus_internal_secret: str | None = Header(default=None),
):
    _verify_internal_service_secret(x_nexus_internal_secret)
    if size is not None and (not math.isfinite(size) or size <= 0):
        raise HTTPException(422, "size must be a finite positive number")
    try:
        broker = await _get_broker()
        result = await broker.close_position(position_id, size=size)

        if result.status == OrderStatus.FILLED:
            raw = result.raw_response or {}
            entry_price = float(raw.get("entry_price", result.requested_price) or 0)
            pnl_usd = float(raw.get("pnl_usd", 0) or 0)
            position_side = raw.get("position_side", result.side)
            opened_at = raw.get("opened_at", "")

            sym_upper = result.symbol.upper()
            if "JPY" in sym_upper:
                pip_mult = 100
            elif "XAU" in sym_upper or "XAG" in sym_upper:
                pip_mult = 10
            elif "BTC" in sym_upper or "ETH" in sym_upper:
                pip_mult = 1
            else:
                pip_mult = 10_000
            pnl_pips = 0.0
            if entry_price > 0 and result.fill_price > 0:
                diff = result.fill_price - entry_price
                if position_side == "SELL":
                    diff = -diff
                pnl_pips = round(diff * pip_mult, 1)

            meta = await _load_trade_meta(str(raw.get("ticket", position_id)))
            close_event = TradeCloseEvent(
                source=SERVICE_NAME,
                trade_id=result.order_id,
                symbol=result.symbol,
                side=position_side,
                entry_price=entry_price,
                exit_price=result.fill_price,
                pnl_pips=pnl_pips,
                pnl_usd=pnl_usd,
                rr_ratio=float(meta.get("rr_planned", 0) or 0),
                reason="manual_close",
                opened_at=opened_at,
                session=str(meta.get("session", "") or ""),
                conviction=float(meta.get("conviction", 0) or 0),
                size=result.size,
                atr=float(meta.get("atr", 0) or 0),
                regime=str(meta.get("regime", "") or ""),
                data={
                    "source": str(meta.get("comment", "") or ""),
                    "strategy": str(meta.get("strategy", "") or ""),
                },
            )
            await redis.publish_event(RedisStream.TRADE_CLOSE, close_event)
            # EA bridge (item 4): mirror the close to MT5 terminals.
            await mirror_close(
                symbol=result.symbol,
                side=str(position_side or result.side or ""),
                volume=result.size,
                comment=str(meta.get("comment", "") or ""),
            )

        return {
            "order_id": result.order_id,
            "status": result.status.value,
            "fill_price": result.fill_price,
            "error": result.error,
        }
    except Exception as exc:
        log.exception("executor.close_position.error")
        raise HTTPException(status_code=500, detail=str(exc))


@app.put("/api/executor/position/{position_id}")
async def modify_position(
    position_id: str,
    req: ModifyPositionRequest,
    x_nexus_internal_secret: str | None = Header(default=None),
):
    _verify_internal_service_secret(x_nexus_internal_secret)
    try:
        broker = await _get_broker()
        result = await broker.modify_order(position_id, sl=req.sl, tp=req.tp)
        if result.is_success():
            # EA bridge (item 4): mirror the SL/TP change to MT5 terminals.
            await mirror_modify(
                symbol=result.symbol,
                sl=result.sl if result.sl is not None else (req.sl or 0),
                tp=result.tp if result.tp is not None else (req.tp or 0),
                comment="",
                position_id=position_id,
            )
        return {
            "order_id": result.order_id,
            "status": result.status.value,
            "sl": result.sl,
            "tp": result.tp,
            "error": result.error,
        }
    except Exception as exc:
        log.exception("executor.modify_position.error")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/executor/positions")
async def get_positions(
    nexus_only: bool = False,
    x_nexus_internal_secret: str | None = Header(default=None),
):
    _verify_internal_service_secret(x_nexus_internal_secret)
    try:
        broker = await _get_broker()
        positions = await broker.get_positions()
        nexus_pos, external_pos = partition_positions(positions)
        account = await broker.get_account_info()
        visible = nexus_pos if nexus_only else positions
        return {
            "positions": visible,
            "nexus_positions": nexus_pos,
            "external_positions": external_pos,
            "count": len(visible),
            "nexus_count": len(nexus_pos),
            "external_count": len(external_pos),
            "total_count": len(positions),
            "account": {
                "balance": account.balance,
                "equity": account.equity,
                "margin": account.margin,
                "free_margin": account.free_margin,
                "currency": account.currency,
                "broker": account.broker,
            },
        }
    except Exception as exc:
        log.exception("executor.get_positions.error")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Account / Balance (dashboard) — Redis-independent, never 500 ─────────────

def _paper_default_balance() -> float:
    """Paper starting balance from NEXUS_PAPER_BALANCE (default 10000.0)."""
    try:
        value = float(os.getenv("NEXUS_PAPER_BALANCE", "10000"))
    except (TypeError, ValueError):
        return 10000.0
    if not math.isfinite(value) or value <= 0:
        return 10000.0
    return value


async def _account_payload() -> dict[str, Any]:
    """Balance/status snapshot for the dashboard.

    Paper mode never depends on Redis or a broker connection: it degrades to
    the configured paper default instead of failing. Live mode reports the
    broker snapshot only when it is real and valid; otherwise balance stays
    0.0 (no fabricated live balance).
    """
    mode = trading_mode()
    paper = not live_mode_enabled()
    balance = 0.0
    equity = 0.0
    margin = 0.0
    free_margin = 0.0
    currency = "USD"
    connected = False

    try:
        broker = await _get_broker()
        account = await broker.get_account_info()
        b = float(getattr(account, "balance", 0) or 0)
        e = float(getattr(account, "equity", 0) or 0)
        if math.isfinite(b) and math.isfinite(e) and b > 0 and e > 0:
            balance = b
            equity = e
            margin = float(getattr(account, "margin", 0) or 0)
            free_margin = float(getattr(account, "free_margin", 0) or 0)
            currency = str(getattr(account, "currency", "") or "USD") or "USD"
            connected = True
    except Exception:
        log.warning("executor.account_snapshot_unavailable", exc_info=True)

    if paper:
        if not connected:
            # No Redis/broker dependency — paper default from env/config.
            balance = _paper_default_balance()
            equity = balance
            margin = 0.0
            free_margin = balance
            connected = True
        status = "PAPER_CONNECTED"
    else:
        status = "LIVE_CONNECTED" if connected else "LIVE"

    return {
        "balance": round(balance, 2),
        "equity": round(equity, 2),
        "margin": round(margin, 2),
        "free_margin": round(free_margin, 2),
        "currency": currency,
        "mode": mode,
        "status": status,
        "connected": connected,
        "broker": DEFAULT_BROKER if live_mode_enabled() else "paper",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/account")
async def get_account():
    return await _account_payload()


@app.get("/balance")
async def get_balance():
    return await _account_payload()
