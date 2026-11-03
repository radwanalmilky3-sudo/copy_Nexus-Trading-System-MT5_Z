# Nexus research/evidence wiring — 2026-10-19

## Authorized scope

First implementation phase of the approved architecture: read existing Nexus
data into Research Lab, distinguish unavailable/degraded/empty sources, and
connect the audit evidence endpoint to its UI. No training, trading, data
restoration, provider download or production schema seeding is part of this phase.

## Read path

- Gateway registers `NexusResearchBackend`.
- Durable reads use the existing authenticated `DataServiceClient.query`
  boundary; the API gateway never opens DuckDB.
- Owner-side `ResearchReader` accepts only allowlisted resources and bounded,
  parameterized queries. Reads never create missing tables.
- Datasets show actual persisted OHLCV groups by symbol/timeframe/source.
  A full-series manifest hash is exposed only for a group covering that
  whole series; a mixed-provider group is not given the combined fingerprint.
- Import jobs, quality runs, news and artifacts project existing owner tables.
  Missing optional tables are unavailable, not healthy empty collections.
- Strategies are explicitly draft reference definitions, not promoted models.
- Provenance uses dataset fingerprints. Cleaning and full research backtest
  results remain explicitly unavailable until their actual readers exist.
- UI requests have total deadlines and cancellation; sections settle separately.

## Evidence UI

`/progress-state` supplies the declared plan. Authenticated
`/api/audit/progress` separately supplies file SHA-256, sizes, modification
times, reading errors and the recorded completion summary. The UI does not
present these file hashes as Git commit hashes, nor declared database
percentages as a database verification result.

## Verification

Regression tests cover missing/empty source distinction, persisted dataset
identity/hash scope, pagination, bounded inputs, contract projections,
unavailable item details, and frontend availability/auth/evidence handling.
Verified results after review fixes:

- Owner/API suites: 569 passed, two existing deprecation warnings
  (`pytest tests/test_data tests/test_api -q --maxfail=5`).
- Frontend: 56 passed (`node --experimental-strip-types --test tests/*.test.mjs`).
- TypeScript: `tsc --noEmit` passed.
- Production build: passed, 21 pages generated.
- Authenticated live smoke: dataset list and exact detail, optional table states,
  six draft strategy definitions, audit SHA matching disk, auto-trade disabled.
- A root-wide `pytest -q --maxfail=10` attempt stalled in collection and was
  interrupted; this is not a claim that the entire repository suite passed.

Running the production build alongside the dev server exposed shared `.next`
cache conflicts. The managed dashboard was restarted and the dev cache regenerated.
The attempted cache preservation was partial because the manager regenerated
the directory concurrently; only generated build cache was affected, not source
files or database content. Do not run another production build against this live
dev cache; stop the dev server or use an isolated build checkout first.

## Next phases (not implemented here)

Research-run persistence and full backtest reader; explicit freshness and
coverage certification; unified model/feature lineage across ML/DL/RL/HMM and
agents; model promotion/shadow validation; long-term research archive.

## WAL replay incident during deployment

A data-service restart exposed DuckDB 1.5.6's
`GetDefaultDatabase with no default database set` error during WAL replay.
The exact main file and WAL were preserved, unchanged, in
`data/backups/wal_replay_20261019_1726/` before probing recovery.

- Original main SHA-256: `61F8121E97A9B0F40EC305FBE7AD0228E94FE51886F1D61E9C9B9EA1DB0513EE`
- Original WAL SHA-256: `0F7B10ECF385DC596684281986BDABD0EBE803F2C478FFD5DE5A3940F97DEDA3`
- An isolated copy successfully replayed via ATTACH from an initialized memory
  catalog, preserving one user and 1,853 bars; checkpoint and direct reopen passed.
- The owner connection now falls back only for this precise internal replay
  error. It keeps the recovered attached connection as its sole durable writer.
  No WAL deletion, old-database restoration, or production-file replacement occurs.
- After application shutdown completed on a later CTRL_BREAK reload, the native
  interpreter emitted a GIL finalization error and its launcher needed cleanup.
  The database had checkpointed; subsequent service startup and authenticated
  read checks passed. This interpreter-exit issue is not claimed fixed.

Live checks confirmed REAL_MT5, synthetic fallback disabled, authenticated
dataset listing and source classification, six draft strategy definitions, and
109 audit files with the state SHA-256 matching disk. Empty results remain empty;
no quality runs, news, artifacts or backtests were manufactured.
