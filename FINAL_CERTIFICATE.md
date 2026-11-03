# FINAL_CERTIFICATE — Golden Reference Pack

**Certificate scope:** reference implementation/static & focused unit verification.  
**Baseline ZIP SHA-256:** `378373d960432f9fbcf3ed5944e35d72e742c25014524ad506dfe04a60f818e1`  
**Compared GitHub main head:** `c9349108cc10a3c55db5b7580f97c073d932036e`  
**Date:** 2026-10-10

## Certificate status

```text
REFERENCE ARCHITECTURE              PASS
REFERENCE CODE STATIC COMPILE      PASS
GOLDEN CONTRACT TESTS              PASS (21)
DATABASE CONTRACT                  PASS (24 core tables, static)
FIVE DOMAINS CONTRACT              PASS
DYNAMIC FUSION CONTRACT            PASS
GOLD IMPACT CONTRACT               PASS
ARABIC UX IMPLEMENTATION           INCLUDED
NO-DOCKER TARGET                   PASS (static artifacts removed)
LOCAL-AI-ONLY TARGET               PASS (static factory/config)
PAPER BROKER ISOLATION             PASS (unit/static)
EXECUTOR FINAL GUARD               PASS (unit/static)

DUCKDB MIGRATION RUNTIME           NOT RUN — ENV BLOCKED
REDIS INTEGRATION                  NOT RUN — ENV BLOCKED
FRONTEND BUILD/TYPECHECK           NOT RUN — ENV BLOCKED
LOCAL OLLAMA INFERENCE             NOT RUN
FULL 9-SERVICE PAPER E2E           NOT RUN
LIVE                               NOT CERTIFIED
```

### Overall

**CERTIFIED FOR APPLY + LOCAL VERIFICATION.**  
This is **not** a `READY FOR PAPER FUNDAMENTAL VALIDATION` certificate yet. That status can only be issued after the local agent applies the pack to the verified baseline and produces runtime/build/PAPER E2E evidence. It is never a guarantee of trading profitability.

## Non-negotiable local acceptance test

With Technical BUY + ML BUY 95% + A7 BUY while a HIGH-impact blackout is active:

```text
Central Risk = REJECT
Executor = BLOCKED
Real broker send calls = 0
MT5 new positions = 0
reason = NEWS_BLACKOUT
```

If any line fails, the only valid state is `NOT READY — BLOCKER FOUND`.
