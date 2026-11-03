import argparse
import re
import shutil
import sys
import time
from pathlib import Path

import duckdb

def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def capture(src):
    tables = src.execute(
        "SELECT table_name, sql FROM duckdb_tables() "
        "WHERE NOT internal AND schema_name='main' ORDER BY table_name"
    ).fetchall()
    fks = src.execute(
        "SELECT table_name, constraint_text FROM duckdb_constraints() "
        "WHERE constraint_type='FOREIGN KEY' AND schema_name='main'"
    ).fetchall()
    indexes = src.execute(
        "SELECT index_name, table_name, sql FROM duckdb_indexes() "
        "WHERE sql IS NOT NULL AND schema_name='main'"
    ).fetchall()
    views = src.execute(
        "SELECT view_name, sql FROM duckdb_views() "
        "WHERE NOT internal AND schema_name='main'"
    ).fetchall()
    sequences = src.execute(
        "SELECT sequence_name, sql FROM duckdb_sequences() "
        "WHERE schema_name='main'"
    ).fetchall()
    counts = {t: src.execute(f'SELECT COUNT(*) FROM main."{t}"').fetchone()[0] for t, _ in tables}
    return {
        "tables": tables,
        "fks": fks,
        "indexes": indexes,
        "views": views,
        "sequences": sequences,
        "counts": counts,
    }

def topo_order(tables, fks):
    deps = {t: set() for t, _ in tables}
    names = set(deps)
    for tbl, text in fks:
        if tbl not in deps or not text:
            continue
        m = re.search(r"REFERENCES\s+\"?([\w]+)\"?", text, re.IGNORECASE)
        if m and m.group(1) in names and m.group(1) != tbl:
            deps[tbl].add(m.group(1))
    order, seen, temp = [], set(), set()

    def visit(n):
        if n in seen:
            return
        if n in temp:
            raise RuntimeError(f"FK cycle involving {n}")
        temp.add(n)
        for d in sorted(deps.get(n, ())):
            visit(d)
        temp.discard(n)
        seen.add(n)
        order.append(n)

    for t, _ in tables:
        visit(t)
    return order, deps

def probe_delete_ok(conn, table: str) -> tuple[bool, str]:
    pk_row = conn.execute(
        "SELECT constraint_text FROM duckdb_constraints() "
        "WHERE table_name=? AND constraint_type='PRIMARY KEY' AND schema_name='main'",
        [table],
    ).fetchone()
    if not pk_row:
        m = re.search(r"PRIMARY\s+KEY\s*\(\s*\"?(\w+\"?)", pk_row[0]) if pk_row else None
        return True, "no pk"
    m = re.search(r"PRIMARY\s+KEY\s*\(\s*\"?(\w+)\"?", pk_row[0], re.IGNORECASE)
    if not m:
        return False, f"cannot parse pk: {pk_row[0]}"
    pk = m.group(1)
    row = conn.execute(f'SELECT "{pk}" FROM main."{table}" LIMIT 1').fetchone()
    if not row:
        return True, "empty table"
    try:
        conn.execute("BEGIN TRANSACTION")
        conn.execute(f'DELETE FROM main."{table}" WHERE "{pk}" = ?', [row[0]])
        conn.execute(
            f'INSERT INTO main."{table}" SELECT * FROM main."{table}" WHERE 1=0'
        )
        conn.execute("ROLLBACK")
        return True, "delete probe ok"
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        return False, str(exc)[:200]

def probe_delete_restore(conn, table: str) -> tuple[bool, str]:
    pk_row = conn.execute(
        "SELECT constraint_text FROM duckdb_constraints() "
        "WHERE table_name=? AND constraint_type='PRIMARY KEY' AND schema_name='main'",
        [table],
    ).fetchone()
    if not pk_row:
        return True, "no pk"
    m = re.search(r"PRIMARY\s+KEY\s*\(\s*\"?(\w+)\"?", pk_row[0], re.IGNORECASE)
    if not m:
        return False, "cannot parse pk"
    pk = m.group(1)
    pk_val_row = conn.execute(f'SELECT "{pk}" FROM main."{table}" LIMIT 1').fetchone()
    if pk_val_row is None:
        return True, "empty"
    row = conn.execute(
        f'SELECT * FROM main."{table}" WHERE "{pk}" = ?', [pk_val_row[0]]
    ).fetchone()
    val = pk_val_row[0]
    if row is None:
        return True, "empty"
    try:
        conn.execute("BEGIN TRANSACTION")
        conn.execute(f'DELETE FROM main."{table}" WHERE "{pk}" = ?', [val])
        conn.execute(
            f'INSERT INTO main."{table}" VALUES ({", ".join(["?"] * len(row))})',
            list(row),
        )
        conn.execute("COMMIT")
        return True, "delete+restore ok"
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        return False, str(exc)[:220]

