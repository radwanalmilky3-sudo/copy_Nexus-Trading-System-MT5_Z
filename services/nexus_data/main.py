"""
Nexus Data Service — FastAPI application.

Exposes tick / OHLCV query endpoints and manages the lifecycle of every
data-feed connector, the DuckDB store, and the Redis tick cache.
"""
from __future__ import annotations

import asyncio
import inspect
import math
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from shared.constants import RedisStream, SERVICE_PORTS, SUPPORTED_TIMEFRAMES
from shared.events import TickEvent, OHLCVEvent
from shared.models import Tick, OHLCV
from shared.nexus_trades import strategy_from_comment as _strategy_from_comment
from shared.redis_client import RedisClient
from shared.security_headers import SecurityHeadersMiddleware

from .duckdb_store import DataStore, OHLCV_RETENTION_DAYS
from .fundamental_store import FundamentalStore
from .trial_registry_router import create_router as create_trial_registry_router
from .broker_settings_router import create_broker_settings_router
from .ml_runs import create_ml_runs_router
from .broker_settings_store import BrokerSettingsStore
from .redis_cache import TickCache
from .mt5_connector import MT5Connector
from .ibkr_connector import IBKRConnector
from .ccxt_connector import CCXTConnector

from shared import setup_logger as _setup_logger
_setup_logger("nexus-data")
log = structlog.get_logger("nexus_data")

# ── Configuration from env ───────────────────────────────────────────────────

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DUCKDB_PATH = os.getenv("DUCKDB_PATH", "./data/nexus.duckdb")

