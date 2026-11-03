# FUNDAMENTAL_UI_DATA_CONTRACT_REPORT

**Date (UTC):** 2026-10-10 ~13:00Z · **Live cycle verified:** `2026-10-10T12:53:43.768379Z` · **Mode:** frontend-only, scoring unchanged, backend untouched

## Contract (formal, implemented in `dashboard/src/lib/fundamental-contract.ts`)

```text
score_state:    AVAILABLE | UNAVAILABLE   (mirrors engine metadata.state — no scoring logic added)
evidence_state: PRESENT | NONE            (evidence_count = domain.details.length, real rows only)
domain_state:   DATA_AVAILABLE | DEGRADED | UNAVAILABLE

Rule 1: score_state=AVAILABLE                      => domain_state=DATA_AVAILABLE
Rule 2: score_state=UNAVAILABLE AND evidence_count>0  => domain_state=DEGRADED
Rule 3: score_state=UNAVAILABLE AND evidence_count=0  => domain_state=UNAVAILABLE
```

DEGRADED means only: real evidence exists but the full engine score was not computed this cycle. It does **not** mean neutral, and does **not** mean an engine score exists. Missing domain (absent from `domains[]`) derives as UNAVAILABLE.

## Files changed

```text
dashboard/src/lib/fundamental-contract.ts           NEW (pure derivation function, no deps)
dashboard/src/components/fundamental/FundamentalWorkspace.tsx
  - imports deriveDomainContract
  - DomainView: UNAVAILABLE early-return; DEGRADED banner shows evidence_count; rest unchanged
backend / scoring / DB / Redis / API                 NONE
```

## Runtime verification (live API 12:53:43Z, contract evaluated by the compiled contract module itself)

| Tab | score_state | evidence_state | domain_state | evidence_count | API result | rendered UI |
|---|---|---|---|---|---|---|
| MACRO | UNAVAILABLE | PRESENT | **DEGRADED** | **18** | meta_state=unavailable, details=18 real releases | amber DEGRADED banner + 18-row details table + honest zeros |
| MONETARY | AVAILABLE | PRESENT | **DATA_AVAILABLE** | 20 | conf 73.5, cov 100, 5 drivers, details=20 | full metrics + drivers + 20-row table (no banner) |
| CROSS_ASSET | UNAVAILABLE | NONE | **UNAVAILABLE** | 0 | meta_state=unavailable, details=0 | honest "بيانات هذا المحور غير متاحة" message |
| GEOPOLITICS | UNAVAILABLE | NONE | **UNAVAILABLE** | 0 | meta_state=unavailable, details=0 (this cycle; auto-upgrades when real clusters appear) | honest "بيانات هذا المحور غير متاحة" message |
| FLOWS | UNAVAILABLE | NONE | **UNAVAILABLE** | 0 | meta_state=unavailable, details=0 | honest "بيانات هذا المحور غير متاحة" message |

Matches the expected states exactly for this cycle.

## Tests (contract only — no backend semantics changed)

```text
Unit rules        6/6 assertions PASS
  AVAILABLE+details=2            => DATA_AVAILABLE / PRESENT
  undefined domain               => UNAVAILABLE / NONE / 0
  unavailable+details=1          => DEGRADED / PRESENT / 1
  unavailable+details=[]         => UNAVAILABLE / NONE
  unavailable+details=3          => DEGRADED / count=3
  unavailable+details=null       => UNAVAILABLE
Live fixtures     5/5 domains PASS (raw API JSON, cycle 12:53:43Z)  => CONTRACT_TESTS_PASS
tsc --noEmit      EXIT=0
Served bundle     app/dashboard/page.js contains DATA_AVAILABLE/DEGRADED/UNAVAILABLE
                  + new evidence_count banner; old ad-hoc string removed (hot-reload live)
npm run build     NOT run (next dev serving on 3100, per rule)
```

Note: the first fixture run failed due to a flattened test-fixture shape (`metadata_state` instead of `metadata.state`) in the temporary test script — the contract code was correct against the real DTO shape (unit tests passed); fixture re-saved raw from the API and passed.

## Final status

```text
FUNDAMENTAL UI DATA CONTRACT PASS
```
