"""Trace startup writes on an explicitly supplied temporary DuckDB copy."""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import tempfile

from services.nexus_data.duckdb_store import DataStore
from services.nexus_data.fundamental_store import FundamentalStore
from services.nexus_news.fundamental.bootstrap_v5 import (
    asset_factor_profile_records, asset_records, indicator_catalog_records, knowledge_seed,
)
from services.nexus_news.fundamental.source_registry import OFFICIAL_SOURCES


async def main(path: Path) -> None:
    path = path.resolve()
    if not path.is_relative_to(Path(tempfile.gettempdir()).resolve()) or not path.is_file():
        raise ValueError("only an existing database copy in the temporary directory is allowed")
    store = DataStore(str(path))
    try:
        await store.init_tables()
        fundamental = FundamentalStore(store)
        await fundamental.init_schema()
        for source in OFFICIAL_SOURCES:
            print("SOURCE", source.source_id, flush=True)
            await fundamental.upsert_source(source.as_record())
        sources, claims = knowledge_seed()
        for table, rows in [
            ("economic_indicator_catalog", indicator_catalog_records()),
            ("asset_registry", asset_records()),
            ("asset_factor_profiles", asset_factor_profile_records()),
            ("fundamental_knowledge_sources", sources),
            ("fundamental_knowledge_claims", claims),
        ]:
            for row in rows:
                identity = next(iter(row.values()))
                print("WRITE", table, identity, flush=True)
                await fundamental.insert_record(table, row)
                print("OK", table, identity, flush=True)
        print("STARTUP_SEED_PASSED", flush=True)
    finally:
        await store.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    asyncio.run(main(parser.parse_args().db))
