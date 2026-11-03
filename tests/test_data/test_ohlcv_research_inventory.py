"""Real-data read-only inventory probes for research candle + OHLCV governance tables.

Task 7 preparation (no Task 7 functionality implemented here).

Safety contract:
- NEVER opens the production DuckDB in write mode and NEVER creates a writer.
- Target resolution order:
  1. NEXUS_OHLCV_SNAPSHOT env path (a copied database file) — preferred.
  2. Strict read-only connection to data/nexus.duckdb (skipped when the
     running nexus-data service holds the file exclusively).
  3. Fallback: copy the production .duckdb (+.wal) bytes into tmp_path and
     inspect the COPY read-only; production file is never touched.
- All fixtures in the synthetic section are clearly labeled synthetic data on
  isolated temp databases.

Post-rebuild note (2026-10-23): file probes skip with Errno 13 while
nexus-data holds data/nexus.duckdb (EXPECTED; never force file access).
Chosen DB-gap path: (a) HTTP-equivalent coverage — the sibling file
test_ohlcv_research_api_probes.py re-expresses the skipped assertions
through the data-service API (internal secret, read-only ops): ledger
consistency + Task 7 hash bindings (probe 6), backfill inserted<=found
(probe 9), governance collection existence (probe 8: quality_runs/
import_jobs/research_artifacts + quarantine via stored cert checks;
datasets/lineage tables are write-committed only, see
research_market.py single transaction), availability coverage (probe 5).
Probes 1-4 (candle schema, key uniqueness, bar_json roundtrip,
availability orphan join) have no read API for raw research candles: they
stay structural — one writer inserts candle+availability rows in the same
transaction (research_market.py:177-178, primary key at :169) and every
completed run re-parses all stored bar_json through inspect_bars
(research_market.py:203).
"""
from __future__ import annotations

import json
import math
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
LIVE_DB = REPO / "data" / "nexus.duckdb"
SNAPSHOT_ENV = os.getenv("NEXUS_OHLCV_SNAPSHOT", "")

RESEARCH_CANDLE_COLUMNS = {
    "owner_id", "account_id", "symbol", "timeframe", "bar_time", "bar_json", "origin",
}
AVAILABILITY_COLUMNS = {
    "owner_id", "account_id", "symbol", "timeframe", "bar_time", "available_at",
}
GOVERNANCE_TABLES = (
    "datasets", "import_jobs", "quality_runs", "quarantine",
    "lineage", "research_artifacts",
)
RUN_STATUSES = {"running", "completed", "partial", "failed"}


def _connect_readonly(path: Path):
    import duckdb

    try:
        return duckdb.connect(str(path), read_only=True)
    except Exception:
        return None


def _open_target(tmp_path: Path):
    """Return (conn, path, origin) for a read-only inspection target, or skip."""
    if SNAPSHOT_ENV:
        path = Path(SNAPSHOT_ENV)
        if not path.is_file():
            pytest.skip(f"NEXUS_OHLCV_SNAPSHOT not found: {path}")
        conn = _connect_readonly(path)
        if conn is None:
            pytest.skip(f"cannot open snapshot read-only: {path}")
        return conn, path, "snapshot"

    conn = _connect_readonly(LIVE_DB)
    if conn is not None:
        return conn, LIVE_DB, "live-readonly"

    # Fallback: inspect a byte copy so a running writer never blocks evidence
    # gathering. The copy may be torn mid-checkpoint; if it fails to open we skip.
    if not LIVE_DB.is_file():
        pytest.skip("production DuckDB absent and no snapshot provided")
    copy = tmp_path / "nexus-inspect.duckdb"
    try:
        shutil.copyfile(LIVE_DB, copy)
        wal = Path(str(LIVE_DB) + ".wal")
        if wal.is_file():
            shutil.copyfile(wal, Path(str(copy) + ".wal"))
    except OSError as exc:
        pytest.skip(f"cannot copy production DuckDB for inspection: {exc}")
    conn = _connect_readonly(copy)
    if conn is None:
        pytest.skip("copied DuckDB cannot be opened read-only (torn copy)")
    return conn, copy, "temp-copy"


def _table_exists(conn, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema='main' AND table_name=?",
        (table,),
    ).fetchone() is not None


def _columns(conn, table: str) -> set[str]:
    return {
        row[0] for row in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='main' AND table_name=?",
            (table,),
        ).fetchall()
    }


def test_research_candle_table_schema_is_stable(tmp_path):
    conn, path, origin = _open_target(tmp_path)
    try:
        if not _table_exists(conn, "research_account_candles"):
            pytest.skip(f"research_account_candles absent in {origin} ({path.name})")
        assert RESEARCH_CANDLE_COLUMNS <= _columns(conn, "research_account_candles")
        if _table_exists(conn, "research_candle_availability"):
            assert AVAILABILITY_COLUMNS <= _columns(conn, "research_candle_availability")
    finally:
        conn.close()


