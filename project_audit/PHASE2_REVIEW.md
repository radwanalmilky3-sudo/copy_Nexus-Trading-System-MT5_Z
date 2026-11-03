# Phase 2 (PIT) Review — R1

**Date:** 2026-10-18
**Reviewer:** R1 · **Phase:** 2 (Point-in-Time availability)
**Baseline:** Phase-1 commit `358abf0` (1031 tests)

## Verdict: APPROVE

No unsanctioned deletions, no forbidden patterns, no secrets, no scope violations.
All 31 new Phase-2 tests pass; full suite matches the expected 1062 total.
One full-suite failure is a **pre-existing timing flake** in an untouched
Phase-0 golden-contract test (details in §4) — not a Phase-2 regression.

---

## 1. Changed-file inventory (git status)

| File | Status | Diff | Expected |
|---|---|---|---|
| `services/nexus_data/duckdb_store.py` | modified | +283 / −74 | C1 ✅ |
| `services/nexus_data/main.py` | modified | +100 / −0 | C2 ✅ (exactly 100 added lines) |
| `tests/test_data/test_pit_availability.py` | new (untracked) | +228 | C1 test ✅ |
| `tests/test_data/test_pit_endpoint.py` | new (untracked) | +343 | C2 test ✅ |
| `project_audit/PHASE2_REVIEW.md` | new | this file | review artifact ✅ |

**File count = 4 expected + review file.** No `.env`, `run.py`, or `shared/`
changes; no secrets in any diff.

> **Pre-existing note (not a Phase-2 touch):** untracked `fx-trading-system-main/`
> (728 files, all file mtimes 8/4/2026, extracted ~10/17 before the Phase-1
> commit) sits in the working tree. Foreign repo archive, zero nexus_data
> content, not modified by Phase 2. Recommend A0 clean it up or gitignore it.

## 2. Deleted-line classification (all 74 deletions, duckdb_store.py only; main.py has 0 deletions)

Extracted via `git diff -U0`; every deleted line is accounted for.

| # | Deleted content | Lines | Class | Justification |
|---|---|---|---|---|
| 1 | `UPDATE ohlcv SET quality='ok' WHERE quality IS NULL` | 1 | (a) sanctioned | Debt-fix removal (Phase-2 spec: legacy quality stays NULL) |
| 2 | `UPDATE ohlcv SET fetched_at=CURRENT_TIMESTAMP ...` | 1 | (a) sanctioned | Reorder only — re-added verbatim 2 lines below; net-zero |
| 3 | `insert_tick` plain tick INSERT | 2 | (a) sanctioned | Replaced by INSERT with `available_at CURRENT_TIMESTAMP` |
| 4 | `insert_ohlcv` direct single-bar INSERT (VALUES) | 7 | (a) sanctioned | Delegates to revision-aware `_apply_ohlcv_upsert` |
| 5 | Ungated batch: `INSERT ... WHERE NOT EXISTS` SQL + params + `_insert` + lock block | 25 | (a) sanctioned | The old first-write-wins conflict branch, replaced by revision-aware upsert (spec-sanctioned) |
| 6 | Gated batch: same `WHERE NOT EXISTS` block + `return len(params)` | 25 | (a) sanctioned | Same replacement; returns `len(kept_bars)` (equivalent semantics) |
| 7 | `insert_batch` tick INSERT (5-col) | 3 | (a) sanctioned | Stamps `available_at` (COALESCE with param) |
| 8 | `insert_batch` ohlcv direct INSERT execute | 12 | (a) sanctioned | OHLCV collected into dict → `_upsert_ohlcv_rows` |
| 9 | Docstrings ×3 ("once, ignoring…", "is unchanged.", "Same first-write-wins SQL…") | 3 | (a) sanctioned | Doc rewrites to match new upsert semantics |

**UNSANCTIONED functional deletions: NONE → no REJECT trigger.**
Pre-existing `DELETE FROM ticks/ohlcv WHERE timestamp < ?` retention code
(duckdb_store.py:1440/1443) is untouched (absent from diff).

## 3. Forbidden-pattern / scope checks

| Check | Result |
|---|---|
| DROP / DELETE / TRUNCATE / ALTER … DROP in production code | ✅ none added (only `ALTER TABLE … ADD COLUMN IF NOT EXISTS` — additive) |
| .env / run.py / shared/ changes | ✅ none |
| Secrets in diff | ✅ none |
| Services started / data loaded / ML / backtests | ✅ none performed |

