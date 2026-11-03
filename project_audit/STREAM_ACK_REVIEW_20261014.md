# Redis Stream Acknowledgement and Recovery Review

**Date:** 2026-10-14  
**Status:** Confirmed P1 defect; Data, ML, Trade Memory, Risk trade-close, Executor and Risk proposal consumers have explicit/failure-aware acknowledgement paths. Legacy consumers and pending recovery remain open.
**Scope:** Static tracing of Redis consumer-group reads, acknowledgements, exception handling, side effects, and retry compatibility. No Redis service, database, broker, or trading process was started or contacted.

## Finding

Multiple consumers acknowledge (`XACK`) messages even when business processing fails. This is at-most-once behavior for those failure paths: after a transient exception, the pending message is removed from the consumer group's pending entries list and cannot be retried by the current `>`-only read loops. This can silently lose trade decisions, persisted trade history, feature/model events, and monitoring updates.

### Shared helper

- `shared/redis_client.py::RedisClient.subscribe_stream` parses an event, yields it to the application, then acknowledges its message in a `finally` block. If a consumer catches its own processing exception and continues, the generator resumes and acknowledges the message anyway. A parse exception is also acknowledged.
- ACR-47 added `subscribe_deliveries` with an explicit `StreamDelivery.ack()` contract and migrated the Executor risk-decision consumer. The legacy helper remains unchanged for compatibility and is still used by risk, agents, monitor, and WebSocket broadcasters.
- ACR-48 migrated the risk proposal evaluator to explicit delivery acknowledgement. Risk trade-close migrated on 2026-10-14; acknowledgement now follows success/intentional filtering, while multi-effect idempotency is still required before recovery.
- Callers include risk, executor, agents, monitor, and API WebSocket broadcasters. WebSocket client delivery is ephemeral; using the same auto-ack helper means a disconnected client can also consume an event without receiving it.

### Direct consumers

- `services/nexus_executor/main.py::_execution_stream_consumer`: ACR-47 uses explicit deliveries; intentional reject/block/dedup decisions are acknowledged explicitly, while guard/broker/publish exceptions remain pending. Tests verify rejected decisions are acked and an approved decision is not acked when guard evaluation fails. There is no reclaim or durable proposal idempotency, so replay remains disabled.
- `services/nexus_risk/main.py::_risk_stream_consumer`: ACR-48 acknowledges only after an intentional drop or published risk decision; an evaluation exception remains pending. Focused tests cover an incomplete proposal drop and evaluation failure. The separate trade-close consumer now uses explicit deliveries and leaves processing failures pending; daily-PnL, recent-results, and directional-streak Redis write errors propagate instead of being swallowed. Focused risk/Redis-client regression suite: **48 passed**. There is still no pending reclaim/DLQ or event-level idempotency, so recovery remains disabled.

- `services/nexus_data/main.py::_trade_close_consumer`: this review found acknowledgement in `finally` after conversion or DuckDB persistence exceptions. ACR-46 now acknowledges only after success or an intentional invalid-event drop; failure injection verified that a failed insert remains pending and success is acknowledged. `DataStore.insert_trade` is keyed/idempotent by trade ID. Consumer identity still changes per process, and there is no pending reclaim/DLQ, so recovery is incomplete.
- `services/nexus_ml/main.py::_handle_feature_event`: this review found unconditional acknowledgement in `finally`. ACR-45 now acknowledges only after successful signal publication or explicit intentional drop; malformed JSON failure injection verified no acknowledgement. Feature history writes and signal publication remain separate effects, and pending recovery/deduplication are unresolved.
- `services/nexus_features/main.py::_ohlcv_consumer`: acknowledges only after its handler returns, which is better for exceptions, but it reads only new IDs (`>`) and has no pending-entry reclaim. A crashed consumer can strand a message indefinitely.
- `services/nexus_ml/traders/trade_memory.py` catches errors then acknowledges in `finally`. Its side effects include recording trade memory and appending outcome-labelled training records.
- ACR-49 now acknowledges the trade-close delivery only after `TradeMemory.record_trade` succeeds; a failure-injection regression confirms persistence failure leaves it unacknowledged. Outcome-record publication remains best-effort and is intentionally outside the primary trade-memory persistence success boundary. There is still no pending-message recovery, and repeated delivery would require stable trade-ID idempotency before recovery is enabled.

## High-impact duplicate/replay hazards