MT5_LOGIN = int(os.getenv("MT5_LOGIN", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")
MT5_PATH = os.getenv("MT5_PATH", "")

IBKR_HOST = os.getenv("IBKR_HOST", "127.0.0.1")
IBKR_PORT = int(os.getenv("IBKR_PORT", "7497"))
IBKR_CLIENT_ID = int(os.getenv("IBKR_CLIENT_ID", "1"))

CCXT_EXCHANGE = os.getenv("CCXT_EXCHANGE", "binance")
CCXT_API_KEY = os.getenv("CCXT_API_KEY", "")
CCXT_SECRET = os.getenv("CCXT_SECRET", "")
# T-024: REAL cloud market data via CCXT public endpoints (paper/dev only —
# synthetic data stays forbidden). Maps logical Nexus symbols to exchange
# pairs: XAUUSD uses PAXG/USDT (tokenized gold on Binance — the closest
# honest real-time gold proxy available without an MT5 terminal).
CCXT_SYMBOL_MAP_RAW = os.getenv("CCXT_SYMBOL_MAP", "XAUUSD:PAXG/USDT")
CCXT_POLL_SEC = max(15, int(os.getenv("CCXT_POLL_SEC", "45")))
ENABLE_CCXT_FLAG = bool(os.getenv("ENABLE_CCXT", ""))


def parse_ccxt_symbol_map(raw: str) -> dict[str, str]:
    """Parse 'LOGICAL:PAIR,LOGICAL:PAIR' — malformed entries are skipped loudly."""
    mapping: dict[str, str] = {}
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" not in chunk:
            log.warning("ccxt.symbol_map_entry_ignored", entry=chunk)
            continue
        logical, pair = (part.strip() for part in chunk.split(":", 1))
        if not logical or "/" not in pair:
            log.warning("ccxt.symbol_map_entry_ignored", entry=chunk)
            continue
        mapping[logical.upper()] = pair
    return mapping


def resolve_data_mode(mt5_ok: bool, ccxt_ok: bool, synthetic: bool) -> str:
    """Honest data-mode label: real sources first, synthetic only when allowed."""
    if synthetic:
        return "SYNTHETIC_ALLOWED"
    if mt5_ok:
        return "REAL_MT5"
    if ccxt_ok:
        return "REAL_CCXT"
    return "REAL_MT5_REQUIRED"


CCXT_SYMBOL_MAP = parse_ccxt_symbol_map(CCXT_SYMBOL_MAP_RAW)

DEFAULT_BROKER = os.getenv("DEFAULT_BROKER", "mt5")
# Production default: MT5-only real data. Set NEXUS_DATA_SYNTHETIC_FALLBACK=1 only for offline dev.
SYNTHETIC_FALLBACK = os.getenv("NEXUS_DATA_SYNTHETIC_FALLBACK", "0").lower() in (
    "1",
    "true",
    "yes",
)

# Symbols to stream on startup (comma-separated env var); logical names (aliases → broker via MT5_SYMBOL_ALIASES).
STREAM_SYMBOLS = [
    s.strip().upper().replace("/", "")
    for s in os.getenv(
        "STREAM_SYMBOLS", "XAUUSD"
    ).split(",")
    if s.strip()
]

# ── Shared instances ─────────────────────────────────────────────────────────

redis_client = RedisClient(url=REDIS_URL)
data_store = DataStore(db_path=DUCKDB_PATH)
fundamental_store = FundamentalStore(data_store)
tick_cache = TickCache(redis_client)

mt5 = MT5Connector()
ibkr = IBKRConnector()
ccxt_conn = CCXTConnector()

_streaming_tasks: list[asyncio.Task] = []


def _base_price(symbol: str) -> float:
    s = symbol.upper()
    if s.startswith("XAU"):
        return 2350.0
    if s.startswith("BTC"):
        return 65000.0
    if "JPY" in s:
        return 155.0
    return 1.08


class TickRow(Tick):
    """Tick API row with optional provenance marker (additive; None on real rows)."""

    source: str | None = None


class OHLCVRow(OHLCV):
    """OHLCV API row with optional provenance marker (additive; None on real rows)."""

    source: str | None = None


# Synthetic fallback rows are API-only: the synthetic paths in get_ticks /
# get_ohlcv return them directly and never write them to the tick cache,
# DuckDB, or Redis Streams. Every synthetic row carries an in-band
# source="synthetic" marker; real rows leave the optional field unset so
# their serialized payload is unchanged.
def _synthetic_tick(symbol: str) -> TickRow:
    now = datetime.now(timezone.utc)
    seed = sum(ord(c) for c in symbol)
    base = _base_price(symbol)
    wiggle = math.sin(now.timestamp() / 60 + seed) * base * 0.0005
    bid = base + wiggle
    spread = 0.25 if symbol.startswith("XAU") else 0.00015
    return TickRow(symbol=symbol, bid=bid, ask=bid + spread, timestamp=now, source="synthetic")


def _synthetic_ohlcv(symbol: str, timeframe: str, limit: int) -> list[OHLCVRow]:
    minutes = {
        "M1": 1,
        "M5": 5,
        "M15": 15,
        "M30": 30,
        "H1": 60,
        "H4": 240,
        "D1": 1440,
    }.get(timeframe, 15)
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    base = _base_price(symbol)
    amp = base * (0.0015 if not symbol.startswith("BTC") else 0.004)
    seed = sum(ord(c) for c in symbol + timeframe)
    out: list[OHLCVRow] = []
    for i in range(limit - 1, -1, -1):
        ts = now - timedelta(minutes=minutes * i)
        x = (limit - i + seed) / 8.0
        close = base + math.sin(x) * amp + math.sin(x / 3) * amp * 0.5
        open_ = base + math.sin(x - 0.2) * amp + math.sin((x - 0.2) / 3) * amp * 0.5
        high = max(open_, close) + amp * 0.2
        low = min(open_, close) - amp * 0.2
        out.append(OHLCVRow(
            symbol=symbol,
            timeframe=timeframe,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=100 + abs(math.sin(x)) * 900,
            timestamp=ts,
            source="synthetic",
        ))
    return out


# ── Tick ingestion callback ──────────────────────────────────────────────────

async def _on_tick(tick: Tick) -> None:
    """Fan-out every incoming tick to cache, DuckDB, and Redis Stream."""
    try:
        await asyncio.gather(
            tick_cache.cache_tick(tick),
            data_store.insert_tick(tick),
            redis_client.publish_event(
                RedisStream.TICK_STREAM,
                TickEvent(
                    source="nexus-data",
                    symbol=tick.symbol,
                    bid=tick.bid,
                    ask=tick.ask,
                    spread=tick.spread,
                ),
            ),
        )
    except Exception:
        await log.aexception("tick_ingest_error", symbol=tick.symbol)


async def _trade_close_consumer() -> None:
    """Consume TradeCloseEvent from Redis Stream and persist to DuckDB.

    Bridges the gap between the executor (publishes close events) and the
    API gateway's trades table so the dashboard history page works.
    """
    import json as _json
    import uuid

    CONSUMER_GROUP = "nexus-data-trades-cg"
    CONSUMER_NAME = f"data-trade-worker-{uuid.uuid4().hex[:6]}"
    STREAM = RedisStream.TRADE_CLOSE

    await asyncio.sleep(5)

    try:
        await redis_client.r.xgroup_create(STREAM, CONSUMER_GROUP, id="0", mkstream=True)
    except Exception as e:
        if "BUSYGROUP" not in str(e):
            await log.aexception("trade_consumer.group_create_failed")

    await log.ainfo("trade_consumer.started", stream=STREAM)

    while True:
        try:
            entries = await redis_client.r.xreadgroup(
                groupname=CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                streams={STREAM: ">"},
                count=10,
                block=3000,
            )
            if not entries:
                continue

            for _stream_name, messages in entries:
                for msg_id, raw in messages:
                    acknowledge = True
                    try:
                        trade_id = raw.get("trade_id", raw.get("order_id", msg_id))
                        symbol = raw.get("symbol", "")
                        side = raw.get("side", "BUY")
                        entry_price = float(raw.get("entry_price", 0))
                        exit_price = float(raw.get("exit_price", 0))
                        pnl_pips = float(raw.get("pnl_pips", 0))
                        pnl_usd = float(raw.get("pnl_usd", 0))
                        rr_ratio = float(raw.get("rr_ratio", 0))
                        reason = raw.get("reason", "")

                        if not symbol:
                            continue

                        if exit_price == 0 and entry_price > 0 and pnl_pips != 0:
                            from shared.asset_specs import pips_to_price
                            signed = pnl_pips if side.upper() == "BUY" else -pnl_pips
                            exit_price = entry_price + pips_to_price(symbol, signed)
                        if exit_price == 0 and pnl_usd == 0 and pnl_pips == 0:
                            continue

                        now = datetime.now(timezone.utc)
                        opened_str = (
                            raw.get("opened_at")
                            or raw.get("data.opened_at")
                            or raw.get("timestamp")
                            or now.isoformat()
                        )
                        if not opened_str or opened_str == "0" or opened_str == "":
                            opened_str = now.isoformat()
                        try:
                            opened_at = datetime.fromisoformat(str(opened_str).replace("Z", "+00:00"))
                            if opened_at.tzinfo is None:
                                opened_at = opened_at.replace(tzinfo=timezone.utc)
                        except Exception:
                            opened_at = now
                        closed_at = now
                        # Broker clocks can drift/skew (server-time epochs); a
                        # future opened_at would store negative durations.
                        if opened_at > closed_at:
                            await log.awarning(
                                "trade_consumer.opened_after_closed",
                                trade_id=trade_id,
                                opened_at=str(opened_at),
                            )
                            opened_at = closed_at
                        duration_s = max(0.0, (closed_at - opened_at).total_seconds())

                        strategy = str(
                            raw.get("data.strategy", "")
                            or _strategy_from_comment(str(raw.get("data.source", "")))
                        )

                        await data_store.insert_trade(
                            trade_id=str(trade_id),
                            symbol=symbol,
                            side=side,
                            entry_price=entry_price,
                            exit_price=exit_price,
                            pnl_pips=pnl_pips,
                            pnl_usd=pnl_usd,
                            rr_ratio=rr_ratio,
                            duration_s=duration_s,
                            session=raw.get("session", ""),
                            conviction=float(raw.get("conviction", 0)),
                            opened_at=opened_at,
                            closed_at=closed_at,
                            strategy=strategy,
                        )
                        await log.ainfo(
                            "trade_consumer.persisted",
                            trade_id=trade_id,
                            symbol=symbol,
                            side=side,
                            pnl_usd=pnl_usd,
                        )
                    except asyncio.CancelledError:
                        # Shutdown/cancellation must not acknowledge a message
                        # whose persistence did not complete (ACR-45/46).
                        acknowledge = False
                        raise
                    except Exception:
                        acknowledge = False
                        await log.aexception("trade_consumer.process_error", msg_id=msg_id)
                    finally:
                        # insert_trade is idempotent by trade id, so retaining
                        # failed events allows safe retry instead of data loss.
                        if acknowledge:
                            await redis_client.r.xack(STREAM, CONSUMER_GROUP, msg_id)

        except asyncio.CancelledError:
            break
        except Exception:
            await log.aexception("trade_consumer.loop_error")
            await asyncio.sleep(5)


OHLCV_POLL_SEC = int(os.getenv("NEXUS_OHLCV_POLL_SEC", "30"))
# Comma-separated list of timeframes to stream. Scalping needs M5 (primary
# decision TF) plus M15/H1 (confirmation TFs). A single value also works.
OHLCV_TIMEFRAMES = [
    tf.strip().upper()
    for tf in os.getenv("NEXUS_OHLCV_TIMEFRAME", "M15").split(",")
    if tf.strip()
] or ["M15"]
OHLCV_BAR_COUNT = int(os.getenv("NEXUS_OHLCV_BAR_COUNT", "300"))

# Gap-detection backfill: bounds are deliberately conservative; windows the
# provider already answered are recorded so market closures are never
# re-requested on every cycle.
OHLCV_BACKFILL_ENABLED = os.getenv("NEXUS_OHLCV_BACKFILL", "1").lower() in (
    "1", "true", "yes",
)
OHLCV_BACKFILL_SEC = max(60, int(os.getenv("NEXUS_OHLCV_BACKFILL_SEC", "600")))
OHLCV_BACKFILL_DAYS = max(1.0, float(os.getenv("NEXUS_OHLCV_BACKFILL_DAYS", "7")))
OHLCV_BACKFILL_MAX_BARS = max(1, min(5000, int(os.getenv("NEXUS_OHLCV_BACKFILL_MAX_BARS", "500"))))
OHLCV_BACKFILL_MAX_INTERVALS = max(1, min(20, int(os.getenv("NEXUS_OHLCV_BACKFILL_MAX_INTERVALS", "4"))))

import json as _json

from services.nexus_data.quality.automation import QualityAutomation
from services.nexus_data.quality.operational import pair_blocked, pair_lock, usable_bars
from services.nexus_data.quality.session_contracts import CalendarPolicy
from services.nexus_data.quality.session_store import SessionEvidenceStore
from services.nexus_data.quality.session_calendar import candidate_gap_windows
from services.nexus_data.quality.stored_audit import INTERVALS as _SESSION_INTERVALS

async def _invalidate_ohlcv_cache(symbol: str, timeframe: str) -> None:
    await redis_client.r.delete(f'nexus:ohlcv:{symbol}:{timeframe}')


_session_path=os.getenv('NEXUS_MT5_SESSION_EXPORT_PATH','').strip()
_session_policy_path=os.getenv('NEXUS_BROKER_CALENDAR_POLICY_PATH','').strip()
session_calendar_store=SessionEvidenceStore(data_store,Path(_session_path) if _session_path else None,CalendarPolicy(),
                                          policy_path=Path(_session_policy_path) if _session_policy_path else None)
quality_automation = QualityAutomation(data_store, provider=mt5, invalidate=_invalidate_ohlcv_cache,calendar_store=session_calendar_store)


async def _persist_closed_ohlcv(bars: list[OHLCV], source: str | None = None) -> None:
    """Persist bars already filtered to completed candles by the provider."""
    if not bars:
        return
    if source is None:
        await data_store.insert_ohlcv_batch(bars)
    else:
        await data_store.insert_ohlcv_batch(bars, source=source)


def _relabel_bars(bars: list[OHLCV], logical: str) -> list[OHLCV]:
    """Relabel provider-pair bars (e.g. PAXG/USDT) to the logical symbol (pure)."""
    relabeled: list[OHLCV] = []
    for b in bars:
        if b.symbol == logical:
            relabeled.append(b)
        elif hasattr(b, "model_copy"):
            relabeled.append(b.model_copy(update={"symbol": logical}))
        else:
            relabeled.append(b)
    return relabeled


async def _ccxt_ohlcv_publisher() -> None:
    """T-024: REAL exchange candles via CCXT for mapped symbols (cloud/dev).

    Mirrors the MT5 publisher's persist/cache/publish path. fetch_ohlcv's last
    bar may be in-progress; usable_bars() filters to completed candles before
    anything is stored or published.
    """
    await asyncio.sleep(3)
    while True:
        for logical, pair in CCXT_SYMBOL_MAP.items():
            for tf in OHLCV_TIMEFRAMES:
                try:
                    raw_bars = await ccxt_conn.get_ohlcv(pair, tf, OHLCV_BAR_COUNT)
                except asyncio.CancelledError:
                    return
                except Exception:
                    await log.aexception("ccxt.ohlcv_fetch_failed", pair=pair, tf=tf)
                    continue
                bars = _relabel_bars(usable_bars(raw_bars), logical)
                if not bars:
                    continue
                try:
                    await _persist_closed_ohlcv(bars, source="ccxt_poll")
                except Exception:
                    await log.aexception("ccxt.persistence_failed", logical=logical, tf=tf)
                    continue
                if await pair_blocked(data_store, logical, tf):
                    await log.awarning(
                        "ccxt.quarantine_blocks_publish", logical=logical, tf=tf,
                    )
                    continue
                last_bar = bars[-1]
                bars_json = [
                    {
                        "timestamp": b.timestamp.isoformat(),
                        "open": b.open,
                        "high": b.high,
                        "low": b.low,
                        "close": b.close,
                        "volume": b.volume,
                    }
                    for b in bars
                ]
                await redis_client.r.set(
                    f"nexus:ohlcv:{logical}:{tf}", _json.dumps(bars_json), ex=3600,
                )
                await redis_client.publish_event(
                    RedisStream.OHLCV_STREAM,
                    OHLCVEvent(
                        source="nexus-data",
                        symbol=last_bar.symbol,
                        timeframe=last_bar.timeframe,
                        open=last_bar.open,
                        high=last_bar.high,
                        low=last_bar.low,
                        close=last_bar.close,
                        volume=last_bar.volume,
                    ),
                )
                await log.ainfo(
                    "ccxt.ohlcv_published",
                    logical=logical,
                    pair=pair,
                    tf=tf,
                    bars=len(bars),
                    close=round(last_bar.close, 2),
                )
        await asyncio.sleep(CCXT_POLL_SEC)


# Markers of a provider answer "this window genuinely has no bars". The
# in-process connector raises ValueError for an empty range, while the
# isolated worker (mt5_worker.py, exit code 6) wraps the very same answer in
# a RuntimeError such as:
#   MT5 worker failed (6): {"ok": false, "error": "MT5 returned no OHLCV for
#   'XAUUSD' in range"}
_EMPTY_RANGE_MARKERS = ("no OHLCV", "no completed OHLCV")


def _is_empty_range_answer(exc: BaseException) -> bool:
    """True when *exc* means "answered: no bars in this range", not a failure."""
    message = str(exc)
    return any(marker in message for marker in _EMPTY_RANGE_MARKERS)


async def _backfill_ohlcv_symbol_tf(symbol: str, tf: str) -> int:
    """Fetch and persist missing closed bars for one (symbol, timeframe).

    Returns the number of unique bars submitted. A provider fetch failure is
    retried on the next cycle (no run recorded); an empty provider answer is
    recorded so weekend/holiday holes are not re-requested forever.
    """
    now = datetime.now(timezone.utc)
    lookback_start = now - timedelta(days=OHLCV_BACKFILL_DAYS)
    retention_floor = now - timedelta(days=OHLCV_RETENTION_DAYS - 1)
    start = max(lookback_start, retention_floor)
    intervals = await data_store.plan_backfill_intervals(
        symbol, tf, start=start, max_gap_bars=OHLCV_BACKFILL_MAX_BARS,
    )
    submitted = 0
    calendar=await session_calendar_store.context(symbol,now)
    windows=[]
    for gap_start,gap_end in intervals:
        if len(windows)>=OHLCV_BACKFILL_MAX_INTERVALS:
            break
        windows.extend(candidate_gap_windows(gap_start,gap_end,timedelta(seconds=_SESSION_INTERVALS[tf]),calendar,
            max_bars=OHLCV_BACKFILL_MAX_BARS,max_windows=OHLCV_BACKFILL_MAX_INTERVALS-len(windows)))
    for gap_start, gap_end in windows:
        if not mt5.connected:
            # A publisher-triggered reconnect raced this cycle: stop quietly
            # instead of logging one traceback per remaining window. Nothing
            # was recorded, so the untouched windows are retried next tick.
            break
        try:
            bars = await mt5.get_ohlcv_range(
                symbol, tf, gap_start, gap_end, limit=OHLCV_BACKFILL_MAX_BARS,
            )
        except Exception as exc:
            if not mt5.connected:
                break
            if not _is_empty_range_answer(exc):
                await log.aexception(
                    "ohlcv.backfill_fetch_failed",
                    symbol=symbol, tf=tf,
                    gap_start=str(gap_start), gap_end=str(gap_end),
                )
                continue
            # Provider answered with an empty range (weekend/holiday): record
            # the window so it is never re-requested. In isolated-worker mode
            # this answer arrives as RuntimeError (exit code 6), not ValueError.
            bars = []
        try:
            inserted = await data_store.insert_ohlcv_batch(bars, source="mt5_backfill")
        except Exception:
            await log.aexception(
                "ohlcv.backfill_persist_failed",
                symbol=symbol, tf=tf,
                gap_start=str(gap_start), gap_end=str(gap_end),
            )
            continue
        await data_store.record_backfill_run(
            symbol, tf, gap_start, gap_end,
            bars_found=len(bars), bars_inserted=inserted, provider="mt5",
        )
        submitted += inserted
    return submitted


async def _ohlcv_backfill_task() -> None:
    """Periodic gap-detection backfill for persisted (symbol, timeframe) history."""
    await asyncio.sleep(10)
    while True:
        if not (OHLCV_BACKFILL_ENABLED and mt5.connected):
            await asyncio.sleep(OHLCV_BACKFILL_SEC)
            continue
        for symbol in STREAM_SYMBOLS:
            for tf in OHLCV_TIMEFRAMES:
                try:
                    submitted = await _backfill_ohlcv_symbol_tf(symbol, tf)
                    if submitted:
                        await log.ainfo(
                            "ohlcv.backfill_progress",
                            symbol=symbol, tf=tf, bars=submitted,
                        )
                except asyncio.CancelledError:
                    return
                except Exception:
                    await log.aexception("ohlcv.backfill_error", symbol=symbol, tf=tf)
        await asyncio.sleep(OHLCV_BACKFILL_SEC)


async def _ohlcv_publisher() -> None:
    """Fetch full OHLCV history from MT5, cache in Redis, publish stream event.

    nexus-features reads the cached bars to compute indicators.
    """
    await asyncio.sleep(3)
    consecutive_failures = 0

    while True:
        for symbol in STREAM_SYMBOLS:
            for tf in OHLCV_TIMEFRAMES:
                try:
                    if await pair_blocked(data_store, symbol, tf):
                        await _invalidate_ohlcv_cache(symbol, tf)
                    bars = await mt5.get_ohlcv(symbol, tf, OHLCV_BAR_COUNT)
                    bars = usable_bars(bars)
                    if not bars:
                        await _invalidate_ohlcv_cache(symbol, tf)
                        await log.awarning("ohlcv.no_bars", symbol=symbol, tf=tf)
                        continue

                    try:
                        await _persist_closed_ohlcv(bars, source="mt5_poll")
                    except Exception:
                        await log.aexception("ohlcv.persistence_failed", symbol=symbol, tf=tf)
                        await _invalidate_ohlcv_cache(symbol, tf)
                        continue

                    if await pair_blocked(data_store, symbol, tf):
                        await redis_client.r.delete(f"nexus:ohlcv:{symbol}:{tf}")
                        await log.awarning("ohlcv.quarantine_blocks_publish", symbol=symbol, tf=tf)
                        continue

                    bars_json = [
                        {
                            "timestamp": b.timestamp.isoformat(),
                            "open": b.open,
                            "high": b.high,
                            "low": b.low,
                            "close": b.close,
                            "volume": b.volume,
                        }
                        for b in bars
                    ]

                    last_bar = bars[-1]
                    async with pair_lock(data_store, symbol, tf):
                        if await pair_blocked(data_store, symbol, tf):
                            await _invalidate_ohlcv_cache(symbol, tf)
                            continue
                        cache_key = f"nexus:ohlcv:{symbol}:{tf}"
                        await redis_client.r.set(cache_key, _json.dumps(bars_json), ex=3600)
                        await redis_client.publish_event(
                            RedisStream.OHLCV_STREAM,
                            OHLCVEvent(
                                source="nexus-data",
                                symbol=last_bar.symbol,
                                timeframe=last_bar.timeframe,
                                open=last_bar.open,
                                high=last_bar.high,
                                low=last_bar.low,
                                close=last_bar.close,
                                volume=last_bar.volume,
                            ),
                        )
                    consecutive_failures = 0
                    await log.ainfo(
                        "ohlcv.published",
                        symbol=symbol,
                        tf=tf,
                        bars=len(bars),
                        close=round(last_bar.close, 2),
                    )
                except Exception:
                    consecutive_failures += 1
                    await log.aexception(
                        "ohlcv_publisher_error",
                        symbol=symbol,
                        tf=tf,
                        failures=consecutive_failures,
                    )
                    if consecutive_failures >= 3 and mt5.connected:
                        await log.awarning("ohlcv.reconnecting_mt5")
                        try:
                            await mt5.disconnect()
                            await asyncio.sleep(2)
                            await mt5.connect(
                                login=MT5_LOGIN,
                                password=MT5_PASSWORD,
                                server=MT5_SERVER,
                                path=MT5_PATH,
                            )
                            consecutive_failures = 0
                        except Exception:
                            await log.aexception("ohlcv.reconnect_failed")

        await asyncio.sleep(OHLCV_POLL_SEC)


# ── Research lineage migration (Phase 0) ─────────────────────────────────────

RESEARCH_LINEAGE_SQL = Path(__file__).resolve().parent / "migrations" / "research_lineage_001.sql"


async def _init_research_lineage(store: DataStore) -> None:
    """Activate migrations/research_lineage_001.sql (additive, IF NOT EXISTS).

    Failure policy is deliberately log-and-continue: creating the research
    tables must never take down nexus-data startup on an existing database.
    Cancellation (startup/shutdown) is still propagated so shutdown is not
    swallowed by the migration attempt.
    """
    if not RESEARCH_LINEAGE_SQL.is_file():
        await log.awarning("research_lineage.missing", schema=str(RESEARCH_LINEAGE_SQL))
        return
    try:
        sql_text = RESEARCH_LINEAGE_SQL.read_text(encoding="utf-8")
        await store._run_script(sql_text)
    except BaseException as exc:
        if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
            raise
        await log.aexception(
            "research_lineage.init_failed",
            schema=str(RESEARCH_LINEAGE_SQL),
            error=str(exc),
        )
        return
    await log.ainfo("research_lineage.ready", schema=str(RESEARCH_LINEAGE_SQL))


# ── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await log.ainfo("startup.begin")

    # 1. Redis
    await redis_client.connect()
    await log.ainfo("startup.redis_connected")

    # 2. DuckDB (must finish before yield — run.py gates other services on this)
    try:
        await data_store.init_tables()
        await fundamental_store.init_schema()
        await _init_research_lineage(data_store)
    except BaseException:
        await log.aexception("startup.duckdb_failed")
        # Startup has not yielded yet, so the normal lifespan shutdown block
        # will never run when database initialization fails. Release resources
        # acquired earlier in startup before propagating the original failure.
        try:
            data_store.close()
        except Exception:
            await log.aexception("startup.duckdb_cleanup_failed")
        try:
            await redis_client.disconnect()
        except Exception:
            await log.aexception("startup.redis_cleanup_failed")
        raise
    await log.ainfo("startup.duckdb_ready")
    _streaming_tasks.append(asyncio.create_task(quality_automation.run()))

    # 3. Broker feeds in background so /health responds while MT5 connects
    async def _start_broker_feeds() -> None:
        if DEFAULT_BROKER == "mt5" and MT5_LOGIN:
            try:
                await mt5.connect(
                    login=MT5_LOGIN,
                    password=MT5_PASSWORD,
                    server=MT5_SERVER,
                    path=MT5_PATH,
                )
                task = asyncio.create_task(
                    mt5.stream_ticks(STREAM_SYMBOLS, _on_tick)
                )
                _streaming_tasks.append(task)

                ohlcv_task = asyncio.create_task(_ohlcv_publisher())
                _streaming_tasks.append(ohlcv_task)

                backfill_task = asyncio.create_task(_ohlcv_backfill_task())
                _streaming_tasks.append(backfill_task)

                await log.ainfo("startup.mt5_streaming", symbols=STREAM_SYMBOLS)
            except Exception:
                await log.aexception("startup.mt5_failed")

        if IBKR_HOST and os.getenv("ENABLE_IBKR", ""):
            try:
                await ibkr.connect(
                    host=IBKR_HOST,
                    port=IBKR_PORT,
                    client_id=IBKR_CLIENT_ID,
                )
                await log.ainfo("startup.ibkr_connected")
            except Exception:
                await log.aexception("startup.ibkr_failed")

        if ENABLE_CCXT_FLAG:
            try:
                await ccxt_conn.connect(
                    exchange_name=CCXT_EXCHANGE,
                    api_key=CCXT_API_KEY,
                    secret=CCXT_SECRET,
                )
                await log.ainfo(
                    "startup.ccxt_connected",
                    mode="keyed" if CCXT_API_KEY else "public",
                )
                if CCXT_SYMBOL_MAP:
                    ccxt_ohlcv_task = asyncio.create_task(_ccxt_ohlcv_publisher())
                    _streaming_tasks.append(ccxt_ohlcv_task)
            except Exception:
                await log.aexception("startup.ccxt_failed")

    trade_task = asyncio.create_task(_trade_close_consumer())
    _streaming_tasks.append(trade_task)
    feed_task = asyncio.create_task(_start_broker_feeds())
    _streaming_tasks.append(feed_task)
    await log.ainfo("startup.trade_consumer_started")
    await log.ainfo("startup.complete")

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────
    await log.ainfo("shutdown.begin")

    for t in _streaming_tasks:
        t.cancel()
    if _streaming_tasks:
        await asyncio.gather(*_streaming_tasks, return_exceptions=True)
    _streaming_tasks.clear()

    await mt5.disconnect()
    await ibkr.disconnect()
    await ccxt_conn.disconnect()
    await data_store.aclose()
    await redis_client.disconnect()

    await log.ainfo("shutdown.complete")


# ── FastAPI app ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="Nexus Data Service",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(SecurityHeadersMiddleware)
app.include_router(create_trial_registry_router(data_store))
app.include_router(create_broker_settings_router(BrokerSettingsStore(data_store)))
app.include_router(create_ml_runs_router(BrokerSettingsStore(data_store)))


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/api/data/mt5/symbols")
async def mt5_symbols(expected_login: str, expected_server: str, x_nexus_internal_secret: str | None = Header(default=None)) -> dict[str, Any]:
    """Read-only Market Watch symbols from the connected MT5 terminal."""
    if not x_nexus_internal_secret or x_nexus_internal_secret != os.getenv("NEXUS_INTERNAL_API_SECRET", ""):
        raise HTTPException(401, "internal authorization required")
    try:
        path = MT5_PATH.strip()
        if path:
            return {"symbols": await mt5.list_symbols_from_terminal(path, expected_login, expected_server)}
        raise HTTPException(503, "MT5 is not connected")
    except Exception as exc:
        raise HTTPException(503, "MT5 symbol list unavailable") from exc


@app.get("/api/data/symbols/{symbol}/snapshot")
async def symbol_snapshot(symbol: str, x_nexus_internal_secret: str | None = Header(default=None)) -> dict[str, Any]:
    """Capture and persist one symbol_info metadata snapshot from MT5."""
    if not x_nexus_internal_secret or x_nexus_internal_secret != os.getenv("NEXUS_INTERNAL_API_SECRET", ""):
        raise HTTPException(401, "internal authorization required")
    symbol = symbol.upper().replace("/", "")
    try:
        info = await mt5.get_symbol_info(symbol)
    except Exception as exc:
        raise HTTPException(503, f"MT5 symbol_info unavailable for {symbol}") from exc
    info["is_available"] = True
    await data_store.insert_symbol_snapshot(info)
    info.pop("raw", None) if isinstance(info.get("raw"), str) else None
    return {"ok": True, "snapshot": {k: v for k, v in info.items() if not isinstance(v, (bytes, bytearray))}}

@app.get("/health")
async def health_check() -> dict[str, Any]:
    redis_ok = await redis_client.health_check()
    mt5_ok = mt5.connected
    data_mode = resolve_data_mode(mt5_ok, ccxt_conn.connected, SYNTHETIC_FALLBACK)
    duckdb_ok = data_store.is_open
    # Startup gate: DuckDB writer must be up; a real source (MT5 or CCXT) may
    # still be connecting — healthy requires at least one real source.
    if redis_ok and duckdb_ok and (mt5_ok or ccxt_conn.connected):
        status = "healthy"
    elif redis_ok and duckdb_ok:
        status = "degraded"
    else:
        status = "unhealthy"
    return {
        "service": "nexus-data",
        "status": status,
        "ready": redis_ok and duckdb_ok,
        "data_mode": data_mode,
        "synthetic_fallback": SYNTHETIC_FALLBACK,
        "redis": redis_ok,
        "duckdb": data_store.is_open,
        "mt5": mt5_ok,
        "ibkr": ibkr.connected,
        "ccxt": ccxt_conn.connected,
        "quality_automation": dict(quality_automation.state),
    }


# ── Tick endpoint ────────────────────────────────────────────────────────────

@app.get(
    "/api/data/ticks/{symbol}",
    response_model=list[TickRow],
    response_model_exclude_none=True,
)
async def get_ticks(
    symbol: str,
    count: int = Query(default=50, ge=1, le=1000),
    source: str = Query(default="cache", regex="^(cache|db)$"),
) -> list[Tick]:
    """Return the most recent ticks for *symbol*."""
    symbol = symbol.upper().replace("/", "")
    if source == "cache":
        ticks = await tick_cache.get_tick_history(symbol, count)
        return ticks or []

    rows = await data_store.query_latest_ticks(symbol, count)
    if rows:
        return rows

    if DEFAULT_BROKER == "mt5" and mt5.connected:
        try:
            live = await mt5.get_tick(symbol)
            return [live]
        except Exception:
            await log.aexception("ticks_mt5_fallback_failed", symbol=symbol)

    if SYNTHETIC_FALLBACK:
        await log.awarning("ticks.synthetic_fallback", symbol=symbol)
        return [_synthetic_tick(symbol)]

    raise HTTPException(404, f"No ticks found for {symbol}")


# ── Order flow (derived from M1 bars + latest tick) ──────────────────────────

@app.get("/api/flow/{symbol}")
@app.get("/api/data/flow/{symbol}")
async def get_order_flow(symbol: str, bars: int = Query(default=20, ge=5, le=100)) -> dict[str, Any]:
    """Estimate bid/ask pressure from recent M1 candle direction and volume."""
    symbol = symbol.upper().replace("/", "")
    if await pair_blocked(data_store, symbol, 'M1'):
        raise HTTPException(503, 'OHLCV quality quarantine unresolved')
    bars_data = await data_store.query_ohlcv(symbol, "M1", limit=bars)
    if not bars_data:
        try:
            bars_data = usable_bars(await mt5.get_ohlcv(symbol, "M1", bars))
            if await pair_blocked(data_store, symbol, 'M1'):
                raise HTTPException(503, 'OHLCV quality quarantine unresolved')
        except HTTPException:
            raise
        except Exception:
            bars_data = []

    # N6 unification (2026-11-05): per-symbol lookups answer 404 when the
    # service holds nothing for the symbol — same semantics as
    # /api/data/ohlcv/{symbol}/{timeframe}. A 200 zero-wrap could be misread
    # as "market is flat"; absence must be explicit (honesty UI-05/UI-06:
    # missing data is never silently zeroed). Consumers already degrade
    # safely: nexus_agents analysis_tools falls back to its own zero
    # envelope on any non-200.
    if not bars_data:
        raise HTTPException(404, f"No order-flow data for {symbol}")

    bid_volume = 0.0
    ask_volume = 0.0
    spreads: list[float] = []

    for bar in bars_data:
        vol = float(getattr(bar, "volume", 0) or (bar.get("volume", 0) if isinstance(bar, dict) else 0))
        o = float(getattr(bar, "open", 0) or (bar.get("open", 0) if isinstance(bar, dict) else 0))
        c = float(getattr(bar, "close", 0) or (bar.get("close", 0) if isinstance(bar, dict) else 0))
        if vol <= 0:
            continue
        if c >= o:
            bid_volume += vol
        else:
            ask_volume += vol

    ticks = await tick_cache.get_tick_history(symbol, 5)
    if not ticks:
        rows = await data_store.query_latest_ticks(symbol, 5)
        ticks = rows or []
    for t in ticks:
        sp = float(getattr(t, "spread", 0) or (t.get("spread", 0) if isinstance(t, dict) else 0))
        if sp > 0:
            spreads.append(sp)

    spread_current = spreads[-1] if spreads else 0.0
    spread_avg = sum(spreads) / len(spreads) if spreads else spread_current or 1.0
    total = bid_volume + ask_volume
    delta = bid_volume - ask_volume
    imbalance = delta / total if total else 0.0

    absorption = "none"
    if total > 0 and abs(imbalance) < 0.1:
        absorption = "balanced"
    elif imbalance > 0.35:
        absorption = "buy_absorption"
    elif imbalance < -0.35:
        absorption = "sell_absorption"

    return {
        "symbol": symbol,
        "bid_volume": round(bid_volume, 2),
        "ask_volume": round(ask_volume, 2),
        "delta": round(delta, 2),
        "absorption": absorption,
        "spread": round(spread_current, 5),
        "spread_avg": round(spread_avg, 5),
        "imbalance": round(imbalance, 4),
        "large_orders": [],
        "iceberg_detected": False,
        "bars_analyzed": len(bars_data),
    }


# ── OHLCV endpoint ───────────────────────────────────────────────────────────

@app.get(
    "/api/data/ohlcv/{symbol}/{timeframe}",
    response_model=list[OHLCVRow],
    response_model_exclude_none=True,
)
async def get_ohlcv(
    symbol: str,
    timeframe: str,
    limit: int = Query(default=500, ge=1, le=5000),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
) -> list[OHLCV]:
    """Return OHLCV bars for *symbol* / *timeframe*."""
    symbol = symbol.upper().replace("/", "")
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise HTTPException(
            400,
            f"Unsupported timeframe '{timeframe}'. Use one of {SUPPORTED_TIMEFRAMES}",
        )
    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")) if start else None
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00")) if end else None
    except ValueError as exc:
        raise HTTPException(400, "start and end must be ISO 8601 timestamps") from exc
    if start_dt and end_dt:
        start_cmp = start_dt if start_dt.tzinfo else start_dt.replace(tzinfo=timezone.utc)
        end_cmp = end_dt if end_dt.tzinfo else end_dt.replace(tzinfo=timezone.utc)
        if start_cmp > end_cmp:
            raise HTTPException(400, "start must be less than or equal to end")
    if await pair_blocked(data_store, symbol, timeframe):
        raise HTTPException(503, 'OHLCV quality quarantine unresolved')
    rows = await data_store.query_ohlcv(
        symbol=symbol, timeframe=timeframe, start=start, end=end, limit=limit,
    )
    if rows and (start or end):
        selected = list(reversed(rows))
        start_bound = start_dt.replace(tzinfo=start_dt.tzinfo or timezone.utc) if start_dt else None
        end_bound = end_dt.replace(tzinfo=end_dt.tzinfo or timezone.utc) if end_dt else None
        if all(
            (start_bound is None or bar.timestamp >= start_bound)
            and (end_bound is None or bar.timestamp <= end_bound)
            for bar in selected
        ) and (start_bound is None or selected[-1].timestamp >= start_bound):
            return selected

    if rows and not start and not end:
        # A short cache is still a valid recent-history response. Return it in
        # chronological order rather than switching providers mid-response.
        return list(reversed(rows))

    if start or end:
        if mt5.connected:
            try:
                range_start = start_dt or (end_dt - timedelta(days=30) if end_dt else datetime.now(timezone.utc) - timedelta(days=30))
                range_end = end_dt or datetime.now(timezone.utc)
                provider_rows = await mt5.get_ohlcv_range(
                    symbol, timeframe, range_start, range_end, limit=limit,
                )
                await _persist_closed_ohlcv(provider_rows, source="mt5_range")
                rows = await data_store.query_ohlcv(
                    symbol=symbol, timeframe=timeframe, start=start, end=end, limit=limit,
                )
                if rows:
                    if await pair_blocked(data_store, symbol, timeframe):
                        raise HTTPException(503, 'OHLCV quality quarantine unresolved')
                    return list(reversed(rows))
            except HTTPException:
                raise
            except Exception as exc:
                if _is_empty_range_answer(exc):
                    # Provider answered "no bars in this window" (weekend /
                    # market break). Expected absence, not a failure — a
                    # polling client retrying M1 ranges must not emit one
                    # warning per request; the access log still shows the 404.
                    await log.adebug(
                        "ohlcv.historical_range_empty",
                        symbol=symbol, timeframe=timeframe,
                        start=start, end=end,
                    )
                else:
                    await log.awarning(
                        "ohlcv.historical_backfill_failed",
                        symbol=symbol, timeframe=timeframe, error=type(exc).__name__,
                    )
        raise HTTPException(404, f"No OHLCV data for {symbol}/{timeframe} in the requested range")

    # DuckDB ``ohlcv`` is not filled from tick ingest — pull live bars from MT5 when connected.
    if DEFAULT_BROKER == "mt5" and mt5.connected and not start and not end:
        try:
            provider_rows = await mt5.get_ohlcv(symbol, timeframe, limit)
            if await pair_blocked(data_store, symbol, timeframe):
                raise HTTPException(503, 'OHLCV quality quarantine unresolved')
            # Connectors return oldest-to-newest, matching the persisted path.
            return usable_bars(provider_rows)
        except HTTPException:
            raise
        except Exception as exc:
            await log.aexception("ohlcv_mt5_fallback_failed", symbol=symbol, tf=timeframe)
            raise HTTPException(503, f"OHLCV provider unavailable for {symbol}/{timeframe}") from exc

    if SYNTHETIC_FALLBACK and not start and not end:
        await log.awarning("ohlcv.synthetic_fallback", symbol=symbol, tf=timeframe)
        return _synthetic_ohlcv(symbol, timeframe, limit)

    raise HTTPException(404, f"No OHLCV data for {symbol}/{timeframe}")


@app.get("/api/data/ohlcv/{symbol}/{timeframe}/provenance")
async def get_ohlcv_provenance(
    symbol: str,
    timeframe: str,
    limit: int = Query(default=100, ge=1, le=1000),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
) -> dict[str, Any]:
    """Per-bar source/quality provenance plus coverage stats for one series.

    Additive market-data read: stored bars only (no broker/synthetic fallback),
    so consumers can certify what DuckDB actually holds.
    """
    symbol = symbol.upper().replace("/", "")
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise HTTPException(
            400,
            f"Unsupported timeframe '{timeframe}'. Use one of {SUPPORTED_TIMEFRAMES}",
        )
    for name, value in (("start", start), ("end", end)):
        if value is None:
            continue
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(400, f"{name} must be an ISO 8601 timestamp") from exc
    result = await data_store.query_ohlcv_provenance(
        symbol, timeframe, start=start, end=end, limit=limit,
    )
    # N6 unification (2026-11-05): an empty series answers 404 like
    # /api/data/ohlcv/{symbol}/{timeframe} — coverage metadata for a series
    # that holds nothing is stated as absence, not as a zeroed envelope.
    coverage = result.get("coverage") or {}
    if not int(coverage.get("bar_count") or 0):
        raise HTTPException(404, f"No OHLCV data for {symbol}/{timeframe}")
    return result


# ── Point-in-time (PIT) research reads (Phase 2, env-flagged) ────────────────

PIT_ENABLED_ENV = "NEXUS_PIT_ENABLED"


def _pit_enabled() -> bool:
    """True when the NEXUS_PIT_ENABLED feature flag is on (default OFF)."""
    return os.getenv(PIT_ENABLED_ENV, "").strip().lower() not in ("", "0", "off", "false", "no")


def _require_pit_enabled() -> None:
    if not _pit_enabled():
        raise HTTPException(503, f"{PIT_ENABLED_ENV} is not set")


def _parse_available_through(value: str | None) -> datetime:
    """Parse the required ``available_through`` query value (ISO 8601, UTC default)."""
    if value is None or not value.strip():
        raise HTTPException(422, "available_through is required (ISO 8601 timestamp)")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(400, "available_through must be an ISO 8601 timestamp") from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _pit_store_query_supported() -> bool:
    """True when DataStore.query_ohlcv exposes the Phase-2 PIT keyword contract."""
    try:
        return "available_through" in inspect.signature(data_store.query_ohlcv).parameters
    except (TypeError, ValueError):
        return False


def _pit_as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@app.get(
    "/api/data/ohlcv/{symbol}/{timeframe}/pit",
    response_model=list[OHLCVRow],
    response_model_exclude_none=True,
)
async def get_ohlcv_pit(
    symbol: str,
    timeframe: str,
    available_through: str | None = Query(default=None),
    max_staleness_s: int | None = Query(default=None, ge=0),
    limit: int = Query(default=500, ge=1, le=5000),
) -> list[OHLCV]:
    """Bars visible as of *available_through* (stored rows only, no live fallback)."""
    _require_pit_enabled()
    as_of = _parse_available_through(available_through)
    symbol = symbol.upper().replace("/", "")
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise HTTPException(
            400,
            f"Unsupported timeframe '{timeframe}'. Use one of {SUPPORTED_TIMEFRAMES}",
        )
    # Fail closed: the store is the only authority on PIT visibility. If the
    # Phase-2 keyword contract is absent, refuse rather than serve rows that
    # may post-date available_through (never edit duckdb_store from here).
    if not _pit_store_query_supported():
        raise HTTPException(503, "point-in-time query support is not available in the data store")
    rows = await data_store.query_ohlcv(
        symbol=symbol, timeframe=timeframe, limit=limit,
        available_through=as_of, max_staleness_s=max_staleness_s,
    )
    # Second guard: a bar that closes after available_through can never be
    # visible, even if the store ignored the parameter.
    visible = [bar for bar in rows if _pit_as_utc(bar.timestamp) <= as_of]
    if not visible:
        raise HTTPException(404, f"No OHLCV data for {symbol}/{timeframe}")
    # Persisted rows arrive newest-first, matching the main OHLCV endpoint.
    return list(reversed(visible))


@app.get("/api/data/ohlcv/{symbol}/{timeframe}/fingerprint")
async def get_ohlcv_fingerprint(
    symbol: str,
    timeframe: str,
    available_through: str | None = Query(default=None),
) -> dict[str, Any]:
    """Content fingerprint of the rows visible as of *available_through*."""
    _require_pit_enabled()
    as_of = _parse_available_through(available_through)
    symbol = symbol.upper().replace("/", "")
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise HTTPException(
            400,
            f"Unsupported timeframe '{timeframe}'. Use one of {SUPPORTED_TIMEFRAMES}",
        )
    fingerprint = getattr(data_store, "fingerprint_ohlcv", None)
    if fingerprint is None:
        raise HTTPException(503, "DataStore.fingerprint_ohlcv is not available")
    result = dict(await fingerprint(symbol, timeframe, as_of))
    return {**result, "status": "ok"}


# ── Subscribe endpoint ───────────────────────────────────────────────────────

@app.get("/api/data/performance")
async def get_performance(
    x_nexus_internal_secret: str | None = Header(default=None),
) -> dict:
    _verify_internal_secret(x_nexus_internal_secret)
    return await data_store.get_performance_metrics()


@app.get("/api/data/performance/equity-curve")
async def get_equity_curve(
    limit: int = Query(200, ge=1, le=2000),
    x_nexus_internal_secret: str | None = Header(default=None),
) -> list:
    _verify_internal_secret(x_nexus_internal_secret)
    return await data_store.get_pnl_curve(limit=limit)


@app.get("/api/data/performance/daily")
async def get_daily_pnl(
    since: str | None = Query(None),
    x_nexus_internal_secret: str | None = Header(default=None),
) -> list:
    _verify_internal_secret(x_nexus_internal_secret)
    return await data_store.get_daily_pnl(since=since)


@app.get("/api/data/performance/by-session")
async def get_perf_by_session(
    x_nexus_internal_secret: str | None = Header(default=None),
) -> list:
    _verify_internal_secret(x_nexus_internal_secret)
    return await data_store.get_grouped_performance("session")


@app.get("/api/data/performance/by-symbol")
async def get_perf_by_symbol(
    x_nexus_internal_secret: str | None = Header(default=None),
) -> list:
    _verify_internal_secret(x_nexus_internal_secret)
    return await data_store.get_grouped_performance("symbol")


@app.get("/api/data/trades")
async def get_trades_history(
    symbol: str | None = Query(None),
    session: str | None = Query(None),
    since: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=5000),
    x_nexus_internal_secret: str | None = Header(default=None),
) -> dict:
    """Paginated trade history from DuckDB — served by the owner of the write lock."""
    _verify_internal_secret(x_nexus_internal_secret)
    return await data_store.query_trades(
        symbol=symbol,
        session=session,
        since=since,
        page=page,
        page_size=page_size,
    )


class SubscribeRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=1)
    broker: str = Field(default="mt5", pattern="^(mt5|ibkr|ccxt)$")