> **Note:** `test_pit_availability.py:28-33` uses `DROP INDEX IF EXISTS` +
> `ALTER COLUMN quality DROP NOT NULL` — **test-only**, on a `tmp_path`
> ephemeral DuckDB, to simulate pre-migration nullable-quality legacy rows;
> index recreated immediately. Production schema untouched. Accepted as
> sanctioned test fixture necessity.

## 4. Test results

Full suite: `.venv\Scripts\python.exe -m pytest tests/ -q --tb=line -p no:cacheprovider`

| Metric | Value |
|---|---|
| Phase-1 baseline | 1031 |
| + `test_pit_availability.py` | +7 |
| + `test_pit_endpoint.py` | +24 (parametrization: 4×2 flag-off + 2+2+1+2+1×8 singles = 24) |
| **Expected total** | **1062** |
| **Collected / run** | **1062** ✅ |
| Passed | 1061 |
| Failed | 1 (pre-existing flake, below) |
| New PIT tests | 31/31 pass (also verified in isolation) |

**The single failure** — `tests/test_fundamental/test_golden_contracts.py::test_executor_guard_rejects_each_modified_approved_field[expires_at-1792283366]`:
- File untouched by Phase 2; Phase-0 golden-contract test.
- Time-window flake: parametrize computes `expires_at = time.time()+120`
  **at collection**, `_approval_payload()` computes `time.time()+60` **at run**.
  When a test executes exactly ~60 s after collection the "altered" value
  equals the approved value → no mismatch → guard correctly allows →
  `assert allowed is False` fails.
- Proof it is not a Phase-2 regression: the whole parametrization (12 cases)
  **passes in isolation** (0.15 s), and no guard/fundamental code was touched
  by Phase 2. Recommend A0 schedule a fix (compute the offset inside the test).

## 5. Checklist verification (source-verified)

| # | Requirement | Evidence | Result |
|---|---|---|---|
| 3 | Default query path has no PIT predicates when both params None | `query_ohlcv` appends `available_at <= ?` / `epoch(timestamp)+? >= epoch(available_at)` **only** under `if available_through is not None` / `if max_staleness_s is not None` (duckdb_store.py:979-984); keyword-only params | ✅ |
| 4a | Flag empty → 503 BEFORE store call | `_require_pit_enabled()` is the first statement of both endpoints (main.py:956, 1022); `test_pit_flag_off_returns_503` uses `UnusedStore` that raises if queried — 4 off-values × 2 paths all 503 | ✅ |
| 4b | Fingerprint empty-hash = sha256(b"") | `_ohlcv_content_hash` updates digest per row; zero rows → `sha256(b"")`; asserted in `test_fingerprint_ohlcv_deterministic_and_pit_sensitive` | ✅ |
| 5 | Revision semantics | `_upsert_ohlcv_rows`: identical OHLC/volume → `continue` (skip, no revision touch); different → `UPDATE … revision = COALESCE(revision,0)+1`; absent → INSERT; **no DELETE anywhere**; row-count stability asserted (`COUNT(*)==2` after correction) | ✅ |
| 6a | Legacy NULL available_at excluded only with PIT param | SQL uses `available_at <= ?` (NULL → unknown → excluded); default path has no predicate; both behaviors asserted in `test_pit_query_excludes_legacy_rows_with_null_available_at` | ✅ |
| 6b | Legacy quality stays NULL after init | Debt line removed; re-init leaves `(None,)`; `test_legacy_null_quality_rows_stay_null_after_init_tables` | ✅ |

## 6. Additional observations (non-blocking)

- **Defense in depth on /pit:** fail-closed store-contract introspection
  (`_pit_store_query_supported`, 503 if keywords absent) + a second
  server-side filter `bar.timestamp <= as_of` so a misbehaving store can
  never leak post-cutoff bars. Fail-closed 404 when nothing visible. Good.
- **Update path resets availability:** a differing re-insert with
  `available_at=None` sets `available_at = CURRENT_TIMESTAMP` (correct PIT
  semantics: the corrected values became visible now); documented in the
  docstring.
- **Manifest refresh scope:** identical re-inserts skip the manifest refresh
  (no data change) — correct; refreshed rows verified to match the
  fingerprint hash of the same horizon (`test_manifest_refreshed_after_batch_insert`).
- **`fingerprint_ohlcv(None)`** on the raw store yields `available_at <= NULL`
  → 0 rows; the endpoint requires the param (422), so unreachable via API.
- Pre-existing >500-line files (duckdb_store.py, main.py) and the
  FastAPI `regex=` deprecation warning predate Phase 2.

## 7. Violations

**None.**

---

*Audited against working tree at Phase-2 state (uncommitted changes on top of
`358abf0`); evidence bound to the exact diff and test run recorded above.*