Removing `XACK` or adding `XCLAIM` alone is not a safe fix:

1. Risk trade-close processing increments daily PnL, updates in-memory and Redis anti-tilt state, pushes recent results, and updates per-direction streaks. These effects are not visibly guarded by a durable processed-message key. Replay can double-count losses and alter circuit-breaker decisions.
2. Monitor trade-close processing updates metrics and sends Telegram. Replay can duplicate externally visible notifications and metrics.
3. Executor consumes approved risk decisions and may submit an order. Its existing `_is_duplicate_order(symbol, side)` is a short-lived burst guard, not durable proposal-level idempotency. If broker submission succeeds but the response is lost, retry cannot safely infer whether to submit again without reconciliation against broker state/order identifiers.
4. ML and feature consumers perform multiple Redis writes/publications; a crash after a partial write but before acknowledgement can duplicate downstream events or training records.

## Compatibility evidence

The project-local Redis server binary was previously identified as 5.0.14.1; no listener on port 6379 was observed during that earlier read-only check, so the active server/version is unknown. `XAUTOCLAIM` requires Redis 6.2+, while `XCLAIM` is available from Redis 5.0. A default implementation must not assume `XAUTOCLAIM` support; either test a Redis-5-compatible `XPENDING` + `XCLAIM` path or make an explicit server upgrade part of deployment.

## Required remediation contract

Implement and test a coordinated consumer contract before changing acknowledgement behavior:

1. Separate stream delivery from acknowledgement. A delivered message is acknowledged only after its complete required processing succeeds; parse/validation failures go to a bounded, observable dead-letter path with the original stream and entry IDs.
2. Add pending recovery compatible with the supported Redis version (`XPENDING` + `XCLAIM` if Redis 5 remains supported), with idle threshold, bounded batch size, consumer ownership, and shutdown behavior. Prevent unbounded retries and avoid starving new messages.
3. Introduce durable idempotency keys based on stream/group/message or stable business IDs, persisted atomically with each business effect where possible. For multi-effect handlers, use an outbox/inbox or equivalent transaction boundary.
4. For executor order submission, define proposal/order idempotency and the broker reconciliation procedure for an uncertain submit before enabling retries. On uncertainty, fail closed and surface reconciliation-required state instead of automatically resubmitting.
5. Define delivery guarantees per subscriber. UI WebSocket broadcasters should not steal work from durable business consumers; use Pub/Sub or a separate consumer group/retention policy where ephemeral delivery is intended.
6. Add failure-injection tests for failure before, during, and after each side effect; redelivery after process restart; duplicate message delivery; dead-letter limits; and two consumers claiming pending entries. Use mocked Redis first, then isolated disposable Redis matching the minimum supported version.

## Verification and disposition

- Static evidence: exact helper and direct-loop paths were inspected; corresponding cross-service exception handling and side effects were traced.
- Runtime tests: Redis failure/reclaim behavior itself was not runtime tested; no Redis was started or contacted. ACR-45/46/47/48/49 use mocked failure injection. ACR-47/48 focused delivery/Risk/Executor tests: **12 passed**; ACR-49 focused tests: **4 passed** (6 passing in the combined Trade Memory/Data consumer group). Historical full Python suite after ACR-49: **823 passed, 3 warnings in 141.80s**. Latest full suite before the current Risk trade-close batch: **899 passed, 3 warnings in 348.20s**; after that batch, the focused Risk/Redis-client set passed **48 tests**. One full run remains pending at the end of the grouped repair batch. The broader legacy-helper and redelivery contracts remain untested.
- Disposition: **Needs repair (P1), partially mitigated.** ACR-45/46 protect ML/Data consumers, ACR-47 migrates Executor, ACR-48 migrates Risk proposals, ACR-49 protects Trade Memory persistence, and the 2026-10-14 follow-up migrates Risk trade-close and propagates daily-PnL write failures. None adds recovery. Legacy `subscribe_stream` still auto-acks and remains in use. Remediation should continue with risk trade-close event-level idempotency, other durable consumers, separation of ephemeral WebSocket fanout, then Redis-version-compatible pending recovery/DLQ; enable retries only after side effects are safe.
- Related evidence: `AUDIT_FOLLOWUP_20261012.md` (confirmed defect E and Redis-version compatibility); `TRADE_FLOW_REVIEW_20261012.md` (risk/executor signed approval contract and remaining stream integration gap).
