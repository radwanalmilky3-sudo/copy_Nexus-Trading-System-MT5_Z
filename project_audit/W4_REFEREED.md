# W4-13 Methodology Referee — Independent Spot Audit (2026-10-16)
READ-ONLY audit of the truth-pass outputs. Sample: 12 items stratified (a/b/c/d). Evidence sources: FILE_MANIFEST.tsv, GIT_EVIDENCE_20261016.json, VERIFICATION_GATE_20261016.md, ≤10s file peeks.

| # | item | stored | evidence | verdict |
|---|---|---|---|---|
| a1 | nexus-risk (parent) | security=80, in_progress | W3_REAPPLY_OVERRIDES.json sets 80 after rollup; DASHBOARD_STATE confirms 80 (down from rollup 88 — conservative, gate proved tests only) | PASS |
| a2 | nexus-executor (parent) | security=75, done | override 75 applied and confirmed (rollup had 82); matches W3_REAPPLY reason "notes admit not live-MT5 tested" | PASS |
| a3 | frontend (parent) | tests=72 | override applied (rollup 42.34); **but 72 exceeds child-mean evidence by ~30 pts**; only supporting evidence is tsc PASS (gate ran no frontend suite) — documented hand-set, not phantom | **FLAG** (soft) |
| a4 | nexus-ml (parent) | ml=72, tests=72 | override applied (rollup 85); downward correction, W3_REAPPLY reason "no training/operational evidence, work uncommitted" — honest direction | PASS |
| b1 | file:shared/redis_client.py | done, sec=88, notes "fixed+verified" | FILE_MANIFEST "fixed and verified — Redis-5 XPENDING/XCLAIM reclaim, DLQ"; GIT_EVIDENCE shared summary + git_log commits e23da44/f3f2861; peek: 72 XPENDING/XCLAIM/dlq hits | PASS |
| b2 | file:services/nexus_api/routers/admin.py | done, all=70, error="…unverified" | FILE_MANIFEST says "Implemented, **not verified**"; peek confirms users.disable fix exists (2 hits); **status=done contradicts manifest "not verified" and own error field** | **FLAG** (status/notes misalignment) |
| b3 | file:dashboard/src/components/progress/ErrorFixCell.tsx | done, metrics null | FILE_MANIFEST "fixed and verified; tsc PASS"; GIT_EVIDENCE (119-file batch) lists it; file exists 2115B | PASS |
| b4 | file:scripts/apply_schema.py | done, metrics null | FILE_MANIFEST "fixed and verified; suite green"; GIT_EVIDENCE lists it; peek: CREATE/ALTER schema logic present | PASS |
| c1 | file:_check_db.py | pending, all metrics null, error=null | scan: 228 pending file:* items, **0 with any non-null metric or error** | PASS |
| c2 | file:package.json | pending, metrics null, error=null | FILE_MANIFEST "Inspected (partial), preserved unchanged"; pending correctly carries no score | PASS |
| d1 | file:services/nexus_news/url_safety.py | done, metrics null (newly added) | exists 1600B; FILE_MANIFEST "fixed and verified; URL safety; suite green"; GIT_EVIDENCE lists it; peek: URL-parsing code present | PASS |
| d2 | file:services/nexus_ml/artifact_guard.py | done, metrics null (newly added) | exists 836B; FILE_MANIFEST "fixed and verified; artifact allowlist guard"; GIT_EVIDENCE lists it; peek: ALLOW* constants present | PASS |

## Methodology-doc consistency
- W3_TRUTH.md flag resolved: W3_REAPPLY_OVERRIDES.json (6 ops) applied and confirmed — nexus-risk.security=80 ✔, nexus-executor.security=75 ✔, nexus-monitor.security=80 ✔, nexus-ml.tests/ml=72 ✔, nexus-agents.tests=80 ✔, frontend.tests=72/security=75 ✔ (all match stored state).
- `python scripts/update_dashboard.py --report`: 578 items (341 done / 228 pending / 9 in_progress). Python one-liner re-check: pending `file:*` with any metric or error = **0** ✔.

## Verdict
- **PASS: 10 / 12**
- **FLAGS: (1) frontend.tests=72 exceeds child-mean evidence (~42) by >10 pts — supported only by tsc PASS; declared override, not phantom. (2) admin.py status=done vs manifest "Implemented, not verified" + own error field "unverified" — status inflation.**
- **Overall: APPROVE-WITH-NOTES** — numbers are earned (manifest/git/file-backed, no invented 100s, max=88, 0 phantom metrics); two soft methodology inconsistencies to fix in next pass.