def build(src_path: Path, dst_path: Path) -> dict:
    if dst_path.exists():
        dst_path.unlink()
    dst = duckdb.connect(str(dst_path))
    summary = {"tables": 0, "rows": 0, "views_ok": 0, "views_fail": [], "indexes": 0}
    try:
        dst.execute(f"ATTACH '{src_path.as_posix()}' AS src (READ_ONLY)")
        cur = dst.execute(
            "SELECT table_name, sql FROM duckdb_tables() "
            "WHERE NOT internal AND schema_name='main' AND database_name='src' "
            "ORDER BY table_name"
        ).fetchall()
        fks = dst.execute(
            "SELECT table_name, constraint_text FROM duckdb_constraints() "
            "WHERE constraint_type='FOREIGN KEY' AND schema_name='main' AND database_name='src'"
        ).fetchall()
        indexes = dst.execute(
            "SELECT index_name, table_name, sql FROM duckdb_indexes() "
            "WHERE sql IS NOT NULL AND schema_name='main' AND database_name='src'"
        ).fetchall()
        views = dst.execute(
            "SELECT view_name, sql FROM duckdb_views() "
            "WHERE NOT internal AND schema_name='main' AND database_name='src'"
        ).fetchall()
        sequences = dst.execute(
            "SELECT sequence_name, sql FROM duckdb_sequences() "
            "WHERE schema_name='main' AND database_name='src'"
        ).fetchall()
        counts = {t: dst.execute(f'SELECT COUNT(*) FROM src.main."{t}"').fetchone()[0] for t, _ in cur}
        log(f"captured: tables={len(cur)} indexes={len(indexes)} views={len(views)} seq={len(sequences)}")

        for _, sql in sequences:
            log(f"create sequence: {sql[:90]}")
            dst.execute(sql)

        order, _ = topo_order(cur, fks)
        log(f"table order: {order}")
        for t in order:
            ddl = dict(cur)[t]
            log(f"create {t} ({counts[t]} rows)")
            dst.execute(ddl)
            dst.execute(f'INSERT INTO main."{t}" SELECT * FROM src.main."{t}"')
            got = dst.execute(f'SELECT COUNT(*) FROM main."{t}"').fetchone()[0]
            if got != counts[t]:
                raise RuntimeError(f"row mismatch {t}: {got} != {counts[t]}")
            summary["tables"] += 1
            summary["rows"] += got

        existing = {
            r[0]
            for r in dst.execute(
                "SELECT index_name FROM main.duckdb_indexes() WHERE schema_name='main'"
            ).fetchall()
        }
        for iname, itbl, isql in indexes:
            if iname in existing:
                log(f"skip index (already created with table): {iname}")
                continue
            try:
                dst.execute(isql)
                summary["indexes"] += 1
                log(f"create index {iname}")
            except Exception as exc:
                log(f"index {iname} issue: {exc}")

        pending = list(views)
        for _round in range(5):
            if not pending:
                break
            still = []
            for vname, vsql in pending:
                try:
                    dst.execute(vsql)
                    summary["views_ok"] += 1
                    log(f"create view {vname}")
                except Exception:
                    still.append((vname, vsql))
            if len(still) == len(pending):
                break
            pending = still
        summary["views_fail"] = [v[0] for v in pending]
    finally:
        dst.close()
    return summary

def main() -> int:
    p = argparse.ArgumentParser(description="Rebuild nexus.duckdb into a clean file")
    p.add_argument("--db", default="data/nexus.duckdb")
    p.add_argument("--out", default="data/nexus_rebuilt.duckdb")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--no-swap", action="store_true")
    args = p.parse_args()

    db = Path(args.db).resolve()
    out = Path(args.out).resolve()
    if not db.is_file():
        log(f"missing {db}")
        return 2

    if not args.apply:
        conn = duckdb.connect(str(db), read_only=True)
        cap = capture(conn)
        conn.close()
        log(f"tables={len(cap['tables'])} rows_total={sum(cap['counts'].values())} "
            f"indexes={len(cap['indexes'])} views={len(cap['views'])} seq={len(cap['sequences'])}")
        for t, c in sorted(cap["counts"].items()):
            log(f"  {t}: {c}")
        return 0

    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup = db.with_name(f"backup_full_{stamp}.duckdb")
    shutil.copy2(db, backup)
    wal = Path(str(db) + ".wal")
    if wal.is_file():
        shutil.copy2(wal, Path(str(backup) + ".wal"))
    log(f"pre-rebuild backup: {backup}")

    conn = duckdb.connect(str(db))
    try:
        conn.execute("CHECKPOINT")
        log("source checkpointed (wal folded)")
    finally:
        conn.close()

    summary = build(db, out)
    log(f"built: {summary}")

    v = duckdb.connect(str(out))
    try:
        for tbl in ("economic_indicator_observations", "asset_event_outcomes"):
            ok, msg = probe_delete_restore(v, tbl)
            log(f"probe {tbl}: ok={ok} ({msg})")
            if not ok:
                log("FAIL probe")
                return 5
    finally:
        v.close()

    if args.no_swap:
        log(f"rebuilt file ready at {out} (no swap)")
        return 0

    superseded = db.with_name(f"nexus.duckdb.superseded_{stamp}")
    db.rename(superseded)
    if wal.is_file():
        wal.rename(Path(str(superseded) + ".wal"))
    out.rename(db)
    out_wal = Path(str(out) + ".wal")
    if out_wal.is_file():
        out_wal.rename(wal)
    log(f"swapped: old -> {superseded.name}; new -> {db.name}")

    final = duckdb.connect(str(db), read_only=True)
    try:
        total = sum(
            final.execute(f'SELECT COUNT(*) FROM main."{t}"').fetchone()[0]
            for t, _ in final.execute(
                "SELECT table_name, sql FROM duckdb_tables() WHERE NOT internal AND schema_name='main'"
            ).fetchall()
        )
        log(f"final db rows total: {total}")
    finally:
        final.close()
    log("REBUILD OK")
    return 0

if __name__ == "__main__":
    sys.exit(main())
