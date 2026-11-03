# PROGRESS SCREEN FORENSIC DIAGNOSIS — 2026-10-16
Agent-1 Forensics Detective · READ-ONLY investigation (only this report written)
Scope: "متابعة التطوير" screen — DASHBOARD_STATE.json, FILE_MANIFEST.tsv, update_dashboard.py, dashboard progress UI, progress-state route.

## Executive verdict
The screen is **structurally functional but factually frozen at 2026-10-15T19:00Z**. It cannot represent the 2026-10-16 fix batch even if the sync script is re-run, because (1) the script's field names diverge from the JSON/Table schema, (2) the script writes raw manifest status strings the UI does not understand, and (3) the route/JSON pipeline carries fabricated per-file metrics and classification text in the `error` column. No parent rollup exists anywhere.

---

## Evidence base
- `DASHBOARD_STATE.json`: 11,358 lines; `last_updated=2026-10-15T19:00:02Z` (:2); `current_task={"id":"nexus-ml"}` (:3-6); 567 items = 12 root parents + 555 `file:*` children; statuses {pending:369, done:190, in_progress:8}; all 567 rows carry `dashboard`+`infra` keys, **0 rows carry `ui`/`infrastructure`**.
- `FILE_MANIFEST.tsv`: 680 lines; 24 distinct status strings; 6 embedded sub-manifest header rows (:240-245); 46 duplicate paths; 468/680 paths use `\` separators.
- Verification gate 2026-10-16 (1000/1000 Python + TS PASS) and the 100+ file fix batch appear **nowhere** in the state JSON.

---

## Defect classes

### (a) Stale / misleading data — CRITICAL
| # | Evidence | Impact |
|---|---|---|
| A1 | `DASHBOARD_STATE.json:2` last_updated=2026-10-15T19:00Z; page polls every 5s (`page.tsx:8`) but source never regenerated after the 2026-10-16 batch | Screen shows 369 pending files that are actually fixed/verified; "Fixed and verified" manifest rows (89 lines, e.g. FILE_MANIFEST.tsv:246) never surface |
| A2 | All 555 `file:*` children have **fabricated identical numeric seeds** (code=50, security=70, redis=0, ml=0, tests=70, audit=70, dashboard=0) despite status `pending` and `database/infra=null` | Category pie (`HierarchicalTable.tsx:20`) averages ~555 phantom measurements → charts look authoritative but measure nothing |
| A3 | 466 `file:*` items have `error` = classification text ("root-or-other", e.g. `file:path` at DASHBOARD_STATE.json:258) | `ErrorFixCell.tsx:19` renders them as red ❌ "errors" — audit classifications masquerade as runtime failures |
| A4 | 6/8 `in_progress` items lack `start_time`; `page.tsx:9` fallback `find(status==='in_progress' && start_time)` only ever matches nexus-ml/infrastructure | "المهمة الحالية" panel silently misattributes the active task |
| A5 | 555 file items vs 680 manifest lines; 46 duplicate manifest paths; duplicate `.env.example` rows (FILE_MANIFEST.tsv:4-5) | Sync drift: new files (incl. 10-16 batch) absent from state; last-writer-wins overwrites on duplicates |

### (b) Field-name mismatches — CRITICAL
Three schemas, two of which disagree:
- `update_dashboard.py:9` FIELDS = (code, database, **ui**, security, redis, ml, tests, **infrastructure**, audit)
- `DASHBOARD_STATE.json` rows (567/567): **dashboard**, **infra** — no `ui`/`infrastructure` keys exist
- `HierarchicalTable.tsx:9` cols read: code, database, **dashboard**, security, redis, ml, tests, **infra**, audit

Consequences:
- B1: CLI `--ui 80 --infrastructure 80` (`update_dashboard.py:15,55-58`) writes keys the UI never reads; the change is invisible on screen while appearing to succeed.
- B2: `--sync-manifest` new-item template (`update_dashboard.py:47`) creates rows with `ui`/`infrastructure` keys → their واجهة/بنية-under-ten columns render as `—` (null) next to legacy rows showing numbers → mixed-schema table after any sync.
- B3: `page.tsx:5` type `current_task:{id,name}|string` papers over another schema split: `update_dashboard.py:67` writes an object, `:49` writes a string ("متابعة كل ملفات FILE_MANIFEST.tsv").

### (c) Status-vocabulary inconsistency — HIGH
- Manifest vocab (24 values): `Not inspected` 224, `Inspected (partial)` 101, `Implemented, not verified` 101, `Fixed and verified` 89, `Reviewed` 47, `Inspected` 25, `Inspected (static)` 25, `In progress` 24, `Excluded` 10, `Generated` 4, `Needs repair` 4, plus junk: `status`×5, `role`×1 (header rows FILE_MANIFEST.tsv:240-245), `Agent 1 scope review`×2, `P1 historical backfill`×3, `P1 Redis recovery`, `P2 dependency review` (notes in the status column).
- State vocab (567 items): only `pending`/`done`/`in_progress`.
- UI logic: `HierarchicalTable.tsx:27` `done = status==='done'`; `ProgressCell.tsx:8-10` special-cases only `done`/`in_progress`/`pending`.
- `update_dashboard.py:43` copies manifest status **verbatim** into state → after the next `--sync-manifest`, no row will ever be `done`; "Fixed and verified" renders as not-done with no green highlight. There is no status normalization/mapping table anywhere.

### (d) Broken / fragile paths — MEDIUM
- D1: `route.ts:6` `path.resolve(process.cwd(), '..', 'project_audit', 'DASHBOARD_STATE.json')` assumes Next's cwd is exactly `<repo>/dashboard`. Breaks if started from repo root, a workspace tool, or after any directory rename. Should resolve from `import.meta.url`/`__dirname` or an env var.
- D2: `update_dashboard.py:7-8` resolves via `Path(__file__).parents[1]` (correct) — proving the route's cwd approach is the outlier.
- D3: `update_dashboard.py:41` `next(x for x in ...)` with no default → `StopIteration` crash on id race instead of a clean error.

### (e) Debug leftovers — MEDIUM
- E1: `page.tsx:10` `console.log('currentTaskId:', …)` — every 5s poll.
- E2: `HierarchicalTable.tsx:29` `console.log('item.id:', …)` **inside `renderRow`** — fires for all 567 rows on every render/poll (~2,835 log lines per 5s cycle; measurable main-thread cost + leaks item metadata to anyone with DevTools open).

### (f) Arabic encoding — LOW (clean in data, one schema risk)
- JSON written with `ensure_ascii=False` (`update_dashboard.py:75`); automated scan found 0 mojibake/U+FFFD in name/description/notes/fix across all 567 items. `infrastructure` name (DASHBOARD_STATE.json:237) is valid UTF-8 Arabic «البنية التحتية والتدقيق» (bytes verified); earlier `???` sightings were PowerShell console codepage, not data corruption.
- Residual risk: `--sync-manifest` sets `current_task` to a raw Arabic string (`update_dashboard.py:49`) against an object schema — consumers must keep the union type forever.

### (g) Missing rollup — HIGH
- No aggregation exists in either writer or reader. `update_dashboard.py` never recomputes parent metrics from children; `HierarchicalTable.tsx:23-36` renders each parent's own stored numbers.
- Parent `code` equals the mean of children `code` for all 12 parents (e.g. frontend 60 vs mean 60.0 over 127 children) **only because children were seeded as copies at sync time** — coincidence, not computation. Editing any child leaves the parent stale.
- The pie chart (`HierarchicalTable.tsx:20`) averages all 567 rows (parents + children + phantom seeds) → double-counting parents against their own children.

### (h) Route caching / error-handling gaps — MEDIUM
- H1: Next 14.2.5 (`dashboard/package.json`); `route.ts` exports no `export const dynamic = 'force-dynamic'` and uses no Dynamic API — GET route handlers are static-cache candidates at build time; the `Cache-Control: no-store` header (`route.ts:9`) does not disable framework-level handler caching. Post-`next build` the screen could serve a build-time snapshot forever.
- H2: `route.ts:10-12` bare `catch` swallows ENOENT vs parse errors alike; no server-side log → 503 with opaque `{error}` body; client (`page.tsx:8`) shows a generic Arabic message and keeps polling the same broken path every 5s with no backoff.
- H3: Full 11k-line JSON re-read + re-parse + re-download every 5s; no ETag/If-None-Match or mtime short-circuit.

---

## Prioritized fix list
1. **P0 — Schema unification (B1-B3):** pick `dashboard`/`infra` everywhere; change `update_dashboard.py:9,15,47` to match, or migrate JSON + `HierarchicalTable.tsx:9` to `ui`/`infrastructure`. Make `current_task` always an object (`:49`).
2. **P0 — Status normalization (C):** add a manifest→state mapping table (e.g. Fixed and verified/Reviewed/Inspected* → done-ish tiers; Not inspected/Excluded → pending; In progress → in_progress) applied at `update_dashboard.py:43`; reject junk header rows (FILE_MANIFEST.tsv:240-245) in the parser; strip notes-in-status-column values.
3. **P0 — Regenerate state (A1):** re-run `--sync-manifest` after fixes 1-2 so the 2026-10-16 batch + 1000/1000 gate appear; verify `last_updated` advances.
4. **P1 — Remove fabricated seeds & error-field abuse (A2, A3):** new file items should carry null metrics (`update_dashboard.py:47` already intends this — purge the legacy seeded values); move classification text out of `error` into `notes`/a dedicated `classification` field.
5. **P1 — Parent rollup (G):** compute parent metrics as child means (status-weighted) in the writer or in a `useMemo` in `HierarchicalTable.tsx:14-21`; exclude parents from the category pie to stop double-counting.
6. **P1 — Delete debug logs (E1, E2):** `page.tsx:10`, `HierarchicalTable.tsx:29`.
7. **P2 — Route hardening (D1, H1-H3):** resolve the JSON path without `process.cwd()`; add `export const dynamic='force-dynamic'`; log the real error server-side; add mtime/ETag short-circuit and client backoff on 5xx.
8. **P2 — Manifest hygiene (A5):** de-duplicate 46 repeated paths, normalize `\`→`/`, remove embedded header rows, resolve the double `.env.example` conflict.
9. **P3 — Consistency nits:** `start_time` backfill for the 6 in_progress items (A4); dedupe `services`/`roots` in `HierarchicalTable.tsx:18-19`; guard `next()` at `update_dashboard.py:41`.
