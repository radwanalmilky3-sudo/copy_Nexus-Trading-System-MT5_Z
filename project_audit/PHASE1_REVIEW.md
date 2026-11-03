# Phase 1 Review — Data Safety (NEXUS_MASTER_PLAN)

**Reviewer:** R1  **Date:** 2026-10-18  **Scope:** C1 `services/nexus_data/duckdb_store.py` + `tests/test_data/test_quality_gate.py`; C2 `services/nexus_data/main.py` + `tests/test_data/test_synthetic_marker.py`

## Verdict: APPROVE WITH NOTES

No blocking violations. Full test suite passes at 1031 vs baseline 1018 (+13 new Phase-1 tests, all passing). Notes below are non-blocking hygiene items.

---

## 1. Diff Summary

```
 services/nexus_data/duckdb_store.py | 338 +++++++++++++++++++++++++++++++++++- (337+, 1-)
 services/nexus_data/main.py         |  40 ++++- (33+, 7-)
 2 files changed, 370 insertions(+), 8 deletions(-)
 New (untracked): tests/test_data/test_quality_gate.py (163 lines, 7 tests)
                  tests/test_data/test_synthetic_marker.py (135 lines, 6 tests)
```

`git status`: only the two assigned source files modified + the two assigned test files added. No other tracked file touched.

## 2. Audit Checklist

| Check | Result |
|---|---|
| Deleted lines functional? | **PASS** — all 8 deletions are import/annotation/decorator rewrites: `typing.Any`→`Any, Sequence`; `_synthetic_tick/OHLCV` return-type annotations `Tick/OHLCV`→`TickRow/OHLCVRow`; the two `@app.get(... response_model=...)` decorator lines. No live-path logic deleted. |
| DROP / DELETE / TRUNCATE added? | **PASS** — none added. Only `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` (additive) and pre-existing retention `DELETE FROM ticks/ohlcv WHERE timestamp < ?` (duckdb_store.py:1231/1234; present at HEAD lines 895/898, untouched). Migration SQL (`migrations/research_lineage_001.sql`) is all `CREATE ... IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` — no destructive statements. |
| Hot path byte-identical when flag OFF? | **PASS** — see §3. |
| Ticks backfill NULL-default compliance? | **PASS** — migration adds `source`/`quality`/`fetched_at` as nullable columns with no DEFAULT and backfills **only** `fetched_at` (`UPDATE ticks SET fetched_at=...WHERE fetched_at IS NULL`, duckdb_store.py:365). `quality` is never set on ticks; `insert_tick` inserts only `(symbol, bid, ask, spread, timestamp)` so legacy and new tick rows keep `quality = NULL`. `rg` confirms no `UPDATE ticks ... quality` and no `quality='ok'` on ticks anywhere in the diff. (The `UPDATE ohlcv SET quality='ok' WHERE quality IS NULL` at line 348 is **pre-existing** — HEAD line 245 — not a Phase-1 change; flagged as legacy debt for Phase 2, out of scope here.) |
| .env / run.py / shared/models.py modified? | **PASS** — `git diff -- run.py shared/models.py` empty; both files last written 10/16 (before Phase 1). `.env` is gitignored, untracked, last written 10/17 evening (before Phase 1). |
| Hardcoded secrets? | **PASS** — none. Only the env var *name* `NEXUS_QUALITY_GATE` appears. |

## 3. Flag Semantics (quality_gate_enabled)

```python
def quality_gate_enabled() -> bool:
    return os.getenv(QUALITY_GATE_ENV, "").strip().lower() not in ("", "0")
```

- Default (unset/empty) → **OFF**; `"0"` → OFF; any other value → ON. Asserted by `test_quality_gate_flag_defaults_off`.
- OFF-path SQL is **identical to HEAD** in all four write paths:
  - `insert_tick` — gate block skipped; same INSERT as HEAD.
  - `insert_ohlcv` — gate block skipped; same forming-bar check + INSERT as HEAD.
  - `insert_ohlcv_batch` — `if quality_gate_enabled()` branches to gated helper only when ON; OFF falls through to the untouched original `sql`/`params`/`executemany` (verified as unchanged context in the diff), returns `len(unique_bars)` as before.
  - `insert_batch` — gate block skipped; same `_bulk()` as HEAD.
