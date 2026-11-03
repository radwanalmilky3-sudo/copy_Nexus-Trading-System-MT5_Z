# PAPER_BASELINE_CERTIFICATE — Nexus Trading System (Paper Fundamental Validation baseline)

**Scope:** certified local baseline for the PAPER FUNDAMENTAL VALIDATION phase (5 domains + fusion + reasoning chain + gold impact + Arabic explanations).
**Issued (UTC):** 2026-10-10T10:00:18Z
**Mode:** PAPER only (live execution disabled and re-verified disabled)
**Baseline ZIP SHA-256:** `378373d960432f9fbcf3ed5944e35d72e742c25014524ad506dfe04a60f818e1`
**GitHub main head (verified baseline):** `c9349108cc10a3c55db5b7580f97c073d932036e`
**APPLY backup:** `_golden_pack_backups\backup\20261010_041249_GOLDEN_PACK`

## Certificate status

```text
CURRENT SOURCE SHA MANIFEST        PASS WITH DOCUMENTED DRIFT (99/100 MATCH_AFTER,
                                   1 DIVERGED = proven-bug fix, see below; 0 MISSING)
DB SCHEMA / VERSION                PASS (live schema API: 27 tables = 24 fundamental
                                   + ticks/ohlcv/trades fleet tables)
GOLDEN CONTRACT TESTS              PASS (21/21, included in the 208/208 run below)
FULL BACKEND SUITE (post-fix)      PASS (208 passed, 141.4s, exit 0 — re-run AFTER
                                   the persistence fix; zero regressions)
FRONTEND BUILD / TYPECHECK         PASS (carried forward unchanged this phase:
                                   tsc --noEmit 0 errors, npm run build 0 errors,
                                   17 routes; no frontend files were modified)
PAPER EXECUTOR STATE               PASS (broker=paper, trading_mode=paper,
                                   real_broker_execution_enabled=false,
                                   broker_connected=true)
SERVICE HEALTH                     PASS (10/10 ports OPEN, 9000-9008 + 3100)
REDIS GUARD STATE                  PASS (auto_trade=false, kill_switch unset,
                                   fundamental blackout=clear, actively recomputed)
MT5 ACCOUNT (paper sandbox)        PASS (#2000020618, balance 1317.16 USD,
                                   XAUUSD positions 0)
NO-DOCKER / LOCAL-AI TARGETS       PASS (unchanged; Ollama local inference
                                   previously certified: "NEXUS OK")
LIVE                               NOT CERTIFIED (out of scope; live_certified=false)
```

## Environment incident found & fixed at the start of this phase (root cause of zero-data shells)

**Bug (proven, reproduced in isolation):** `services/nexus_data/fundamental_store.py` `upsert_source()` used `updated_at=CURRENT_TIMESTAMP` inside `INSERT ... ON CONFLICT(source_id) DO UPDATE SET`. DuckDB 1.5.5 binds `CURRENT_TIMESTAMP` in that position as a **column identifier** → `BinderException: Table "fund_sources" does not have a column named "CURRENT_TIMESTAMP"`. Reproduced on a scratch DuckDB 1.5.5 connection; `now()` (identical database clock semantics) works in the same position; `CURRENT_TIMESTAMP` in the VALUES clause is unaffected.

**Cascade (live evidence from run_stdout.log):** every `POST /api/data/fundamental/source` returned 500 → `fund_sources` stayed empty (0 rows) → 5,407 FK failures on `source_id` (fund_events, source_fetch_runs, source_health_history) → 7,407 FK failures on `event_id` (macro_releases, central_bank_events, expectations) → 2,122 FK failures on `prediction_id` (child chain) → all domain factor scores were zero-data shells and all gold predictions were neutral zero-confidence shells.

**Fix applied (1 token, semantics-identical, persistence infrastructure only — no scoring/fusion/contracts change):** `updated_at=CURRENT_TIMESTAMP` → `updated_at=now()` at `fundamental_store.py:50`. This is the **only** local source divergence from the golden pack (SHA_MANIFEST.json documents it: 99 MATCH_AFTER + 1 DIVERGED).

**Verification after fix:**
```text
fund_sources                 0 → 15 (all OFFICIAL_SOURCES registered)
fund_events                  0 → real calendar/Fed/macro events flowing
macro_releases               0 → 27 rows (real releases with forecast/previous;
                                   pre-release rows keep actual=null — no leakage)
central_bank_events          0 → 5 rows
factor scores                shells → real: monetary conf 73.5 (cov 100, fresh 100),
                                   geopolitical conf 75.2 (cov 74, fresh 100);
                                   macro/cross_asset/flows honest zeros (sources
                                   unavailable — documented per domain)
fusion / gold predictions    shells → real snapshots (e.g. bullish conf 70.16 with
                                   weight_reasons + transmission chain + horizons)
last fundamental.persistence_failed   2026-10-10T09:37:51Z (pre-restart);
                                   zero failures after the fix
news_poll_ok / calendar_poll_ok      active (last seen 09:44:40Z / 09:43:40Z)
pytest after fix             208 passed / exit 0
```

## Runtime state at certificate time

```text
Ports                 10/10 OPEN (9000-9008, 3100)
nexus-api             healthy, redis connected, duckdb connected
nexus-news            healthy, fundamental_runtime=true, blackout clear,
                      calendar_cache=83, news_cache=1 (provider-limited batch)
nexus-executor        healthy, broker=paper, real_broker_execution_enabled=false
Redis                 auto_trade=false, blackout clear, kill_switch unset
MT5                   #2000020618 balance 1317.16 USD, positions 0
DuckDB live schema    27 tables
SHA_MANIFEST.json     regenerated 2026-10-10T~09:58Z: 99 MATCH_AFTER / 1 DIVERGED
                      (documented fix) / 0 MISSING
```

## Status

```text
BASELINE CERTIFIED FOR PAPER FUNDAMENTAL VALIDATION
```

This certificate is **not** a `READY FOR LIVE` statement and never guarantees trading profitability. All domain validations in this phase inherit this baseline; any later source change re-triggers the SHA manifest check.

## Standing open tech debt (unchanged semantics; per user directive)

1. FK insertion warnings family — root cause found and fixed (see above); residual child-row warnings only occur when a parent insert legitimately fails (outage) and are expected noise.
2. nexus-news Redis client lacks socket timeouts — after an external Redis outage the news/calendar loops can hang; watchdog + service restart recovers them (verified this session).
