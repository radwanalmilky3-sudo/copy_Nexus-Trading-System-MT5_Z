# Risk Approval Payload Binding Plan

> Inline implementation plan for the current Nexus project checkout; no Git metadata is available for a worktree or commit ledger.

**Goal:** Ensure a central risk approval signature is cryptographically bound to the exact approved trade terms and the executor rejects any mismatched order before broker access.

**Architecture:** Risk constructs a versioned canonical payload containing proposal identity, expiry, symbol, side, entry, SL, TP, approved size, signal timestamp, order type, execution price, and slippage, signs it, and carries it through both the risk REST and Redis-stream paths. Executor verifies the signature and equality between the approved payload and the actual execution request for both REST and stream paths. Autonomous ML must forward the exact approved terms rather than adjusting size/prices after approval.

**Tech Stack:** Python, FastAPI/Pydantic, HMAC-SHA256, pytest.

**Spec:** `project_audit/TRADE_FLOW_REVIEW_20261012.md`, P1 finding “approval proof is not bound to the approved order.”

## Global Constraints

- Fail closed when a payload field is missing, malformed, expired, or differs.
- Preserve the existing paper/live broker-selection gate and do not connect to a broker.
- Do not start services, access Redis/MT5, or submit an order during tests.
- Use the project's existing test environment and focused suites; no dependency changes.

## Review Focus

- A valid signature replayed with a changed symbol, side, entry, SL, TP, size, signal timestamp, order type, execution price, slippage, proposal ID, or expiry must be rejected.
- Both REST and stream execution paths must verify against their actual order fields before broker access.
- Smart routing must not change a risk-approved order type or price after guard validation; a changed route must fail closed before broker acquisition.
- Risk REST responses and stream events must carry exactly the values used to mint the signature.
- Autonomous ML must not mutate approved size/SL/TP or replace the signed signal timestamp.
- Existing paper-mode guard and expired/missing-signature behavior must remain fail-closed/unchanged.

## Files and Interfaces

- Modify `shared/safety.py`: introduce canonical payload serialization; sign/verify a complete approval payload; guard compares the signed payload to the execution payload.
- Modify `services/nexus_risk/main.py`: mint and return/pass the same payload in REST and stream approval paths.
- Modify `services/nexus_executor/main.py`: build execution payloads and verify before broker access in REST and stream paths.
- Modify `services/nexus_ml/traders_api.py`: forward the returned approval payload and exact approved terms.
- Test `tests/test_fundamental/test_golden_contracts.py` plus focused risk/executor tests as needed.
- Update `project_audit/COVERAGE.md` and `TRADE_FLOW_REVIEW_20261012.md` with implementation and verification evidence.

## Execution Steps

1. Add direct canonical-signature and executor-guard tamper tests; run them and observe expected failure before production edits.
2. Implement canonical signing and fail-closed payload equality in shared safety; run shared safety regressions.
3. Update risk REST/stream producers and executor REST/stream consumers; add tests for payload propagation/field preservation and rerun relevant tests.
4. Update the autonomous ML caller to preserve signed values; verify payload passed to executor matches risk response.
5. Run focused risk, executor, and golden-contract suites; record any unverified end-to-end or live-runtime boundaries.
