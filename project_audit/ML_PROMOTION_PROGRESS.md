# ML-03 implementation progress

Plan: `docs/superpowers/plans/2026-10-14-ml-model-promotion.md`
Spec: `docs/superpowers/specs/2026-10-14-ml-model-promotion-design.md`

Ruling: Implement in the authorized project directory without a Git worktree — `.git` is absent, so worktree/commit-based rollback is unavailable; retain all existing files and use tests plus model-generation rollback. Cost if wrong: no VCS checkpoint for reverting workspace edits.

Ruling: Preserve the incumbent anomaly detector only when its feature schema exactly matches; reject a candidate on mismatch, and never auto-introduce an unscored detector. — The anomaly flag gates signals to `NO_TRADE`, so classifier acceptance does not validate its operational behavior. Cost if wrong: retrains with changed feature schemas may be rejected more often until a separate anomaly acceptance design exists.

Ruling: Require every supervised model artifact in a candidate bundle to have complete comparable same-fold metrics before promoting any part of the bundle. — A bundle-level pointer switches all included models, so partial per-model acceptance could activate an unmeasured component. Cost if wrong: one model with unavailable probabilities can block promotion of other improved models.

## Tasks

- Task 1: complete — 7 registry tests passed; active-pointer replace failure preserved the previous manifest; startup fallback and path checks passed.
- Task 2: complete — strict save/load tests passed; existing ML model tests remained green.
- Task 3: complete — 10 promotion tests passed for metric gates, row/fold/target identity, anomaly preservation, and invalid metrics.
- Task 4: complete — candidate orchestration tests verified rejection, promotion, and activation failure without losing the prior serving object.
- Task 5: complete for ML-03 — startup fallback, legacy compatibility, coverage reconciliation, and reports updated. The overall project audit remains incomplete.

Final review: self-review by implementer; no Git metadata exists for a review diff, and no separate reviewer was dispatched. Inspection rechecked registry path/manifest handling, strict ensemble loading, same-fold metric binding, cache/pointer update order, anomaly preservation, and startup fallback. No unresolved Critical/Important finding in the ML-03 changes; market-data and runtime integration remain unverified.

## Verification

- Final verification: `\.venv\Scripts\python.exe -m pytest tests\test_ml -q` → 48 passed; `\.venv\Scripts\python.exe -m pytest -q` → 339 passed, 2 deprecation warnings, 38.91s; `\.venv\Scripts\python.exe -m compileall -q services\nexus_ml tests\test_ml` → exit 0.
- Inventory: 476 manifest rows, reconciled with zero unmanifested source files; 81/476 (17.0%) reviewed-or-more, 380 not inspected. Full audit is not complete.
- Live services, Redis, DuckDB, MT5, and trading actions are out of scope and will not be started.
