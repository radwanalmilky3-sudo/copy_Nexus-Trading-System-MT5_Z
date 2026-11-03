"""Deterministic in-process paper broker.

This adapter is selected automatically whenever NEXUS_TRADING_MODE is not LIVE.
It never imports or calls MetaTrader5, IBKR, CCXT, or any external broker API.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from .broker_adapter import (
    AccountInfo,
    BrokerAdapter,
    OrderRequest,
    OrderResponse,
    OrderStatus,
)


class PaperExecutor(BrokerAdapter):
    def __init__(self) -> None:
        self._connected = False
        self._positions: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._balance = float(os.getenv("NEXUS_PAPER_BALANCE", "10000"))

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def disconnect(self) -> None:
        self._connected = False

    async def send_order(self, order: OrderRequest) -> OrderResponse:
        async with self._lock:
            oid = f"PAPER-{uuid.uuid4().hex[:12]}"
            fill = float(order.price or 0.0)
            now = datetime.now(timezone.utc)
            self._positions[oid] = {
                "id": oid,
                "ticket": oid,
                "symbol": order.symbol,
                "side": order.side.value,
                "order_type": order.order_type.value,
                "entry_price": fill,
                "current_price": fill,
                "size": order.size,
                "volume": order.size,
                "sl": order.sl,
                "tp": order.tp,
                "comment": order.comment,
                "magic": order.magic,
                "pnl_usd": 0.0,
                "pnl_pips": 0.0,
                "opened_at": now.isoformat(),
                "broker": "paper",
            }
            return OrderResponse(
                order_id=oid,
                symbol=order.symbol,
                side=order.side.value,
                order_type=order.order_type.value,
                requested_price=order.price,
                fill_price=fill,
                size=order.size,
                sl=order.sl,
                tp=order.tp,
                status=OrderStatus.FILLED,
                broker="paper",
                raw_response={"simulated": True},
            )

    async def modify_order(
        self,
        position_id: str,
        *,
        sl: float | None = None,
        tp: float | None = None,
    ) -> OrderResponse:
        async with self._lock:
            p = self._positions.get(str(position_id))
            if not p:
                return OrderResponse(order_id=str(position_id), status=OrderStatus.ERROR, error="paper position not found", broker="paper")
            if sl is not None:
                p["sl"] = float(sl)
            if tp is not None:
                p["tp"] = float(tp)
            return OrderResponse(
                order_id=str(position_id), symbol=p["symbol"], side=p["side"],
                order_type=p["order_type"], requested_price=p["entry_price"],
                fill_price=p["current_price"], size=p["size"], sl=p["sl"], tp=p["tp"],
                status=OrderStatus.FILLED, broker="paper", raw_response={"simulated": True},
            )

    async def close_position(
        self,
        position_id: str,
        *,
        size: float | None = None,
    ) -> OrderResponse:
        async with self._lock:
            p = self._positions.get(str(position_id))
            if not p:
                return OrderResponse(order_id=str(position_id), status=OrderStatus.ERROR, error="paper position not found", broker="paper")
            open_size = float(p["size"])
            close_size = open_size if size is None else float(size)
            if not close_size > 0 or close_size > float(p["size"]):
                return OrderResponse(
                    order_id=str(position_id), status=OrderStatus.ERROR,
                    error="close size must be positive and no greater than the open position",
                    broker="paper",
                )
            if close_size == open_size:
                self._positions.pop(str(position_id), None)
                close_status = OrderStatus.FILLED
            else:
                p["size"] = float(p["size"]) - close_size
                p["volume"] = p["size"]
                close_status = OrderStatus.PARTIAL
            return OrderResponse(
                order_id=str(position_id), symbol=p["symbol"], side=p["side"],
                order_type=p["order_type"], requested_price=p["entry_price"],
                fill_price=p["current_price"], size=close_size, sl=p["sl"], tp=p["tp"],
                status=close_status, broker="paper", raw_response={"simulated": True, "closed": close_status == OrderStatus.FILLED},
            )

    async def get_positions(self) -> list[dict[str, Any]]:
        async with self._lock:
            return [dict(v) for v in self._positions.values()]

    async def get_account_info(self) -> AccountInfo:
        return AccountInfo(
            balance=self._balance,
            equity=self._balance,
            free_margin=self._balance,
            currency="USD",
            broker="paper",
            server="local-simulator",
        )
