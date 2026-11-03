# Phase 5 Review — Signal Contract + Lifecycle + Statistics (Reviewer R1)

**Date:** 2026-10-18
**Scope:** P5a (signal risk fields), P5b (paper lifecycle), P5c (statistical gates), A0 integration (`disclose_promotion_family` wiring)
**Mode:** Read-only source audit + full test suite. One review file written.

---

## Verdict: **APPROVE**

All changes are sanctioned, additive, and fail-closed where required. Full suite: **1271 passed / 0 failed** (Phase-4 baseline 1218 + 53 new tests: 20 executor + 13 lifecycle + 20 statistics — exact match with the plan). No unsanctioned deletions, no secrets, no `.env`/`run.py` changes, no DROP/DELETE/TRUNCATE outside test tmp DBs.

---

## 1. Diff / file-set audit

`git status` modified (11) + new (6, all expected):

| File | +/- | Classification |
|---|---|---|
| `shared/events.py` | +16/−1 | Sanctioned: 6 optional `SignalEvent` fields (None/`""` defaults) + `field_validator` normalising `""`/`"None"` stream round-trip strings back to None |
| `shared/research_contracts.py` | +7/−0 | Sanctioned: same 6 optional fields on `SignalContract`, additive only |
| `services/nexus_executor/main.py` | +78/−8 | Sanctioned: `_derive_sl_tp_from_signal_risk` + conditional call sites; deletions are `req.sl/req.tp` → `sl_val/tp_val` swaps |
| `services/nexus_ml/main.py` | +28/−1 | Sanctioned: publish optional risk fields (only when present in features, never fabricated); `disclose_promotion_family` wiring before `evaluate_promotion` |
| `services/nexus_ml/backtester.py` | +50/−2 | Sanctioned conditional-branch rewrite: ATR SL/TP intra-bar exits only when all three arrays present and positive; legacy time/reversal exits unchanged otherwise |
| `services/nexus_ml/traders/sl_tp_backtester.py` | +44/−21 | Sanctioned conditional-branch rewrite: entry prefers ATR×multiple distances; falls back to `sl_pips`/`tp_pips` unchanged |
| `services/nexus_ml/model_promotion.py` | +112/−1 | Sanctioned: `_trials_gate_enforced`, `check_trial_universe`, `disclose_promotion_family`, kwarg-only `trial_family_id`/`fdr_threshold`; −1 is a docstring line |
| `services/nexus_agents/main.py` | +13/−0 | Sanctioned: pass risk fields into evaluator context via `getattr` (tolerates absence) |
| `services/nexus_agents/research/registry.py` | +114/−3 | Sanctioned: `ALL_STATUSES += ("shadow","paper")`, `PaperPromotionRules`, active-gate in `set_status`/`evaluate_and_promote`; −3 are the old tuple, the status comment, and the unconditional `record.status = "active"` |
| `services/nexus_agents/research/researcher.py` | +22/−8 | Sanctioned P5b classification edits: `GRADUATED_STATUSES`, comparisons `== "active"` → `in GRADUATED_STATUSES`, docstrings |
| `services/nexus_agents/research/evaluator.py` | +164/−1 | Sanctioned: purged CV windows + fold aggregation + family disclosure; −1 is the `typing` import line |
| **New:** `services/nexus_ml/statistical_gates.py`, `services/nexus_data/trial_registry.py`, `services/nexus_agents/research/paper_tracker.py`, `tests/test_executor/test_signal_risk_fields.py`, `tests/test_agents/test_paper_lifecycle.py`, `tests/test_ml/test_statistical_gates.py` | — | All expected per plan |

### Deletion classification (46 deleted lines total)

Every deleted line is one of: (a) conditional-branch rewrites (executor SL/TP swaps, backtester entry/exit blocks), (b) docstring/comment lines, (c) P5b researcher/registry classification edits replacing the unconditional `status = "active"` assignment. **No blackout-style rewrites, no removed safety checks, no unsanctioned deletions.**

**Untracked `fx-trading-system-main/`:** pre-existing (flagged since Phase-1 review, timestamps predate all Phase work); not touched by Phase 5. Carry-over housekeeping item only.

## 2. Defaults / backward compatibility — PASS

- All 6 new `SignalEvent`/`SignalContract` fields default `None`/`""`; old constructors unaffected (verified by `test_signal_event_defaults`, `test_signal_contract_defaults`, stream round-trips).
- Executor ATR path is strictly conditional (`_derive_sl_tp_from_signal_risk`): requires finite `atr > 0` and at least one positive multiple; each component independently falls back when its multiple is None/non-positive; all-None → caller's SL/TP returned unchanged (byte-identical pass-through, tested including NaN/zero-entry).
- `SendOrderRequest` new fields default `None`/`""` — REST callers unchanged.
- ml/main publishes fields only when the feature context carries positive finite values; `group_id` only when a non-empty string — never fabricates.

## 3. Lifecycle (P5b) — PASS

- `ALL_STATUSES` strictly additive (`shadow`, `paper` appended; all legacy statuses retained).
- `set_status(…, "active")` fail-closed: NULL among `paper_trades`/`paper_pf`/`paper_wr` → blocked with reason `paper_metrics_missing`, current status kept.
- Grandfathering: already-`active` strategy with NULL paper metrics stays `active` on re-evaluation (`evaluate_and_promote` explicit branch; `test_existing_active_legacy_not_demoted_on_reeval`).
- Researcher never grants `active` directly: fresh backtested passes route `backtested → shadow → paper → active`; `GRADUATED_STATUSES` only affects accepted/rejected accounting.
- `PaperTracker`: Redis persistence matching the registry pattern (capped fill list + running aggregates blob, log-and-continue on failure, PF capped at 999, open fills tracked separately).

