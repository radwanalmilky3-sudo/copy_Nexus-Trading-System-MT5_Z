# ML-03 Candidate Promotion Remediation — 2026-10-14

## Finding and impact

The automatic and manual walk-forward retraining paths trained directly into `models_store/<SYMBOL>/`, the same directory read by serving ensembles. Save exceptions were logged and ignored; after retraining the cached ensemble was discarded and the directory reloaded without any performance acceptance check. This allowed partial or weaker model files to replace the serving bundle.

## Implemented remediation

- `services/nexus_ml/model_registry.py` stores symbol-specific generations under `versions/<generation-id>/`, validates safe path components and non-empty artifacts, writes bundle/active JSON atomically, retains prior generations, and resolves startup fallback generations. Legacy symbol directories remain supported when no valid active generation is declared.
- `services/nexus_ml/training.py` preserves legacy best-effort defaults but supports strict candidate persistence. Candidate mode fails if any model/schema save fails, requires a feature schema, records exact original validation row IDs, and evaluates the incumbent on the same validation rows as each candidate fold. Loaded classifier scoring handles LightGBM Booster state that lacks `classes_` but carries `_n_classes`.
- `services/nexus_ml/ensemble.py` supports strict generation loading: schema must parse and contain names, all declared artifacts must exist and be non-empty, and any declared model load failure rejects the bundle. Existing permissive legacy loading remains the default.
- `services/nexus_ml/model_promotion.py` requires at least 3 folds, matching model key, target identity, fold IDs, and exact validation row IDs. For each included supervised model, mean outer log-loss must strictly improve and mean accuracy must not decline. Invalid/nonfinite/out-of-range metrics, missing comparisons, and partial supervised metrics reject the candidate. Stable reasons are returned.
- `services/nexus_ml/main.py` routes both manual and scheduled retraining into an isolated generation, validates and compares before activation, leaves serving state unchanged on rejection or failure, then updates the cached ensemble and active pointer. Startup loads active then retained generations and falls back to the legacy bundle if the pointer is unreadable or all versioned bundles fail. The existing Redis retrain-result key keeps its fields and adds scheduled candidate outcomes without paths or sample data; manual retrains emit a structured, sanitized candidate-outcome log.
- Isolation/anomaly detection is not judged by supervised metrics but gates decisions to `NO_TRADE`. The incumbent artifact is copied unchanged only when its feature schema exactly matches; a fitted incumbent without a preservable artifact/schema rejects the candidate. When no incumbent anomaly model exists, a new unscored detector is excluded from the promoted bundle.

## Regression evidence

New or expanded tests:

- `tests/test_ml/test_model_registry.py`: path safety, missing artifacts, atomic pointer failure, retained-generation fallback, and legacy startup.
- `tests/test_ml/test_model_bundle_validation.py`: strict persistence failure and invalid/incomplete candidate loading.
- `tests/test_ml/test_model_promotion.py`: minimum fold count, strict loss gate, accuracy non-regression, target/fold/row identity, invalid metrics, and anomaly-model preservation.
- `tests/test_ml/test_model_generation_startup.py`: corrupt active-pointer fallback plus candidate rejection, promotion, and activation failure preserving the serving object.
- `tests/test_ml/test_walk_forward_validation.py`: untouched outer-fold score, exact validation row IDs, and loaded Booster class metadata.

Actual results after the final changes:

- `\.venv\Scripts\python.exe -m pytest tests\test_ml -q` → **48 passed**.
- `\.venv\Scripts\python.exe -m pytest -q` → **339 passed, 2 warnings, 38.91s**.
- `\.venv\Scripts\python.exe -m compileall -q services\nexus_ml tests\test_ml` → exit **0**.

Warnings are existing deprecations: LangGraph's future `allowed_objects` default and FastAPI's `regex` parameter. No service, Redis, DuckDB, MT5, model training on market history, or trading operation was run. Tests prove deterministic code contracts, not profitability or readiness for live/paper promotion.

## Remaining risks / next gates

- The approval rule requires an existing comparable incumbent; cold-start models stay inactive until a future explicit baseline/bootstrap design exists.
- Candidate and incumbent use the same sample in-memory and source feature schema, but no market-history dataset was used to establish whether thresholds produce sensible promotion rates.
- Probability calibration, leakage in feature preprocessing/feature selection, transaction-cost-aware backtesting, and paper-only service integration remain unverified.
- Model generations are deliberately retained indefinitely; disk-retention/garbage-collection policy is out of scope.
- The project audit remains partial (see `COVERAGE.md`); stream ACK/recovery, remaining API authorization, historical import, frontend build/tests, dependencies, and runtime checks remain open.

## Workspace caveat

The project folder has no `.git` metadata. No diff, commit, or Git rollback was possible; all source and test changes are in the authorized project path, with this report and `ML_PROMOTION_PROGRESS.md` recording the work.
