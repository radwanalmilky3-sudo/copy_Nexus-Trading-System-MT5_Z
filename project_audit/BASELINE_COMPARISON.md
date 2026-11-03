# Baseline comparison — original repository

**User clarification:** `https://github.com/MirandaCR/Nexus-Trading-System-MT5.git` is the original project before development. Treat it as the architectural baseline, not as the latest state to merge into the local folder.

## Evidence and limits

- The public GitHub repository page and README were reviewed. The README describes nine services, event-driven market-data flow through Redis Streams, DuckDB trade memory, a final non-overridable risk veto, and a dashboard backtest over historical closed trades.
- The local project folder has no `.git` metadata, so its commit, branch, and local modifications cannot be identified.
- A shallow clone to a separate audit workspace was attempted and failed because this environment could not connect to `github.com:443`.
- Therefore this is an architecture-level comparison between the README claims and partial local source findings. It is not a file/commit diff, and statements in the README are not treated as proof that features are implemented or validated.

## Preliminary comparison

| Area | Original baseline (README) | Local evidence reviewed so far | Status |
|---|---|---|---|
| Service topology | Nine cooperating services plus Next.js dashboard | Nine service folders and dashboard discovered | Inspected partially; topology exists, integration not certified |
| Market-data flow | MT5 → `nexus-data` → Redis Streams → features/ML/agents | Reviewed MT5 path caches OHLCV in Redis and publishes the latest bar; DuckDB write was not found in that path | Potential durable-history gap; audit all connectors/callers |
| Historical data | README describes DuckDB for trade memory; diagram does not fully specify an OHLCV archive | Candle endpoint reads DuckDB, then may fall back to MT5 or synthetic OHLCV depending on configuration | Provenance and persistence contracts need clarification; no data-quality certification |
| Database ownership | Not specified in README | `nexus-data` retains a read-write DuckDB connection; monitor contains a read-only opener | Windows concurrency risk candidate; verify full call graph and isolated behavior |
| Backtesting | README describes a backtest of historical closed trades | Independent source review found API paths that may convert data-source errors into empty data and zero-valued results | High-confidence code-path concern; reproduce with isolated tests |
| Risk/execution | Risk manager has final veto; executor checks kill-switch | Local end-to-end decision path has not yet been fully traced | Not yet comparable or certified |
| Frontend | Overview, Positions, Risk, News, Agents, Intelligence, Journal, Backtest, Console | Additional settings/model/analytics pages found; no historical import page found | Product surface expanded; historical-data workflow appears absent from reviewed route inventory |

## Impact and next checks

1. Establish a complete local source inventory and trace every MT5, CSV, and external data connector through validation, Redis, DuckDB, and consumers.
2. Prove whether the history/backtest endpoints distinguish unavailable data from valid empty results.
3. Trace risk veto and executor gating end-to-end, including failure behavior and paper-only test isolation.
4. If exact commit-level comparison is required, provide a source archive or restore outbound GitHub access; do not merge upstream into the working project as part of the audit.

No source code, live database, service state, credentials, or trading mode was changed for this comparison.
