"""
DuckDB persistent storage for ticks and OHLCV bars.

All heavy I/O is offloaded to a thread-pool so the event loop stays free.
Includes automatic data-retention pruning.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

import structlog

from shared.models import Tick, OHLCV

from .imports.contracts import CanonicalOHLCV, CanonicalTick, canonical_record_key
from .quality.quarantine import QuarantineReason, QuarantineRecord
from .quality.validators import validate_ohlcv, validate_ticks

log = structlog.get_logger("nexus_data.duckdb")

try:
    import duckdb  # type: ignore[import-untyped]
except ImportError:
    duckdb = None  # type: ignore[assignment]

_POOL = ThreadPoolExecutor(max_workers=2)

# Retention: keep ticks for 7 days, OHLCV for 365 days
TICK_RETENTION_DAYS = 7
OHLCV_RETENTION_DAYS = 365

TIMEFRAME_SECONDS: dict[str, int] = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D1": 86400,
}

DEFAULT_OHLCV_SOURCE = "mt5"

# Quality-gate dataset ids (must exist in `datasets` for the quarantine FK).
QUALITY_DATASET_OHLCV = "market_ohlcv"
QUALITY_DATASET_TICKS = "market_ticks"

# Feature flag: NEXUS_QUALITY_GATE controls validation + quarantine on write
# paths. Task 7 (raw -> cleaning -> verification -> trace with raw preservation)
# requires gating on ingestion, so it defaults ON; set "0"/"false"/"off" to opt
# out explicitly. Unset and empty behave the same (ON).
QUALITY_GATE_ENV = "NEXUS_QUALITY_GATE"

_RESEARCH_LINEAGE_SQL = Path(__file__).resolve().parent / "migrations" / "research_lineage_001.sql"


def quality_gate_enabled() -> bool:
    """True unless NEXUS_QUALITY_GATE explicitly disables the write gate.

    The Task 7 plan mandates raw-preserving validation on ingestion, so the
    default is ON (unset/empty). Explicit falsy values ("0", "false", "off")
    restore the plain revision-aware upsert path for emergencies/debugging.
    """
    return os.getenv(QUALITY_GATE_ENV, "1").strip().lower() not in ("0", "false", "off")


def _ensure_tz(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _canonical_ohlcv(bar: OHLCV) -> CanonicalOHLCV:
    return CanonicalOHLCV(
        symbol=bar.symbol, timeframe=bar.timeframe, timestamp=_ensure_tz(bar.timestamp),
        open=bar.open, high=bar.high, low=bar.low, close=bar.close, volume=bar.volume,
    )


def _canonical_tick(tick: Tick) -> CanonicalTick:
    return CanonicalTick(
        symbol=tick.symbol, timestamp=_ensure_tz(tick.timestamp),
        bid=tick.bid, ask=tick.ask,
    )


def _ohlcv_invariant_issue(bar: OHLCV) -> str | None:
    """Return a reason string when a bar breaks basic OHLC invariants, else None."""
    prices = (bar.open, bar.high, bar.low, bar.close)
    if any(not math.isfinite(price) for price in prices):
        return "non-finite price"
    if any(price <= 0 for price in prices):
        return "non-positive price"
    if bar.low > min(bar.open, bar.close) or bar.high < max(bar.open, bar.close):
        return "OHLC envelope violated"
    return None


def _quarantine_id(dataset_id: str, reason: QuarantineReason, record_key: str) -> str:
    identity = json.dumps(
        {"dataset_id": dataset_id, "reason": reason.value, "key": record_key},
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(identity).hexdigest()[:24]


def _ohlcv_quarantine_from_bar(
    bar: OHLCV, *, detail: str,
    reason: QuarantineReason = QuarantineReason.INVALID_RECORD,
    dataset_id: str = QUALITY_DATASET_OHLCV,
) -> QuarantineRecord:
    """Quarantine envelope for a raw bar that may fail canonical conversion."""
    timestamp = _ensure_tz(bar.timestamp).astimezone(timezone.utc).isoformat()
    payload: dict[str, Any] = {
        "symbol": bar.symbol, "timeframe": bar.timeframe, "timestamp": timestamp,
        "open": bar.open, "high": bar.high, "low": bar.low,
        "close": bar.close, "volume": bar.volume,
    }
    record_key = json.dumps(["ohlcv", bar.symbol, bar.timeframe, timestamp], sort_keys=True)
    return QuarantineRecord(
        quarantine_id=_quarantine_id(dataset_id, reason, record_key),
        dataset_id=dataset_id, reason_code=reason, record_key=record_key,
        payload=payload, detail=detail,
    )


def _tick_quarantine_from_model(
    tick: Tick, *, detail: str,
    reason: QuarantineReason = QuarantineReason.INVALID_RECORD,
    dataset_id: str = QUALITY_DATASET_TICKS,
) -> QuarantineRecord:
    """Quarantine envelope for a raw tick that may fail canonical conversion."""
    timestamp = _ensure_tz(tick.timestamp).astimezone(timezone.utc).isoformat()
    payload: dict[str, Any] = {
        "symbol": tick.symbol, "timestamp": timestamp,
        "bid": tick.bid, "ask": tick.ask, "spread": tick.spread,
    }
    record_key = json.dumps(["tick", tick.symbol, timestamp, tick.bid, tick.ask], sort_keys=True)
    return QuarantineRecord(
        quarantine_id=_quarantine_id(dataset_id, reason, record_key),
        dataset_id=dataset_id, reason_code=reason, record_key=record_key,
        payload=payload, detail=detail,
    )


def timeframe_seconds(timeframe: str) -> int:
    seconds = TIMEFRAME_SECONDS.get(timeframe)
    if seconds is None:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return seconds


def is_closed_bar(
    timestamp: datetime,
    timeframe: str,
    now: datetime | None = None,
) -> bool:
    """SAFETY INVARIANT: a bar may only be persisted once its window has fully
    elapsed; the still-forming candle must never be written."""
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return timestamp + timedelta(seconds=timeframe_seconds(timeframe)) <= now


def _ohlcv_canonical_line(
    symbol: str,
    timeframe: str,
    timestamp: datetime,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    revision: int,
) -> str:
    """One canonical line of the ohlcv content-hash series.

    Format: ``symbol|timeframe|iso-utc-timestamp|open|high|low|close|volume|revision\\n``.
    Timestamps are normalized to UTC ISO-8601; floats render via ``repr``
    (stable IEEE-754 round-trip); NULL revisions are COALESCEd to 0 by the
    callers before hashing, so they hash as ``0``.
    """
    ts = _ensure_tz(timestamp).astimezone(timezone.utc).isoformat()
    return (
        f"{symbol}|{timeframe}|{ts}|"
        f"{open_!r}|{high!r}|{low!r}|{close!r}|{volume!r}|{int(revision)}\n"
    )


def _ohlcv_content_hash(rows: Sequence[Sequence[Any]]) -> str:
    """sha256 over the concatenation of canonical lines, rows pre-ordered by timestamp.

    Each row contributes its first 9 columns:
    ``symbol, timeframe, timestamp, open, high, low, close, volume, revision``.
    Zero rows hash the empty byte string (``sha256(b"")``).
    """
    digest = hashlib.sha256()
    for row in rows:
        digest.update(_ohlcv_canonical_line(*row[:9]).encode("utf-8"))
    return digest.hexdigest()


class DataStore:
    """Async-friendly DuckDB wrapper for market-data persistence."""

    def __init__(self, db_path: str = "./data/nexus.duckdb") -> None:
        self._db_path = db_path
        self._conn: Any | None = None
        self._invalidated = False
        # DuckDB cursors share mutable state on a connection.  The data service
        # owns one long-lived writer connection, therefore every SQL operation
        # must be serialized even though its blocking work is offloaded from the
        # event loop.
        self._connection_lock = asyncio.Lock()
        self._quality_pair_locks: dict[tuple[str,str], asyncio.Lock] = {}
        # Research lineage schema (datasets/quarantine) is activated lazily on
        # first quarantine write so the quality gate never blocks plain inserts.
        self._lineage_schema_ready = False

    @property
    def is_open(self) -> bool:
        return self._conn is not None and not self._invalidated

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def _recover_stale_wal(self, db_path: str) -> None:
        """Defer large-WAL replay and checkpoint to the primary connection.

        Never delete the WAL here. The primary connection opened by
        ``init_tables`` replays it and checkpoints after schema setup, avoiding
        a temporary second engine touching the same database file.
        """
        wal_path = Path(f"{db_path}.wal")
        if not wal_path.exists():
            return
        wal_mb = wal_path.stat().st_size / (1024 * 1024)
        if wal_mb < 5:
            return

        await log.awarning(
            "duckdb.large_wal_deferred_to_primary_connection",
            path=str(wal_path), size_mb=round(wal_mb, 1),
        )

    async def init_tables(self, *, timeout_s: float = 60.0) -> None:
        if duckdb is None:
            raise RuntimeError("duckdb package is not installed")

        db_path = str(Path(self._db_path).resolve())
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path

        await self._recover_stale_wal(db_path)

        loop = asyncio.get_running_loop()
        try:
            # Single attempt — retries after a hung connect leave orphan threads
            # holding the DuckDB file lock on Windows.
            self._conn = await asyncio.wait_for(
                loop.run_in_executor(_POOL, lambda: self._open_primary_connection(db_path)),
                timeout=timeout_s,
            )
            self._invalidated = False
            await asyncio.wait_for(self._execute_locked(self._create_schemas), timeout=timeout_s)
        except TimeoutError as exc:
            self.close()
            raise RuntimeError(
                f"DuckDB open timed out after {timeout_s}s ({db_path}). "
                "Kill stray python.exe processes, then reopen the database in a "
                "dedicated session so DuckDB replays the WAL automatically. "
                "Do NOT delete the .wal file manually: it holds committed "
                "un-checkpointed data; checkpoint first, then stop."
            ) from exc
        except Exception as exc:
            fatal_type = getattr(duckdb, "FatalException", None)
            if fatal_type is not None and isinstance(exc, fatal_type):
                self._invalidated = True
            self.close()
            raise

        await log.ainfo("duckdb.tables_ready", path=db_path)

    @staticmethod
    def _open_primary_connection(db_path: str):
        try:
            return duckdb.connect(db_path)
        except duckdb.InternalException as exc:
            message = str(exc)
            if not ('replaying WAL' in message and 'GetDefaultDatabase with no default database set' in message):
                raise
            # Known DuckDB replay bug: binding WAL expressions needs an already
            # initialized default catalog. ATTACH within a memory catalog provides
            # that context. Keep this very connection as the sole durable owner;
            # never delete WAL, copy an older database, or open a competing writer.
            log.warning('duckdb.default_catalog_wal_replay_recovery', path=db_path)
            connection = duckdb.connect(':memory:')
            try:
                escaped_path = db_path.replace("'", "''")
                connection.execute(f"ATTACH '{escaped_path}' AS nexus_recovered")
                connection.execute('USE nexus_recovered')
                connection.execute('CHECKPOINT nexus_recovered')
                return connection
            except Exception:
                connection.close()
                raise

    def _create_schemas(self) -> None:
        assert self._conn is not None
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS ticks (
                symbol     VARCHAR   NOT NULL,
                bid        DOUBLE    NOT NULL,
                ask        DOUBLE    NOT NULL,
                spread     DOUBLE    NOT NULL DEFAULT 0,
                timestamp  TIMESTAMP WITH TIME ZONE NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS ohlcv (
                symbol     VARCHAR   NOT NULL,
                timeframe  VARCHAR   NOT NULL,
                open       DOUBLE    NOT NULL,
                high       DOUBLE    NOT NULL,
                low        DOUBLE    NOT NULL,
                close      DOUBLE    NOT NULL,
                volume     DOUBLE    NOT NULL DEFAULT 0,
                timestamp  TIMESTAMP WITH TIME ZONE NOT NULL,
                source     VARCHAR   NOT NULL DEFAULT 'mt5',
                quality    VARCHAR   NOT NULL DEFAULT 'ok',
                fetched_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id          VARCHAR PRIMARY KEY,
                symbol      VARCHAR   NOT NULL,
                side        VARCHAR   NOT NULL,
                entry_price DOUBLE    NOT NULL,
                exit_price  DOUBLE    NOT NULL,
                pnl_pips    DOUBLE    NOT NULL DEFAULT 0,
                pnl_usd     DOUBLE    NOT NULL DEFAULT 0,
                rr_ratio    DOUBLE    NOT NULL DEFAULT 0,
                duration_s  DOUBLE    NOT NULL DEFAULT 0,
                session     VARCHAR,
                conviction  DOUBLE    NOT NULL DEFAULT 0,
                opened_at   TIMESTAMP NOT NULL,
                closed_at   TIMESTAMP NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id            VARCHAR PRIMARY KEY,
                symbol        VARCHAR NOT NULL,
                side          VARCHAR NOT NULL,
                entry_price   DOUBLE NOT NULL,
                current_price DOUBLE NOT NULL DEFAULT 0,
                sl            DOUBLE NOT NULL DEFAULT 0,
                tp1           DOUBLE NOT NULL DEFAULT 0,
                tp2           DOUBLE,
                tp3           DOUBLE,
                size          DOUBLE NOT NULL DEFAULT 0.01,
                pnl_pips      DOUBLE NOT NULL DEFAULT 0,
                pnl_usd       DOUBLE NOT NULL DEFAULT 0,
                status        VARCHAR NOT NULL DEFAULT 'open',
                opened_at     TIMESTAMP NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_logs (
                agent_id   VARCHAR NOT NULL,
                agent_name VARCHAR NOT NULL,
                msg_type   VARCHAR NOT NULL,
                content    TEXT NOT NULL,
                metadata   JSON,
                ts         TIMESTAMP NOT NULL
            )
        """)
        # Migration for DBs created before per-strategy attribution existed.
        self._conn.execute(
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS strategy VARCHAR DEFAULT ''"
        )
        # Migration for DBs created before OHLCV provenance existed.
        # DuckDB cannot ADD COLUMN with constraints; add plain columns then backfill.
        self._conn.execute(
            "ALTER TABLE ohlcv ADD COLUMN IF NOT EXISTS source VARCHAR"
        )
        self._conn.execute(
            "ALTER TABLE ohlcv ADD COLUMN IF NOT EXISTS quality VARCHAR"
        )
        self._conn.execute(
            "ALTER TABLE ohlcv ADD COLUMN IF NOT EXISTS fetched_at TIMESTAMP WITH TIME ZONE"
        )
        self._conn.execute(
            "UPDATE ohlcv SET source='mt5' WHERE source IS NULL"
        )
        # Phase-2 PIT: legacy rows keep quality NULL (NULL-default principle);
        # the former blind `UPDATE ohlcv SET quality='ok'` backfill is removed.
        self._conn.execute(
            "UPDATE ohlcv SET fetched_at=CURRENT_TIMESTAMP WHERE fetched_at IS NULL"
        )
        # Phase-2 point-in-time availability. available_at marks when a row
        # became visible to readers (NULL = legacy, availability unknown);
        # revision counts in-place OHLC corrections (NULL = original).
        self._conn.execute(
            "ALTER TABLE ohlcv ADD COLUMN IF NOT EXISTS available_at TIMESTAMP WITH TIME ZONE"
        )
        self._conn.execute(
            "ALTER TABLE ohlcv ADD COLUMN IF NOT EXISTS revision INTEGER"
        )
        # Migration for DBs created before tick provenance existed.
        # Pre-migration tick rows keep quality NULL (NULL-default principle).
        self._conn.execute(
            "ALTER TABLE ticks ADD COLUMN IF NOT EXISTS source VARCHAR"
        )
        self._conn.execute(
            "ALTER TABLE ticks ADD COLUMN IF NOT EXISTS quality VARCHAR"
        )
        self._conn.execute(
            "ALTER TABLE ticks ADD COLUMN IF NOT EXISTS fetched_at TIMESTAMP WITH TIME ZONE"
        )
        self._conn.execute(
            "UPDATE ticks SET fetched_at=CURRENT_TIMESTAMP WHERE fetched_at IS NULL"
        )
        # Phase-2 PIT: tick availability timestamp (NULL = legacy, unknown).
        self._conn.execute(
            "ALTER TABLE ticks ADD COLUMN IF NOT EXISTS available_at TIMESTAMP WITH TIME ZONE"
        )
        # Per-series manifest: row count + canonical content hash, refreshed
        # after each ohlcv write for the affected (symbol, timeframe).
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS ohlcv_manifests (
                symbol            VARCHAR   NOT NULL,
                timeframe         VARCHAR   NOT NULL,
                row_count         BIGINT    NOT NULL DEFAULT 0,
                content_hash      VARCHAR,
                available_through TIMESTAMP WITH TIME ZONE,
                computed_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (symbol, timeframe)
            )
        """)
        # Completed backfill windows: gap detection must not re-request ranges
        # the provider already answered (weekends/holidays return no bars).
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS ohlcv_backfill_runs (
                symbol         VARCHAR   NOT NULL,
                timeframe      VARCHAR   NOT NULL,
                range_start    TIMESTAMP WITH TIME ZONE NOT NULL,
                range_end      TIMESTAMP WITH TIME ZONE NOT NULL,
                bars_found     INTEGER   NOT NULL DEFAULT 0,
                bars_inserted  INTEGER   NOT NULL DEFAULT 0,
                provider       VARCHAR   NOT NULL DEFAULT 'mt5',
                completed_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Symbol metadata snapshots (NEXUS data dictionary:
        # broker.symbol_property_snapshots adapted to DuckDB). Append-only:
        # each capture inserts a new row; captured_at distinguishes them.
        # is_available=False records "symbol known but MT5 provided no data"
        # — absence is never stored as zero (NULL-default principle).
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS symbol_property_snapshots (
                symbol               VARCHAR   NOT NULL,
                broker_symbol        VARCHAR   NOT NULL,
                description          VARCHAR,
                path                 VARCHAR,
                digits               INTEGER,
                point                DOUBLE,
                spread               INTEGER,
                spread_float         DOUBLE,
                trade_contract_size  DOUBLE,
                tick_value           DOUBLE,
                tick_size            DOUBLE,
                volume_min           DOUBLE,
                volume_max           DOUBLE,
                volume_step          DOUBLE,
                margin_initial       DOUBLE,
                margin_maintenance   DOUBLE,
                swap_long            DOUBLE,
                swap_short           DOUBLE,
                swap_mode            INTEGER,
                trade_mode           INTEGER,
                trade_calc_mode      INTEGER,
                filling_mode         INTEGER,
                order_mode           INTEGER,
                execution_mode       INTEGER,
                currency_base        VARCHAR,
                currency_profit      VARCHAR,
                currency_margin      VARCHAR,
                is_available         BOOLEAN   NOT NULL DEFAULT TRUE,
                source_build         INTEGER,
                raw                  JSON,
                captured_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_symbol_snapshots_sym_ts
            ON symbol_property_snapshots (symbol, captured_at DESC)
        """)
        # Ingest job ledger (development plan Phase 0): every explicit
        # write-path sweep (POST /api/data/ingest/range) journals one row so
        # it is auditable and resumable. Lifecycle: running -> succeeded|failed.
        # Append-only in spirit: finished rows are never rewritten except the
        # running row's own finish transition.
        self._conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS seq_ingest_jobs
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS ingest_jobs (
                id           BIGINT    NOT NULL DEFAULT nextval('seq_ingest_jobs'),
                kind         VARCHAR   NOT NULL,
                symbol       VARCHAR,
                timeframe    VARCHAR,
                window_start TIMESTAMP WITH TIME ZONE,
                window_end   TIMESTAMP WITH TIME ZONE,
                status       VARCHAR   NOT NULL,
                rows         BIGINT    NOT NULL DEFAULT 0,
                error        VARCHAR,
                started_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at  TIMESTAMP WITH TIME ZONE
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ingest_jobs_sym_tf_started
            ON ingest_jobs (symbol, timeframe, started_at DESC)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ticks_symbol_ts
            ON ticks (symbol, timestamp DESC)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_tf_ts
            ON ohlcv (symbol, timeframe, timestamp DESC)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ohlcv_backfill_runs_sym_tf
            ON ohlcv_backfill_runs (symbol, timeframe, range_start)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_trades_closed_at
            ON trades (closed_at DESC)
        """)
        # Flush WAL after unclean shutdown so the next open is fast on Windows.
        self._conn.execute("CHECKPOINT")

    def close(self) -> None:
        if self._conn is not None:
            connection, self._conn = self._conn, None
            try:
                connection.close()
            except Exception as exc:
                fatal_type = getattr(duckdb, "FatalException", None)
                if fatal_type is not None and isinstance(exc, fatal_type):
                    self._invalidated = True
                raise

    async def aclose(self) -> None:
        """Close after in-flight SQL has released the shared connection lock."""
        async with self._connection_lock:
            self.close()

    # ── Insert ───────────────────────────────────────────────────────────

    async def insert_tick(self, tick: Tick) -> None:
        # Gate ON: validate the single tick via canonical conversion (cheap;
        # in-batch duplicate detection does not apply to one tick) and route
        # invalid rows to quarantine instead of the ticks table.
        if quality_gate_enabled():
            try:
                _canonical_tick(tick)
            except (TypeError, ValueError) as exc:
                await log.awarning(
                    "duckdb.tick_invalid_rejected",
                    symbol=tick.symbol, error=str(exc),
                )
                await self._write_quarantine([
                    _tick_quarantine_from_model(tick, detail=f"invalid_record: {exc}")
                ])
                return
        await self._run(
            "INSERT INTO ticks (symbol, bid, ask, spread, timestamp, available_at) "
            "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (tick.symbol, tick.bid, tick.ask, tick.spread, tick.timestamp),
        )

    async def insert_ohlcv(
        self,
        bar: OHLCV,
        *,
        source: str = DEFAULT_OHLCV_SOURCE,
        quality: str = "ok",
        available_at: datetime | None = None,
    ) -> None:
        """Persist one closed bar with revision-aware conflict handling.

        On a (symbol, timeframe, timestamp) conflict an identical stored row
        is left untouched (idempotent) and a differing row is updated in place
        with ``revision = COALESCE(revision, 0) + 1`` (never deleted).
        ``available_at`` defaults to CURRENT_TIMESTAMP when None.
        """
        if not is_closed_bar(bar.timestamp, bar.timeframe):
            await log.awarning(
                "duckdb.ohlcv_forming_bar_rejected",
                symbol=bar.symbol, timeframe=bar.timeframe,
                timestamp=str(bar.timestamp),
            )
            return
        # Gate ON: light per-bar OHLC invariant check; broken bars are skipped
        # and quarantined as invalid_record rather than persisted.
        if quality_gate_enabled():
            issue = _ohlcv_invariant_issue(bar)
            if issue is not None:
                await log.awarning(
                    "duckdb.ohlcv_invalid_bar_rejected",
                    symbol=bar.symbol, timeframe=bar.timeframe,
                    timestamp=str(bar.timestamp), issue=issue,
                )
                await self._write_quarantine([
                    _ohlcv_quarantine_from_bar(bar, detail=f"invalid_record: {issue}")
                ])
                return
        await self._apply_ohlcv_upsert(
            {(bar.symbol, bar.timeframe, bar.timestamp): bar},
            source=source, quality=quality, available_at=available_at,
        )

    async def insert_ohlcv_batch(
        self,
        bars: list[OHLCV],
        *,
        source: str = DEFAULT_OHLCV_SOURCE,
        quality: str = "ok",
        available_at: datetime | None = None,
    ) -> int:
        """Persist closed bars with revision-aware conflict handling.

        Returns the number of unique closed bars submitted for insert.

        For each (symbol, timeframe, timestamp) key an identical stored row
        is skipped (idempotent) and a differing row is updated in place with
        ``revision = COALESCE(revision, 0) + 1`` (rows are never deleted).
        After the write each affected (symbol, timeframe) row in
        ``ohlcv_manifests`` is refreshed on the same locked connection
        (row_count, canonical content_hash, available_through = MAX(available_at),
        computed_at = now). ``available_at`` defaults to CURRENT_TIMESTAMP
        per inserted/updated row when None.

        Quality gate (NEXUS_QUALITY_GATE, default ON): when enabled, bars are
        converted to canonical records and validated via ``validate_ohlcv``;
        ERROR-severity rows (price outliers, duplicates, broken OHLC
        invariants) are written to the quarantine table and are never
        inserted. WARNING-only findings (e.g. time gaps) are not corruption:
        those bars still insert with the caller-provided quality value, so the
        default ``quality="ok"`` is preserved. With the gate OFF the SQL path
        is unchanged apart from the revision-aware upsert.
        """
        if not bars:
            return 0

        unique_bars: dict[tuple[str, str, datetime], OHLCV] = {}
        rejected_forming = 0
        now = datetime.now(timezone.utc)
        for bar in sorted(bars, key=lambda item: item.timestamp):
            if not is_closed_bar(bar.timestamp, bar.timeframe, now):
                rejected_forming += 1
                continue
            unique_bars[(bar.symbol, bar.timeframe, bar.timestamp)] = bar
        if rejected_forming:
            await log.awarning(
                "duckdb.ohlcv_forming_bars_rejected",
                count=rejected_forming, source=source,
            )
        if not unique_bars:
            return 0

        if quality_gate_enabled():
            return await self._insert_ohlcv_batch_gated(
                unique_bars, source=source, quality=quality,
                available_at=available_at,
            )

        # The service owns one DuckDB connection.  Batch writes must use the
        # same lock as _run/_fetch or concurrent consumers can interleave
        # cursor operations on the shared connection.
        await self._apply_ohlcv_upsert(
            unique_bars, source=source, quality=quality, available_at=available_at,
        )
        return len(unique_bars)

    async def _insert_ohlcv_batch_gated(
        self,
        unique_bars: dict[tuple[str, str, datetime], OHLCV],
        *,
        source: str,
        quality: str,
        available_at: datetime | None = None,
    ) -> int:
        """Quality-gated batch insert (NEXUS_QUALITY_GATE ON).

        Same revision-aware upsert as the ungated path, minus ERROR-severity
        rows: broken OHLC invariants and validate_ohlcv outliers/duplicates
        are quarantined and skipped. WARNING findings do not block inserts.
        """
        quarantined: list[QuarantineRecord] = []
        groups: dict[tuple[str, str], list[CanonicalOHLCV]] = {}
        for bar in unique_bars.values():
            try:
                canonical = _canonical_ohlcv(bar)
            except (TypeError, ValueError) as exc:
                quarantined.append(
                    _ohlcv_quarantine_from_bar(bar, detail=f"invalid_record: {exc}")
                )
                continue
            groups.setdefault((canonical.symbol, canonical.timeframe), []).append(canonical)

        for (symbol, timeframe), group in groups.items():
            findings = validate_ohlcv(
                group,
                dataset_id=QUALITY_DATASET_OHLCV,
                expected_interval=timedelta(seconds=timeframe_seconds(timeframe)),
            )
            quarantined.extend(findings.quarantined)
            if findings.issues:
                await log.awarning(
                    "duckdb.ohlcv_quality_findings",
                    symbol=symbol, timeframe=timeframe,
                    status=findings.status, issue_count=len(findings.issues),
                )

        skip_keys: set[tuple[str, str, str]] = set()
        for record in quarantined:
            payload = record.payload
            skip_keys.add((
                str(payload.get("symbol")), str(payload.get("timeframe")),
                str(payload.get("timestamp")),
            ))

        kept_bars = {
            key: bar
            for key, bar in unique_bars.items()
            if (
                bar.symbol, bar.timeframe,
                _ensure_tz(bar.timestamp).astimezone(timezone.utc).isoformat(),
            ) not in skip_keys
        }

        await self._apply_ohlcv_upsert(
            kept_bars, source=source, quality=quality, available_at=available_at,
        )
        if quarantined:
            await self._write_quarantine(quarantined)
        return len(kept_bars)

    async def insert_batch(
        self,
        items: list[Tick | OHLCV],
        *,
        source: str = DEFAULT_OHLCV_SOURCE,
        quality: str = "ok",
        available_at: datetime | None = None,
    ) -> None:
        """Persist a mixed batch; OHLCV rows use the revision-aware upsert.

        ``available_at`` (default None → CURRENT_TIMESTAMP) is stamped on
        inserted ticks and inserted/updated ohlcv rows.
        """
        if not items:
            return

        # Gate ON: validate ticks (canonical conversion + in-batch duplicate
        # detection via validate_ticks) and OHLCV invariants; ERROR rows are
        # quarantined and skipped. The first tick per canonical key wins.
        if quality_gate_enabled():
            items, quarantined = self._gate_batch_items(items)
            if quarantined:
                await log.awarning(
                    "duckdb.batch_quality_findings",
                    quarantined=len(quarantined),
                )
                await self._write_quarantine(quarantined)
            if not items:
                return

        def _bulk() -> None:
            assert self._conn is not None
            ohlcv_bars: dict[tuple[str, str, datetime], OHLCV] = {}
            for item in items:
                if isinstance(item, Tick):
                    self._conn.execute(
                        "INSERT INTO ticks (symbol, bid, ask, spread, timestamp, available_at) "
                        "VALUES (?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))",
                        (
                            item.symbol, item.bid, item.ask, item.spread,
                            item.timestamp, available_at,
                        ),
                    )
                elif isinstance(item, OHLCV):
                    if not is_closed_bar(item.timestamp, item.timeframe):
                        continue
                    ohlcv_bars[(item.symbol, item.timeframe, item.timestamp)] = item
            if ohlcv_bars:
                self._upsert_ohlcv_rows(
                    ohlcv_bars, source=source, quality=quality,
                    available_at=available_at,
                )

        await self._execute_locked(_bulk)

    def _upsert_ohlcv_rows(
        self,
        bars: dict[tuple[str, str, datetime], OHLCV],
        *,
        source: str,
        quality: str,
        available_at: datetime | None,
    ) -> None:
        """Revision-aware ohlcv upsert (sync; caller already holds the lock).

        Per (symbol, timeframe, timestamp) key: identical stored OHLC/volume
        → no-op (idempotent); different → in-place UPDATE of OHLC/volume,
        fetched_at, available_at and ``revision = COALESCE(revision, 0) + 1``
        (rows are never deleted); absent → INSERT. Each affected
        (symbol, timeframe) manifest is refreshed on the same connection.
        """
        assert self._conn is not None
        affected: set[tuple[str, str]] = set()
        for bar in bars.values():
            stored = self._conn.execute(
                "SELECT open, high, low, close, volume FROM ohlcv "
                "WHERE symbol = ? AND timeframe = ? AND timestamp = ?",
                (bar.symbol, bar.timeframe, bar.timestamp),
            ).fetchall()
            if not stored:
                self._conn.execute(
                    "INSERT INTO ohlcv "
                    "(symbol, timeframe, open, high, low, close, volume, timestamp, "
                    " source, quality, fetched_at, available_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, "
                    " COALESCE(?, CURRENT_TIMESTAMP))",
                    (
                        bar.symbol, bar.timeframe, bar.open, bar.high, bar.low,
                        bar.close, bar.volume, bar.timestamp, source, quality,
                        available_at,
                    ),
                )
            elif tuple(stored[0]) == (bar.open, bar.high, bar.low, bar.close, bar.volume):
                continue
            else:
                self._conn.execute(
                    "UPDATE ohlcv "
                    "SET open = ?, high = ?, low = ?, close = ?, volume = ?, "
                    "    fetched_at = CURRENT_TIMESTAMP, "
                    "    available_at = COALESCE(?, CURRENT_TIMESTAMP), "
                    "    revision = COALESCE(revision, 0) + 1 "
                    "WHERE symbol = ? AND timeframe = ? AND timestamp = ?",
                    (
                        bar.open, bar.high, bar.low, bar.close, bar.volume,
                        available_at, bar.symbol, bar.timeframe, bar.timestamp,
                    ),
                )
            affected.add((bar.symbol, bar.timeframe))
        for symbol, timeframe in sorted(affected):
            self._refresh_ohlcv_manifest(symbol, timeframe)

    def _refresh_ohlcv_manifest(self, symbol: str, timeframe: str) -> None:
        """Recompute one ohlcv_manifests row (sync; caller already holds the lock).

        content_hash = sha256 over the canonical ordered series (every stored
        row ordered by timestamp hashed via ``_ohlcv_canonical_line``; rows
        with NULL available_at are included — the manifest reflects the whole
        stored series). available_through = MAX(available_at) of the series
        (NULL when no row has an availability timestamp). computed_at = now.
        """
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT symbol, timeframe, timestamp, open, high, low, close, volume, "
            "       COALESCE(revision, 0), available_at "
            "FROM ohlcv WHERE symbol = ? AND timeframe = ? ORDER BY timestamp",
            (symbol, timeframe),
        ).fetchall()
        content_hash = _ohlcv_content_hash(rows)
        available_through = max(
            (row[9] for row in rows if row[9] is not None), default=None,
        )
        self._conn.execute(
            "INSERT INTO ohlcv_manifests "
            "(symbol, timeframe, row_count, content_hash, available_through, computed_at) "
            "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT (symbol, timeframe) DO UPDATE SET "
            "    row_count = excluded.row_count, "
            "    content_hash = excluded.content_hash, "
            "    available_through = excluded.available_through, "
            "    computed_at = excluded.computed_at",
            (symbol, timeframe, len(rows), content_hash, available_through),
        )

    async def reconcile_ohlcv_manifests(self) -> dict[str, int]:
        """Recompute ohlcv_manifests rows that disagree with stored ohlcv.

        Manifests are declared state (row_count, content_hash,
        available_through). If the underlying series is truncated or emptied
        outside the write path, the declaration becomes a lie; this scans every
        known (symbol, timeframe) — manifests and live pairs alike — and
        refreshes only the mismatched ones on the locked connection (a vanished
        series is declared honestly as 0 rows, an unmanifested live pair gets
        its missing row). Returns checked/stale/refreshed counts. Idempotent.
        """
        rows = await self._fetch(
            "SELECT k.symbol, k.timeframe, m.row_count, "
            "       COALESCE((SELECT COUNT(*) FROM ohlcv o "
            "                 WHERE o.symbol = k.symbol AND o.timeframe = k.timeframe), 0) AS actual "
            "FROM (SELECT symbol, timeframe FROM ohlcv_manifests "
            "      UNION "
            "      SELECT DISTINCT symbol, timeframe FROM ohlcv) k "
            "LEFT JOIN ohlcv_manifests m ON m.symbol = k.symbol AND m.timeframe = k.timeframe"
        )
        stale = [
            (str(symbol), str(timeframe))
            for symbol, timeframe, declared, actual in rows
            if declared is None or int(declared) != int(actual)
        ]
        if stale:
            def _refresh() -> None:
                assert self._conn is not None
                for symbol, timeframe in stale:
                    self._refresh_ohlcv_manifest(symbol, timeframe)

            await self._execute_locked(_refresh)
        return {"checked": len(rows), "stale": len(stale), "refreshed": len(stale)}

    async def _apply_ohlcv_upsert(
        self,
        bars: dict[tuple[str, str, datetime], OHLCV],
        *,
        source: str,
        quality: str,
        available_at: datetime | None,
    ) -> None:
        """Run the revision-aware upsert + manifest refresh under the conn lock."""
        def _exec() -> None:
            self._upsert_ohlcv_rows(
                bars, source=source, quality=quality, available_at=available_at,
            )

        await self._execute_locked(_exec)

    @staticmethod
    def _gate_batch_items(
        items: list[Tick | OHLCV],
    ) -> tuple[list[Tick | OHLCV], list[QuarantineRecord]]:
        """Filter a mixed insert batch through the quality gate (pure).

        Invalid OHLCV/tick rows and in-batch duplicate ticks (ERROR severity
        from ``validate_ticks``) are returned as quarantine records and
        removed from the insert list; the first tick per canonical key wins.
        Out-of-order rows are findings only and are not dropped here.
        """
        quarantined: list[QuarantineRecord] = []
        kept: list[Tick | OHLCV] = []
        canonical_ticks: list[CanonicalTick] = []
        for item in items:
            if isinstance(item, Tick):
                try:
                    canonical_ticks.append(_canonical_tick(item))
                except (TypeError, ValueError) as exc:
                    quarantined.append(
                        _tick_quarantine_from_model(item, detail=f"invalid_record: {exc}")
                    )
                    continue
                kept.append(item)
            elif isinstance(item, OHLCV):
                try:
                    _canonical_ohlcv(item)
                except (TypeError, ValueError) as exc:
                    quarantined.append(
                        _ohlcv_quarantine_from_bar(item, detail=f"invalid_record: {exc}")
                    )
                    continue
                kept.append(item)
        if canonical_ticks:
            findings = validate_ticks(canonical_ticks, dataset_id=QUALITY_DATASET_TICKS)
            quarantined.extend(findings.quarantined)
            seen: set[object] = set()
            deduped: list[Tick | OHLCV] = []
            tick_iter = iter(canonical_ticks)
            for item in kept:
                if isinstance(item, Tick):
                    key = canonical_record_key(next(tick_iter))
                    if key in seen:
                        continue
                    seen.add(key)
                deduped.append(item)
            kept = deduped
        return kept, quarantined

    def _activate_lineage_schema(self) -> None:
        """Run the datasets/lineage/quarantine DDL once (sync; holds no lock of its own)."""
        assert self._conn is not None
        if not self._lineage_schema_ready:
            self._conn.execute(_RESEARCH_LINEAGE_SQL.read_text(encoding="utf-8"))
            self._lineage_schema_ready = True

    async def ensure_lineage_schema(self) -> None:
        """Activate the datasets/lineage/quarantine/quality DDL exactly once.

        Idempotent; callers that persist lineage or dataset registrations
        outside a quarantine write use this first so the FK targets exist.
        """
        await self._execute_locked(self._activate_lineage_schema)

    async def _write_quarantine(self, records: Sequence[QuarantineRecord]) -> None:
        """Persist quarantine envelopes (additive; activates lineage schema once)."""
        if not records:
            return
        def _persist() -> None:
            assert self._conn is not None
            self._activate_lineage_schema()
            for dataset_id in sorted({r.dataset_id for r in records}):
                self._conn.execute(
                    "INSERT INTO datasets (dataset_id, dataset_name) VALUES (?, ?) "
                    "ON CONFLICT (dataset_id) DO NOTHING",
                    (dataset_id, dataset_id),
                )
            for record in records:
                self._conn.execute(
                    "INSERT INTO quarantine "
                    "(quarantine_id, dataset_id, record_key, reason_code, reason_detail, "
                    " payload_json, resolution_status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (quarantine_id) DO NOTHING",
                    (
                        record.quarantine_id, record.dataset_id, record.record_key,
                        record.reason_code.value, record.detail,
                        json.dumps(record.payload), record.resolution_status,
                    ),
                )

        await self._execute_locked(_persist)

    async def insert_trade(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        pnl_pips: float,
        pnl_usd: float,
        rr_ratio: float,
        duration_s: float,
        session: str,
        conviction: float,
        opened_at: datetime,
        closed_at: datetime,
        strategy: str = "",
    ) -> None:
        await self._run(
            "INSERT INTO trades "
            "(id, symbol, side, entry_price, exit_price, pnl_pips, pnl_usd, "
            "rr_ratio, duration_s, session, conviction, opened_at, closed_at, strategy) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (id) DO NOTHING",
            (
                trade_id, symbol, side, entry_price, exit_price,
                pnl_pips, pnl_usd, rr_ratio, duration_s,
                session, conviction, opened_at, closed_at, strategy,
            ),
        )

    # ── Query ────────────────────────────────────────────────────────────

    async def query_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: str | None = None,
        end: str | None = None,
        limit: int = 500,
        *,
        available_through: datetime | None = None,
        max_staleness_s: int | None = None,
    ) -> list[OHLCV]:
        """Query stored bars; PIT filters are opt-in and keyword-only.

        With both PIT params None the SQL is identical to the pre-PIT query
        (legacy rows are returned regardless of available_at).

        available_through=T adds ``available_at <= T``: rows with NULL
        available_at (legacy rows — availability unknown) are EXCLUDED.
        max_staleness_s=N adds ``epoch(timestamp) + N >= epoch(available_at)``:
        a row is only visible when it became available no later than N
        seconds after its bar time; NULL available_at rows are again excluded.
        """
        from .quality.operational import blocked_on_connection
        conditions = ["symbol = ?", "timeframe = ?",
                      "isfinite(open) AND isfinite(high) AND isfinite(low) AND isfinite(close) AND isfinite(volume)",
                      "low > 0 AND open >= low AND close >= low AND high >= open AND high >= close AND volume >= 0",
                      "epoch(timestamp) + ? <= epoch(CURRENT_TIMESTAMP)"]
        params: list[Any] = [symbol, timeframe, TIMEFRAME_SECONDS.get(timeframe, 86400)]

        if start:
            conditions.append("timestamp >= ?")
            params.append(start)
        if end:
            conditions.append("timestamp <= ?")
            params.append(end)
        if available_through is not None:
            conditions.append("available_at <= ?")
            params.append(self._as_utc(available_through))
        if max_staleness_s is not None:
            conditions.append("epoch(timestamp) + ? >= epoch(available_at)")
            params.append(int(max_staleness_s))

        where = " AND ".join(conditions)
        sql = (
            f"SELECT symbol, timeframe, MIN(open), MIN(high), MIN(low), MIN(close), MIN(volume), timestamp "
            f"FROM ohlcv WHERE {where} "
            f"GROUP BY symbol,timeframe,timestamp HAVING COUNT(DISTINCT (open,high,low,close,volume))=1 "
            f"ORDER BY timestamp DESC LIMIT ?"
        )
        params.append(limit)

        def select_safe():
            if blocked_on_connection(self._conn, symbol, timeframe):
                return []
            return self._conn.execute(sql, tuple(params)).fetchall()
        rows = await self._execute_locked(select_safe)
        return [
            OHLCV(
                symbol=r[0], timeframe=r[1],
                open=r[2], high=r[3], low=r[4], close=r[5],
                volume=r[6], timestamp=r[7],
            )
            for r in rows
        ]

    async def fingerprint_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        available_through: datetime | None,
    ) -> dict[str, Any]:
        """Point-in-time content fingerprint of one (symbol, timeframe) series.

        Computed over rows with ``available_at <= available_through`` (NULL
        available_at legacy rows are excluded — unknown availability). The
        content_hash is the sha256 of the canonical ordered series (same
        canonicalization as ohlcv_manifests, see ``_ohlcv_canonical_line``;
        NULL revisions hash as 0). With zero visible rows the result is
        ``row_count: 0`` and ``content_hash`` of the empty byte string
        (``sha256(b"")``).
        """
        cutoff = self._as_utc(available_through) if available_through is not None else None
        rows = await self._fetch(
            "SELECT symbol, timeframe, timestamp, open, high, low, close, volume, "
            "       COALESCE(revision, 0) "
            "FROM ohlcv "
            "WHERE symbol = ? AND timeframe = ? AND available_at <= ? "
            "ORDER BY timestamp",
            (symbol, timeframe, cutoff),
        )
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "available_through": cutoff.isoformat() if cutoff is not None else None,
            "row_count": len(rows),
            "content_hash": _ohlcv_content_hash(rows),
        }

    # ── Coverage / backfill planning ────────────────────────────────────

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

    @staticmethod
    def _interval_subtract(
        start: datetime,
        end: datetime,
        blockers: list[tuple[datetime, datetime]],
    ) -> list[tuple[datetime, datetime]]:
        """Remove *blockers* from the inclusive interval [start, end]."""
        remaining = [(start, end)]
        for b_start, b_end in blockers:
            next_remaining: list[tuple[datetime, datetime]] = []
            for r_start, r_end in remaining:
                if b_end < r_start or b_start > r_end:
                    next_remaining.append((r_start, r_end))
                    continue
                if r_start < b_start:
                    next_remaining.append((r_start, b_start - timedelta(seconds=1)))
                if b_end < r_end:
                    next_remaining.append((b_end + timedelta(seconds=1), r_end))
            remaining = [iv for iv in next_remaining if iv[0] <= iv[1]]
        return remaining

    async def plan_backfill_intervals(
        self,
        symbol: str,
        timeframe: str,
        *,
        start: datetime,
        end: datetime | None = None,
        max_gap_bars: int = 500,
    ) -> list[tuple[datetime, datetime]]:
        """Detect holes in stored (symbol, timeframe) history for backfill.

        Holes are derived from deltas between consecutive stored bars, so
        broker-server timezone offsets cannot create phantom grid gaps.
        Intervals already covered by a recorded ``ohlcv_backfill_runs`` row are
        excluded (the provider was asked once and must not be re-queried for
        weekends/holidays that legitimately have no bars). Returned intervals
        are inclusive (first_missing_open, last_missing_open), each at most
        *max_gap_bars* wide.
        """
        tf = timeframe_seconds(timeframe)
        if max_gap_bars < 1:
            raise ValueError("max_gap_bars must be >= 1")
        start = self._as_utc(start)
        if end is None:
            end = datetime.now(timezone.utc) - timedelta(seconds=tf)
        else:
            end = self._as_utc(end)
        if start > end:
            return []

        rows = await self._fetch(
            "SELECT timestamp FROM ohlcv "
            "WHERE symbol = ? AND timeframe = ? AND timestamp >= ? AND timestamp <= ? "
            "ORDER BY timestamp",
            (symbol, timeframe, start, end),
        )
        stored = [self._as_utc(r[0]) for r in rows]

        holes: list[tuple[datetime, datetime]] = []
        if not stored:
            holes.append((start, end))
        else:
            if stored[0] > start:
                holes.append((start, stored[0] - timedelta(seconds=tf)))
            for prev, nxt in zip(stored, stored[1:]):
                if nxt - prev > timedelta(seconds=tf):
                    holes.append((prev + timedelta(seconds=tf), nxt - timedelta(seconds=tf)))
            if stored[-1] + timedelta(seconds=tf) <= end:
                holes.append((stored[-1] + timedelta(seconds=tf), end))

        run_rows = await self._fetch(
            "SELECT range_start, range_end FROM ohlcv_backfill_runs "
            "WHERE symbol = ? AND timeframe = ? AND range_end >= ? AND range_start <= ?",
            (symbol, timeframe, start, end),
        )
        attempted = [(self._as_utc(r[0]), self._as_utc(r[1])) for r in run_rows]

        step = timedelta(seconds=tf * max_gap_bars)
        out: list[tuple[datetime, datetime]] = []
        for h_start, h_end in holes:
            if h_start > h_end:
                continue
            for u_start, u_end in self._interval_subtract(h_start, h_end, attempted):
                chunk_start = u_start
                while chunk_start <= u_end:
                    chunk_end = min(chunk_start + step - timedelta(seconds=tf), u_end)
                    out.append((chunk_start, chunk_end))
                    chunk_start = chunk_end + timedelta(seconds=tf)
        return out

    # ── Symbol metadata snapshots ────────────────────────────────────────

    _SNAPSHOT_COLUMNS = (
        "symbol", "broker_symbol", "description", "path", "digits", "point",
        "spread", "spread_float", "trade_contract_size", "tick_value",
        "tick_size", "volume_min", "volume_max", "volume_step",
        "margin_initial", "margin_maintenance", "swap_long", "swap_short",
        "swap_mode", "trade_mode", "trade_calc_mode", "filling_mode",
        "order_mode", "execution_mode", "currency_base", "currency_profit",
        "currency_margin", "is_available", "source_build", "raw",
    )

    async def insert_symbol_snapshot(self, info: dict[str, Any]) -> None:
        """Persist one symbol_info snapshot (append-only)."""
        raw = {k: v for k, v in info.items()
               if k not in self._SNAPSHOT_COLUMNS and not k.startswith("_")}
        row = {
            "symbol": info.get("logical_symbol") or info.get("symbol") or info.get("name"),
            "broker_symbol": info.get("broker_symbol") or info.get("name"),
            "description": info.get("description"),
            "path": info.get("path"),
            "digits": info.get("digits"),
            "point": info.get("point"),
            "spread": info.get("spread"),
            "spread_float": info.get("spread_float"),
            "trade_contract_size": info.get("trade_contract_size"),
            "tick_value": info.get("tick_value"),
            "tick_size": info.get("tick_size"),
            "volume_min": info.get("volume_min"),
            "volume_max": info.get("volume_max"),
            "volume_step": info.get("volume_step"),
            "margin_initial": info.get("margin_initial"),
            "margin_maintenance": info.get("margin_maintenance"),
            "swap_long": info.get("swap_long"),
            "swap_short": info.get("swap_short"),
            "swap_mode": info.get("swap_mode"),
            "trade_mode": info.get("trade_mode"),
            "trade_calc_mode": info.get("trade_calc_mode"),
            "filling_mode": info.get("filling_mode"),
            "order_mode": info.get("order_mode"),
            "execution_mode": info.get("execution_mode"),
            "currency_base": info.get("currency_base"),
            "currency_profit": info.get("currency_profit"),
            "currency_margin": info.get("currency_margin"),
            "is_available": bool(info.get("is_available", True)),
            "source_build": info.get("build"),
            "raw": json.dumps(raw, default=str) if raw else None,
        }
        cols = ", ".join(self._SNAPSHOT_COLUMNS)
        placeholders = ", ".join(["?"] * len(self._SNAPSHOT_COLUMNS))
        values = tuple(row.get(c) for c in self._SNAPSHOT_COLUMNS)
        await self._run(
            f"INSERT INTO symbol_property_snapshots ({cols}) VALUES ({placeholders})",
            values,
        )

    async def get_latest_symbol_snapshots(self) -> list[dict[str, Any]]:
        """Latest snapshot per symbol."""
        cols = ", ".join(self._SNAPSHOT_COLUMNS)
        rows = await self._fetch(
            "SELECT " + cols + " FROM symbol_property_snapshots s "
            "WHERE captured_at = (SELECT MAX(captured_at) FROM symbol_property_snapshots "
            "WHERE symbol = s.symbol) ORDER BY symbol",
            (),
        )
        return [dict(zip(self._SNAPSHOT_COLUMNS, r)) for r in rows]

    # ── Ingest job ledger (development plan Phase 0) ────────────────────

    async def ingest_job_start(
        self,
        kind: str,
        symbol: str | None,
        timeframe: str | None,
        window_start: datetime | None,
        window_end: datetime | None,
    ) -> int:
        """Open one ingest job and return its id (status='running')."""
        def _exec() -> int:
            assert self._conn is not None
            row = self._conn.execute(
                "INSERT INTO ingest_jobs "
                "(kind, symbol, timeframe, window_start, window_end, status) "
                "VALUES (?, ?, ?, ?, ?, 'running') RETURNING id",
                (
                    kind, symbol, timeframe,
                    self._as_utc(window_start) if window_start else None,
                    self._as_utc(window_end) if window_end else None,
                ),
            ).fetchone()
            return int(row[0]) if row else -1

        return await self._execute_locked(_exec)

    async def ingest_job_finish(
        self,
        job_id: int,
        status: str,
        *,
        rows: int = 0,
        error: str | None = None,
    ) -> None:
        """Close an ingest job with its terminal status ('succeeded'|'failed')."""
        await self._run(
            "UPDATE ingest_jobs SET status = ?, rows = ?, error = ?, "
            "finished_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'running'",
            (status, int(rows), error, int(job_id)),
        )

    async def record_backfill_run(
        self,
        symbol: str,
        timeframe: str,
        range_start: datetime,
        range_end: datetime,
        *,
        bars_found: int = 0,
        bars_inserted: int = 0,
        provider: str = "mt5",
    ) -> None:
        """Record one attempted backfill window so gap detection will not re-request it."""
        await self._run(
            "INSERT INTO ohlcv_backfill_runs "
            "(symbol, timeframe, range_start, range_end, bars_found, bars_inserted, provider, completed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (
                symbol, timeframe,
                self._as_utc(range_start), self._as_utc(range_end),
                int(bars_found), int(bars_inserted), provider,
            ),
        )

    async def get_ohlcv_coverage(
        self,
        symbol: str,
        timeframe: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, Any]:
        """Return provenance/coverage statistics for one (symbol, timeframe)."""
        tf = timeframe_seconds(timeframe)
        if end is None:
            end = datetime.now(timezone.utc) - timedelta(seconds=tf)
        conditions = ["symbol = ?", "timeframe = ?", "timestamp <= ?"]
        params: list[Any] = [symbol, timeframe, end]
        if start is not None:
            conditions.append("timestamp >= ?")
            params.append(start)
        where = " AND ".join(conditions)

        rows = await self._fetch(
            f"SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM ohlcv WHERE {where}",
            tuple(params),
        )
        first_ts, last_ts, count = (rows[0] if rows else (None, None, 0)) or (None, None, 0)
        expected = 0
        missing = 0
        if first_ts is not None and last_ts is not None and count:
            first_ts = self._as_utc(first_ts)
            last_ts = self._as_utc(last_ts)
            expected = int((last_ts - first_ts).total_seconds() // tf) + 1
            missing = max(0, expected - int(count))

        source_rows = await self._fetch(
            f"SELECT source, COUNT(*) FROM ohlcv WHERE {where} GROUP BY source",
            tuple(params),
        )
        quality_rows = await self._fetch(
            f"SELECT quality, COUNT(*) FROM ohlcv WHERE {where} GROUP BY quality",
            tuple(params),
        )
        return {
            "first_bar": first_ts.isoformat() if first_ts is not None else None,
            "last_bar": last_ts.isoformat() if last_ts is not None else None,
            "bar_count": int(count or 0),
            "expected_bars": expected,
            "missing_bars": missing,
            "sources": {r[0]: int(r[1]) for r in source_rows},
            "qualities": {r[0]: int(r[1]) for r in quality_rows},
        }

    async def query_ohlcv_provenance(
        self,
        symbol: str,
        timeframe: str,
        *,
        start: str | None = None,
        end: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Return per-bar provenance flags plus coverage and recent backfill runs."""
        timeframe_seconds(timeframe)
        conditions = ["symbol = ?", "timeframe = ?"]
        params: list[Any] = [symbol, timeframe]
        if start:
            conditions.append("timestamp >= ?")
            params.append(start)
        if end:
            conditions.append("timestamp <= ?")
            params.append(end)
        where = " AND ".join(conditions)

        rows = await self._fetch(
            f"SELECT timestamp, source, quality, fetched_at FROM ohlcv "
            f"WHERE {where} ORDER BY timestamp DESC LIMIT ?",
            (*params, limit),
        )
        bars = [
            {
                "timestamp": r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0]),
                "source": r[1],
                "quality": r[2],
                "fetched_at": r[3].isoformat() if hasattr(r[3], "isoformat") else r[3],
            }
            for r in rows
        ]
        coverage = await self.get_ohlcv_coverage(
            symbol, timeframe,
            start=self._as_utc(datetime.fromisoformat(start.replace("Z", "+00:00"))) if start else None,
            end=self._as_utc(datetime.fromisoformat(end.replace("Z", "+00:00"))) if end else None,
        )
        run_rows = await self._fetch(
            "SELECT range_start, range_end, bars_found, bars_inserted, provider, completed_at "
            "FROM ohlcv_backfill_runs WHERE symbol = ? AND timeframe = ? "
            "ORDER BY completed_at DESC LIMIT 10",
            (symbol, timeframe),
        )
        recent_runs = [
            {
                "range_start": r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0]),
                "range_end": r[1].isoformat() if hasattr(r[1], "isoformat") else str(r[1]),
                "bars_found": int(r[2] or 0),
                "bars_inserted": int(r[3] or 0),
                "provider": r[4],
                "completed_at": r[5].isoformat() if hasattr(r[5], "isoformat") else str(r[5]),
            }
            for r in run_rows
        ]
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "coverage": coverage,
            "recent_backfill_runs": recent_runs,
            "bars": bars,
        }

    async def query_trades(
        self,
        symbol: str | None = None,
        session: str | None = None,
        since: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        conditions: list[str] = []
        params: list[Any] = []
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol.upper())
        if session:
            conditions.append("session = ?")
            params.append(session)
        if since:
            conditions.append("closed_at >= ?")
            params.append(since)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        count_rows = await self._fetch(
            f"SELECT COUNT(*) FROM trades {where}", tuple(params)
        )
        total = count_rows[0][0] if count_rows else 0

        offset = (page - 1) * page_size
        rows = await self._fetch(
            f"SELECT id, symbol, side, entry_price, exit_price, pnl_pips, pnl_usd, "
            f"rr_ratio, duration_s, session, conviction, opened_at, closed_at, strategy "
            f"FROM trades {where} ORDER BY closed_at DESC LIMIT ? OFFSET ?",
            tuple([*params, page_size, offset]),
        )
        cols = [
            "id", "symbol", "side", "entry_price", "exit_price", "pnl_pips",
            "pnl_usd", "rr_ratio", "duration_s", "session", "conviction",
            "opened_at", "closed_at", "strategy",
        ]
        trades = []
        for row in rows:
            d = dict(zip(cols, row))
            for k in ("opened_at", "closed_at"):
                if d[k] is not None:
                    d[k] = d[k].isoformat() if hasattr(d[k], "isoformat") else str(d[k])
            trades.append(d)
        return {"trades": trades, "total": total, "page": page, "page_size": page_size}

    async def query_latest_ticks(
        self, symbol: str, count: int = 50,
    ) -> list[Tick]:
        rows = await self._fetch(
            "SELECT symbol, bid, ask, spread, timestamp "
            "FROM ticks WHERE symbol = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (symbol, count),
        )
        return [
            Tick(symbol=r[0], bid=r[1], ask=r[2], spread=r[3], timestamp=r[4])
            for r in rows
        ]

    async def get_performance_metrics(self) -> dict[str, Any]:
        """Overall performance for the dashboard KPI panel.

        Must return **all 8** fields the panel requires (``PLDashboard.coercePerf``):
        an earlier revision only produced the first six, so ``sharpe_ratio`` and
        ``max_drawdown`` were absent and the panel blanked every KPI behind
        "Performance response is incomplete".

        Formulas mirror ``nexus_monitor.performance.PerformanceAnalyzer`` so the
        two services agree:

        * ``sharpe_ratio`` — mean/std(ddof=1) * sqrt(252) over the **daily** P&L
          series; 0.0 when there are fewer than two days or a zero/NULL std.
        * ``max_drawdown`` — peak-to-trough of the running equity ordered by
          ``(closed_at, id)``, expressed as a percentage of the peak when that
          peak is positive, otherwise in absolute currency (as the monitor does).
        """
        rows = await self._fetch(
            """
            WITH base AS (
                SELECT pnl_usd, closed_at, id FROM trades
            ),
            agg AS (
                SELECT
                    COALESCE(SUM(pnl_usd), 0)                        AS total_pnl,
                    COUNT(*)                                          AS total_trades,
                    COALESCE(AVG(CASE WHEN pnl_usd > 0 THEN pnl_usd END), 0) AS avg_win,
                    COALESCE(AVG(CASE WHEN pnl_usd <= 0 THEN pnl_usd END), 0) AS avg_loss,
                    CASE WHEN COUNT(*) > 0
                         THEN ROUND(SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2)
                         ELSE 0 END AS win_rate,
                    CASE WHEN ABS(COALESCE(SUM(CASE WHEN pnl_usd <= 0 THEN pnl_usd END), 1)) > 0
                         THEN ROUND(COALESCE(SUM(CASE WHEN pnl_usd > 0 THEN pnl_usd END), 0)
                              / ABS(COALESCE(SUM(CASE WHEN pnl_usd <= 0 THEN pnl_usd END), 1)), 2)
                         ELSE 0 END AS profit_factor
                FROM base
            ),
            daily AS (
                SELECT CAST(closed_at AS DATE) AS day,
                       COALESCE(SUM(pnl_usd), 0) AS pnl
                FROM base
                GROUP BY 1
            ),
            daily_stats AS (
                SELECT COUNT(*) AS n, AVG(pnl) AS mu, STDDEV_SAMP(pnl) AS sd
                FROM daily
            ),
            equity AS (
                SELECT
                    ROW_NUMBER() OVER (ORDER BY closed_at, id) AS rn,
                    SUM(pnl_usd) OVER (
                        ORDER BY closed_at, id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) AS balance
                FROM base
            ),
            peaks AS (
                SELECT rn, balance,
                       MAX(balance) OVER (
                           ORDER BY rn
                           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                       ) AS peak
                FROM equity
            ),
            troughs AS (
                SELECT rn, peak, peak - balance AS dd FROM peaks
            ),
            worst AS (
                SELECT MAX(dd) AS max_dd, arg_max(peak, dd) AS peak_at_worst
                FROM troughs
            )
            SELECT
                a.total_pnl,
                a.total_trades,
                a.avg_win,
                a.avg_loss,
                a.win_rate,
                a.profit_factor,
                CASE WHEN s.n < 2 OR s.sd IS NULL OR s.sd = 0 THEN 0.0
                     ELSE ROUND(s.mu / s.sd * sqrt(252.0), 4) END AS sharpe_ratio,
                CASE WHEN w.max_dd IS NULL OR w.max_dd <= 0 THEN 0.0
                     WHEN w.peak_at_worst > 0
                         THEN ROUND(w.max_dd / w.peak_at_worst * 100.0, 2)
                     ELSE ROUND(w.max_dd, 2) END AS max_drawdown
            FROM agg a, daily_stats s, worst w
            """
        )
        if not rows or not rows[0]:
            return {}
        row = rows[0]
        cols = [
            "total_pnl", "total_trades", "avg_win", "avg_loss",
            "win_rate", "profit_factor", "sharpe_ratio", "max_drawdown",
        ]
        return dict(zip(cols, row))

    async def get_pnl_curve(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = await self._fetch(
            """
            WITH recent AS (
                SELECT closed_at, pnl_usd
                FROM trades
                ORDER BY closed_at DESC
                LIMIT ?
            )
            SELECT
                closed_at,
                pnl_usd,
                SUM(pnl_usd) OVER (
                    ORDER BY closed_at ASC
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS cumulative_pnl
            FROM recent
            ORDER BY closed_at ASC
            """,
            (limit,),
        )
        return [
            {
                "closed_at": r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0]),
                "pnl_usd": r[1],
                "cumulative_pnl": r[2],
            }
            for r in rows
        ]

    async def get_daily_pnl(self, since: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE closed_at >= ?" if since else ""
        params = (since,) if since else ()
        rows = await self._fetch(
            f"""
            SELECT
                CAST(closed_at AS DATE) AS date,
                COALESCE(SUM(pnl_usd), 0) AS pnl,
                COUNT(*) AS trades,
                COALESCE(ROUND(
                    SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END)
                    * 100.0 / NULLIF(COUNT(*), 0), 2), 0) AS win_rate
            FROM trades {where}
            GROUP BY CAST(closed_at AS DATE)
            ORDER BY date DESC
            """,
            params,
        )
        return [
            {"date": str(r[0]), "pnl": r[1], "trades": r[2], "win_rate": r[3]}
            for r in rows
        ]

    async def get_grouped_performance(self, group_col: str) -> list[dict[str, Any]]:
        safe_col = group_col if group_col in ("session", "symbol") else "session"
        rows = await self._fetch(
            f"""
            SELECT
                {safe_col} AS grp,
                COALESCE(SUM(pnl_usd), 0) AS total_pnl,
                COUNT(*) AS trades,
                COALESCE(ROUND(
                    SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END)
                    * 100.0 / NULLIF(COUNT(*), 0), 2), 0) AS win_rate,
                COALESCE(AVG(rr_ratio), 0) AS avg_rr
            FROM trades
            GROUP BY {safe_col}
            ORDER BY total_pnl DESC
            """,
        )
        return [
            {"group": r[0], "total_pnl": r[1], "trades": r[2],
             "win_rate": r[3], "avg_rr": r[4]}
            for r in rows
        ]

    # ── Retention ────────────────────────────────────────────────────────

    async def prune_old_data(self) -> None:
        tick_cutoff = datetime.now(timezone.utc) - timedelta(days=TICK_RETENTION_DAYS)
        ohlcv_cutoff = datetime.now(timezone.utc) - timedelta(days=OHLCV_RETENTION_DAYS)

        await self._run(
            "DELETE FROM ticks WHERE timestamp < ?", (tick_cutoff,),
        )
        await self._run(
            "DELETE FROM ohlcv WHERE timestamp < ?", (ohlcv_cutoff,),
        )
        await log.ainfo(
            "duckdb.pruned",
            tick_cutoff=str(tick_cutoff),
            ohlcv_cutoff=str(ohlcv_cutoff),
        )

    # ── Internal helpers ─────────────────────────────────────────────────

    async def _execute_locked(self, operation: Callable[[], Any]) -> Any:
        """Serialize one connection operation and surface fatal DB invalidation.

        2026-11-06 hardening: the asyncio lock must never wedge the whole
        service. A cancelled/timed-out holder used to leave everything queued
        behind it forever (login, ledger, certificates all froze). Now: a
        hard acquire deadline, release guaranteed by the context manager
        even when the waiter is cancelled, and the culprit is named in the
        log when the queue is long.

        Phase 0 (development plan 2026-11-09): waiters QUEUE instead of
        refusing at 60s. Large batch writes legitimately hold the lock for
        minutes and the old refusal produced 500-storms on every concurrent
        reader (evidence E5). Now: poll up to 10 minutes total, log a
        warning at ~60s naming the holder, and only then give up — a
        genuinely wedged lock still surfaces instead of freezing forever.
        """
        loop = asyncio.get_running_loop()
        deadline_sec = 600.0
        poll_sec = 5.0
        waited = 0.0
        warned = False
        while True:
            try:
                await asyncio.wait_for(self._connection_lock.acquire(), timeout=poll_sec)
                break
            except asyncio.TimeoutError:
                waited += poll_sec
                held = getattr(self, '_lock_holder', '<unknown>')
                if not warned and waited >= 60.0:
                    warned = True
                    await log.awarning(
                        'duckdb.lock_wait_long',
                        waited_s=int(waited), held_by=held,
                    )
                if waited >= deadline_sec:
                    raise RuntimeError(
                        f'DuckDB owner-store lock busy >{int(deadline_sec)}s (held by {held}) — '
                        'gave up after queueing; the long operation must finish or be cancelled'
                    ) from None
        self._lock_holder = getattr(operation, '__name__', repr(operation)[:60])
        try:
            return await self._execute_locked_inner(operation, loop)
        finally:
            self._lock_holder = None
            self._connection_lock.release()

    async def _execute_locked_inner(self, operation: Callable[[], Any], loop) -> Any:
        # القفل ممسوك أصلاً من _execute_locked — لا يعاد اقتناؤه هنا
        if self._invalidated or self._conn is None:
            raise RuntimeError("DuckDB store is unavailable; reinitialize the data service")
        try:
            return await loop.run_in_executor(_POOL, operation)
        except Exception as exc:
            fatal_type = getattr(duckdb, "FatalException", None)
            if fatal_type is not None and isinstance(exc, fatal_type):
                self._invalidated = True
                connection, self._conn = self._conn, None
                if connection is not None:
                    try:
                        await loop.run_in_executor(_POOL, connection.close)
                    except Exception:
                        log.exception("duckdb.close_after_fatal_failed")
            raise

    async def _run(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        def _exec() -> None:
            assert self._conn is not None
            self._conn.execute(sql, params)

        await self._execute_locked(_exec)

    async def _run_script(self, sql_script: str) -> None:
        """Execute a trusted migration script on the single owned DuckDB connection."""
        def _exec_script() -> None:
            assert self._conn is not None
            self._conn.execute(sql_script)

        await self._execute_locked(_exec_script)

    async def _fetch(
        self, sql: str, params: tuple[Any, ...] = (),
    ) -> list[tuple[Any, ...]]:
        def _query() -> list[tuple[Any, ...]]:
            assert self._conn is not None
            return self._conn.execute(sql, params).fetchall()

        return await self._execute_locked(_query)

    async def _fetch_with_columns(
        self, sql: str, params: tuple[Any, ...] = (),
    ) -> tuple[list[tuple[Any, ...]], list[str]]:
        def _query() -> tuple[list[tuple[Any, ...]], list[str]]:
            assert self._conn is not None
            cursor = self._conn.execute(sql, params)
            rows = cursor.fetchall()
            cols = [d[0] for d in (cursor.description or [])]
            return rows, cols

        return await self._execute_locked(_query)
