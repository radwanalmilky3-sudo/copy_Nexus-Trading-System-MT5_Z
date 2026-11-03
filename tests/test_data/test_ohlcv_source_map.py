"""Static source-map invariants for OHLCV producers, consumers, and DDL.

Read-only: scans repository sources only. No database, network, or service I/O.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SERVICES = REPO / "services"

SANCTIONED_OHLCV_WRITERS = frozenset({
    "nexus_data/duckdb_store.py",
    "nexus_data/quality/repair.py",
})

WRITE_PATTERNS = (
    re.compile(r"\bINSERT\s+INTO\s+ohlcv\b", re.IGNORECASE),
    re.compile(r"\bUPDATE\s+ohlcv\b", re.IGNORECASE),
    re.compile(r"\bDELETE\s+FROM\s+ohlcv\b", re.IGNORECASE),
)

CREATE_PATTERN = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?ohlcv\b", re.IGNORECASE)

DDL_COLUMN_PATTERN = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?ohlcv\s*\((.*?)\)",
    re.IGNORECASE | re.DOTALL,
)
COLUMN_PATTERN = re.compile(r"^\s*([a-z_]+)\s+[a-z]", re.IGNORECASE | re.MULTILINE)


def _service_sources() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for path in sorted(SERVICES.rglob("*.py")):
        rel = path.relative_to(SERVICES).as_posix()
        out.append((rel, path.read_text(encoding="utf-8")))
    return out


def _ohlcv_columns(source: str) -> set[str]:
    match = DDL_COLUMN_PATTERN.search(source)
    if match is None:
        return set()
    return {m.group(1).lower() for m in COLUMN_PATTERN.finditer(match.group(1))}


def test_ohlcv_write_statements_only_in_sanctioned_files():
    violations: list[str] = []
    for rel, source in _service_sources():
        for pattern in WRITE_PATTERNS:
            if pattern.search(source) and rel not in SANCTIONED_OHLCV_WRITERS:
                violations.append(f"{rel}: {pattern.pattern}")
    assert violations == [], f"unsanctioned ohlcv writers: {violations}"


def test_ohlcv_create_table_only_in_data_store():
    creators = [rel for rel, source in _service_sources() if CREATE_PATTERN.search(source)]
    assert creators == ["nexus_data/duckdb_store.py"]


def test_insert_ohlcv_batch_callers_are_data_service_only():
    callers: set[str] = set()
    pattern = re.compile(r"\binsert_ohlcv_batch\s*\(")
    for rel, source in _service_sources():
        for line in source.splitlines():
            if pattern.search(line) and not line.lstrip().startswith(("async def", "def")):
                callers.add(rel)
    assert callers == {"nexus_data/main.py"}


def test_query_ohlcv_callers_stay_in_data_and_agent_boundaries():
    callers: set[str] = set()
    pattern = re.compile(r"\bquery_ohlcv\s*\(")
    for rel, source in _service_sources():
        for line in source.splitlines():
            if pattern.search(line) and not line.lstrip().startswith(("async def", "def")):
                callers.add(rel)
    assert callers == {"nexus_data/main.py"}


def test_data_store_ddl_exposes_pit_columns():
    source = (SERVICES / "nexus_data" / "duckdb_store.py").read_text(encoding="utf-8")
    columns = _ohlcv_columns(source)
    assert {
        "symbol", "timeframe", "open", "high", "low", "close", "volume",
        "timestamp", "source", "quality", "fetched_at",
    } <= columns
    store_source = source
    assert "ADD COLUMN IF NOT EXISTS available_at" in store_source
    assert "ADD COLUMN IF NOT EXISTS revision" in store_source


def test_legacy_shared_ddl_diverges_from_authoritative_store():
    """Document the known schema split: shared client vs DataStore."""
    shared = (REPO / "shared" / "duckdb_client.py").read_text(encoding="utf-8")
    store = (SERVICES / "nexus_data" / "duckdb_store.py").read_text(encoding="utf-8")
    shared_cols = _ohlcv_columns(shared)
    store_cols = _ohlcv_columns(store)
    assert "ts" in shared_cols
    assert "timestamp" in store_cols
    assert "available_at" not in shared_cols
    assert store_cols - shared_cols >= {"source", "quality", "fetched_at"}


def test_pit_keyword_contract_present_on_query_ohlcv():
    import inspect

    from services.nexus_data.duckdb_store import DataStore

    params = inspect.signature(DataStore.query_ohlcv).parameters
    assert "available_through" in params
    assert "max_staleness_s" in params
    assert hasattr(DataStore, "fingerprint_ohlcv")
    assert hasattr(DataStore, "query_ohlcv_provenance")
    assert hasattr(DataStore, "plan_backfill_intervals")
    assert hasattr(DataStore, "get_ohlcv_coverage")


def test_research_candle_tables_are_lazy_and_owner_scoped():
    research_market = (SERVICES / "nexus_data" / "research_market.py").read_text(encoding="utf-8")
    data_loader = (SERVICES / "nexus_data" / "data_loader.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS research_account_candles" in research_market
    assert "CREATE TABLE IF NOT EXISTS research_candle_availability" in research_market
    assert "store.owner_store._conn" in research_market
    assert "research_account_candles" in data_loader
    assert "point_in_time" in data_loader


def test_lineage_migration_file_defines_governance_tables():
    migration = (
        SERVICES / "nexus_data" / "migrations" / "research_lineage_001.sql"
    ).read_text(encoding="utf-8")
    lowered = migration.lower()
    for table in ("datasets", "import_jobs", "quality_runs", "quarantine", "lineage"):
        assert table in lowered, f"missing governance table {table}"


def test_repair_module_never_invents_ohlc_values():
    repair = (SERVICES / "nexus_data" / "quality" / "repair.py").read_text(encoding="utf-8")
    assert "Archive before removing; never invent OHLCV values" in repair
    assert "auto_conflict" in repair
    assert "auto_duplicate" in repair
    assert "auto_invalid" in repair
    assert "auto_forming" in repair


@pytest.mark.parametrize("consumer", [
    "nexus_data/research_reader.py",
    "nexus_data/quality/automation.py",
    "nexus_data/quality/stored_audit.py",
    "nexus_data/quality/session_quality.py",
    "nexus_data/research_analysis.py",
])
def test_declared_research_consumers_exist(consumer):
    assert (SERVICES / consumer).is_file()
