from __future__ import annotations

from pathlib import Path

import pytest

SQL_PATH = (
    Path(__file__).resolve().parents[2]
    / "services"
    / "nexus_data"
    / "migrations"
    / "research_lineage_001.sql"
)

EXPECTED_TABLES = (
    "datasets",
    "import_jobs",
    "quality_runs",
    "quarantine",
    "lineage",
    "research_artifacts",
)

ALLOWED_PREFIXES = ("CREATE TABLE IF NOT EXISTS", "CREATE INDEX IF NOT EXISTS")


def _statements(sql_text: str) -> list[str]:
    lines: list[str] = []
    for line in sql_text.splitlines():
        stripped = line.split("--", 1)[0].strip()
        if stripped:
            lines.append(stripped)
    joined = " ".join(lines)
    return [s.strip() for s in joined.split(";") if s.strip()]


def test_migration_file_exists_and_is_additive_only():
    assert SQL_PATH.is_file(), f"missing migration: {SQL_PATH}"
    sql_text = SQL_PATH.read_text(encoding="utf-8")

    upper = sql_text.upper()
    for forbidden in ("DROP ", "DELETE ", "TRUNCATE", "ALTER TABLE"):
        assert forbidden not in upper, f"migration must not contain {forbidden.strip()}"

    statements = _statements(sql_text)
    assert statements, "migration has no executable statements"
    for statement in statements:
        assert statement.upper().startswith(
            ALLOWED_PREFIXES
        ), f"unexpected statement: {statement[:80]}"


def test_migration_creates_expected_tables_statistically():
    sql_text = SQL_PATH.read_text(encoding="utf-8")
    upper = sql_text.upper()
    for table in EXPECTED_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}".upper() in upper, table


def test_migration_applies_against_in_memory_duckdb():
    duckdb = pytest.importorskip("duckdb")

    sql_text = SQL_PATH.read_text(encoding="utf-8")
    conn = duckdb.connect(":memory:")
    try:
        conn.execute(sql_text)
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
        present = {row[0] for row in rows}
        for table in EXPECTED_TABLES:
            assert table in present, f"table not created: {table}"

        conn.execute(sql_text)
        rows_after = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
        assert {row[0] for row in rows_after} == present
    finally:
        conn.close()
