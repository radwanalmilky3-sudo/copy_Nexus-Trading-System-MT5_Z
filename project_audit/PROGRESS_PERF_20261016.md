# PROGRESS_PERF_20261016 — Agent-14 Performance Auditor (read-only scan)

Scope: `/progress-state` polling screen. All line refs are current as of 2026-10-16.
No source file was modified by this agent.

## 0. Measurements (raw evidence)

| Metric | Value |
|---|---|
| `project_audit/DASHBOARD_STATE.json` exact size | **363,969 bytes** (`Get-Item …Length`) |
| newlines in file | 12,504 (pretty-printed) |
| minified equivalent | 291,235 bytes → **72,734 B (20.0%) pure whitespace** |
| gzip (Optimal) of file as-is | **29,525 B (8.1%)** |
| gzip -9 of file as-is / minified | 29,108 B / 28,114 B |
| deflate (HTTP `Content-Encoding: deflate`) | 29,507 B |
| items | 568; roots 12; maxDepth 2; children/parent: infrastructure 212, frontend 128, nexus-agents 48, nexus-api 38, nexus-ml 30, nexus-news 28, shared 24, nexus-features 14, nexus-data 12, nexus-executor 9, nexus-risk 7, nexus-monitor 6 |
| `JSON.parse` cost (Node 18+, 364 KB) | 1st call 119 ms (JIT warm-up), steady avg **3.8 ms** |
| `JSON.stringify` of parsed state | **2.6 ms** |
| rollup/aggregate walk (568×9) | 0.95 ms |
| status mix | done 268, pending 291, in_progress 9 |
| non-null per field (of 568) | error 364, fix 204, start_time 5, end_time 5, is_current 1; notes 568 (all non-empty), description 568 |
| error/fix exclusive | `!error && !fix` = **0** → every item has exactly one of the two, the other is always `null` |
| HTTP probe | dev server :3100 not running → `Content-Encoding` **not verified live**; `next.config.js` does not set `compress`, and Next defaults `compress: true`, so gzip/br is expected |

### Per-field byte budget (sum of values only, item objects)

| field | bytes | non-null | used by UI? |
|---|---:|---:|---|
| description | 35,104 | 568 | yes — HierarchicalTable.tsx:83 |
| notes | 31,102 | 568 | yes — HierarchicalTable.tsx:83 |
| id | 24,683 | 568 | yes — keys/lookup |
| name | 22,012 | 568 | yes |
| error | 18,045 | 364 | yes — :84 → ErrorFixCell |
| fix | 12,828 | 204 | yes — :84 → ErrorFixCell |
| parent_id | 7,324 | 556 | yes — :22/:26/:37 |
| status | 4,344 | 568 | yes — :76/:87 |
| is_current | 2,839 | 568 (1 true) | yes — :33 (seed only) |
| start_time | 2,422 | **5** | yes — page.tsx:98,101,104-107 (single active item only) |
| **end_time** | **2,422** | **5** | **NO — appears only in the type (HierarchicalTable.tsx:8); zero readers in `dashboard/src`** |
| 9 pct columns (code…audit) | ~10,682 | — | yes — :9 cols |
| `ui`/`infrastructure` legacy keys | folded above | — | yes — legacyKeys :11 |
| item subtotal | 174,033 | | +72,734 whitespace + top-level/escapes = 363,969 |

## 1. Payload / transport

- **Waste is mostly whitespace, not fields.** Minifying alone removes 72,734 B (20%) of file bytes; gzip hides it (gzip raw 29,525 → gzip minified 28,114, only −4.8%). So minification helps disk/CPU, barely helps the wire.
- **Gzip is the dominant lever on the wire:** 363,969 → 29,525 B (−91.9%).
- **Transfer rate at `POLL_MS = 5000` (page.tsx:16):**
  - uncompressed: 363,969 / 5 = **72,794 B/s ≈ 71 KiB/s → 262 MB/h, 6.3 GB/day** per open tab.
  - gzip: 29,525 / 5 = **5,905 B/s ≈ 5.8 KiB/s → 21.3 MB/h, 510 MB/day** per open tab.
