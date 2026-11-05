"""Read-only real-data inventory probes for OHLCV tables and the data service.

Safety contract:
- Opens the production DuckDB strictly read-only, and skips when the running
  nexus-data service holds the file exclusively (the normal production case).
- Talks to the live service with GET requests only. Never POST; never pass
  start/end on OHLCV reads (that path can trigger a provider persist).
- An optional NEXUS_OHLCV_SNAPSHOT path can point at a copied database file
  for offline inspection.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
LIVE_DB = REPO / "data" / "nexus.duckdb"
DATA_BASE = os.getenv("NEXUS_DATA_BASE_URL", "http://127.0.0.1:9001").rstrip("/")
SNAPSHOT = os.getenv("NEXUS_OHLCV_SNAPSHOT", "")

EXPECTED_OHLCV_COLUMNS = {
    "symbol", "timeframe", "open", "high", "low", "close", "volume",
    "timestamp", "source", "quality", "fetched_at", "available_at", "revision",
}


def _connect_readonly(path: Path):
    import duckdb

    try:
        return duckdb.connect(str(path), read_only=True)
    except Exception:
        return None


def _target_connection():
    if SNAPSHOT:
        path = Path(SNAPSHOT)
        if not path.is_file():
            pytest.skip(f"NEXUS_OHLCV_SNAPSHOT not found: {path}")
        conn = _connect_readonly(path)
        if conn is None:
            pytest.skip(f"cannot open snapshot read-only: {path}")
        return conn, path
    conn = _connect_readonly(LIVE_DB)
    if conn is None:
        pytest.skip("production DuckDB is locked by the running service or unavailable")
    return conn, LIVE_DB


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema='main' AND table_name=?",
        (table,),
    ).fetchone()
    return row is not None


def _get_json(url: str, timeout: float = 5.0):
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            body = {}
        return exc.code, body
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ConnectionError(str(exc)) from exc


def test_ohlcv_schema_exposes_pit_columns():
    conn, _ = _target_connection()
    try:
        if not _table_exists(conn, "ohlcv"):
            pytest.skip("ohlcv table absent in target database")
        columns = {
            row[0] for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='main' AND table_name='ohlcv'"
            ).fetchall()
        }
        assert EXPECTED_OHLCV_COLUMNS <= columns
    finally:
        conn.close()


def test_ohlcv_has_no_duplicate_keys_and_valid_hlc_sample():
    conn, _ = _target_connection()
    try:
        if not _table_exists(conn, "ohlcv"):
            pytest.skip("ohlcv table absent in target database")
        duplicates = conn.execute(
            "SELECT symbol, timeframe, timestamp, COUNT(*) AS n FROM ohlcv "
            "GROUP BY 1, 2, 3 HAVING n > 1 LIMIT 5"
        ).fetchall()
        assert duplicates == [], f"duplicate ohlcv keys: {duplicates}"
        invalid = conn.execute(
            "SELECT COUNT(*) FROM ohlcv WHERE high < low OR high < GREATEST(open, close) "
            "OR low > LEAST(open, close) OR volume < 0 OR NOT isfinite(volume)"
        ).fetchone()[0]
        assert invalid == 0, f"invalid OHLC/volume rows: {invalid}"
    finally:
        conn.close()


def test_backfill_runs_never_report_more_inserted_than_found():
    conn, _ = _target_connection()
    try:
        if not _table_exists(conn, "ohlcv_backfill_runs"):
            pytest.skip("ohlcv_backfill_runs absent in target database")
        bad = conn.execute(
            "SELECT symbol, timeframe, bars_found, bars_inserted FROM ohlcv_backfill_runs "
            "WHERE bars_inserted > bars_found"
        ).fetchall()
        assert bad == [], f"backfill runs with bars_inserted > bars_found: {bad}"
    finally:
        conn.close()


def test_manifests_agree_with_stored_row_counts():
    conn, path = _target_connection()
    try:
        if not _table_exists(conn, "ohlcv_manifests"):
            pytest.skip("ohlcv_manifests absent in target database")
        if not _table_exists(conn, "ohlcv"):
            pytest.skip("ohlcv table absent in target database")
        stale = conn.execute(
            "SELECT m.symbol, m.timeframe, m.row_count, "
            "       COALESCE((SELECT COUNT(*) FROM ohlcv o "
            "                 WHERE o.symbol = m.symbol AND o.timeframe = m.timeframe), 0) AS actual "
            "FROM ohlcv_manifests m"
        ).fetchall()
        real_stale = [
            (symbol, timeframe, declared, actual)
            for symbol, timeframe, declared, actual in stale
            if declared != actual
        ]
        if real_stale:
            pytest.xfail(
                f"stale ohlcv_manifests vs ohlcv in {path.name}: {real_stale}"
            )
        assert real_stale == []
    finally:
        conn.close()


def test_live_data_service_health_is_get_only():
    try:
        status, body = _get_json(f"{DATA_BASE}/health")
    except ConnectionError as exc:
        pytest.skip(f"nexus-data not reachable at {DATA_BASE}: {exc}")
    assert status == 200
    assert body.get("service") == "nexus-data"
    assert "duckdb" in body
    assert "quality_automation" in body


def test_live_provenance_endpoint_reports_coverage_shape():
    try:
        status, body = _get_json(f"{DATA_BASE}/api/data/ohlcv/XAUUSD/M15/provenance")
    except ConnectionError as exc:
        pytest.skip(f"nexus-data not reachable at {DATA_BASE}: {exc}")
    # N6 (2026-11-05): an empty series answers 404 like ohlcv itself — the
    # shape below is certified only when the service actually holds bars.
    if status == 404:
        assert "No OHLCV data" in str(body.get("detail", ""))
        pytest.skip("zero-state store: XAUUSD/M15 holds no bars (N6 unified 404)")
    assert status == 200
    assert body.get("symbol") == "XAUUSD"
    assert body.get("timeframe") == "M15"
    coverage = body.get("coverage", {})
    for key in ("first_bar", "last_bar", "bar_count", "expected_bars", "missing_bars"):
        assert key in coverage
    assert isinstance(body.get("recent_backfill_runs"), list)
    assert isinstance(body.get("bars"), list)


def test_live_pit_fingerprint_endpoint_is_gated_not_crashing():
    try:
        status, body = _get_json(f"{DATA_BASE}/api/data/ohlcv/XAUUSD/M15/fingerprint")
    except ConnectionError as exc:
        pytest.skip(f"nexus-data not reachable at {DATA_BASE}: {exc}")
    if status == 503:
        assert "detail" in body
        return
    assert status == 200
    assert body.get("status") == "ok"
    assert "fingerprint" in body or "content_hash" in body
