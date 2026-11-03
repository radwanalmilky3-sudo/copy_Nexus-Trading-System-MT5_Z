import argparse
import re
import shutil
import sys
import time
from pathlib import Path

import duckdb

FAILING_ROW_ID = "econobs-3592cd5acfcfbef7e31c1a66"
PK_COL = "observation_id"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def diagnose(db: Path, table: str) -> dict:
    conn = duckdb.connect(str(db), read_only=True)
    try:
        info = conn.execute(
            "SELECT sql FROM duckdb_tables() WHERE table_name = ?", [table]
        ).fetchone()
        indexes = conn.execute(
            "SELECT index_name, sql FROM duckdb_indexes() WHERE table_name = ?",
            [table],
        ).fetchall()
        count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        fks = conn.execute(
            "SELECT table_name, constraint_text FROM duckdb_constraints() "
            "WHERE constraint_type = 'FOREIGN KEY' AND constraint_text LIKE ?",
            [f"%REFERENCES {table}%"],
        ).fetchall()
        pk_row = conn.execute(
            "SELECT constraint_text FROM duckdb_constraints() "
            "WHERE table_name = ? AND constraint_type = 'PRIMARY KEY'",
            [table],
        ).fetchone()
        pk = PK_COL
        if pk_row:
            m = re.search(r"PRIMARY\s+KEY\s*\(\s*\"?(\w+)\"?", pk_row[0], re.IGNORECASE)
            if m:
                pk = m.group(1)
        row = conn.execute(
            f'SELECT * FROM "{table}" WHERE "{pk}" = ?', [FAILING_ROW_ID]
        ).fetchall()
    finally:
        conn.close()
    return {
        "table_ddl": info[0] if info else None,
        "indexes": indexes,
        "count": count,
        "fks": fks,
        "pk": pk,
        "failing_row_found": len(row),
    }


def rebuild(db: Path, table: str, ddl: str, index_ddls: list[str]) -> list[str]:
    tmp = f"{table}__repair_tmp"
    m = re.search(r"(CREATE\s+TABLE\s+)(\"?[\w.]+\"?)", ddl, re.IGNORECASE)
    if not m:
        raise RuntimeError(f"cannot parse table DDL: {ddl[:120]}")
    tmp_ddl = ddl[: m.start(2)] + tmp + ddl[m.end(2) :]
    problems: list[str] = []
    conn = duckdb.connect(str(db))
    try:
        conn.execute(f'DROP TABLE IF EXISTS "{tmp}"')
        log(f"create tmp table {tmp}")
        conn.execute(tmp_ddl)
        log(f"copy rows into tmp from {table}")
        conn.execute(f'INSERT INTO "{tmp}" SELECT * FROM "{table}"')
        tmp_count = conn.execute(f'SELECT COUNT(*) FROM "{tmp}"').fetchone()[0]
        log(f"tmp rows: {tmp_count}")
        log(f"drop {table} (frees index names)")
        conn.execute(f'DROP TABLE "{table}"')
        log(f"rename {tmp} -> {table}")
        conn.execute(f'ALTER TABLE "{tmp}" RENAME TO "{table}"')
        for idx_ddl in index_ddls:
            if not idx_ddl:
                continue
            try:
                log(f"recreate index: {idx_ddl[:100]}")
                conn.execute(idx_ddl)
            except Exception as exc:
                problems.append(f"{idx_ddl[:80]} -> {exc}")
                log(f"index recreate issue: {exc}")
        present = {
            r[0]
            for r in conn.execute(
                "SELECT index_name FROM duckdb_indexes() WHERE table_name = ?",
                [table],
            ).fetchall()
        }
        log(f"indexes present after rebuild: {sorted(present)}")
    finally:
        conn.close()
    return problems


def exercise_delete(db: Path, table: str, pk: str) -> None:
    conn = duckdb.connect(str(db))
    try:
        row = conn.execute(
            f'SELECT * FROM "{table}" WHERE "{pk}" = ?', [FAILING_ROW_ID]
        ).fetchall()
        before = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        log(f"row present before delete test: {len(row)} (total {before})")
        conn.execute(f'DELETE FROM "{table}" WHERE "{pk}" = ?', [FAILING_ROW_ID])
        mid = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        log(f"delete on previously failing id succeeded (total {before} -> {mid})")
        if row:
            conn.execute(
                f'INSERT INTO "{table}" VALUES ({", ".join(["?"] * len(row[0]))})',
                list(row[0]),
            )
            after = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            log(f"row restored after delete test (total {after})")
    finally:
        conn.close()


def main() -> int:
    p = argparse.ArgumentParser(description="Rebuild corrupt table index in nexus.duckdb")
    p.add_argument("--db", default="data/nexus.duckdb")
    p.add_argument("--table", default="economic_indicator_observations")
    p.add_argument("--diagnose", action="store_true")
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()

    db = Path(args.db).resolve()
    if not db.is_file():
        log(f"db not found: {db}")
        return 2
    if not args.diagnose and not args.apply:
        log("choose --diagnose or --apply")
        return 2

    d = diagnose(db, args.table)
    log(f"table DDL: {(d['table_ddl'] or 'MISSING')[:160]}")
    log(f"indexes: {[(i[0], (i[1] or '')[:60]) for i in d['indexes']]}")
    log(f"rows: {d['count']}; pk: {d['pk']}; failing row present: {d['failing_row_found']}")
    log(f"FKs FROM other tables referencing this table: {d['fks']}")
    if not d["table_ddl"]:
        log("table missing or unreadable")
        return 3
    if d["fks"]:
        log(f"ABORT: FKs reference this table: {d['fks']}")
        return 4
    if args.diagnose:
        return 0

    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup = db.with_name(f"backup_{args.table}_{stamp}.duckdb")
    shutil.copy2(db, backup)
    wal = db.with_suffix(".duckdb.wal")
    if wal.is_file():
        shutil.copy2(wal, backup.with_name(backup.name + ".wal"))
    log(f"backup created: {backup}")

    index_ddls = [i[1] for i in d["indexes"]]
    problems = rebuild(db, args.table, d["table_ddl"], index_ddls)
    exercise_delete(db, args.table, d["pk"])

    d2 = diagnose(db, args.table)
    log(f"post-repair rows: {d2['count']} (was {d['count']})")
    if d2["count"] != d["count"]:
        log("FAIL: row count mismatch")
        return 5
    if problems:
        log(f"REPAIR OK WITH INDEX NOTES: {problems}")
        return 0
    log("REPAIR OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
