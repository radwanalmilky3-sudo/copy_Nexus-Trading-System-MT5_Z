# Stored candle quality automation

The data-owner service starts a quality worker after database initialization.
It checks all persisted symbol/timeframe/source groups at startup and every
60 seconds. Changed or expired snapshots are audited; unchanged, current
certificates are skipped. New data is therefore detected within the polling
interval, not by a synchronous ingestion hook.

Reports and validation artifacts retain the exact snapshot SHA-256, scope,
checks, reasons and expiry. Research Lab displays passed/warning/failed or
stale evidence. Basic checks are not trading or model-training approval.
Operational state is available in data-service `/health.quality_automation`.

## Autonomous remediation

Before certification, the worker cleans supported MT5 ingestion groups. Invalid
prices/volume, forming/future candles and duplicate/conflicting records are
archived with every original column in `quarantine`, then removed from active
OHLCV in the same transaction. Identical duplicates retain one active row;
conflicts require a validated MT5 answer rather than an arbitrary winner.
Originals remain recoverable in quarantine; nothing is permanently discarded.

Missing timestamps are detected on the combined MT5 history within 365 days,
not on each ingestion path in isolation. Each cycle submits at most four
500-bar windows. Historical invalid rows also receive exact-time replacement
requests. Only matching symbol/timeframe/time and valid closed candles are
accepted. Other providers are neither overwritten nor silently substituted.
Replacement availability is the actual repair time, with a revision increment.

Attempts and retry deadlines survive restarts in `quality_repair_attempts`.
Empty/partial answers are retried after six hours, errors use capped exponential
backoff. Empty answers are not proof of market closure. If ingestion changes
the selected rows during network fetch, the mutation is deferred to avoid
overwriting concurrent work. Applied repairs are re-audited in the same cycle.

Unresolved quarantine makes the group certificate failed and blocks operational
stored reads, the OHLCV HTTP route and live-cache publishing for that pair.
The publisher removes its cached pair when blocked. Raw evidence remains
readable for auditing. Live projections reject malformed or forming candles.
Existing MT5 tail backfill remains separately scheduled for new ranges.

Limitations: no broker session calendar is implemented; source-separated
certificates can retain gap warnings even if another ingestion path contains
the timestamps. Missing provider history cannot be manufactured. These basic
checks are not full training/PIT/execution certification. Direct external SQL
readers outside the data service are not covered by the operational gate.
Selections over 100,000 rows fail explicitly instead of receiving partial
certificates. Errors remain visible in health state and service logs.

## Activation evidence (2026-10-19)

The service was gracefully stopped and checkpointed before activation. A full
pre-activation database copy is retained at
`data/backups/before_autonomous_quality_20261019_1818/nexus.duckdb`
(SHA-256 `7FA352635AD03FFBD90BA9343A7DCA3840E4F7766EE2A1B8434CF0DF86992C34`).
The running service reports `repair_enabled: true`, real MT5 connected, no
synthetic fallback and no blocked pairs. Authenticated gateway verification
confirmed quality reports/artifacts and dataset details are readable; both
Research Lab and Audit Progress HTTP pages returned 200. Automatic trading
remains disabled. A live concurrent-ingestion deferral was observed without
an error or an overwritten snapshot. This is not evidence that corrupt live
rows were repaired: none were quarantined in the observed cycle.

Read-only independent review cleared its critical/important findings after
regression fixes. Regression scenarios include corruption, duplicates,
forming bars, disconnected MT5, empty-answer backoff, concurrent ingestion,
quarantine-only certificate changes, source conflicts before result limits,
over-2,000-target retry fairness, all-isolated datasets and strict JSON
preservation of nonfinite values. Full multi-service `pytest tests` did not
complete collection and was stopped; data/API suites are verified separately.
Final data/API suite: 590 passed, with two dependency deprecation warnings.
The subsequently added strict-JSON regression passed separately (1 passed).
Live operational HTTP reads returned 500 M5 and 467 M15 candles, each checked
for closed timestamps, finite valid OHLCV, chronological order and uniqueness.

## Certificate display clarification

The M15 backfill warning at 14:57 UTC was reproduced as a current, unexpired
certificate of an unchanged historical source slice, not evidence that the
quality worker had stopped. Certificates intentionally retain their original
issue time until the data changes or expiry. Dataset reads now additionally
return `snapshot_verified_at` for the owner-locked comparison performed on that
read; this is not a newly issued certificate or a provider re-fetch.
The lab refreshes every 60 seconds while mounted, distinguishes issue,
verification and expiry times, formats them in Asia/Aden, and identifies
`mt5_backfill` as a historical slice.

Broker-session classification remains deliberately unconnected. The installed
MetaTrader5 Python package (5.0.6231) exposes no session-window functions
(checked through its public names). MQL5's `SymbolInfoSessionTrade` can obtain
weekly session windows; a read-only terminal bridge or broker-attested calendar
is required before these gaps may be classified as confirmed closure. Empty
history responses, weekdays/weekends alone and `session_close` price fields
must not be substituted for a session calendar. Historical holidays and broker
time/DST also need explicit coverage; no warning was suppressed or promoted.
