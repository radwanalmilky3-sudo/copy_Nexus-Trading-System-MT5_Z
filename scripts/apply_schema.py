"""Apply the owned DuckDB schema migrations to the configured database.

Idempotent and non-destructive: every statement is CREATE TABLE IF NOT EXISTS,
CREATE INDEX IF NOT EXISTS, or ALTER TABLE ADD COLUMN IF NOT EXISTS — the same
migrations nexus-data runs at startup — so a fresh database and an existing
one converge to the same schema. No DROP, TRUNCATE, or DELETE is ever issued.

Run by the data owner only, while nexus-data is stopped (DuckDB allows a
single writer; a running service holds the file lock). The WAL is preserved
on any failure — never delete *.wal to "fix" a lock or timeout.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.nexus_data.duckdb_store import DataStore
from services.nexus_data.fundamental_store import FundamentalStore


async def apply_owned_schema() -> None:
    store = DataStore()
    try:
        await store.init_tables()
        await FundamentalStore(store).init_schema()
    finally:
        store.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply idempotent, non-destructive DuckDB schema migrations.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="confirm you are the data owner and nexus-data is stopped",
    )
    args = parser.parse_args()

    if not args.yes and os.getenv("NEXUS_APPLY_SCHEMA_CONFIRM", "").strip() != "1":
        print(
            "refusing to run: this script writes the production DuckDB file.\n"
            "Stop nexus-data first (single-writer lock), keep a backup, then\n"
            "re-run with --yes (or set NEXUS_APPLY_SCHEMA_CONFIRM=1).",
            file=sys.stderr,
        )
        return 2

    try:
        asyncio.run(apply_owned_schema())
    except Exception as exc:
        print(f"apply_schema failed: {exc}", file=sys.stderr)
        print(
            "If the database is locked, stop nexus-data and retry. The WAL is "
            "preserved on failure — do not delete *.wal; reopen the database so "
            "DuckDB replays it.",
            file=sys.stderr,
        )
        return 1

    print("schema applied (idempotent; no destructive statements)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
