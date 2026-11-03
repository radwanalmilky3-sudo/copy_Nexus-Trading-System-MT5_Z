# Nexus System Final Acceptance Plan

> **For agentic workers:** Use `superpowers:executing-plans` to carry out this plan after the full audit and all approved repairs are complete. Steps use checkbox syntax for tracking.

**Goal:** Perform one final, one-hour end-to-end acceptance run of the fully audited Nexus project and report whether it is ready for its declared PAPER-mode use.

**Architecture:** The acceptance run is a single bounded 60-minute soak after static audit, confirmed fixes, and one consolidated preflight are complete. It must use an isolated disposable database and Redis state (or verified test copies), PAPER mode, and test/replay inputs; it must not send broker orders or mutate the user's live database. The audit lead collects service, API, dashboard, stream, data-integrity, and resource evidence into one timestamped report.

**Tech Stack:** Windows PowerShell, project `run.py`/preflight, Python test suite, local TypeScript compiler, project health/API endpoints, isolated Redis and DuckDB test copies.

**Spec:** Full engineering audit objective; `project_audit/COVERAGE.md`; `project_audit/STREAM_ACK_REVIEW_20261014.md`; current project safety constraints.

## Global Constraints

- Run this acceptance plan only after every in-scope inventory item is inspected, explicitly excluded with rationale, or recorded as blocked with evidence; confirmed repairable P0/P1 issues must be fixed.
- Use PAPER mode only; never submit a real order or change the user's trading mode.
- Do not open, modify, or replace the user's live DuckDB/WAL; use a disposable isolated copy or test database.
- Do not use production Redis state; use an isolated disposable Redis instance/namespace and verify its identity before startup.
- Do not rotate secrets or change security settings during the soak; use already validated test configuration.
- The soak duration is exactly 60 minutes once readiness checks pass; failed readiness checks do not consume the soak window.
- A failure means the system is **not accepted**. Repair and a new full acceptance run are required before claiming readiness; never force a pass to preserve the one-run target.

## Review Focus

- Any service restart, crash loop, or readiness loss during the 60-minute interval — record service, timestamp, and logs; the run fails.
- Any unhandled processing error, corrupted/missing test record, or unbounded Redis pending entry — record stream/group/message and error; the run fails.
- Any non-PAPER mode, broker order submission, or access to live user DB/Redis — abort immediately and classify as a safety failure.
- Dashboard data that is shown as current after an API/data-source failure — capture endpoint response and rendered state; the run fails.
- CPU/memory growth or queue depth that does not stabilize during the interval — record beginning/end samples and thresholds; the run fails pending an explicit resource budget.

---

### Task 1: Prove the acceptance environment is isolated and safe

**Files:**
- Read: `project_audit/COVERAGE.md`
- Read: `run.py`, `preflight.py`, and test/deployment configuration (do not read secret values)
- Record: `project_audit/FINAL_ACCEPTANCE_REPORT.md`

**Interfaces:**
- Consumes: completed coverage manifest, repair disposition, safe test configuration.
- Produces: a recorded PASS/FAIL for isolation, PAPER mode, and zero real-order capability before the soak.

- [ ] Verify all required audit items have final statuses and no confirmed P0/P1 issue is left without a documented containment decision.
- [ ] Start only isolated test Redis and disposable DuckDB state; prove endpoints/paths are not the user's live instances.
- [ ] Run consolidated preflight once and verify PAPER mode, service credentials, signing keys, and loopback bindings without printing secrets.
- [ ] Verify order execution is paper/test-adapter-only and broker order methods are unreachable or stubbed.

### Task 2: Run the single 60-minute end-to-end soak

**Files:**
- Record: `project_audit/FINAL_ACCEPTANCE_REPORT.md`
- Evidence: timestamped service health, API checks, dashboard state, Redis stream counters, disposable DB checks, and resource samples.

**Interfaces:**
- Consumes: Task 1 isolation PASS.
- Produces: one 60-minute evidence bundle and a final PASS/FAIL disposition.

- [ ] Start the complete project stack in isolated PAPER mode and verify all expected services and dashboard routes are ready.
- [ ] Exercise supported read, event, and paper-order paths using safe test/replay data; do not place live orders or access the live DB.
- [ ] Observe health, process restarts, logs/errors, stream pending counts, expected test-record persistence, dashboard freshness, CPU, and memory throughout the hour.
- [ ] Stop only the processes created by this acceptance run and verify their owned ports are released; do not terminate unrelated processes.
- [ ] Mark PASS only if all invariants held for the full 60 minutes and attach evidence; otherwise record FAIL, preserve diagnostics, and do not claim readiness.

### Task 3: Publish the acceptance disposition

**Files:**
- Modify: `project_audit/FINAL_ACCEPTANCE_REPORT.md`
- Update: `project_audit/COVERAGE.md`

- [ ] Record exact start/end times, code/worktree identity evidence available, environment isolation, commands, exit codes, warning/error counts, health snapshots, stream counts, DB integrity, and resource measurements.
- [ ] Separate verified results from unsupported claims; state any untested production-only integration explicitly.
- [ ] State the final disposition as `PASS — PAPER-mode acceptance only`, `FAIL`, or `BLOCKED`; never imply live-trading certification from a PAPER test.

---

**Current status (2026-10-14):** Not started. The full audit and repair scope remains incomplete. Last full Python suite (899 passed, 3 warnings) predates the newest Risk trade-close changes; the related focused group passed 48 tests. Those results are not the final acceptance run. The 60-minute soak is reserved for after system-wide audit completion, not after an individual repair batch.