@app.post("/api/data/subscribe")
async def subscribe(
    req: SubscribeRequest,
    x_nexus_internal_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    """Start streaming ticks for additional symbols at runtime."""
    _verify_internal_secret(x_nexus_internal_secret)
    broker_map = {"mt5": mt5, "ibkr": ibkr, "ccxt": ccxt_conn}
    connector = broker_map.get(req.broker)
    if connector is None or not connector.connected:
        raise HTTPException(
            503, f"Broker '{req.broker}' is not connected",
        )

    task = asyncio.create_task(
        connector.stream_ticks(req.symbols, _on_tick),
    )
    _streaming_tasks.append(task)

    await log.ainfo(
        "subscribe.started", broker=req.broker, symbols=req.symbols,
    )
    return {"status": "subscribed", "symbols": req.symbols, "broker": req.broker}

# ── Fundamental intelligence persistence (single DuckDB writer) ──────────────

class FundamentalSourceUpsert(BaseModel):
    source: dict[str, Any]


class FundamentalRecordInsert(BaseModel):
    table: str
    record: dict[str, Any]


class InternalQueryRequest(BaseModel):
    operation: str = Field(min_length=1, max_length=80)
    params: dict[str, Any] = Field(default_factory=dict)


def _verify_internal_secret(x_nexus_internal_secret: str | None) -> None:
    import hmac
    secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
    if not secret:
        raise HTTPException(503, "NEXUS_INTERNAL_API_SECRET is not configured")
    if not x_nexus_internal_secret or not hmac.compare_digest(secret, x_nexus_internal_secret):
        raise HTTPException(403, "invalid internal service credential")


@app.post("/api/data/fundamental/source")
async def fundamental_source_upsert(
    payload: FundamentalSourceUpsert,
    x_nexus_internal_secret: str | None = Header(default=None),
):
    _verify_internal_secret(x_nexus_internal_secret)
    try:
        await fundamental_store.upsert_source(payload.source)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "source_id": payload.source.get("source_id")}


