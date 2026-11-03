# RISK_GUARD_EVIDENCE — Live Guard Proofs (PAPER mode)

All tests executed against the running fleet on 2026-10-10. Real broker send calls = **0** throughout. MT5 XAUUSD positions = **0** before and after.

## Guard architecture (verified in code, exercised live)

**Executor final guard** (`shared/safety.py evaluate_executor_guard`) — fail-closed order:
1. `system:kill_switch` → `GUARD_BLOCKED_KILL_SWITCH`
2. `system:auto_trade` must be `True` → `GUARD_BLOCKED_AUTO_TRADE_OFF`
3. `fundamental:blackout` → active/unknown → `GUARD_BLOCKED_NEWS_BLACKOUT` (Arabic reason passed through)
4. Signal staleness → `GUARD_BLOCKED_STALE_SIGNAL`
5. Risk approval required → `GUARD_BLOCKED_RISK_REJECT`
6. Only then paper (simulated) or live broker path

**Central risk** (`services/nexus_risk`, `POST :9006/api/risk/evaluate`) — evaluates `auto_trade` → blackout → risk rules; returns `decision` + `reason_code` + signature. TradeProposal validation enforces BUY `sl < entry` and conviction ∈ [0,1].

Persisted state keys (Redis, prefix `nexus:`): `system:auto_trade`, `system:kill_switch`, `fundamental:blackout` (JSON: active/state/reason/reason_ar/policy_version/checked_at).

## Test 6 — Hard guard without approval

Request: `POST http://127.0.0.1:9007/api/executor/order` with a valid BUY proposal, no risk approval.

```text
Response: GUARD_BLOCKED_AUTO_TRADE_OFF
broker:   none
```

Paper positions unchanged: `account.broker=paper, balance=10000` (paper ledger), nexus_count=0.

## Test 7 — Basic blackout guard

With `fundamental:blackout` set active in Redis:

```text
POST :9007/api/executor/order  →  GUARD_BLOCKED_NEWS_BLACKOUT
```

After restoring `state=clear, active=false` (and keeping auto_trade off):

```text
POST :9007/api/executor/order  →  GUARD_BLOCKED_AUTO_TRADE_OFF   (correct fail-closed order)
```

## Test 9 — Critical Blackout Test (pack acceptance, 8/8 PASS)

Payload: Technical BUY + ML BUY 95% + A7 BUY + HIGH-impact blackout active (`blackout_id=STEP9-CRITICAL-HIGH-TEST`, reason "HIGH impact news window").

| # | Check | Result |
|---|---|---|
| 1 | Central risk decision | **REJECT** |
| 2 | Risk rule/reason_code | **NEWS_BLACKOUT** |
| 3 | Risk signature | **empty** (no approval token issued) |
| 4 | Executor response | **GUARD_BLOCKED_NEWS_BLACKOUT**, `broker=none` |
| 5 | Paper mode unchanged | trading_mode=paper |
| 6 | Paper nexus positions | 0 (no simulated fill either — proposal rejected upstream) |
| 7 | MT5 real positions | 0 → 0 (terminal queried before/after via MetaTrader5 API) |
| 8 | After restore | auto_trade=false persisted → orders blocked with `auto_trade_off` |

Executor log line (run.py stdout):

```text
{"symbol":"XAUUSD","side":"BUY","code":"NEWS_BLACKOUT",
 "reason":"HIGH impact news window (STEP9 critical blackout test)",
 "event":"executor.final_guard_blocked","service":"nexus-executor","level":"warning"}
```

## Final persisted state at certificate time

```text
nexus:system:auto_trade      = false
nexus:fundamental:blackout   = {"state":"clear","active":false,"reason_code":"CLEAR",...}
nexus:system:kill_switch     = (unset)
```

## Statement

The non-negotiable acceptance test passes exactly as specified by the pack: during a HIGH-impact blackout, even a fully-aligned bullish stack (technical + ML 95 + A7) is REJECTED by Central Risk with reason `NEWS_BLACKOUT`, the executor blocks with zero broker calls, and the real MT5 account gains no positions. Auto-trade remains OFF after all tests.
