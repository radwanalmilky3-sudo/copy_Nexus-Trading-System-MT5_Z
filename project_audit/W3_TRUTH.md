# W3-12 Truth Regression Verifier — Diff Forensics
Compared `DASHBOARD_STATE_PRE_TRUTH_20261016.json.bak` (568 items) vs `DASHBOARD_STATE.json` (578 items). READ-ONLY audit.

## 1. Phantom removal — PASS
| metric | bak | now | expect |
|---|---|---|---|
| `file:*` + status=pending + any non-null metric | **291** | **0** | 291 → 0 |

Exactly the 291 pending file items had their 9 metric columns nulled (status kept `pending`; pending count now 228 = 291 − 63 flips + 0). Column non-null counts confirm: code 568→277 (=568−291), tests/audit/security/dashboard identical arithmetic. No collateral nulling (see §6).

## 2. Status flips — PASS
- pending→done: **63** (expect ≈63) ✔
- done→pending: **0** ✔ (other transitions: 0)
- items removed: **0** ✔
- items added: **10** (expect ≈10) ✔ — all `status=done`, all metrics null (no fabricated scores):
  1. `file:dashboard/src/components/progress/ErrorFixCell.tsx`
  2. `file:dashboard/src/components/progress/HierarchicalTable.tsx`
  3. `file:dashboard/src/components/progress/ProgressCell.tsx`
  4. `file:dashboard/src/lib/system-state.ts`
  5. `file:project_audit/DISTRIBUTED_FIX_BATCH_20261016.md`
  6. `file:project_audit/VERIFICATION_GATE_20261016.md`
  7. `file:scripts/apply_schema.py`
  8. `file:scripts/update_dashboard.py`
  9. `file:services/nexus_ml/artifact_guard.py`
  10. `file:services/nexus_news/url_safety.py`

## 3. Overrides — 5/13 stuck, 8 overwritten by post-override rollup (FLAGGED)
| target | decided | bak | now | verdict |
|---|---|---|---|---|
| nexus-risk.security | 80 | 88 | **88** | LOST → rollup (child mean 88.0) |
| nexus-executor.security | 75 | 88 | **82** | LOST → rollup (child mean 81.78) |
| nexus-monitor.security | 80 | 88 | **88** | LOST → rollup (child mean 88.0) |
| nexus-ml.tests | 72 | 82 | **85** | LOST → rollup (85.0) |
| nexus-ml.ml | 72 | 82 | **85** | LOST → rollup (85.0) |
| nexus-agents.tests | 80 | 72 | **75** | LOST → rollup (75.0) |
| frontend.tests | 72 | 58 | **42** | LOST → rollup (42.34) |
| frontend.security | 75 | 70 | **62** | LOST → rollup (62.07) |
| nexus-data.database | 75 | 82 | **75** | APPLIED (children have no `database` → rollup skipped) |
| progress-reconcile.dashboard | 88 | 85 | **88** | APPLIED (no children) |
| progress-reconcile.audit | 85 | 80 | **85** | APPLIED |
| progress-reconcile.infra | 80 | 75 | **80** | APPLIED |
| progress-reconcile.security | 70 | null | **70** | APPLIED |

**Ordering confirmed:** overrides ran BEFORE null+rollup; rollup recomputed every parent that has scoring children and clobbered 8 of 13 overrides. Every replacement value **is child-mean-honest** (drift ≤0.35, §5) — so no fabrication, but 8/13 decided targets were silently discarded. FLAG: override pass must run AFTER rollup, or rollup must pin hand-set parents.

## 4. No fabricated 100s — PASS
- now: max numeric across all items = **88** (`shared.security`); items at 100 = **0**; values >95 = **0**
- bak: max = 89, at 100 = 0 → truth pass did not push anything up; ceiling lowered.

## 5. Rollup sanity — PASS (now)
Stored vs children mean (non-null children, tol ±1):
- `nexus-executor.code` 73 vs 73.33 (−0.33); `nexus-executor.security` 82 vs 81.78 (+0.22)
- `frontend.tests` 42 vs 42.34 (−0.34); `nexus-data.code` 74 vs 73.75 (+0.25)
- All 12 top-level parents × 9 columns: **drift >1 count: bak = 65 → now = 0** (e.g. `frontend.dashboard` 84 vs 6.6 in bak, now 7 vs 6.66). Rollup repaired a large pre-existing parent-inflation defect.

## 6. Net effect (bak → now), honest direction
Raw all-item column means:
| col | bak | now | raw Δ | residual Δ on retained 277-item cohort |
|---|---|---|---|---|
| tests | 64.61 | 60.09 | **−4.52** | −0.07 |
| audit | 66.15 | 63.70 | **−2.45** | −0.28 |
| security | 71.06 | 71.21 | +0.15 | −0.03 |
| code | 63.35 | 70.66 | +7.31 | **+0.08** |
| ml | 17.84 | 23.19 | +5.35 | +0.02 |
| dashboard | 1.64 | 3.10 | +1.46 | −0.27 |
| redis | 4.77 | 7.90 | +3.13 | −1.90 |
| database | 12.38 | 19.04 | +6.66 | **−2.62** |
| infra | 18.72 | 31.28 | +12.56 | −0.92 |

- tests/audit **down** as required ✔ (phantom tests mean 68.8 / audit 68.2 were above average, so nulling them mechanically lowers the average).
- Columns showing raw UP are **100% composition effect**: phantom cohort means were code 56.5, dashboard/redis/database/infra 0, ml 12.8 (all below average). Counterfactual "no-edit after nulling" prediction matches observed within ±0.08 for code/ml/dashboard/security/tests; explained residual only for database (−2.62 = nexus-data 82→75 override ✔) and redis (−1.90 = parent re-rolls, children untouched).
- **No column went UP without a reason; on a fixed cohort no column rose materially (+0.08 max).** No item-level fabricated increases except the 10 parent rollups (nexus-* →85/88, frontend.infra 54→80, progress-reconcile overrides) — all child-mean-derived or declared overrides.

## 7. Regression scan — PASS
- Collateral metric loss (non-phantom item → null): **0**
- Items removed: 0; done→pending: 0; other status transitions: 0
- No new item carries any numeric metric (all 10 additions are metric-null)

## Verdict
**PASS with 1 flag.** Phantom 291→0, flips 63/0, additions 10, max 88 / zero 100s, rollup drift 65→0, no fabricated or collateral edits — the truth pass did exactly what was decided. **FLAG:** 8 of 13 hand-set overrides (nexus-risk/executor/monitor security, nexus-ml tests+ml, nexus-agents tests, frontend tests+security) were overwritten by the subsequent rollup; replacement values are child-mean-honest but differ from the decision — re-apply overrides after rollup.
