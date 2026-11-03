# Finding attribution against original ZIP — 2026-10-12

This note distinguishes newly introduced behavior from inherited behavior. Comparison source is the user-provided archive with SHA-256 `378373D960432F9FBCF3ED5944E35D72E742C25014524AD506DFE04A60F818E1`.

## Backtest outage -> zero-trade result: inherited

The original archive's `services/nexus_api/routers/backtest.py` contains the same fallback behavior as the developed local file: `_fetch_trades` catches a failure from the data-service fallback and returns `[]`; `run_backtest` then computes regular metrics from that empty list. The local failure reproduction confirms this remains observable today. Classify as **inherited defect retained in the developed version**, not a regression introduced by local development.

## User update partial write before role denial: added authorization path

The original archive does not contain `services/nexus_api/routers/admin.py` (the archive listing contains no `admin.py`); the local tree adds role-aware user management. The local isolated test shows that its update handler persists `app_users` before checking `roles.manage`, resulting in a partial update after HTTP 403. Classify as a **defect in the added user-management implementation**. Since no same endpoint exists in the baseline, do not claim this is a direct line-for-line regression.

## Scope caveat

These attributions are based on direct source inspection of the relevant ZIP entry and local file, plus isolated test reproductions. They do not establish authorship, intent, or when a specific local change was made. The rest of the 74 changed files has not yet received a semantic review.
