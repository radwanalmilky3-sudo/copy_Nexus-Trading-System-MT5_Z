# Research context evidence

The eight Research Lab views now share account, selected saved asset, timeframe, and source-date scope. Source download controls remain mounted during tab navigation so changing views does not reset the scope. Older global evidence remains separate and explicitly labeled.

## Computation and ownership

`services/nexus_data/data_loader.py` reads only the selected website owner's broker account archive. New successful history/merge writes record first observed availability in `research_candle_availability`; existing unknown timestamps are never backdated. Source publication time is currently unavailable. Source candle time is not asserted to be UTC. Historical point-in-time eligibility requires both a known UTC close and a known availability timestamp at or before the requested instant. Missing evidence excludes the row.

`shared/research_context_engine.py` computes source-clock-aligned log returns, Pearson windows 20/60/120, and cross-correlation lags -10 through +10. Returns spanning a gap are excluded. Positive lag k means the other asset's return at t-k is paired with gold at t. Minimum lag sample count is 30. Results are observations; predictive validation and calibrated confidence remain false/null. US10Y is blocked until its instrument type is documented. Exact logical names and known `s` suffix aliases are recognized; arbitrary broker names are not guessed.

The analysis endpoint derives price validity, duplicate and unclassified gap checks, availability coverage, provenance hashes, and missing asset flags from the actual archive. Cleaning is a read-only scan of its stored version; it does not invent prices or assert that unknown market closures are corruption. Current clock observations do not certify historical timezone rules.

## Views and artifacts

- Sources: saved instrument mapping, series type, coverage, availability counts.
- Cleaning: valid/invalid/duplicate rows, unclassified gaps, scan action and fingerprint.
- Validation: price, sample count, availability, publication time, clock conversion and gap checks.
- Provenance: broker server, source candle range, publication/availability evidence and hash.
- Strategies: observational gold cross-asset rolling correlations and lead/lag, or explicit missing-data reasons.
- Backtests: point-in-time eligibility and blockers. No PnL is fabricated: baseline strategy, execution costs and historical UTC evidence are not yet supplied.
- News: actual source-tagged news filtered by selected asset and publication period; unknown first availability is explicit. Not used in historical decisions.
- Artifacts: explicitly saved immutable analysis reports, with authorized retrieval and JSON export. Reports never activate trading or change runtime risk permissions.

GET/POST `/api/brokers/accounts/{account_id}/research-analysis` reads/saves evidence. GET `/api/brokers/accounts/{account_id}/research-analysis/{report_id}` retrieves a saved report. Existing internal-secret data routing and website user permissions are enforced. `research_context_reports` stores reports in the sole database owner's process.
