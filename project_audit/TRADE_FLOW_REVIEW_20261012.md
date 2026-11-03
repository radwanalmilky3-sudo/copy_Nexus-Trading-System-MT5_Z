# Trade-flow review — 2026-10-12

## Scope and safety

Read-only static review of the local source files listed below. No service, Redis, MT5, broker, or database was started or contacted; no order was placed. This is not proof that runtime configuration is paper-only.

## Observed event chain

1. `services/nexus_agents/main.py` consumes `RedisStream.SIGNAL_STREAM`; evaluation short-circuits when `system:kill_switch` is set and publishes final verdicts through `_publish_results`.
2. `services/nexus_risk/main.py::_risk_stream_consumer` consumes `RedisStream.AGENT_VERDICT`, converts event fields to `TradeProposal`, rejects missing entry/SL, evaluates the proposal, then publishes `RedisStream.RISK_DECISION`.
3. Approval decisions receive expiry and an HMAC approval signature. If the internal secret is absent, the risk consumer changes the approval to REJECT.
4. `services/nexus_executor/main.py::_execution_stream_consumer` ignores non-APPROVE decisions, calls `evaluate_executor_guard(... require_risk_approval=True)`, applies dedup/anti-stacking/lot clamping, obtains a broker and calls `send_order`.
5. `_get_broker` selects `DEFAULT_BROKER` only when `live_mode_enabled()` is true; otherwise it selects `paper`. This is a source-level safety gate, not a runtime-mode verification.
6. The executor lifecycle-action worker also checks `system:kill_switch`; it is a separate path from the risk-decision stream and requires its own safeguards/tests.

## Evidence-backed observations

- **Positive control present (static):** signed, expiring risk approval is passed in event data and rechecked at executor; rejected risk decisions do not proceed to order construction.
- **P1 security finding — approval proof was not bound to the approved order.** `shared/safety.py::approval_signature` previously signed only `proposal_id:expires_at_epoch`, so changed order terms could pass the proof check.
- **Fix implemented (2026-10-14):** approvals now use canonical version-1 HMAC payloads covering symbol, side, order type, approved entry, execution price, SL, TP, approved size, slippage, signal timestamp, proposal ID, and expiry. `evaluate_executor_guard` compares signed terms to actual request terms. Risk canonicalizes symbols before evaluation; REST and stream producers create/carry the payload; executor REST and stream paths verify before broker acquisition and use canonical symbol/side values for the broker request. Autonomous ML forwards the exact terms; risk applies its regime size multiplier before signing, and rejects a reduced size below 0.01 instead of silently restoring the minimum. Pending-order prices must equal the risk-evaluated entry. If smart routing proposes an order type or price different from signed terms, executor fails closed before broker acquisition. Old ID/expiry-only proofs fail closed.
- **Verification:** Tamper tests cover all 12 signed inputs; REST executor tests verify size mismatch, smart-router changes, and canonical symbol/side behavior; risk REST tests verify adjusted-size signing, reject an unappliable policy reduction, and reject a pending price different from evaluated entry. `compileall` passed for all four modified Python modules. Focused risk/executor/API/shared-event suites: **67 passed** (2026-10-14, rerun after the latest corrections). No broker, Redis, live service, or order was used.
- **Residual coverage:** Risk stream payload creation and executor stream consumption were inspected and compiled but not exercised end-to-end with fake Redis. The standalone agent execution helper still does not forward approval fields; search found no active caller beyond its definition. Confirm intended lifecycle before enabling it. The executor's existing lot clamp may lower an approved size (never raise it); that safe reduction is not reflected in the HMAC request terms and merits a follow-up contract test. Stream size-multiplier policy across REST versus agent stream is not established. Existing stream ACK-on-error defect remains open.
- **Coverage gap:** no test evidence in this audit exercises the full agent → risk → executor chain, signature tampering/expiry, kill switch races, duplicate delivery, broker selection, or lifecycle-action path. Existing focused tests do not establish that real broker I/O is unreachable in paper mode.
- **Potential robustness issue to test:** risk consumer silently `continue`s when entry or SL is zero, so malformed proposals do not produce a correlated explicit rejection event. This can leave the agent/dashboard without a terminal risk result. Severity provisional P2; confirm downstream correlation expectations before changing behavior.
- **Potential validation gap to test:** executor maps any non-`BUY` side to `SELL` at order construction. Upstream risk event contracts should guarantee direction enum validation; enforce or prove that contract before classifying this as a defect.
- **Potential idempotency gap to test:** stream handler catches broad exceptions and continues. Whether failed messages are acknowledged/retried depends on `shared/redis_client.py` consumer-group semantics; inspect that implementation and test redelivery before assessing loss/duplicate risk.
- **P1 reliability finding — stream messages are acknowledged even when processing fails.** `shared/redis_client.py::subscribe_stream` performs `XACK` in `finally` after yielding each parsed event. Risk/executor consumers catch processing exceptions and continue, so the generator resumes and acknowledges the failed message. The next read uses only `>` and no `XPENDING`/`XAUTOCLAIM` recovery exists in `RedisClient`. `services/nexus_data/main.py::_trade_close_consumer` likewise XACKs in `finally` after persistence exceptions. A transient DB/broker failure can therefore permanently drop an approved order or closed-trade record instead of retrying or dead-lettering it. No failure injection was run against live services.

## Required next verification

- Add isolated contract tests with fake Redis and fake broker for approval/deny/expiry, kill switch, `paper` versus live broker factory, duplicate stream delivery, invalid side, malformed proposal, and lifecycle actions. (Signed-payload tamper tests are now present for every contract field.)
- Replace implicit generator ACK with explicit post-success ACK/negative-ack or a bounded retry/dead-letter policy; test processing exception, crash/reclaim, idempotent retry, and correlation of rejected proposals in the dashboard/API.
- Run only against fakes or an explicitly isolated paper adapter; never connect the audit to a real MT5 account.

## Status

Partial review. The unbound risk-approval payload is fixed and covered by focused tests; unconditional ACK-on-processing-error is a confirmed remaining defect, and other observations remain test candidates. The subsystem remains open pending stream-path integration tests, ACK/reclaim repair, and runtime-safe evidence.