- **The ETag/304 path in route.ts is currently dead code.** route.ts:73-83 computes `W/"<size>-<mtime>"` and answers `304`, but:
  - page.tsx:40 fetches with `cache: 'no-store'` → the browser is not allowed to store or revalidate → no `If-None-Match` is ever sent, so line 81 can never fire.
  - route.ts:75/8 `Cache-Control: no-store` independently forbids storing the validator for later revalidation.
  - Net: every poll transfers the full body. Fix = client `cache: 'no-cache'` (revalidate-always) + `Cache-Control: no-cache`/`must-revalidate` server-side. Expected saving: ~99% of the 5.9 KB/s when the file is unchanged (mtime-based ETag only changes when an agent rewrites the file).
- **Server does redundant work before the 304 check:** route.ts:56 `readFile` (364 KB) and :63 `JSON.parse` (~4 ms) run *before* the `if-none-match` test at :80. The ETag needs only `stat` (:55), so the conditional check should move to right after :55. Saves ~364 KB read + 4 ms parse + 2.6 ms stringify per poll.
- **Field-usage verdict:** only `end_time` is provably unused (2,422 B). `start_time` costs 2,422 B to serve 5 values for a single active item; `notes` 31,102 B and `description` 35,104 B are read but only rendered for *visible* rows (12 collapsed by default).
- **Projected payload sizes (minified, gzip-9):**

  | projection | raw | gzip |
  |---|---:|---:|
  | current (minified) | 291,235 | 28,114 |
  | UI fields only (drop `end_time`, `start_time`, `is_current`) | 235,409 | 24,155 |
  | + drop `notes` | 291,235−notes ≈ 260 k | ~24,000 |
  | ids+name+parent+status+9 pcts only | 141,033 | **8,726 (−69%)** |

- **Recommendation order for payload:** (a) conditional GET/304 [biggest, ~0 bytes when idle]; (b) gzip verified on [29.5 KB]; (c) projection of `end_time`/`start_time`/`notes`/`description` [28.1 → ~24 KB gzip]; (d) full slim projection [→ 8.7 KB gzip]; (e) 30 s poll for hidden tabs — **already superseded**: page.tsx:77-88 stops polling entirely on `visibilitychange: hidden` and does an immediate `load()` + `start()` on visible (correct, no change needed).

## 2. React render cost

