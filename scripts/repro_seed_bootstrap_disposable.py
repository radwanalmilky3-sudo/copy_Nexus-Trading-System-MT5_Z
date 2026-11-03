"""Reproduce repeated fundamental seeding only on explicitly disposable DB copies.

This script never resolves or opens the configured production database. The
caller must provide a DuckDB file inside a fresh temporary directory.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path

import duckdb

from services.nexus_data.duckdb_store import DataStore
from services.nexus_data.fundamental_store import FundamentalStore
from services.nexus_news.fundamental.bootstrap_v5 import (
    asset_factor_profile_records,
    asset_records,
    indicator_catalog_records,
    knowledge_seed,
)


def _snapshot(conn: duckdb.DuckDBPyConnection) -> dict[str, object]:
    tables = [r[0] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='main' ORDER BY table_name"
    ).fetchall()]
    result: dict[str, object] = {"tables": tables}
    for table in ("ohlcv", "ticks", "economic_indicator_catalog",
                  "asset_registry", "asset_factor_profiles",
                  "fundamental_knowledge_sources", "fundamental_knowledge_claims"):
        if table in tables:
            result[f"rows:{table}"] = conn.execute(
                f'SELECT COUNT(*) FROM "{table}"'
            ).fetchone()[0]
    if "ohlcv" in tables:
        result["ohlcv_null_fetched_at"] = conn.execute(
            "SELECT COUNT(*) FROM ohlcv WHERE fetched_at IS NULL"
        ).fetchone()[0]
    if "ticks" in tables:
        result["ticks_null_fetched_at"] = conn.execute(
            "SELECT COUNT(*) FROM ticks WHERE fetched_at IS NULL"
        ).fetchone()[0]
    indexes = conn.execute(
        "SELECT index_name, table_name, sql FROM duckdb_indexes() "
        "WHERE schema_name='main' ORDER BY table_name,index_name"
    ).fetchall()
    constraints = conn.execute(
        "SELECT table_name,constraint_type,constraint_text "
        "FROM duckdb_constraints() WHERE schema_name='main' "
        "ORDER BY table_name,constraint_index"
    ).fetchall()
    result["indexes"] = [list(row) for row in indexes]
    result["constraints"] = [list(row) for row in constraints]
    if "ohlcv_manifests" in tables:
        result["ohlcv_manifests"] = [list(row) for row in conn.execute(
            "SELECT symbol,timeframe,row_count,content_hash,available_through "
            "FROM ohlcv_manifests ORDER BY symbol,timeframe"
        ).fetchall()]
    return result


async def _seed(store: DataStore, fundamental: FundamentalStore) -> None:
    for row in indicator_catalog_records():
        await fundamental.insert_record("economic_indicator_catalog", row)
    for row in asset_records():
        await fundamental.insert_record("asset_registry", row)
    for row in asset_factor_profile_records():
        await fundamental.insert_record("asset_factor_profiles", row)
    sources, claims = knowledge_seed()
    for row in sources:
        await fundamental.insert_record("fundamental_knowledge_sources", row)
    for row in claims:
        await fundamental.insert_record("fundamental_knowledge_claims", row)


async def run(db_path: Path, rounds: int) -> dict[str, object]:
    db_path = db_path.resolve()
    temporary_root = Path(tempfile.gettempdir()).resolve()
    if not db_path.is_relative_to(temporary_root):
        raise ValueError("--db must be a disposable copy inside the system temporary directory")
    if not db_path.is_file() or db_path.suffix.lower() != ".duckdb":
        raise ValueError("--db must name an existing disposable .duckdb file")
    if os.getenv("NEXUS_ALLOW_DISPOSABLE_DB_REPRO") != "1":
        raise RuntimeError("Set NEXUS_ALLOW_DISPOSABLE_DB_REPRO=1 to confirm disposable target")
    store = DataStore(db_path=str(db_path))
    try:
        await store.init_tables()
        fundamental = FundamentalStore(store)
        await fundamental.init_schema()
        snapshots: list[dict[str, object]] = []
        # Exercise seed persistence directly through FundamentalStore on the
        # disposable copy. This does not exercise the HTTP transport.
        for iteration in range(rounds + 1):
            snapshots.append({"iteration": iteration, "db": _snapshot(store._conn)})
            if iteration < rounds:
                await _seed(store, fundamental)
        return {"database": str(db_path), "rounds": rounds, "snapshots": snapshots}
    finally:
        await store.aclose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.rounds <= 10:
        parser.error("--rounds must be between 1 and 10")
    print(json.dumps(asyncio.run(run(args.db, args.rounds)), default=str, indent=2))


if __name__ == "__main__":
    main()
