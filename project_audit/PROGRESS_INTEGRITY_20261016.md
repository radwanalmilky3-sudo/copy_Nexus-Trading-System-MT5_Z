# Agent-10 Integrity Validator — End-to-End Validation Report

- **Date:** 2026-10-16
- **Validator:** Agent-10 (read-only; sole output = this file)
- **Targets:** `project_audit/DASHBOARD_STATE.json`, `project_audit/FILE_MANIFEST.tsv`, `project_audit/GIT_EVIDENCE_20261016.json`, `scripts/update_dashboard.py`
- **Tooling:** `.venv/Scripts/python.exe` (UTF-8 stdout), read-only `git status`
- **Overall:** **FAIL** — state JSON passes all 14 sub-checks; `FILE_MANIFEST.tsv` structure fails 3 sub-checks (column counts, embedded headers, duplicate paths).

---

## Check 1 — DASHBOARD_STATE.json schema & content — **PASS** (14/14 sub-checks)

| # | Sub-check | Result | Evidence |
|---|-----------|--------|----------|
| 1.0 | Valid UTF-8 | **PASS** | 363,969 bytes decode as UTF-8, no errors |
| 1.1 | Parses as JSON | **PASS** | top-level `dict` |
| 1.2 | Required top keys | **PASS** | `last_updated`, `current_task`, `items` all present (only these 3) |
| 1.3 | `items` shape | **PASS** | JSON array, 568 items |
| 1.4 | Item schema completeness | **PASS** | all 22 keys present on all 568 items: `id,name,description,parent_id,status,notes,start_time,end_time,code,database,dashboard,security,redis,ml,tests,infra,audit,error,fix,is_current` — 0 missing, 0 extra |
| 1.5 | Status vocabulary | **PASS** | all statuses ∈ {pending, in_progress, done}; 0 invalid |
| 1.6 | Numerics null or 0..100 | **PASS** | 9 numeric fields (`code,database,dashboard,security,redis,ml,tests,infra,audit`) × 568 items → 0 violations (all `int` or `null`, all in range). `error`/`fix` are **text** fields by design (364 str / 204 null for `error`; 204 str / 364 null for `fix`) — matches `update_dashboard.py` `FIELDS` tuple; verified both are never non-string non-null |
| 1.7 | Unique ids | **PASS** | 568 ids / 568 unique |
| 1.8 | `parent_id` resolution | **PASS** | 0 orphans; 12 root items (`shared`, `nexus-data`, `nexus-api`, `nexus-features`, `nexus-ml`, `nexus-agents`, `nexus-news`, `nexus-risk`, `nexus-executor`, `nexus-monitor`, `frontend`, `infrastructure`); 556 items hang off roots |
| 1.9 | Exactly one `is_current` + matches `current_task.id` | **PASS** | exactly 1 → `progress-reconcile`; `current_task = {"id":"progress-reconcile","name":"مزامنة شاشة متابعة التطوير مع إصلاحات 2026-10-16"}` (dict, matches) |
| 1.10 | No U+FFFD in strings | **PASS** | 0 `U+FFFD` in any item string field |
| 1.11 | No mojibake in strings | **PASS** | 0 hits for classic UTF-8→cp1252 markers (`Ø Ù Ã Â â`) across `name/description/notes/fix` |
| 1.12 | `last_updated` recent | **PASS** | `2026-10-16T12:04:39.567920+00:00` |
| 1.13 | File-wide no U+FFFD | **PASS** | 0 occurrences in raw file |
| — | Arabic integrity (extra) | **PASS** | 2,277 Arabic codepoints (U+0600–U+06FF) present; sample `النماذج والأحداث وRedis والسلامة والإعدادات` round-trips intact; 13 items carry Arabic descriptions. Note: `?` glyphs seen in a GBK/ANSI console are a rendering artifact only — file bytes are clean UTF-8 |

**Status distribution (568 items):**

| status | count | share |
|--------|------:|------:|
| pending | 291 | 51.2% |
| done | 268 | 47.2% |
| in_progress | 9 | 1.6% |

`file:`-prefixed items: 555 (pending 291, done 264); non-file items: 13 (12 roots + `progress-reconcile`).

---

## Check 2 — GIT_EVIDENCE paths with a `file:` item must be `done` — **PASS** (0 exceptions)

Replayed `scripts/update_dashboard.py::_evidence_paths()` + `file:` lookup exactly as the pipeline does:

- Evidence JSON: valid JSON, keys `generated_at, total_files_changed, by_subsystem, git_log_recent, verification, subsystem_fix_summary`; 130 unique path-like strings.
- **109 unique evidence paths resolve to a `file:` item → 109/109 status `done`. Non-done: 0. Exceptions: none.**

Coverage note (informational, not a violation of the rule): 21 evidence strings have **no** `file:` item — 10 are prose/commit messages, 11 are real tracked files never registered in the state:

```
dashboard/src/components/progress/ErrorFixCell.tsx
dashboard/src/components/progress/HierarchicalTable.tsx
dashboard/src/components/progress/ProgressCell.tsx
dashboard/src/lib/system-state.ts
project_audit/DISTRIBUTED_FIX_BATCH_20261016.md
project_audit/VERIFICATION_GATE_20261016.md
scripts/apply_schema.py
scripts/update_dashboard.py
services/nexus_ml/artifact_guard.py
services/nexus_news/url_safety.py
(+ 'dashboard/src/lib/system-state.ts' is untracked in git)
```

---

## Check 3 — FILE_MANIFEST.tsv structure — **FAIL** (3 of 4 sub-checks)