## 4. Statistics (P5c) — PASS

- **BH/BY correctness:** tests hand-compute against Benjamini & Hochberg (1995) Table 1 example p-values (`[0.0001,…,0.5929]` → q `[0.0007, 0.02835, 0.0679, 0.0679, 0.0679, 0.0987, 0.5929]`) — independently verified; BY conservativeness verified as BH × Hₘ; step-up running-min and tie handling correct; NaN/inf/out-of-range rejected.
- `minimum_resamples_for_fdr`: formula `ceil(m·cₘ/α)−1` hand-checked (m=1→9, m=2→19 at α=0.10).
- `paired_sign_test_pvalue`: exact two-sided, hand-checked known values (3/3→0.25, 2/4→capped 1.0, n=0→1.0).
- **Promotion hook placement:** after all existing metric gates, before `accepted` (`test_existing_fold_gates_run_before_trial_gate`: `accuracy_regressed` still wins). Reason codes exactly `trial_universe_undisclosed` (missing family, absent record, registry unreachable — fail-closed) and `fdr_threshold_exceeded`.
- **Evaluator:** purged fold windows with embargo from `max_holding_hours`; returns `[]` on short series and `None` on fold failure → **legacy single-window path always retained** as fallback (`windows` empty → old `sltp_bt.backtest` call; purged trades < 5 → legacy). Family disclosed per-run with unique id; disclosure failure logs and leaves family undisclosed (gate then rejects — fail-closed).
- **trial_registry:** `CREATE TABLE IF NOT EXISTS`, every failure logged-and-continued returning safe defaults (`None`/`[]`/`False`); `TRIAL_REGISTRY_DB` override for single-writer rule; no DROP/DELETE/TRUNCATE anywhere (tests use `tmp_path` DuckDB files).

## 5. Test-bypass semantics (`_trials_gate_enforced`) — ACCEPTABLE, noted concern

- Production (no `PYTEST_CURRENT_TEST` in env): **gate ON, fail-closed** — undisclosed family rejects promotion.
- `NEXUS_FDR_GATE=1/0` (or true/false/on/off/strict) forces either behaviour explicitly.
- Under pytest: gate OFF by default so the legacy promotion suite (which predates disclosure) keeps passing; new gate tests force it ON via `NEXUS_FDR_GATE=1` and one test pins the legacy-bypass behaviour.
- **No production bypass found:** `.env` contains no `NEXUS_FDR_GATE`/FDR entry (grep-verified); `run.py` and all service entrypoints unchanged in this diff; the env var appears only in `model_promotion.py` and the new test file.

## 6. Secrets / destructive SQL / config — PASS

- No secrets, keys, or credentials in the diff (pattern scan clean).
- No `.env` / `run.py` / config-manifest changes (git confirms neither file modified).
- Only SQL is `CREATE TABLE IF NOT EXISTS`, `INSERT`, `SELECT` in `trial_registry.py`.

## 7. Test totals

```
1271 passed, 3 warnings in 115.75s
```

Phase-4: 1218 → Phase-5: **1271** (+53 = 20 `test_signal_risk_fields` + 13 `test_paper_lifecycle` + 20 `test_statistical_gates`). Zero failures, zero skips introduced by this phase.

---

## Concerns (non-blocking)

- **C-1 (design note, executor):** the ATR-derived SL/TP are placed into `execution_payload`, whose canonical form is HMAC-compared byte-for-byte against the central-risk signed approval (which binds `sl`/`tp` in `_APPROVAL_NUMERIC_FIELDS`, `shared/safety.py:83`). So the derived values take effect only when central risk signed those same values; otherwise the guard rejects with "Execution terms differ from central risk approval". This is correctly fail-closed (matches the in-code comment), but means the feature is inert until the risk service also derives/signs ATR SL/TP — worth confirming that is the intended rollout order.
- **C-2 (gate bypass surface):** `_trials_gate_enforced` correctly defaults ON in production, but `NEXUS_FDR_GATE=0` in a production environment would silently disable the FDR gate. Intentional override per plan; recommend documenting that this var must never be set outside test harnesses.
- **C-3 (duplication, minor):** `_sign_test_p_value` in `evaluator.py` duplicates the logic of `paired_sign_test_pvalue` in `statistical_gates.py` (same math, verified). Consider consolidating later.
- **C-4 (carry-over):** untracked `fx-trading-system-main/` in repo root — pre-existing since before Phase 1; must stay out of the Phase-5 commit (add to `.gitignore` or remove).

---

**Return to A0:** Verdict **APPROVE**. Totals: 1271 passed / 0 failed (1218 + 53 new, as planned). Deletions: 46 lines, all sanctioned (conditional SL/TP rewrites, docstrings, P5b classification edits replacing unconditional `status="active"`). Violations: none. Concerns: C-1 (ATR SL/TP bound by signed-approval HMAC — inert until risk signs derived values; fail-closed), C-2 (`NEXUS_FDR_GATE=0` can disable gate in prod — by design, document), C-3 (minor sign-test duplication), C-4 (pre-existing untracked `fx-trading-system-main/`).
