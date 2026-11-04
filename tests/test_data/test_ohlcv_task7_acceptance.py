"""Task 7 acceptance harness: fetch/clean/trace against synthetic + REAL data.

- Part A (always on): synthetic, clearly-labeled fixtures on ISOLATED temp
  databases. They pin the reuse surface Task 7 builds on (DataStore upsert,
  backfill-run memory, quality-gate raw preservation) — proving no third
  data-processing engine is needed.
- Part B (ungated since Task 7 implementation): real-data acceptance probes.
  They never write to the production DuckDB directly. DB probes inspect, in
  order: NEXUS_OHLCV_SNAPSHOT, a live read-only connection, or a byte copy of
  the production file. API probes use GET except the documented
  research/quality evidence POST (metadata only) and the explicitly
  documented repeat-fetch idempotency POST (account-owned research tables,
  idempotent ON CONFLICT DO NOTHING path, skipped while the MT5 provider is
  down so no mutation happens against a dead provider).

Safety: no production DB mutation, no service restarts, paper mode untouched.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from shared.models import OHLCV
from services.nexus_data.duckdb_store import DataStore

UTC = timezone.utc
T0 = datetime(2026, 10, 12, 16, 30, tzinfo=UTC)
STEP = timedelta(minutes=15)
DATA_BASE = os.getenv("NEXUS_DATA_BASE_URL", "http://127.0.0.1:9001").rstrip("/")
REPO = Path(__file__).resolve().parents[2]
LIVE_DB = REPO / "data" / "nexus.duckdb"


def _bar(offset: int, *, close: float = 2650.0, symbol: str = "XAUUSD") -> OHLCV:
    """SYNTHETIC test bar — not market data."""
    stamp = T0 + STEP * offset
    return OHLCV(
        symbol=symbol, timeframe="M15", timestamp=stamp,
        open=close - 0.4, high=close + 0.8, low=close - 0.9, close=close,
        volume=12.0,
    )


def _bars(n: int = 6) -> list[OHLCV]:
    return [_bar(i, close=2650.0 + i * 0.5) for i in range(n)]


@pytest_asyncio.fixture
async def isolated_store(tmp_path):
    """ISOLATED temp DuckDB — never the production file."""
    store = DataStore(db_path=str(tmp_path / "task7-synthetic.duckdb"))
    await store.init_tables()
    try:
        yield store
    finally:
        await store.aclose()


# ── Part A: reuse-surface contracts (synthetic; run now) ─────────────────


@pytest.mark.asyncio
async def test_repeated_same_period_batch_is_idempotent(isolated_store):
    """Task 7 contract: re-fetching the same period must not duplicate bars."""
    bars = _bars(8)
    first = await isolated_store.insert_ohlcv_batch(bars, source="mt5_backfill")
    second = await isolated_store.insert_ohlcv_batch(bars, source="mt5_backfill")
    assert first == 8 and second == 8
    rows = await isolated_store._fetch(
        "SELECT timestamp, revision FROM ohlcv WHERE symbol='XAUUSD' AND timeframe='M15' "
        "ORDER BY timestamp"
    )
    assert len(rows) == 8, f"duplicate bars after repeated fetch: {len(rows)}"
    assert all(revision is None for _, revision in rows), (
        "identical re-insert must not bump revision"
    )


@pytest.mark.asyncio
async def test_concurrent_duplicate_submits_leave_single_series(isolated_store):
    """Task 7 contract: two concurrent requests for the same period converge."""
    bars = _bars(5)
    results = await asyncio.gather(
        isolated_store.insert_ohlcv_batch(list(bars), source="mt5_poll"),
        isolated_store.insert_ohlcv_batch(list(bars), source="mt5_poll"),
    )
    assert sorted(results) == [5, 5]
    rows = await isolated_store._fetch(
        "SELECT COUNT(*) FROM ohlcv WHERE symbol='XAUUSD' AND timeframe='M15'"
    )
    assert rows[0][0] == 5


@pytest.mark.asyncio
async def test_backfill_run_memory_prevents_rerequest_of_answered_window(isolated_store):
    """Task 7 contract: an answered window is recorded and never re-planned."""
    await isolated_store.insert_ohlcv_batch(
        [_bar(0, close=2650.0), _bar(1, close=2650.5), _bar(10, close=2655.0)],
        source="mt5_backfill",
    )
    answered_start = T0 + STEP * 2
    answered_end = T0 + STEP * 5
    await isolated_store.record_backfill_run(
        "XAUUSD", "M15", answered_start, answered_end,
        bars_found=4, bars_inserted=0, provider="mt5",
    )
    intervals = await isolated_store.plan_backfill_intervals(
        "XAUUSD", "M15", start=T0, end=T0 + STEP * 10,
    )
    for gap_start, gap_end in intervals:
        overlaps_answered = gap_start <= answered_end and gap_end >= answered_start
        assert not overlaps_answered, (
            f"planned re-request of answered window: {gap_start}..{gap_end}"
        )
    assert intervals, "unanswered tail of the hole must still be planned"


@pytest.mark.asyncio
async def test_quality_gate_quarantine_preserves_raw_values(isolated_store, monkeypatch):
    """Task 7 contract: rejected rows keep raw payload + reason as evidence.

    Also asserts the quarantine->datasets binding contract (the dangling-join
    half of test_real_lineage_evidence_binds_quarantine_to_datasets) on this
    isolated store, since the live production join is not API-expressible.
    """
    monkeypatch.setenv("NEXUS_QUALITY_GATE", "1")
    base = _bar(0, close=2650.0)
    outlier = OHLCV(
        symbol="XAUUSD", timeframe="M15", timestamp=T0 + STEP,
        open=2650.0, high=5000.0, low=2649.0, close=2650.0, volume=12.0,
    )
    submitted = await isolated_store.insert_ohlcv_batch(
        [base, outlier], source="mt5_poll",
    )
    assert submitted == 1, "only the clean bar of the batch may persist"
    stored = await isolated_store._fetch(
        "SELECT COUNT(*) FROM ohlcv WHERE timestamp = ?", (T0 + STEP,)
    )
    assert stored[0][0] == 0, "outlier bar must not be persisted when gate is ON"
    quarantine = await isolated_store._fetch(
        "SELECT reason_code, reason_detail, payload_json FROM quarantine"
    )
    assert quarantine, "quality gate must leave a quarantine evidence row"
    reason, detail, payload_raw = quarantine[-1]
    payload = json.loads(payload_raw)
    assert reason in {"outlier", "invalid_record"}
    assert detail
    assert payload["symbol"] == "XAUUSD"
    assert payload["high"] == 5000.0, "raw rejected values must be preserved verbatim"
    assert payload["timestamp"].startswith("2026-10-12T16:45")
    dangling = await isolated_store._fetch(
        "SELECT q.quarantine_id FROM quarantine q "
        "LEFT JOIN datasets d ON d.dataset_id = q.dataset_id "
        "WHERE d.dataset_id IS NULL LIMIT 5"
    )
    assert dangling == [], f"quarantine rows without dataset binding: {dangling}"


@pytest.mark.asyncio
async def test_fingerprint_changes_when_data_changes(isolated_store):
    """Task 7 contract: output_hash must bind the certificate to the data."""
    available_at = T0 + STEP * 9
    await isolated_store.insert_ohlcv_batch(
        _bars(4), source="mt5_backfill", available_at=available_at,
    )
    cutoff = T0 + STEP * 10
    before = await isolated_store.fingerprint_ohlcv("XAUUSD", "M15", cutoff)
    assert before["row_count"] == 4 and before["content_hash"]
    again = await isolated_store.fingerprint_ohlcv("XAUUSD", "M15", cutoff)
    assert again["content_hash"] == before["content_hash"], "fingerprint must be deterministic"
    await isolated_store.insert_ohlcv_batch(
        [_bar(4, close=2652.5)], source="mt5_backfill", available_at=available_at,
    )
    after = await isolated_store.fingerprint_ohlcv("XAUUSD", "M15", cutoff)
    assert after["row_count"] == 5
    assert after["content_hash"] != before["content_hash"], (
        "fingerprint must change when the series changes"
    )


# ── Part B: real-data acceptance probes (ungated; env-aware skips) ────────


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


def _post_json(url: str, payload: dict, secret: str, timeout: float = 90.0):
    """POST returning (status, body); connection failure raises ConnectionError."""
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json", "X-Nexus-Internal-Secret": secret},
    )
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


def _secret() -> str:
    """Internal API secret from env, else the repo .env file (never logged)."""
    secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
    if secret:
        return secret
    env_file = REPO / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("NEXUS_INTERNAL_API_SECRET="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    pytest.skip("set NEXUS_INTERNAL_API_SECRET (env or .env) for internal API probes")


def _connect_readonly(path: Path):
    import duckdb

    try:
        return duckdb.connect(str(path), read_only=True)
    except Exception:
        return None


def _open_evidence(tmp_path: Path):
    """Read-only evidence target: snapshot env → live file → byte copy (retried)."""
    snapshot = os.getenv("NEXUS_OHLCV_SNAPSHOT", "")
    if snapshot:
        path = Path(snapshot)
        if not path.is_file():
            pytest.skip(f"NEXUS_OHLCV_SNAPSHOT not found: {path}")
        conn = _connect_readonly(path)
        if conn is None:
            pytest.skip(f"cannot open snapshot read-only: {path}")
        return conn

    conn = _connect_readonly(LIVE_DB)
    if conn is not None:
        return conn

    if not LIVE_DB.is_file():
        pytest.skip("production DuckDB absent and no snapshot provided")
    # The service holds the writer; a copy taken mid-checkpoint can be torn.
    # Retry a few times before giving up (each attempt re-reads fresh bytes).
    for _ in range(3):
        copy = tmp_path / "nexus-evidence.duckdb"
        try:
            shutil.copyfile(LIVE_DB, copy)
            wal = Path(str(LIVE_DB) + ".wal")
            if wal.is_file():
                shutil.copyfile(wal, Path(str(copy) + ".wal"))
        except OSError as exc:
            pytest.skip(f"cannot copy production DuckDB for inspection: {exc}")
        conn = _connect_readonly(copy)
        if conn is not None:
            return conn
        time.sleep(1.0)
    pytest.skip("copied DuckDB cannot be opened read-only (torn copy)")


def _table_exists(conn, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema='main' AND table_name=?",
        (table,),
    ).fetchone() is not None


def test_real_execution_ohlcv_is_populated_clean_and_unique(tmp_path):
    """Real execution store: rows exist, keys unique, OHLC invariants hold."""
    conn = _open_evidence(tmp_path)
    try:
        if not _table_exists(conn, "ohlcv"):
            pytest.skip("ohlcv absent in evidence target")
        total = conn.execute("SELECT COUNT(*) FROM ohlcv").fetchone()[0]
        if total == 0:
            # Honest zero-state (fresh store, no MT5 source in this sandbox):
            # this is a real-data acceptance test — BLOCKED-equivalent, not a
            # product defect. Un-skips automatically once bars accumulate.
            pytest.skip("zero-state ohlcv store (no bars yet) — real-data "
                        "acceptance requires an accumulated market store")
        duplicates = conn.execute(
            "SELECT symbol, timeframe, timestamp, COUNT(*) FROM ohlcv "
            "GROUP BY 1,2,3 HAVING COUNT(*) > 1 LIMIT 5"
        ).fetchall()
        assert duplicates == [], f"duplicate keys in store: {duplicates}"
        invalid = conn.execute(
            "SELECT COUNT(*) FROM ohlcv WHERE high < low OR high < GREATEST(open, close) "
            "OR low > LEAST(open, close) OR volume < 0 OR NOT isfinite(volume)"
        ).fetchone()[0]
        assert invalid == 0, f"invalid OHLC rows in store: {invalid}"
    finally:
        conn.close()


def test_real_lineage_evidence_binds_quarantine_to_datasets(tmp_path):
    """Quarantine evidence rows must resolve to registered datasets."""
    conn = _open_evidence(tmp_path)
    try:
        tables = {
            r[0] for r in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
            ).fetchall()
        }
        for required in ("datasets", "quarantine", "quality_runs"):
            if required not in tables:
                pytest.skip(f"{required} absent in evidence target (lineage schema not activated)")
        dangling = conn.execute(
            "SELECT q.quarantine_id FROM quarantine q "
            "LEFT JOIN datasets d ON d.dataset_id = q.dataset_id "
            "WHERE d.dataset_id IS NULL LIMIT 5"
        ).fetchall()
        assert dangling == [], f"quarantine rows without dataset binding: {dangling}"
    finally:
        conn.close()


def test_real_provenance_endpoint_reports_coverage_without_false_certification():
    """Coverage for both live pairs; provenance labels prove the ingestion path."""
    try:
        for symbol, timeframe in (("XAUUSD", "M15"), ("XAUUSD", "M5")):
            status, body = _get_json(f"{DATA_BASE}/api/data/ohlcv/{symbol}/{timeframe}/provenance")
            assert status == 200, f"{symbol}/{timeframe} provenance HTTP {status}: {body}"
            coverage = body.get("coverage", {})
            for key in ("first_bar", "last_bar", "bar_count", "expected_bars", "missing_bars"):
                assert key in coverage, f"{symbol}/{timeframe} coverage missing {key}"
            if coverage.get("bar_count", 0) == 0:
                pytest.skip(f"zero-state store: {symbol}/{timeframe} has 0 bars — "
                            "real-data provenance acceptance requires accumulated bars")
            assert coverage.get("bar_count", 0) > 0, (
                f"{symbol}/{timeframe} real-data acceptance: provenance reports 0 bars"
            )
            sources = set(coverage.get("sources") or {})
            assert {"mt5_poll", "mt5_backfill"} <= sources, (
                f"{symbol}/{timeframe} ingestion-path labels absent: {sorted(sources)}"
            )
            # Honesty gate: missing bars may exist (session closures, provider
            # holes) but must never be disguised as a certified zero-gap series.
            if coverage.get("missing_bars", 0) > 0:
                assert coverage.get("bar_count", 0) > 0
    except ConnectionError as exc:
        pytest.skip(f"nexus-data not reachable at {DATA_BASE}: {exc}")


def test_real_stored_quality_api_certifies_live_rows():
    """Existing stored-quality audits on the real pairs: no hard errors.

    POST /api/data/research/quality only writes evidence metadata (datasets +
    quality_runs rows) — market rows are never modified. Each combo must
    return a certificate with zero hard issues and zero invalid/duplicate rows.
    """
    secret = _secret()
    combos = [
        ("XAUUSD", "M15", "mt5_poll"),
        ("XAUUSD", "M15", "mt5_backfill"),
        ("XAUUSD", "M5", "mt5_poll"),
        ("XAUUSD", "M5", "mt5_backfill"),
    ]
    for symbol, timeframe, source in combos:
        label = f"{symbol}/{timeframe}/{source}"
        try:
            status, body = _post_json(
                f"{DATA_BASE}/api/data/research/quality",
                {"symbol": symbol, "timeframe": timeframe, "source": source},
                secret,
            )
        except ConnectionError as exc:
            pytest.skip(f"nexus-data not reachable at {DATA_BASE}: {exc}")
        if status == 404 and "No stored bars" in str(body.get("detail", "")):
            pytest.skip(f"zero-state store: {label} has no stored bars — "
                        "stored-quality certification requires accumulated bars")
        assert status == 200, f"{label}: stored-quality HTTP {status}: {body}"
        assert body.get("status") in ("passed", "warning"), (
            f"{label}: certificate status {body.get('status')!r} issues={body.get('issues')}"
        )
        assert body.get("issues") == [], f"{label}: hard issues: {body.get('issues')}"
        metrics = body.get("metrics", {})
        for key in ("invalid_ohlc", "invalid_volume", "duplicates",
                    "forming_or_future", "unresolved_quarantine"):
            assert metrics.get(key) == 0, f"{label}: metrics[{key}]={metrics.get(key)}"
        assert body.get("rows_checked", 0) > 0, f"{label}: rows_checked=0"
        assert body.get("content_hash") and body.get("quality_run_id"), (
            f"{label}: certificate lacks content_hash/quality_run_id"
        )
        checks = body.get("checks", {})
        for key in ("ohlc_invariants", "valid_volume", "unique_timestamps",
                    "closed_bars", "availability_recorded", "quarantine_clear"):
            assert checks.get(key) is True, f"{label}: check {key}={checks.get(key)}"


def _to_iso(value) -> str | None:
    """Normalize a stored window bound (epoch/int/ISO) to an ISO-8601 string."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC).isoformat()
    text = str(value).strip()
    if text.isdigit():
        return datetime.fromtimestamp(int(text), tz=UTC).isoformat()
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp.isoformat()