@app.post("/api/data/fundamental/record")
async def fundamental_record_insert(
    payload: FundamentalRecordInsert,
    x_nexus_internal_secret: str | None = Header(default=None),
):
    _verify_internal_secret(x_nexus_internal_secret)
    try:
        await fundamental_store.insert_record(payload.table, payload.record)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        await log.aerror(
            "fundamental.record_storage_failed",
            table=payload.table,
            error_type=type(exc).__name__,
            store_ready=data_store.is_open,
        )
        raise
    return {"ok": True, "table": payload.table}


@app.post("/api/data/query")
async def internal_data_query(
    payload: InternalQueryRequest,
    x_nexus_internal_secret: str | None = Header(default=None),
):
    _verify_internal_secret(x_nexus_internal_secret)
    try:
        rows = await fundamental_store.query_named(payload.operation, payload.params)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"rows": rows}


class StoredQualityRequest(BaseModel):
    model_config = {"extra": "forbid"}
    symbol: str = Field(min_length=1, max_length=160)
    timeframe: str = Field(min_length=2, max_length=4)
    source: str = Field(min_length=1, max_length=160)


@app.post('/api/data/research/quality')
async def run_stored_quality(
    payload: StoredQualityRequest,
    x_nexus_internal_secret: str | None = Header(default=None),
):
    _verify_internal_secret(x_nexus_internal_secret)
    if not data_store.is_open:
        raise HTTPException(503, 'Data store unavailable')
    from .quality.stored_audit import audit_stored_ohlcv
    try:
        return await audit_stored_ohlcv(data_store, payload.symbol, payload.timeframe, payload.source)
    except ValueError as exc:
        raise HTTPException(404 if str(exc).startswith('No stored bars') else 422, str(exc)) from exc


@app.get("/api/data/fundamental/latest/{table}")
async def fundamental_latest(
    table: str,
    order_col: str = Query(default="created_at"),
    limit: int = Query(default=50, ge=1, le=500),
    x_nexus_internal_secret: str | None = Header(default=None),
):
    _verify_internal_secret(x_nexus_internal_secret)
    # Fundamental records are available only to authenticated internal services;
    # the dashboard must use the scoped API gateway endpoints.
    try:
        rows = await fundamental_store.latest_rows(table, order_col, limit)
        return {"table": table, "rows": rows, "count": len(rows)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/data/fundamental/schema")
async def fundamental_schema_inventory():
    return await fundamental_store.schema_inventory()
