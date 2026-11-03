# Phase 0 Baseline Test Report

- **Date:** 2026-10-18
- **Tester:** T1 (Phase 0.1, NEXUS_MASTER_PLAN)
- **Workdir:** `D:\Nexus-Trading-System-MT5`
- **Python:** `D:\Nexus-Trading-System-MT5\.venv\Scripts\python.exe` (pytest 9.1.1, pytest-asyncio 1.4.0; no pytest-timeout installed)
- **Mode:** read-only; no services started, no data loading, no ML training, no backtests.

## Commands used

```bash
# 1) Full suite
D:\Nexus-Trading-System-MT5\.venv\Scripts\python.exe -m pytest tests/ -q --tb=line -p no:cacheprovider
# -> 1018 passed, 3 warnings in 215.30s (0:03:35)  [no hang, single run]

# 2) Phase-0 new tests, explicit
D:\Nexus-Trading-System-MT5\.venv\Scripts\python.exe -m pytest tests/test_risk/test_golden_decisions.py tests/test_data/test_research_lineage_migration.py -q --tb=line -p no:cacheprovider
# -> 18 passed in 0.64s
```

No split/`--timeout` re-runs were needed: the full suite completed in 3m35s (< 8-10 min budget) with no hangs.

## Summary counts (full suite: `tests/`)

| Metric        | Count |
|---------------|-------|
| Collected     | 1018  |
| Passed        | 1018  |
| Failed        | 0     |
| Errors        | 0     |
| Skipped       | 0     |
| Xfailed       | 0     |
| Xpassed       | 0     |
| Warnings      | 3     |
| Duration      | 215.30s (0:03:35) |

Warnings (non-fatal, dependency deprecations):
1. `langgraph/cache/base/__init__.py:8` — LangChainPendingDeprecationWarning (JsonPlusSerializer `allowed_objects` default change)
2. `fastapi/testclient.py:1` — StarletteDeprecationWarning (`httpx` with `starlette.testclient`, install `httpx2`)
3. `services/nexus_data/main.py:681` — FastAPIDeprecationWarning (`regex` kwarg → use `pattern`)

## Failures / errors with classification

| Test | Error (one-line) | Class |
|------|------------------|-------|
| — none — | — | — |

- **Code failures:** 0
- **Environmental failures:** 0 (no connection-refused / Redis / localhost-service errors observed; no services were started and none were required by the suite)
- **Unknown:** 0

## Phase-0 new tests confirmation

| Test file | Result |
|-----------|--------|
| `tests/test_risk/test_golden_decisions.py` | PASS (included in the 18 passed below) |
| `tests/test_data/test_research_lineage_migration.py` | PASS (included in the 18 passed below) |

Explicit run output: `18 passed in 0.64s` (both files, zero failures).

## Verdict

baseline captured
