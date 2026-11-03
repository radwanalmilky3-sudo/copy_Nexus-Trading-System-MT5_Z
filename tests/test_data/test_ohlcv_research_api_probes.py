"""HTTP-equivalent research/OHLCV governance probes (Task 7 path (a)).

Task 7 verification companion to test_ohlcv_research_inventory.py: its file
probes skip with Errno 13 while the nexus-data service holds data/nexus.duckdb
(EXPECTED; never force file access). Chosen DB-gap path (a): re-express the
skipped assertions through the data-service API — all operations here are
READ-ONLY (GET endpoints, /api/data/query research_collection rows, and
whitelisted read ops on /api/data/broker-settings: list_profiles,
research_runs, research_analysis without persist).

Coverage map (inventory probe -> API equivalent here):
- probe 5  availability coverage -> test_real_research_availability_coverage_reported_via_api
- probe 6  ledger consistency    -> test_real_research_ledger_consistent_and_bound_via_api
           (+ Task 7 binding acceptance: sha256 input/output hashes, failed
           runs never carry output_hash, >=1 bound completed/partial run)
- probe 8  governance tables     -> test_real_governance_collections_readable_via_api
           (reader information_schema status for quality_runs/import_jobs/
           research_artifacts/datasets; quarantine via stored certificate
           quarantine_clear check; lineage rows are only write-committed in
           research_market.py single transaction and not API-readable)
- probe 9  backfill invariant    -> test_real_backfill_runs_never_overstate_inserted_via_api

Probes 1-4 (candle schema, key uniqueness, bar_json roundtrip, availability
orphan join) have no read API for raw research candles: they remain in the
inventory file as structural probes (single writer inserts candle+availability
rows in one transaction, research_market.py:177-178; every completed run
re-parses stored bar_json through inspect_bars, research_market.py:203).

Safety: no file access, no service control, no trading calls; skips cleanly
when nexus-data is unreachable.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DATA_BASE = "http://127.0.0.1:9001"
RUN_STATUSES = {"running", "completed", "partial", "failed"}
MODES = {"history", "live", "unified"}
HEX64 = set("0123456789abcdef")


def _secret() -> str:
    secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
    if secret:
        return secret
    env_file = REPO / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("NEXUS_INTERNAL_API_SECRET="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    pytest.skip("set NEXUS_INTERNAL_API_SECRET (env or .env) for API probes")


def _api(method: str, url: str, payload=None, secret: str = "", timeout: float = 60.0):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    if secret:
        headers["X-Nexus-Internal-Secret"] = secret
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
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


def _discover_owner(secret: str) -> str:
    try:
        status, body = _api("POST", f"{DATA_BASE}/api/data/query", {
            "operation": "users_list", "params": {},
        }, secret)
    except ConnectionError as exc:
        pytest.skip(f"nexus-data not reachable at {DATA_BASE}: {exc}")
    assert status == 200 and body.get("rows"), f"users_list HTTP {status}: {body}"
    return body["rows"][0]["user_id"]


def _broker_op(secret: str, operation: str, payload: dict, timeout: float = 60.0):
    try:
        status, body = _api("POST", f"{DATA_BASE}/api/data/broker-settings", {
            "operation": operation, "owner_id": _discover_owner(secret), "payload": payload,
        }, secret, timeout)
    except ConnectionError as exc:
        pytest.skip(f"nexus-data not reachable at {DATA_BASE}: {exc}")
    assert status == 200, f"{operation} HTTP {status}: {body}"
    return body["result"]


def _discover_research_account(secret: str):
    """(owner, account_id): first broker account that has research run records."""
    try:
        status, body = _api("POST", f"{DATA_BASE}/api/data/query", {
            "operation": "users_list", "params": {},
        }, secret)
    except ConnectionError as exc:
        pytest.skip(f"nexus-data not reachable at {DATA_BASE}: {exc}")
    assert status == 200 and body.get("rows"), f"users_list HTTP {status}: {body}"
    for user in body["rows"]:
        owner = user["user_id"]
        status, body = _api("POST", f"{DATA_BASE}/api/data/broker-settings", {
            "operation": "list_profiles", "owner_id": owner, "payload": {},
        }, secret)
        if status != 200:
            continue
        for profile in body.get("result") or []:
            for account in profile.get("accounts") or []:
                status, runs = _api("POST", f"{DATA_BASE}/api/data/broker-settings", {
                    "operation": "research_runs", "owner_id": owner,
                    "payload": {"account_id": account["account_id"]},
                }, secret)
                if status == 200 and runs.get("result"):
                    return owner, account["account_id"]
    pytest.skip("no research run records available through the API")


def _is_hex64(value) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value.lower()) <= HEX64


def test_real_research_ledger_consistent_and_bound_via_api():
    """Probe 6 equivalent + live-binding acceptance via the research_runs op.

    Re-expresses test_research_run_ledger_records_are_consistent without file
    access, and asserts Task 7 bindings: runs carry sha256 input_hash, bound
    (non-failed) runs carry sha256 output_hash, failed runs never carry an
    output_hash, and at least one bound run exists (activation evidence).
    """
    secret = _secret()
    owner, account = _discover_research_account(secret)
    records = _broker_op(secret, "research_runs", {"account_id": account})
    assert records, "research_runs returned no records"
    problems: list[str] = []
    bound = 0
    for record in records:
        run_id = str(record.get("run_id") or "?")
        if record.get("status") not in RUN_STATUSES:
            problems.append(f"{run_id}: unknown status {record.get('status')!r}")
        if record.get("mode") not in MODES:
            problems.append(f"{run_id}: unknown mode {record.get('mode')!r}")
        if record.get("status") in {"completed", "partial"}:
            for key in ("count", "received", "added", "existing"):
                if key in record and not isinstance(record[key], int):
                    problems.append(f"{run_id}: non-integer {key}")
            if record.get("count", 0) and not record.get("first"):
                problems.append(f"{run_id}: completed run without first bar")
        if record.get("input_hash") is not None and not _is_hex64(record["input_hash"]):
            problems.append(f"{run_id}: malformed input_hash")
        if record.get("output_hash") is not None and not _is_hex64(record["output_hash"]):
            problems.append(f"{run_id}: malformed output_hash")
        if record.get("status") == "failed" and record.get("output_hash"):
            problems.append(f"{run_id}: failed run must not carry output_hash")
        if record.get("input_hash") and record.get("output_hash") \
                and record.get("status") in {"completed", "partial"}:
            bound += 1
    assert problems == [], f"inconsistent research runs via API: {problems[:5]}"
    assert bound >= 1, (
        "no bound research run found (input_hash+output_hash on a completed/"
        "partial record): live activation evidence missing"
    )
    print(f"research ledger via API: {len(records)} records, {bound} bound")


def test_real_backfill_runs_never_overstate_inserted_via_api():
    """Probe 9 equivalent: provenance recent_backfill_runs inserted<=found."""
    secret = _secret()
    checked = 0
    for symbol, timeframe in (("XAUUSD", "M15"), ("XAUUSD", "M5")):
        try:
            status, body = _api("GET", f"{DATA_BASE}/api/data/ohlcv/{symbol}/{timeframe}/provenance")
        except ConnectionError as exc:
            pytest.skip(f"nexus-data not reachable at {DATA_BASE}: {exc}")
        assert status == 200, f"{symbol}/{timeframe} provenance HTTP {status}: {body}"
        runs = (body.get("recent_backfill_runs") or [])
        bad = [r for r in runs
               if isinstance(r.get("bars_inserted"), int) and isinstance(r.get("bars_found"), int)
               and r["bars_inserted"] > r["bars_found"]]
        assert bad == [], f"{symbol}/{timeframe} backfill runs inserted>found: {bad}"
        checked += len(runs)
    assert checked > 0, "no recent backfill runs reported by provenance"
    print(f"backfill invariant via API: {checked} runs checked")


def test_real_research_availability_coverage_reported_via_api():
    """Probe 5 equivalent: availability gaps surfaced per series, never hidden."""
    secret = _secret()
    owner, account = _discover_research_account(secret)
    report = _broker_op(secret, "research_analysis", {"account_id": account, "timeframe": "M15"}, 120.0)
    datasets = report.get("datasets") or []
    if not any(entry.get("rows", 0) > 0 for entry in datasets):
        pytest.skip("research_analysis reports no stored rows for any asset")
    gaps: dict[str, int] = {}
    for entry in datasets:
        symbol = entry.get("symbol") or "?"
        rows = entry.get("rows") or 0
        known = entry.get("availability_known")
        assert entry.get("status") in {"stored", "missing"}, f"{symbol}: status={entry.get('status')!r}"
        if rows <= 0:
            continue
        assert isinstance(known, int), f"{symbol}: availability_known not reported"
        assert 0 <= known <= rows, f"{symbol}: availability_known={known} rows={rows}"
        if known < rows:
            gaps[symbol] = rows - known
    prov = report.get("provenance") or []
    assert prov, "research_analysis returned no provenance entries"
    for entry in prov:
        assert isinstance(entry.get("total"), int), f"{entry.get('symbol')}: total missing"
        assert "availability_known" in entry, f"{entry.get('symbol')}: availability_known missing"
    print(f"availability coverage via API (reported, not hidden): gaps={gaps or 'none'}")


def test_real_governance_collections_readable_via_api():
    """Probe 8 equivalent: governance tables reachable through the reader API.

    quality_runs/import_jobs/research_artifacts/datasets existence is the
    reader's information_schema status; per-group stored certificates prove
    quality_runs rows incl. quarantine_clear; a researchqr: certificate proves
    the research-run evidence writes. lineage rows are only write-committed
    (single transaction, research_market.py single commit) and not
    API-readable.
    """
    secret = _secret()

    def collection(resource: str, query=None) -> dict:
        try:
            status, body = _api("POST", f"{DATA_BASE}/api/data/query", {
                "operation": "research_collection",
                "params": {"resource": resource, "limit": 100, "offset": 0, "query": query},
            }, secret)
        except ConnectionError as exc:
            pytest.skip(f"nexus-data not reachable at {DATA_BASE}: {exc}")
        assert status == 200 and body.get("rows"), f"{resource} query HTTP {status}: {body}"
        return body["rows"][0]

    datasets = collection("datasets")
    assert datasets["status"] == "available", f"datasets reader status={datasets['status']}"
    groups = [item for item in datasets.get("items") or [] if (item.get("row_count") or 0) > 0]
    assert groups, "no dataset groups with rows>0"

    quality = collection("quality_runs")
    assert quality["status"] == "available", f"quality_runs reader status={quality['status']}"
    assert (quality.get("total") or 0) > 0, "quality_runs table is empty"
    for resource in ("import_jobs", "artifacts"):
        result = collection(resource)
        assert result["status"] == "available", f"{resource} reader status={result['status']}"

    for item in groups:
        cert = collection("quality_runs", item["dataset_id"])
        items = [c for c in cert.get("items") or []
                 if c.get("scope") == "stored_ohlcv_basic_v1"]
        assert items, f"no stored_ohlcv_basic_v1 certificate for {item['dataset_id']}"
        latest = items[0]
        assert latest.get("status") in {"passed", "warning"}, (
            f"{item['dataset_id']}: latest cert status={latest.get('status')!r}"
        )
        assert (latest.get("rows_checked") or 0) > 0, f"{item['dataset_id']}: rows_checked=0"
        assert _is_hex64(latest.get("content_hash")), f"{item['dataset_id']}: bad content_hash"
        checks = latest.get("checks") or {}
        if "quarantine_clear" in checks:
            assert checks["quarantine_clear"] is True, (
                f"{item['dataset_id']}: quarantine_clear={checks['quarantine_clear']}"
            )

    research_certs = collection("quality_runs", "researchqr:")
    assert any(str(c.get("quality_run_id", "")).startswith("researchqr:")
               for c in research_certs.get("items") or []), (
        "no researchqr: certificate rows via API (research evidence writes missing)"
    )
    print(f"governance via API: {len(groups)} certified groups, "
          f"quality_runs total={quality.get('total')}")