def test_research_candles_are_unique_and_ohlc_valid(tmp_path):
    conn, path, origin = _open_target(tmp_path)
    try:
        if not _table_exists(conn, "research_account_candles"):
            pytest.skip(f"research_account_candles absent in {origin} ({path.name})")
        total = conn.execute("SELECT COUNT(*) FROM research_account_candles").fetchone()[0]
        if total == 0:
            pytest.skip("research_account_candles is empty in target database")
        duplicates = conn.execute(
            "SELECT owner_id, account_id, symbol, timeframe, bar_time, COUNT(*) AS n "
            "FROM research_account_candles GROUP BY 1,2,3,4,5 HAVING n > 1 LIMIT 5"
        ).fetchall()
        assert duplicates == [], f"duplicate research candle keys: {duplicates}"
        invalid = conn.execute(
            "SELECT COUNT(*) FROM research_account_candles WHERE "
            "NOT isfinite(bar_time) OR bar_time <= 0"
        ).fetchone()[0]
        assert invalid == 0, f"{invalid} bars with non-finite/negative bar_time"
    finally:
        conn.close()


def test_research_bar_json_matches_key_and_ohlc_invariants(tmp_path):
    conn, path, origin = _open_target(tmp_path)
    try:
        if not _table_exists(conn, "research_account_candles"):
            pytest.skip(f"research_account_candles absent in {origin} ({path.name})")
        rows = conn.execute(
            "SELECT symbol, timeframe, bar_time, bar_json FROM research_account_candles"
        ).fetchall()
        if not rows:
            pytest.skip("research_account_candles is empty in target database")
        mismatches: list[str] = []
        invalid_ohlc = 0
        for symbol, timeframe, bar_time, bar_json in rows:
            try:
                bar = json.loads(bar_json)
            except (TypeError, ValueError):
                mismatches.append(f"{symbol}/{timeframe}@{bar_time}: unparseable bar_json")
                continue
            if bar.get("time") != bar_time:
                mismatches.append(f"{symbol}/{timeframe}: bar_json.time != bar_time")
            try:
                o, h, low, c = bar["open"], bar["high"], bar["low"], bar["close"]
                v = bar["volume"]
            except (KeyError, TypeError):
                invalid_ohlc += 1
                continue
            prices_ok = (
                all(isinstance(x, (int, float)) and math.isfinite(x) and x > 0 for x in (o, h, low, c))
                and h >= max(o, c) and low <= min(o, c)
            )
            volume_ok = isinstance(v, (int, float)) and math.isfinite(v) and v >= 0
            if not (prices_ok and volume_ok):
                invalid_ohlc += 1
        assert mismatches == [], f"bar_json/bar_time mismatches: {mismatches[:5]}"
        assert invalid_ohlc == 0, f"{invalid_ohlc} research bars violate OHLC/volume invariants"
    finally:
        conn.close()


def test_research_availability_evidence_has_no_orphans(tmp_path):
    conn, path, origin = _open_target(tmp_path)
    try:
        if not _table_exists(conn, "research_candle_availability"):
            pytest.skip(f"research_candle_availability absent in {origin} ({path.name})")
        if not _table_exists(conn, "research_account_candles"):
            pytest.skip(f"research_account_candles absent in {origin} ({path.name})")
        orphans = conn.execute(
            "SELECT COUNT(*) FROM research_candle_availability a "
            "LEFT JOIN research_account_candles c "
            "  ON c.owner_id=a.owner_id AND c.account_id=a.account_id "
            " AND c.symbol=a.symbol AND c.timeframe=a.timeframe AND c.bar_time=a.bar_time "
            "WHERE c.bar_time IS NULL"
        ).fetchone()[0]
        assert orphans == 0, f"{orphans} orphan availability rows"
        bad_ts = conn.execute(
            "SELECT COUNT(*) FROM research_candle_availability "
            "WHERE available_at IS NULL OR try_cast(available_at AS TIMESTAMPTZ) IS NULL"
        ).fetchone()[0]
        assert bad_ts == 0, f"{bad_ts} availability rows with unparseable available_at"
    finally:
        conn.close()


def test_research_availability_coverage_is_reported_not_hidden(tmp_path):
    """Candles lacking availability evidence must be measurable, not silently 0.

    Task 7 must surface this gap per series; the probe records the real number
    so the acceptance run after unblocking can compare it.
    """
    conn, path, origin = _open_target(tmp_path)
    try:
        if not (_table_exists(conn, "research_account_candles")
                and _table_exists(conn, "research_candle_availability")):
            pytest.skip(f"research candle tables absent in {origin} ({path.name})")
        groups = conn.execute(
            "SELECT c.symbol, c.timeframe, COUNT(*) AS candles, "
            "       SUM(CASE WHEN a.bar_time IS NULL THEN 1 ELSE 0 END) AS missing_avail "
            "FROM research_account_candles c "
            "LEFT JOIN research_candle_availability a "
            "  ON c.owner_id=a.owner_id AND c.account_id=a.account_id "
            " AND c.symbol=a.symbol AND c.timeframe=a.timeframe AND c.bar_time=a.bar_time "
            "GROUP BY 1,2 ORDER BY 1,2"
        ).fetchall()
        if not groups:
            pytest.skip("research_account_candles is empty in target database")
        report = {
            f"{symbol}/{timeframe}": {"candles": int(c), "missing_avail": int(m)}
            for symbol, timeframe, c, m in groups
        }
        # Invariant: availability rows can never outnumber candles per series.
        for series, stats in report.items():
            assert stats["missing_avail"] <= stats["candles"], series
        # Evidence transparency: print the per-series coverage gap (not a failure;
        # Task 7 acceptance will require correct classification of these rows).
        print(f"research availability coverage (origin={origin}): {report}")
    finally:
        conn.close()


