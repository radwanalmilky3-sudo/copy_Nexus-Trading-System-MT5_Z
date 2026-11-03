# Phase 4 Review — Event Timing Integrity + Strict Blackout (Reviewer R1)

**Date:** 2026-10-18
**Scope:** C1 (fundamental_schema.sql, fundamental_store.py) + C2 (blackout.py, runtime.py) + 2 new test files
**Verdict: APPROVE** — clean, with minor notes (C-1…C-4 below).

## 1. Diff scope & deletion classification

`git status` / `git diff HEAD --stat`: exactly the 4 expected modified files
(`fundamental_schema.sql` +31, `fundamental_store.py` +185, `blackout.py` +366/−23,
`runtime.py` +25/−~4) and 2 untracked test files. No `.env`, `run.py`, or `shared/`
changes (`git diff HEAD -- shared/` empty; `git status` clean for those paths).
No new services. No secrets in the diff.

**blackout.py deletions (23 lines across the change set) — all sanctioned:**
- Import line replaced (adds `re`, `date`/`time`, `ZoneInfo`).
- Class docstring extended; `version` "1.0.0" → "1.1.0".
- The inline legacy time-parse block (raw_time fallback chain, `fromisoformat` with
  `Z`→`+00:00`, naive→UTC, ±minute window, invalid→degraded) was **moved verbatim**
  into `_legacy_window()` (blackout.py:228). Verified line-by-line against
  `git show HEAD:...blackout.py` — literal copy, same "invalid" semantics.
- `evaluate()` restructured to route through the activation gate; clear/degraded
  return shapes unchanged.

**Legacy path exists in source, not only tests:** gate `event_carries_timing_fields()`
(blackout.py:104) + `_legacy_window()` (blackout.py:228); legacy branch in
`evaluate()` sets `kind="timed", tags=[]` and returns the untouched legacy payload
(no `_annotate` call). No unsanctioned deletion of legacy behavior.

Untracked `fx-trading-system-main/` in repo root: **pre-existing** (flagged in
PHASE1/2/3 reviews, timestamp 2026-10-17, before this work); not in the diff, not
touched by C1/C2. Exclude from commit (repeats C-3 from prior phases).

## 2. Schema & store (C1)

- 9 columns, each `ALTER TABLE fund_events ADD COLUMN IF NOT EXISTS`, all nullable
  (no `NOT NULL`, no defaults), plus the same 9 nullable in `CREATE TABLE`.
  **No backfill** of legacy rows — legacy insert stores NULL for all 9 (asserted by
  test).
- No `DROP`/`DELETE`/`TRUNCATE` on `fund_events` anywhere in the schema or store
  (grep verified).
- `mark_event_cancelled()` is **append-only**: `INSERT INTO fund_events` a new row
  (`{id}:cancelled`, `cancelled=TRUE`, `supersedes_event_id` → original) +
  `INSERT OR IGNORE` audit row. Original row never UPDATEd/DELETEd (verified in
  source and by `test_cancellation_is_append_only`: original still NULL/scheduled
  after cancel).
- `TIMING_QUALITY_VALUES` = exactly the 5 reference values. `get_event_timeline`
  includes cancelled/superseded by default (no silent net view).

## 3. Legacy gate (blackout.py)

Activation: `event_carries_timing_fields` — a field counts only when present and
meaningful; `None`, empty/whitespace strings, and default-negative `cancelled`
(0/False/"0") do **not** activate (blackout.py:75–90). Payload with none of the 9
fields meaningful → `_legacy_window` path → identical window math, identical payload
keys, `reason_code` NEWS_BLACKOUT/CLEAR/CALENDAR_DEGRADED. Tests assert full-dict
equality (`passthrough == legacy`) and key-set equality against frozen LEGACY_KEYS.

## 4. Date-only blackout

`civil_day_window()` (blackout.py:205): `[day 00:00, next-day 00:00)` local IANA
civil day converted to UTC — no invented minute anywhere (date-only never calls the
timed path; verified-quality-without-clock-time degrades to `invalid`, not a made-up
minute). Zone priority in `resolve_event_zone()` (blackout.py:171):
`release_tzid` → `decision_date_local` tz (datetime tzinfo or ISO offset) → UTC.
Tests cover America/New_York EDT, Europe/Berlin CET, UTC fallback, medium impact,
low-impact-stays-clear, and boundary persistence until local midnight.

## 5. `unverified_timing` is blocking (fail-closed)

- Blackout payload: `state = "unverified_timing"`, `active = True` — not "clear"
  (blackout.py:392).
- `shared/safety.py:193` allowlist is `{"clear", "active", "degraded", "unknown",
  "unavailable"}` — **does NOT contain `unverified_timing`** →
  `GuardDecision(False, SAFETY_STATE_UNAVAILABLE, ...)` fail-closed by absence.
  C2's claim verified. `git diff HEAD -- shared/` is **empty** — nobody loosened it.
- Enriched payload with NULL `timing_quality` (any other Phase-4 field set) also
  fails closed to `unverified_timing`.

## 6. Test suite

Full suite: `.venv\Scripts\python.exe -m pytest tests/ -q --tb=line -p no:cacheprovider`
→ **1218 passed, 0 failed**, 3 pre-existing deprecation warnings, 112.7 s.
New files contribute 38 tests (5 schema + 33 timing), matching the plan.
Baseline (excluding the 2 new files) re-collects at 1180 vs Phase-3's reported 1175
(+5 variance, see C-4) — all pass; not attributable to Phase-4 files.

## 7. Violations

**None.** No unsanctioned deletions, no schema unsafe operations, no safety
loosening, no scope creep.

## 8. Concerns (non-blocking)

- **C-1:** `version` bump 1.0.0→1.1.0 changes `policy_version` **and** the
  `blackout_id` hash (version is embedded in the SHA input) for identical legacy
  payloads. Decisions/windows are identical, but consumers diffing `blackout_id`
  across the rollout will see it change. Inherent to a policy-version bump; be aware.
- **C-2:** `degraded()` (blackout.py:406) still hardcodes `policy_version:
  "1.0.0"` while active/clear return `"1.1.0"` — inconsistent version reporting on
  the degraded path. Cosmetic.
- **C-3:** evaluate() uses inclusive `start <= now <= end`; a civil-day window's
  end instant (exactly local next-midnight) is still blocked, i.e. closed
  `[00:00, 24:00]` rather than half-open `[00:00, 24:00)`. Matches the legacy timed
  convention; one-instant difference. Negligible.
- **C-4:** Baseline collection 1180 vs Phase-3 report 1175 (+5) — env/conditional
  collection variance, not from Phase-4 files. All pass.
- **C-5 (carry-over):** untracked `fx-trading-system-main/` must stay out of the
  Phase-4 commit.

**Return to A0:** Verdict **APPROVE**. Totals: 1218 collected / 1218 passed / 0
failed (Phase-3 baseline ~1175–1180 + 38 new). Violations: none. Concerns: C-1
blackout_id/policy_version change for legacy payloads, C-2 degraded path version
string stale, C-3 inclusive end instant on civil-day windows, C-4 +5 baseline
collection variance, C-5 pre-existing untracked reference directory.
