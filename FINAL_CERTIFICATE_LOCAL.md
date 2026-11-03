# FINAL_CERTIFICATE_LOCAL — Nexus Trading System (post-APPLY)

**Certificate scope:** local APPLY + full local verification of the Golden Reference Pack against the user's machine.
**Baseline ZIP SHA-256:** `378373d960432f9fbcf3ed5944e35d72e742c25014524ad506dfe04a60f818e1`
**GitHub main head (verified baseline):** `c9349108cc10a3c55db5b7580f97c073d932036e`
**APPLY backup:** `_golden_pack_backups\backup\20261010_041249_GOLDEN_PACK`
**Date:** 2026-10-10
**Mode:** PAPER (live execution disabled and verified disabled)

## Certificate status

```text
REFERENCE ARCHITECTURE              PASS (APPLY 100/100 MATCH_AFTER)
REFERENCE CODE STATIC COMPILE      PASS (compileall exit 0)
GOLDEN CONTRACT TESTS              PASS (21/21)
FULL BACKEND SUITE                 PASS (208/208)
DATABASE CONTRACT                  PASS (27 tables live = 24 fundamental + 3 fleet)
FIVE DOMAINS CONTRACT              PASS
DYNAMIC FUSION CONTRACT            PASS
GOLD IMPACT CONTRACT               PASS
ARABIC UX IMPLEMENTATION           INCLUDED (guard reasons + explanations in Arabic)
NO-DOCKER TARGET                   PASS (0 Dockerfiles in project root)
LOCAL-AI-ONLY TARGET               PASS (qwen2.5:3b real reply: "NEXUS OK")
PAPER BROKER ISOLATION             PASS (live: broker=paper, real_broker_execution_enabled=false)
EXECUTOR FINAL GUARD               PASS (live: auto-OFF + blackout blocks, broker=none)

DUCKDB MIGRATION RUNTIME           PASS (live schema API: 27 tables)
REDIS INTEGRATION                  PASS (live PING, guard state, heartbeat, caches)
FRONTEND BUILD/TYPECHECK           PASS (tsc --noEmit 0; npm run build 0, 17 routes)
LOCAL OLLAMA INFERENCE             PASS ("NEXUS OK")
FULL 9-SERVICE PAPER E2E           PASS (10/10 ports, health probes green)
CRITICAL BLACKOUT TEST             PASS (8/8: REJECT+BLOCKED+0 broker calls+0 MT5 positions)
LIVE                               NOT CERTIFIED (explicitly out of scope; live_certified=false)
```

### Non-negotiable acceptance test (pack FINAL_CERTIFICATE §Non-negotiable)

With Technical BUY + ML BUY 95% + A7 BUY while a HIGH-impact blackout is active:

```text
Central Risk = REJECT            (rule=NEWS_BLACKOUT, signature empty)
Executor = BLOCKED               (code=NEWS_BLACKOUT, broker=none)
Real broker send calls = 0
MT5 new positions = 0            (XAUUSD 0 → 0; balance 1317.16 unchanged)
reason = NEWS_BLACKOUT
```

All five lines verified live. Auto-trade remains OFF after tests (`nexus:system:auto_trade=false` persisted in Redis).

## Status

```text
READY FOR PAPER FUNDAMENTAL VALIDATION
```

This certificate is **not** a `READY FOR LIVE` statement and never guarantees trading profitability.

## Conditions attached (paper-validation watch list)

1. **Fundamental persistence FK chain** — ~4 warnings/min of child rows whose parent prediction insert failed; core tables otherwise persist. Non-blocking for guards/risk (Redis-driven); review insert order in a future pack iteration (semantics change — not applied here).
2. **nexus-news Redis client lacks socket timeouts** — after an external Redis outage the news/calendar loops can hang; the run.py watchdog + service restart recovers them (verified). A future pack iteration should add connect/read timeouts.
3. **WSL environment** — the WSL VM must stay up for Redis: `vmIdleTimeout` removed from `.wslconfig`, in-WSL `systemd-timesyncd` disabled (clock-jump storm fix), and a persistent keep-alive WSL session is running. If the VM ever dies, restart nexus-news via the run.py watchdog after Redis returns.
4. **Unpaid sources** remain `config_required` by design (listed in `SOURCE_HEALTH_ACTUAL.md`); BLS and Fed RSS are the live healthy sources.

## Runtime state at certificate time

```text
Ports                 10/10 OPEN (9000-9008, 3100)
nexus-api             healthy, redis connected, duckdb connected
nexus-news            healthy, redis True, blackout clear (actively recomputed)
nexus-executor        healthy, broker=paper, trading_mode=paper, real_broker_execution_enabled=false
Redis keys            auto_trade=false, blackout clear, kill_switch unset
MT5                   #2000020618 balance 1317.16 USD, XAUUSD positions 0
WSL VM                up (observation window: 15+ min, zero poweroffs, redis active)
SHA_MANIFEST.json     100/100 MATCH_AFTER
LOCAL_VERIFY_RESULT   STATIC_LOCAL_VERIFY_PASS, live_certified=false
```

Issued per pack rule 10 with evidence in: `IMPLEMENTATION_REPORT.md`, `DB_SCHEMA_ACTUAL.md`, `SOURCE_HEALTH_ACTUAL.md`, `TEST_RESULTS.md`, `TRACEABILITY_REPORT.md`, `UI_ACCEPTANCE.md`, `RISK_GUARD_EVIDENCE.md`, `SHA_MANIFEST.json`, `LOCAL_VERIFY_RESULT.json`.
