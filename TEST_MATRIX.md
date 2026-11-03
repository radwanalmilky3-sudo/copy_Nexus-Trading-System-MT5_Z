# TEST_MATRIX — Golden Reference Pack

| Gate | Result in build sandbox | Evidence / next action |
|---|---|---|
| Full Python compile | **PASS** | `python -m compileall -q .` |
| Golden contract tests | **PASS — 21** | `pytest ... tests/test_fundamental/test_golden_contracts.py` |
| 24-table schema static contract | **PASS** | Golden test + `fundamental_schema.sql` |
| Missing != neutral | **PASS** | Unit contract |
| Native score vs Gold impact sign | **PASS** | CPI + hawkish monetary tests |
| Structural flow not M5 tactical | **PASS** | Unit contract |
| Dependency/double-count penalty | **PASS** | Fusion unit contract |
| High-impact blackout blocks | **PASS** | Blackout + executor guard unit contract |
| Historical future vintage rejected | **PASS** | Replay leakage test |
| PAPER uses simulated broker | **PASS** | PaperExecutor unit contract |
| No Docker artifacts | **PASS** | Static contract |
| Local-AI-only factory | **PASS** | Static contract |
| Safe defaults PAPER / auto OFF | **PASS** | Static contract |
| NewsFeed no mock live fallback | **PASS** | Static contract |
| A9 cannot directly call executor | **PASS** | Static contract |
| Executor final guard before broker send | **PASS** | Static contract |
| Required source IDs declared | **PASS** | Static contract |
| Stable blackout window ID | **PASS** | Unit contract |
| Gateway auto-trade reset OFF | **PASS** | Static contract |
| DuckDB migration execution | **NOT RUN — ENV BLOCKED** | sandbox lacks `duckdb`; must run locally |
| Redis integration/stream contract | **NOT RUN — ENV BLOCKED** | sandbox lacks Redis package/server; must run locally |
| Local Ollama real inference | **NOT RUN** | requires user's local Ollama/model |
| Frontend `npm run build` / full TS typecheck | **NOT RUN — ENV BLOCKED** | `node_modules` absent and no network in sandbox |
| Source live fetches/API keys | **NOT CERTIFIED** | depends on keys/endpoints/licenses; unavailable must stay explicit |
| Full PAPER E2E 9-service run | **MUST PASS LOCALLY** | agent executes after APPLY |
| Critical BUY+95+A7+HIGH blackout -> 0 broker calls | **MUST PASS LOCALLY** | integration evidence required |
| LIVE execution | **NOT CERTIFIED** | explicitly outside this pack |

## Required local acceptance

A local certificate is forbidden unless Python compile, backend tests, frontend build/typecheck, DuckDB migration, Redis integration, source status, and PAPER E2E evidence are recorded. A blocker yields `NOT READY — BLOCKER FOUND`.
