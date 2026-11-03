# TEST_RESULTS — Local Verification Evidence

**Date:** 2026-10-10 · **Mode:** PAPER · **Machine:** Windows 10 + WSL2 (Redis) + MT5 terminal (read-only checks)

## Gate results

| Gate | Command / endpoint | Result | Evidence |
|---|---|---|---|
| Pack PRE-APPLY verify | `VERIFY.ps1` (pre) | **PASS** | 100 checked, 0 drift |
| Pack APPLY | `APPLY.ps1` via compat wrapper | **PASS** | 100/100 `MATCH_AFTER`; backup `20261010_041249_GOLDEN_PACK` |
| Pack VERIFY (post) | `VERIFY.ps1` exit code | **PASS (7/7)** | `LOCAL_VERIFY_RESULT.json` = `STATIC_LOCAL_VERIFY_PASS`, `live_certified: false` |
| SHA manifest | `SHA_MANIFEST.json` | **PASS (100/100)** | every pack entry in expected post-APPLY state |
| Python full compile | `python -m compileall -q .` | **PASS** exit 0 | after torch py312 stub + backup moved out of root |
| Golden contract tests | `pytest tests/test_fundamental/test_golden_contracts.py` | **PASS 21/21** | includes 24-table schema, missing≠neutral, blackout block, paper isolation, no-mock-news, executor final guard |
| Full backend suite | `pytest tests/` | **PASS 208/208** | 197 pre-existing + 3 compat test fixes + 8 env-resolved; log `pytest_final.log` |
| TS typecheck | `npx tsc --noEmit` | **PASS** exit 0 | dashboard/ |
| Frontend production build | `npm run build` (dashboard) | **PASS** exit 0 | 17 routes built, First Load JS 87.3 kB shared |
| Preflight | `python preflight.py` | **LISTO** exit 0 | Redis PING OK, local AI qwen2.5:3b available, MT5 #2000020618 balance 1317.16, XAUUSD bid live, AutoTrading allowed, safe defaults PAPER/auto OFF |
| 9-service PAPER E2E | `python run.py --paper --replace-running` | **PASS 10/10 ports** | 9000-9008 + dashboard 3100 all serving; api/executor/news health checks green |
| DuckDB migration runtime | `GET :9001/api/data/fundamental/schema` | **PASS 27 tables** | 24 fundamental + ohlcv/ticks/trades (see `DB_SCHEMA_ACTUAL.md`) |
| Redis integration | live: caches, guard state, heartbeat, blackout publish | **PASS** | sync+async PING True; `nexus:` prefix JSON; heartbeat keys updating |
| Local Ollama real inference | `ollama run qwen2.5:3b` | **PASS** | model replied exactly `NEXUS OK` |
| API smoke | health/latest/schema/dashboard routes | **PASS 9/9 + UI 200** | see `UI_ACCEPTANCE.md` |
| Hard guard — auto OFF | `POST :9007/api/executor/order` (no approval) | **BLOCKED** | `GUARD_BLOCKED_AUTO_TRADE_OFF`, `broker=none` |
| Blackout guard (basic) | step7 script | **BLOCKED** | `GUARD_BLOCKED_NEWS_BLACKOUT` while active; restored state verified |
| **Critical Blackout Test (pack step 9)** | Technical BUY + ML BUY 95 + A7 BUY + HIGH blackout | **PASS 8/8** | see `RISK_GUARD_EVIDENCE.md` |

## Critical Blackout Test — acceptance lines (all satisfied)

```text
Central Risk = REJECT (rule=NEWS_BLACKOUT, signature empty)
Executor     = BLOCKED (code=NEWS_BLACKOUT, broker=none)
Real broker send calls = 0
MT5 new positions = 0   (XAUUSD positions 0 → 0, balance unchanged 1317.16)
reason = NEWS_BLACKOUT
Restored state blocks again via auto_trade_off (auto_trade=false persisted)
```

## Known issues (documented, non-blocking for paper validation)

1. **Fundamental persistence FK chain** — ~4 `fundamental.persistence_failed` warnings/min: child rows referencing a prediction whose parent insert failed in the same cycle. Parent tables otherwise persist correctly (fusion, predictions, explanations, fund_events, factor_scores, source_health verified via latest-rows API). Guards/blackout/risk are unaffected (Redis-state driven). Requires pack-side insert-order review (semantics change — not made unilaterally).
2. **nexus-news Redis client has no socket timeouts** — after an external Redis outage the news/calendar loops can hang until service restart (restarts are handled by run.py watchdog; incident documented in `IMPLEMENTATION_REPORT.md` §5).

## Not certified (unchanged from pack scope)

- LIVE execution — explicitly outside scope (`live_certified: false` everywhere).
- Profitability of any strategy or fundamental prediction.
- Sources requiring unpaid/absent API keys (listed in `SOURCE_HEALTH_ACTUAL.md`).
