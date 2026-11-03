# Remaining Audit and Repair Queue

Updated: 2026-10-14. Source of truth for per-file state: `FILE_MANIFEST.tsv`.

## Current inventory snapshot

Current manifest contains 554 scoped paths and reconciles exactly with the current scoped inventory (554/554; zero differences). Statuses: 226 not inspected; 84 partially inspected; 26 in progress; 26 inspected; 82 implemented but not verified; 4 need repair; 91 fixed and verified historically; 10 excluded; 4 generated; 1 unable to inspect. The broad review/fix bucket is 313/554 (56.5%), but only 91/554 (16.4%) are marked fixed and verified. These are path-status measures, not readiness or end-to-end completion.

## Active parallel assignments

| Owner | Scope | Deliverable | State / constraint |
|---|---|---|---|
| Hume | `services/nexus_data` (12 paths; 11 open), `services/nexus_api` (37; 23 open) | Static audit, narrow fixes, regression cases, residual risks | Active; tests/build prohibited until audit repair scope is complete; no live DB/services |
| Dalton | `dashboard/` (116 paths; 112 open) frontend and API integration | State/auth/control defects, narrow fixes, regression cases | Active; no tests/build or live service calls |
| Banach | `services/nexus_ml` (27 paths; 25 open), model metadata and ML config | Data correctness/leakage/lifecycle review and fixes | Active; no tests/build or live data/service access |
| Darwin | `services/nexus_executor` (9; 9 open), `services/nexus_risk` (7; 5 open) | Risk/execution correctness and safety review | Active; prioritize account-state fail-closed concern; no tests/build/live access |
| Hooke | `shared/` (24 paths; all open) | Redis/config/auth/runtime safety review | Active; no tests/build/live access |

Agent slots are currently full. On each completion, reuse the slot for the next independent queue: `services/nexus_agents` (47 paths; 42 open), `services/nexus_features` (12; 12 open), `services/nexus_monitor` (6; 6 open), and `services/nexus_news` (27; 26 open); then root orchestration/config/hidden files and docs/evidence; finally remaining tests/notebooks/diagnostics (62 tests paths; 46 open). Keep writes disjoint. The coordinator owns this queue and coverage reconciliation.

## Work remaining, in order

1. **P1 trading safety and correctness:** finish Risk/Executor review; confirm/reject proposals when the authoritative account snapshot is unavailable; inspect stream ack/reclaim/idempotency, approval expiry and broker mutation semantics. Do not touch the live database or place orders.
2. **P1 data/API correctness:** finish DuckDB ownership/write paths, data consumers and error contracts; complete gateway route authorization and response semantics. Never open the live DB from a second process.
3. **P1/P2 ML validity:** finish temporal labels, leakage-safe walk-forward evaluation, model artifact compatibility/rollback, retraining task lifecycle, and published prediction provenance.
4. **P1/P2 frontend integration:** reconcile every critical screen with backend contracts; remove fabricated success/zero states; verify permission gates and explicit confirmations in source.
5. **Remaining services:** static review agents, features, monitor, news/fundamental source lifecycle and network safety.
6. **Shared infrastructure:** Redis consumer pending/reclaim/dead-letter/idempotency contracts, config-loader/runtime-settings coherence, HTTP/auth/error handling.
7. **Root/config/docs/hidden and diagnostics:** validate startup/shutdown/restart ownership, configuration parity, secret handling without printing `.env`, stale reports, and scripts/notebooks without executing them.
8. **Manifest reconciliation:** resolve every row currently `Not inspected` (226), `In progress` (26), `Needs repair` (4), `Implemented, not verified` (80), and `Inspected (partial)` (83) to a fully inspected/fixed/excluded/unable status with evidence and reason. Reconcile component status and correct stale counts in `COVERAGE.md` before declaring static audit complete.
9. **Only after audit/repairs are complete:** perform the single consolidated test/build/isolated acceptance plan authorized by the user, with paper-only controls and no live DB mutation. The deferred tests are a verification gate, so overall system readiness cannot reach 100% before that gate passes.

## User constraints

- Make code/UI changes directly in the project; preserve existing data.
- Do not run tests, build, or start/stop services during the current audit/repair phase.
- Do not alter the live database or create experimental DB changes.
- No real trades; PAPER isolation only for the final acceptance phase.
- A 100% claim requires reconciled coverage and successful final verification, not a filled-in manifest alone.