- **Rows actually rendered: 12 by default** (roots only — children render only inside the expanded branch, HierarchicalTable.tsx:90). Worst case = one root expanded; because the toggle stores `{[id]: true}` or `{}` (line 82) only one root can be open → worst case **224 rows** (12 + infrastructure's 212), never all 568.
  - default: 12 rows × 13 columns = **156 `<td>`**, 108 `ProgressCell`, 24 `ErrorFixCell`
  - worst: 224 rows × 13 = **2,912 `<td>`**, 2,016 `ProgressCell`, 448 `ErrorFixCell`
  - all-expanded (not reachable) would be 7,384 `<td>` / 5,112 / 1,136.
- **`renderRow` is not memoized** — plain closure at HierarchicalTable.tsx:72, rebuilt each render; no `React.memo` row component anywhere (`Fragment key={item.id}` at :90 is the only memo-ish thing, and key strategy there is correct/stable).
- **Rollup deps are correct but churn every poll:** `childrenByParent` :22-25 `[items]`, `roots` :26-29 `[items]`, `activeIds` :30-41 `[items, currentTaskId]`, `rollupMap` :42-66 `[items, childrenByParent]` (redundant but harmless — no staleness risk). Since page.tsx:46-48 does `res.json()` → `setState(data)`, **`items` is a brand-new array of brand-new objects every 5 s**, so all four memos invalidate on every poll. Cost measured ≈ 0.95 ms for the walk — cheap; the memoization *intent* is right, the input identity defeats it.
- **Chart data is recomputed on every render with no `useMemo`:** `categoryData` (568×9 `readNum` + filter ≈ 10 k ops) and `serviceData` at HierarchicalTable.tsx:69-70, then two `ResponsiveContainer` charts re-render (recharts SVG rebuild + ResizeObserver). This is the single largest per-poll render cost, and it runs even when the payload is byte-identical.
- **Redundant renders inside `load()`:** `setRefreshing(true)` + `setNow(Date.now())` (page.tsx:37-38) fire *before* the fetch, and `setState`/`setError(null)`/`setRefreshing(false)` after — React 18 batches each group, so ~**2 full renders per 5 s poll minimum**, even if data is unchanged. `setNow` alone guarantees a re-render every poll.
- **Layout thrash:** `ProgressCell.tsx:17` puts `transition-[width] duration-500` on a width% bar — 108 (default) to 2,016 (worst) simultaneous 500 ms width transitions right after a poll that changes values; combined with `min-w-[1800px]` table (HierarchicalTable.tsx:92) + `overflow-x-auto` this forces repeated style/layout passes across a 1,800 px layout. Additionally the expanded branch wraps children in a **nested `<table>` inside a `colSpan={13}` `<td>`** (:90) — table-in-table re-resolves layout twice on every expand/collapse (not per poll, but it is the most expensive interaction).
- **Strict mode** (`next.config.js:4` `reactStrictMode: true`) doubles render work in dev — dev timings overstate production by ~2×.

## 3. Repeated work

- **Does `load()` re-`JSON.parse` ~400 KB every 5 s? YES.** page.tsx:46 `await res.json()` on a 363,969 B body → ~3.8 ms parse + 364 KB transient string + a brand-new 568-item object graph every poll (plus server-side route.ts:63 parse + :85 stringify ~6.4 ms per request).
- **Redundant fetch of identical content: YES.** No content-hash/ETag is used client-side; `cache:'no-store'` (page.tsx:40) + `Cache-Control: no-store` (route.ts:8,75) force a full 29.5 KB body on every poll even though the file's mtime rarely changes within 5 s. route.ts:73-83 already has a working ETag/304 matcher — unreachable (see §1).
- **`ErrorFixCell` state hooks:** `'use client'` + `useState` at ErrorFixCell.tsx:5 — **2 instances per rendered row** (HierarchicalTable.tsx:84 renders it twice, once for `error`, once for `fix`). Actual mounted counts: **24 default, 448 worst-case, 1,136 only if all 568 rows were ever mounted at once** (they can't be — single-open toggle). Data shows `!error && !fix === 0`, so exactly one of the two cells always renders the `—` placeholder (ErrorFixCell.tsx:20,22): **half the instances (and half the hooks) are structurally useless.**
- `ProgressCell` has no state — pure, but un-memoized (no `React.memo`), so all 108/2,016 re-render each poll.

## 4. Memory

- **Retained old state on failed fetch: yes, by design.** page.tsx:50-51 only `setError('network')`; `setState` is not reached, so the previous 568-item graph (≲1 MB heap) stays mounted and keeps rendering (page.tsx:180 `state && <HierarchicalTable …>`). Correct UX; no leak — it is replaced on the next success and then GC-able.
- **Event listener cleanup: correct.** `visibilitychange` added at page.tsx:88 and removed at :91; interval created :68 / cleared :74; `aliveRef` flipped false at :60 so late `setState` from an in-flight fetch is suppressed (:47, :51, :53).
- **No `AbortController`:** an in-flight fetch at unmount still downloads and `JSON.parse`s the full 364 KB body (page.tsx:40,46) — wasted CPU/alloc only, results discarded by `aliveRef`. Minor.
- **Uncleared timer:** ErrorFixCell.tsx:14 `setTimeout(() => setCopied(false), 1200)` is never cleared on unmount → a 1.2 s timer + post-unmount `setState` (harmless in React 18, still a stale-timer smell).
- Old poll generations can't stack: `start()` guards `timer !== null` (page.tsx:67) and `stop()` runs on hidden (page.tsx:78-79).

## 5. Prioritized recommendations

| # | Pri | Recommendation | Evidence | Est. impact | Auto-apply? |
|---|---|---|---|---|---|
| R1 | **P0** | Skip re-render when payload unchanged: compare `data.last_updated` (or response `ETag`/`X-State-Last-Updated`) to current state before `setState`; drop `setNow`/`setRefreshing` churn for no-op polls | page.tsx:37-38,46-48; route.ts:77 | Kills ~95% of the 2 charts + 156-2,912 cells re-rendering every 5 s; ~2 renders → 0 on unchanged polls | **safe to auto-apply** |
| R2 | **P0** | Make the existing ETag path work: `fetch(..., {cache:'no-cache'})` instead of `'no-store'`, and stop sending `Cache-Control: no-store` for 200s (keep it on 503) | page.tsx:40 vs route.ts:73-83,75 | 29.5 KB → ~200 B on unchanged polls (**−99%** of the 5.9 KB/s); no server change needed | **needs decision** (coordinate with agent hardening route.ts; must confirm mtime-based ETag invalidates on every writer) |
| R3 | **P0** | In route.ts, evaluate `if-none-match` immediately after `stat`, before `readFile`/`JSON.parse`/stringify | route.ts:55 → 56 → 63 → 73 → 80 | Saves 364 KB read + ~6.4 ms CPU per poll per client | **needs decision** (owned by concurrent agent — do not touch) |
| R4 | **P1** | `React.memo` on `ProgressCell` and `ErrorFixCell` (props are numbers/booleans/strings → value comparison works across polls, unlike object props) | ProgressCell.tsx:1, ErrorFixCell.tsx:4 | Skips up to 2,016 + 448 leaf re-renders/poll when only a few values changed | **safe to auto-apply** |
| R5 | **P1** | `useMemo` for `categoryData`/`serviceData` (`[items]`) + `React.memo(HierarchicalTable)` (`props: items, currentTaskId` stay referentially stable when R1 short-circuits) | HierarchicalTable.tsx:69-70; page.tsx:180 | recharts (2× ResponsiveContainer/SVG) stops re-running on no-op polls — biggest single render win after R1 | **safe to auto-apply** |
| R6 | **P1** | Payload projection: drop `end_time` (dead), serve `start_time` only for `status==='in_progress'`, optionally defer `description`/`notes` to an expanded-row fetch; also emit minified JSON | HierarchicalTable.tsx:8 (only occurrence of `end_time`); byte table §0 | raw 363,969 → 291,235 (minify) → ~235 k (projection); gzip 28.1 → 24.2 KB; slim variant → **8.7 KB gzip (−70%)** | **needs decision** (DASHBOARD_STATE.json is a shared artifact; other consumers may read dropped fields) |
| R7 | **P2** | Render one `ErrorFixCell` per row only when its text exists (or merge into a single cell); halves default 24 → 12 and worst 448 → 224 state hooks | HierarchicalTable.tsx:84; data: `!error && !fix === 0` | −50% cell components in the two heaviest columns | **safe to auto-apply** |
| R8 | **P2** | `AbortController` for the fetch, aborted in the unmount effect | page.tsx:40,57-62 | Avoids one wasted 364 KB download+parse per page leave | **safe to auto-apply** |
| R9 | **P2** | Clear the `copied` timeout on unmount in `ErrorFixCell` | ErrorFixCell.tsx:14 | Removes a 1.2 s stale timer per unmounted cell | **safe to auto-apply** |
| R10 | **P2** | Replace the nested `<table>` expand branch (or render a flat list with `data-depth`) and keep `width` transitions only on changed bars | HierarchicalTable.tsx:90; ProgressCell.tsx:17 | Halves table-layout resolution on expand; fewer 500 ms layout passes across the 1,800 px table | **needs decision** (changes DOM structure/RTL table semantics; a11y review) |
| R11 | **P2** | Row-level `React.memo` is **not** recommended alone: `item` identity changes every poll after `res.json()` — it only pays off if paired with R1/structural sharing (reuse previous `items` when content is equal) | page.tsx:46-48; HierarchicalTable.tsx:72 | Would otherwise be 0% effective | **needs decision** |

Bottom line: transport is a 5.9 KB/s (gzip) or 72.8 KB/s (uncompressed) stream that a working 304 would reduce to ~nothing; render cost is chart- and cell-driven, not row-count-driven (12 rows visible by default, 224 worst), and every poll forces ≥2 renders because `setNow`/`setRefreshing` fire unconditionally.