- `_write_quarantine` (lazy lineage-schema activation) is reachable only from gated branches → with the flag OFF no quarantine write, no migration execution, no extra SQL.
- One unconditional-at-OPEN change (flag independent): the ticks column `ALTER ... IF NOT EXISTS` migration. This is schema-additive (per Phase-1 requirement), idempotent, and touches only `fetched_at` on existing rows — it does not alter row data semantics and does not set `quality`.
- Gate-ON semantics verified: ERROR severity (outlier / duplicate / broken OHLC invariant / non-canonical record) → quarantined + skipped; WARNING (time gap) → still inserted with caller `quality` (default `"ok"` preserved for OHLCV). Tests cover both ON and OFF.

## 4. Synthetic Marker (C2)

- `TickRow(Tick)` / `OHLCVRow(OHLCV)` add `source: str | None = None` only.
- Both endpoints now use `response_model=list[TickRow/OHLCVRow]` + `response_model_exclude_none=True`.
- Real rows serialize **without** the `source` key: no other field on `Tick`/`OHLCV` can be `None` (`spread` has default 0.0 and is force-computed by the model validator; `volume` default 0.0; all other fields required), so `exclude_none` strips only `source=None`. Confirmed by `test_real_tick_rows_do_not_gain_source_key` and `test_real_ohlcv_rows_do_not_gain_source_key`.
- Synthetic helpers return API-only rows: `_synthetic_tick` (main.py:724) and `_synthetic_ohlcv` (main.py:879) are only reached on the read-fallback branches; no write to tick cache, DuckDB, or Redis. Markers present: `test_synthetic_tick_helper_marks_source_in_band`, `test_synthetic_ohlcv_helper_marks_every_row_in_band`, plus endpoint-level JSON assertions.

## 5. Test Results

Command: `.venv\Scripts\python.exe -m pytest tests/ -q --tb=line -p no:cacheprovider` (workdir: repo root)

| | Count |
|---|---|
| Baseline | 1018 passed |
| New Phase-1 tests | +13 (7 quality gate + 6 synthetic marker; 1018 + 13 = 1031) |
| **Phase-1 run** | **1031 passed, 0 failed**, 3 warnings, 452 s |

Warnings: 2 pre-existing third-party deprecations (langgraph, starlette) + 1 pre-existing `regex=` deprecation at main.py:703 (untouched by the diff; shifted line number only).

## 6. Violations

**None blocking.** Clean on every mandated check: no functional deletions, no destructive SQL, byte-identical OFF path, ticks `quality` stays NULL, no .env/run.py/shared/models.py changes, no secrets.

## 7. Notes (non-blocking)

1. **Test isolation (reproducibility):** running `tests/test_data/test_quality_gate.py` + `tests/test_data/test_synthetic_marker.py` *together, alone* fails 2 sync helper tests (`test_synthetic_tick_helper_marks_source_in_band`, `test_synthetic_ohlcv_helper_marks_every_row_in_band`) with `RuntimeError: There is no current event loop` from `eventkit`/`ib_insync` at `services.nexus_data.main` import time — prior async tests leave no current loop, and `main` is not yet in `sys.modules`. The mandated full-suite run passes because earlier test files import `main` inside async tests first. Suggested fix (Phase 2): import `main` at module scope of the test file or mark the two helpers `@pytest.mark.asyncio`. Each file in isolation and the full suite both pass today.
2. **File size (CLAUDE.md "keep files under 500 lines"):** `duckdb_store.py` 954 → 1290 lines, `main.py` 1065 → 1091 lines. Both already exceeded 500 at baseline — pre-existing debt, worsened; consider extracting the quality-gate helpers in a later phase.
3. **Untracked `fx-trading-system-main/`** directory present in `git status` (created 10/17, unrelated research material, not referenced by the Phase-1 diff). Exclude from any Phase-1 commit.
4. **Pre-existing NULL-default debt (out of scope):** `UPDATE ohlcv SET quality='ok' WHERE quality IS NULL` (duckdb_store.py:348, present since HEAD) backfills legacy OHLCV rows to `'ok'` — contrary to the NULL-default principle but not introduced by Phase 1; recommend tracking for Phase 2.
5. **Gated return-value semantics:** `_insert_ohlcv_batch_gated` returns `len(params)` (rows actually submitted) vs ungated `len(unique_bars)`. Different only when the flag is ON and quarantine drops rows — matches the docstring; no OFF-path impact.