| # | Sub-check | Result | Evidence |
|---|-----------|--------|----------|
| 3.1 | Uniform tab column counts | **FAIL** | 680 non-empty lines; distribution **{3: 640, 6: 26, 4: 14}** → **40 lines off the modal width of 3**. Off-modal line numbers: 4, 240, 243, 245, 250, 253, 275, 277–291, 293–301, 303, 305, 359, 366, 372, 378, 381, 534, 535, 536. Cause: the file is a **concatenation of heterogeneous sub-manifests** (3-col, 4-col `path/status/note/…`, 6-col `path/role/change/verification` and `path/status/owner/scope/evidence/constraints`). `update_dashboard._sync-manifest` uses `split("\t", 2)`, so tail columns are silently folded into the note — no crash, but semantics differ per section |
| 3.2 | No embedded header rows | **FAIL** | **6 embedded header rows at lines 240–245**: `path/role/change/verification`, `path/status/classification`, `path/status/evidence_or_scope`, `path/status/finding_or_change/constraints`, `path/status/note`, `path/status/owner/scope/evidence/constraints` |
| 3.3 | No duplicate paths | **FAIL** | **45 duplicate paths (45 surplus rows)**; after separator normalization still 45 → genuine re-listings, not `\` vs `/` artifacts. **All 45 have conflicting payloads**, e.g. `run.py` = `Implemented and verified statically` vs `Implemented, not verified`; `.env.example` appears with both 6-col and 3-col records; `services\nexus_api\routers\backtest.py` listed with two different verification notes. No machine-identical duplicate rows |
| 3.4 | Status vocabulary (no junk) | **PASS** | Data-row column-1 vocabulary = **20 legitimate values**, no bare `status`/`role`/`path`: `Not inspected 191, fixed and verified 152, Fixed and verified 82, Implemented, not verified 71, Inspected (partial) 61, Reviewed 33, Inspected 24, Inspected (static) 21, In progress 13, Excluded 10, Generated 4, P1 historical backfill 2, Fixed 2, Fixed and verified (audit evidence) 2, Unable to inspect 1, Fixed and reviewed 1, Created 1, P2 dependency review 1, Implemented and verified statically 1, Needs repair 1`. Zero junk cells (`path/status/role/…`) outside header rows |

**Blast radius of 3.2 (important):** header line 240 was ingested by `--sync-manifest` as a real record → the state now contains a **junk item `id="file:path"`, description `"classification"`** (duplicate-path count of 46 when headers are included). Schema-valid, but semantically spurious.

**Coverage:** 674 data rows / 629 unique paths; **7 manifest paths have no `file:` item** (`dashboard/src/app/dashboard/progress/page.tsx`, `dashboard/src/app/progress-state/route.ts`, `dashboard/src/components/progress/HierarchicalTable.tsx`, `project_audit/manifest_3.tsv`, `project_audit/requirements_lock.tsv`, `services/nexus_agents`, `services/nexus_ml`); **0 state `file:` items are absent from the manifest** → state ⊆ manifest for path items.

---

## Check 4 — `python scripts/update_dashboard.py --report` (idempotent, no writes) — **PASS**

```
$ .venv/Scripts/python.exe scripts/update_dashboard.py --report
Status distribution (568 items, last_updated=2026-10-16T12:04:39.567920+00:00):
  pending           291  ( 51.2%)
  done              268  ( 47.2%)
  in_progress         9  (  1.6%)
EXIT=0
```

- Exit code **0**.
- mtime snapshot before/after over 146 files (`project_audit/**`, `scripts/**`, `dashboard/src/**`): **0 modified, 0 created, 0 deleted**.
- No leftover `project_audit/DASHBOARD_STATE.*.tmp` files.
- (Note: `--report` still executes `_migrate()` in memory; harmless here because no legacy keys exist — see Check 5.)

---

## Check 5 — Legacy keys `ui` / `infrastructure` — **PASS**

- Regex over raw JSON `"ui"\s*:` / `"infrastructure"\s*:` → **0 hits**.
- Per-item key scan across all 568 items → **0 hits** (no unmigrated rows).
- Migrated targets `dashboard` / `infra` present on all 568 items (567 int + 1 null for `dashboard`... see types: `dashboard` 568 int; `infra` 43 int + 525 null — nulls are file items where the field is not applicable, consistent with `--sync-manifest` which writes `None`).

---

## Verdict summary

| Check | Result |
|-------|--------|
| 1. DASHBOARD_STATE.json schema/content/Arabic/recency | **PASS** (14/14) |
| 2. Evidence paths with `file:` item → status `done` | **PASS** (0 exceptions, 109/109) |
| 3. FILE_MANIFEST.tsv structure | **FAIL** — 3.1 column counts, 3.2 embedded headers, 3.3 duplicate paths |
| 4. `update_dashboard.py --report` exit 0, no writes | **PASS** |
| 5. Legacy `ui`/`infrastructure` keys | **PASS** |
| **Overall** | **FAIL** (state JSON green; manifest hygiene red) |

**Recommended follow-ups (not applied — read-only mandate):**
1. Drop manifest lines 240–245 (embedded headers) and delete the orphaned state item `file:path`.
2. Deduplicate the 45 conflicting path rows in `FILE_MANIFEST.tsv` (keep one authoritative record per path, or add a round/agent column instead of stacking rows).
3. Normalize the file to one column schema (3-col) or split per-section manifests; 40 off-modal lines currently rely on `split("\t", 2)` folding.
4. Register the 11 untracked evidence files (progress components, `system-state.ts`, `apply_schema.py`, `update_dashboard.py`, `artifact_guard.py`, `url_safety.py`, 2 audit docs) as `file:` items and mark `done`, since evidence already shows them verified.