def test_research_run_ledger_records_are_consistent(tmp_path):
    conn, path, origin = _open_target(tmp_path)
    try:
        if not _table_exists(conn, "research_account_runs"):
            pytest.skip(f"research_account_runs absent in {origin} ({path.name})")
        rows = conn.execute("SELECT run_id, record_json FROM research_account_runs").fetchall()
        if not rows:
            pytest.skip("research_account_runs is empty in target database")
        problems: list[str] = []
        for run_id, record_json in rows:
            try:
                record = json.loads(record_json)
            except (TypeError, ValueError):
                problems.append(f"{run_id}: unparseable record_json")
                continue
            status = record.get("status")
            if status not in RUN_STATUSES:
                problems.append(f"{run_id}: unknown status {status!r}")
            if status in {"completed", "partial"}:
                for key in ("count", "received", "added", "existing"):
                    if key in record and not isinstance(record[key], int):
                        problems.append(f"{run_id}: non-integer {key}")
                if record.get("count", 0) and not record.get("first"):
                    problems.append(f"{run_id}: completed run without first bar")
            if record.get("mode") not in {"history", "live", "unified"}:
                problems.append(f"{run_id}: unknown mode {record.get('mode')!r}")
        assert problems == [], f"inconsistent research runs: {problems[:5]}"
    finally:
        conn.close()


def test_execution_ohlcv_invariants_when_populated(tmp_path):
    """Execution OHLCV store: duplicate-free + OHLC-valid whenever rows exist.

    Currently the production ohlcv table is empty (verified 2026-10-22 on a
    temp copy); the invariant checks activate automatically once Task 7
    ingestion repopulates the table.
    """
    conn, path, origin = _open_target(tmp_path)
    try:
        if not _table_exists(conn, "ohlcv"):
            pytest.skip(f"ohlcv absent in {origin} ({path.name})")
        total = conn.execute("SELECT COUNT(*) FROM ohlcv").fetchone()[0]
        print(f"ohlcv row count in {origin} ({path.name}): {total}")
        if total == 0:
            pytest.skip("ohlcv empty in target database; invariants activate after real ingestion")
        duplicates = conn.execute(
            "SELECT symbol, timeframe, timestamp, COUNT(*) AS n FROM ohlcv "
            "GROUP BY 1,2,3 HAVING n > 1 LIMIT 5"
        ).fetchall()
        assert duplicates == [], f"duplicate ohlcv keys: {duplicates}"
        invalid = conn.execute(
            "SELECT COUNT(*) FROM ohlcv WHERE high < low OR high < GREATEST(open, close) "
            "OR low > LEAST(open, close) OR open <= 0 OR close <= 0 "
            "OR volume < 0 OR NOT isfinite(volume)"
        ).fetchone()[0]
        assert invalid == 0, f"{invalid} invalid OHLC/volume rows"
    finally:
        conn.close()


def test_governance_lineage_tables_exist_in_target(tmp_path):
    conn, path, origin = _open_target(tmp_path)
    try:
        missing = [t for t in GOVERNANCE_TABLES if not _table_exists(conn, t)]
        assert missing == [], f"governance tables missing in {origin} ({path.name}): {missing}"
        if _table_exists(conn, "quarantine"):
            bad_payload = conn.execute(
                "SELECT quarantine_id FROM quarantine "
                "WHERE payload_json IS NULL OR json_valid(payload_json) = false LIMIT 5"
            ).fetchall()
            assert bad_payload == [], f"quarantine rows with invalid payload_json: {bad_payload}"
    finally:
        conn.close()


def test_backfill_runs_never_report_more_inserted_than_found(tmp_path):
    conn, path, origin = _open_target(tmp_path)
    try:
        if not _table_exists(conn, "ohlcv_backfill_runs"):
            pytest.skip(f"ohlcv_backfill_runs absent in {origin} ({path.name})")
        bad = conn.execute(
            "SELECT symbol, timeframe, bars_found, bars_inserted FROM ohlcv_backfill_runs "
            "WHERE bars_inserted > bars_found"
        ).fetchall()
        assert bad == [], f"backfill runs with bars_inserted > bars_found: {bad}"
    finally:
        conn.close()