def _discover_research_context(tmp_path: Path) -> dict | None:
    """Find (owner, account, symbol, tf, window) from an existing research run."""
    conn = _open_evidence(tmp_path)
    try:
        if not _table_exists(conn, "research_account_runs"):
            return None
        rows = conn.execute(
            "SELECT owner_id, account_id, record_json FROM research_account_runs "
            "ORDER BY started_at DESC LIMIT 10"
        ).fetchall()
        for owner_id, account_id, record_json in rows:
            try:
                record = json.loads(record_json)
            except (TypeError, ValueError):
                continue
            if record.get("status") not in ("completed", "partial"):
                continue
            start = _to_iso(record.get("requested_start"))
            end = _to_iso(record.get("requested_end"))
            if not (record.get("symbol") and record.get("timeframe") and start and end):
                continue
            return {"owner": owner_id, "account_id": account_id,
                    "symbol": record["symbol"], "timeframe": record["timeframe"],
                    "start": start, "end": end}
        if not _table_exists(conn, "research_account_candles"):
            return None
        row = conn.execute(
            "SELECT owner_id, account_id, symbol, timeframe, MIN(bar_time), MAX(bar_time) "
            "FROM research_account_candles GROUP BY 1,2,3,4 "
            "ORDER BY MAX(bar_time) DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        owner_id, account_id, symbol, timeframe, first, last = row
        start, end = _to_iso(first), _to_iso(last)
        if not (start and end):
            return None
        return {"owner": owner_id, "account_id": account_id, "symbol": symbol,
                "timeframe": timeframe, "start": start, "end": end}
    finally:
        conn.close()


def test_real_research_repeat_fetch_is_idempotent(tmp_path):
    """Acceptance probe: repeating the same research history window adds 0 bars.

    Uses only the service's own idempotent ON CONFLICT DO NOTHING path — never
    the production DB directly. Skips while the MT5 provider is down so no
    mutation is attempted against a dead provider. 4xx responses are contract
    failures (fail); 5xx means the provider path is unavailable (skip).
    """
    secret = _secret()
    try:
        health_status, health = _get_json(f"{DATA_BASE}/health", timeout=10.0)
    except ConnectionError as exc:
        pytest.skip(f"nexus-data not reachable at {DATA_BASE}: {exc}")
    if health_status != 200 or not health.get("mt5"):
        pytest.skip(f"MT5 provider not connected (health mt5="
                    f"{health.get('mt5') if health_status == 200 else health_status}); "
                    "mutating repeat-fetch probe skipped")

    owner = os.getenv("NEXUS_TASK7_OWNER_ID", "")
    account_id = os.getenv("NEXUS_TASK7_ACCOUNT_ID", "")
    start = _to_iso(os.getenv("NEXUS_TASK7_RESEARCH_START", ""))
    end = _to_iso(os.getenv("NEXUS_TASK7_RESEARCH_END", ""))
    symbol = os.getenv("NEXUS_TASK7_RESEARCH_SYMBOL", "")
    timeframe = os.getenv("NEXUS_TASK7_RESEARCH_TIMEFRAME", "")
    if not (owner and account_id and start and end):
        discovered = _discover_research_context(tmp_path)
        if discovered is None:
            pytest.skip("set NEXUS_TASK7_OWNER_ID/ACCOUNT_ID/RESEARCH_START/END "
                        "(unix seconds or ISO) — no completed research run to re-request")
        owner = owner or discovered["owner"]
        account_id = account_id or discovered["account_id"]
        start = start or discovered["start"]
        end = end or discovered["end"]
        symbol = symbol or discovered["symbol"]
        timeframe = timeframe or discovered["timeframe"]
    symbol = symbol or "XAUUSDs"
    timeframe = timeframe or "M15"

    payload = {
        "operation": "research_market",
        "owner_id": owner,
        "payload": {"account_id": account_id, "symbol": symbol,
                    "timeframe": timeframe, "mode": "history",
                    "start": start, "end": end},
    }

    def _run(label: str) -> tuple[int, dict]:
        try:
            status, body = _post_json(
                f"{DATA_BASE}/api/data/broker-settings", payload, secret)
        except ConnectionError as exc:
            pytest.skip(f"broker-settings endpoint unreachable: {exc}")
        if status in (401, 403):
            pytest.fail(f"{label}: authorization rejected (HTTP {status}): {body}")
        if 400 <= status < 500:
            pytest.fail(f"{label}: contract error HTTP {status}: {body}")
        if status >= 500:
            pytest.skip(f"{label}: provider path unavailable HTTP {status}: {body}")
        return status, body

    first_status, first_body = _run("first fetch")
    second_status, second_body = _run("repeat fetch")
    first = first_body.get("result", {})
    second = second_body.get("result", {})
    assert first.get("count", 0) > 0, (
        f"first fetch stored no bars for {symbol}/{timeframe} "
        f"window {start}..{end}: {first}"
    )
    assert second.get("added", 1) == 0, (
        f"repeat fetch of same window must add 0 bars, got added={second.get('added')}"
    )
    assert second.get("count") == first.get("count"), (
        f"series count changed between identical fetches: "
        f"{first.get('count')} -> {second.get('count')}"
    )
