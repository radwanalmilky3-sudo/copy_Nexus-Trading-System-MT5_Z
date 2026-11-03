# DB_SCHEMA_ACTUAL — Runtime DuckDB Inventory

**Source of truth:** `GET http://127.0.0.1:9001/api/data/fundamental/schema` (nexus-data, live DB `data/nexus.duckdb`)
**Captured:** 2026-10-10 (post-migration, services running); market-data additions aligned 2026-10-16 (static, DB not opened)
**Result:** **28 tables after next schema apply** = 24 fundamental contract tables + `ohlcv` + `ticks` + `trades` + `ohlcv_backfill_runs` (27 as of 2026-10-10 capture)

The pack's contract requires 24 core fundamental tables; the live database satisfies it and adds the trading tables required by the rest of the fleet.

## Fundamental contract tables (24) — all present

| # | Table | Purpose |
|---|---|---|
| 1 | `central_bank_events` | Policy decisions, rate surprise, hawkish/dovish scores |
| 2 | `data_vintages` | Vintage-aware values with `known_at` (leakage guard) |
| 3 | `event_expectations` | Forecasts/consensus with freshness & quality scores |
| 4 | `flow_observations` | Positioning/flow observations (COT, ETF, etc.) |
| 5 | `fund_events` | Canonical economic/geopolitical event registry |
| 6 | `fund_sources` | Source registry incl. health state, license, auth config |
| 7 | `fundamental_audit_log` | Before/after audit trail of record changes |
| 8 | `fundamental_blackout_windows` | Blackout windows (id, impact, assets, policy version) |
| 9 | `fundamental_event_outcomes` | Actual outcomes vs prediction (Brier, direction accuracy) |
| 10 | `fundamental_explanations` | Arabic explainability records (what/why/transmission) |
| 11 | `fundamental_factor_scores` | Five-domain factor scores per event |
| 12 | `fundamental_fusion_results` | Weighted fusion (macro/monetary/cross-asset/geopolitical/flows) |
| 13 | `fundamental_guard_decisions` | Risk/executor guard decisions with reason codes |
| 14 | `fundamental_training_features` | Leakage-guarded training rows (known_at_cutoff) |
| 15 | `geopolitical_events` | Geopolitical severity/safe-haven scoring |
| 16 | `gold_impact_predictions` | Horizon probabilities (5m/15m/60m/4h), stages, blackout flags |
| 17 | `macro_releases` | Indicator releases, surprise z-scores, gold relevance |
| 18 | `market_series_observations` | External series (DXY, yields, VIX, oil…) |
| 19 | `model_evaluations` | Brier/calibration tracking per model version |
| 20 | `news_articles` | Ingested articles with dedup/cluster fields |
| 21 | `news_nlp_analysis` | NLP labels (FinBERT, gold relevance, severity) |
| 22 | `prediction_reasoning_steps` | Causal transmission chain steps per prediction |
| 23 | `source_fetch_runs` | Fetch telemetry (status, latency, quota, payload hash) |
| 24 | `source_health_history` | Health state transitions per source |

## Fleet trading tables (3 + backfill bookkeeping) — present

| Table | Purpose |
|---|---|
| `ohlcv` | Candles per symbol/timeframe; provenance columns `source` (e.g. `mt5_poll`, `mt5_range`, `mt5_backfill`), `quality` (default `ok`), `fetched_at` (additive via `ALTER TABLE ADD COLUMN IF NOT EXISTS`) |
| `ticks` | Tick stream (paper/live broker feed) |
| `trades` | Executed trade journal (paper + live schema; live empty by mode) |
| `ohlcv_backfill_runs` | Completed backfill windows per (symbol, timeframe) so gap detection never re-requests provider-empty ranges (weekends/holidays) |

## Market-data reads

- `GET /api/data/ohlcv/{symbol}/{timeframe}/provenance` (nexus-data, public market data like the candles/ticks reads) returns per-bar `source`/`quality`/`fetched_at`, coverage stats (`first_bar`, `last_bar`, `bar_count`, `expected_bars`, `missing_bars`, source/quality counts), and the 10 most recent backfill runs.
- Persistence invariant: the still-forming candle is never written; a bar is inserted only when `timestamp + timeframe <= now`.

## Verification notes

- Schema served dynamically by nexus-data's `fundamental_store.schema_inventory()` — reflects the actual connected database, not the static SQL file.
- Foreign keys are enforced (observed `ConstraintException` on invalid `prediction_id`/`blackout_id` references — see known issue in `IMPLEMENTATION_REPORT.md` §5.3).
- Paper isolation: `trades` receives only paper-broker rows while `NEXUS_TRADING_MODE=paper`; real broker path disabled in executor config.
