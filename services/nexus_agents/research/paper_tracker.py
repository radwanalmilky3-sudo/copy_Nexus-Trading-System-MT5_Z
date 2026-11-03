"""
PaperTracker — paper-fill ledger for strategies graduating through the
shadow/paper lifecycle (Phase 5B).

The master plan's ``strategy_paper_fills`` table is modelled with the same
columns (``id, strategy_id, symbol, side, entry_price, exit_price, qty,
opened_at, closed_at, pnl, source, created_at``) but persisted with the
established research-module pattern — Redis via
:class:`shared.redis_client.RedisClient`, exactly like :mod:`registry`:

* fills  → capped list under ``strategy:paper:fills:<id>`` (audit window,
  mirrors the registry's research-log list);
* metrics → JSON blob under ``strategy:paper:metrics:<id>`` holding running
  aggregates so ``get_metrics`` is O(1) and never skewed by the fill cap.

Every Redis failure follows the registry's log-and-continue pattern: warn
and return safe defaults so a store outage never crashes the research loop.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

import structlog

from shared.redis_client import RedisClient

logger = structlog.get_logger(__name__)

# ── Redis keys ──────────────────────────────────────────────────────────────
FILLS_KEY = "strategy:paper:fills:{id}"       # capped list of fill records
METRICS_KEY = "strategy:paper:metrics:{id}"   # running aggregates per strategy

MAX_FILLS = 2000                              # audit window (list is capped)
METRICS_TTL_SEC = 60 * 60 * 24 * 90           # aggregates survive a paper run
PF_UNBOUNDED = 999.0                          # profit factor when no losses


class PaperTracker:
    """Record paper fills and derive the metrics the ``active`` gate needs."""

    def __init__(self, redis: RedisClient) -> None:
        self.redis = redis

    # ─── Helpers ────────────────────────────────────────────────────────────

    def _full(self, key: str) -> str:
        from shared.constants import REDIS_KEY_PREFIX
        return f"{REDIS_KEY_PREFIX}{key}"

    def _fills_key(self, strategy_id: str) -> str:
        return FILLS_KEY.format(id=strategy_id)

    def _metrics_key(self, strategy_id: str) -> str:
        return METRICS_KEY.format(id=strategy_id)

    async def _load_aggregates(self, strategy_id: str) -> dict[str, Any]:
        try:
            raw = await self.redis.cache_get(self._metrics_key(strategy_id))
        except Exception:
            await logger.awarning("paper_tracker.metrics_unreadable", id=strategy_id)
            raw = None
        if not raw or not isinstance(raw, dict):
            raw = {}
        return {
            "trades": int(raw.get("trades", 0) or 0),
            "wins": int(raw.get("wins", 0) or 0),
            "losses": int(raw.get("losses", 0) or 0),
            "open_trades": int(raw.get("open_trades", 0) or 0),
            "gross_profit": float(raw.get("gross_profit", 0.0) or 0.0),
            "gross_loss": float(raw.get("gross_loss", 0.0) or 0.0),
            "net_pnl": float(raw.get("net_pnl", 0.0) or 0.0),
            "last_updated": raw.get("last_updated"),
        }

    # ─── Write ──────────────────────────────────────────────────────────────

    async def record_fill(
        self,
        *,
        strategy_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float | None = None,
        qty: float = 1.0,
        opened_at: float | None = None,
        closed_at: float | None = None,
        pnl: float | None = None,
        source: str = "paper",
    ) -> dict[str, Any] | None:
        """Append one paper fill and update the strategy's aggregates.

        Returns the stored fill, or ``None`` when the store is unavailable
        (log-and-continue: a Redis outage never raises into the caller).
        """
        if not strategy_id:
            return None
        now = time.time()
        fill: dict[str, Any] = {
            "id": uuid.uuid4().hex[:12],
            "strategy_id": strategy_id,
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "qty": qty,
            "opened_at": opened_at if opened_at is not None else now,
            "closed_at": closed_at,
            "pnl": pnl,
            "source": source,
            "created_at": now,
        }
        try:
            key = self._full(self._fills_key(strategy_id))
            await self.redis.r.lpush(key, json.dumps(fill, default=str))
            await self.redis.r.ltrim(key, 0, MAX_FILLS - 1)
            await self._bump_aggregates(fill)
        except Exception:
            await logger.awarning("paper_tracker.record_failed", id=strategy_id)
            return None
        return fill

    async def _bump_aggregates(self, fill: dict[str, Any]) -> None:
        strategy_id = str(fill["strategy_id"])
        agg = await self._load_aggregates(strategy_id)
        if fill.get("exit_price") is None and fill.get("pnl") is None:
            agg["open_trades"] += 1
        else:
            pnl = float(fill.get("pnl") or 0.0)
            agg["trades"] += 1
            if pnl > 0:
                agg["wins"] += 1
                agg["gross_profit"] += pnl
            elif pnl < 0:
                agg["losses"] += 1
                agg["gross_loss"] += abs(pnl)
            agg["net_pnl"] += pnl
        agg["last_updated"] = time.time()
        await self.redis.cache_set(
            self._metrics_key(strategy_id), agg, ttl_sec=METRICS_TTL_SEC,
        )

    async def reset(self, strategy_id: str) -> None:
        """Clear a strategy's paper fills and metrics."""
        try:
            await self.redis.cache_delete(self._metrics_key(strategy_id))
            await self.redis.r.delete(self._full(self._fills_key(strategy_id)))
        except Exception:
            await logger.awarning("paper_tracker.reset_failed", id=strategy_id)

    # ─── Read ───────────────────────────────────────────────────────────────

    async def get_metrics(self, strategy_id: str) -> dict[str, Any]:
        """Return paper metrics for a strategy.

        Shape: ``{trades, wins, losses, win_rate, profit_factor,
        gross_profit, gross_loss, net_pnl, open_trades, last_updated}``.
        ``win_rate``/``profit_factor`` are ``None`` when undefined (no closed
        trades, or no losses against which to form a ratio); PF is capped at
        :data:`PF_UNBOUNDED` when a run has profits but no losses.
        """
        empty: dict[str, Any] = {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": None,
            "profit_factor": None,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "net_pnl": 0.0,
            "open_trades": 0,
            "last_updated": None,
        }
        agg = await self._load_aggregates(strategy_id)
        trades = agg["trades"]
        wins = agg["wins"]
        gp = agg["gross_profit"]
        gl = agg["gross_loss"]
        empty.update({
            "trades": trades,
            "wins": wins,
            "losses": agg["losses"],
            "open_trades": agg["open_trades"],
            "gross_profit": gp,
            "gross_loss": gl,
            "net_pnl": agg["net_pnl"],
            "last_updated": agg["last_updated"],
            "win_rate": (wins / trades) if trades else None,
        })
        if gl > 0:
            empty["profit_factor"] = gp / gl
        elif gp > 0:
            empty["profit_factor"] = PF_UNBOUNDED
        return empty


__all__ = ["PaperTracker"]
