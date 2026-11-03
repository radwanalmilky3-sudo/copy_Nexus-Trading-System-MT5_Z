# ML Model Candidate Promotion and Rollback

## Purpose and scope

Prevent automatic walk-forward retraining from replacing the serving model with an incomplete, unloadable, or objectively weaker model bundle. This change applies to the `nexus_ml` per-symbol ensemble and its existing automatic retraining path. It does not alter trading mode, execute trades, change risk decisions, or mutate historical training data.

## Current evidence

- `services/nexus_ml/main.py::_auto_retrain_loop` trains directly into `symbol_model_dir(symbol)`, the same directory used by serving ensembles.
- After training, the serving cache entry is removed and the model is loaded again from that directory, even if training or saving was incomplete.
- `WalkForwardTrainer._save_all` logs each model save exception and continues, so a partial bundle is not reported as a failed training run.
- `ModelEnsemble.load_all_models` records per-model failures but does not provide an all-or-nothing bundle validation operation.
- Walk-forward outer folds already report classifier accuracy and log-loss, providing the candidate-side measurements needed for promotion.

## Chosen design

Each symbol stores immutable model generations below its existing model directory, e.g. `models_store/XAUUSD/versions/<generation-id>/`. The legacy symbol directory remains readable as the initial incumbent; migration is lazy and does not rewrite legacy files. A small active-generation manifest identifies the serving generation after the first successful promotion. Generation identifiers are opaque, unique, and safe as path components.

Training for automatic retraining occurs in a newly created staging directory, never in the active generation or legacy incumbent directory. Saving becomes strict for candidate publication: any required model or feature-schema save failure fails the candidate. A generation is publishable only when the bundle manifest identifies every artifact actually produced, all required files exist and are non-empty, metadata/schema are readable, and an isolated `ModelEnsemble` can load the complete bundle without errors. No partial candidate can be selected.

## Acceptance and comparison

Use the already-approved rule: require at least three valid chronological outer folds. Compare each promotable supervised model independently against the incumbent on the exact same rows and fold boundaries, using the same feature schema and evaluator. Do not aggregate scores across targets: in particular, LightGBM regime classification is evaluated only against its own regime labels, not binary direction labels. For each model with a corresponding incumbent, candidate mean outer log-loss must be strictly lower and candidate mean accuracy must be greater than or equal to incumbent mean accuracy. A model without an incumbent is not auto-promoted in this release. Missing, malformed, incomparable, or fewer-than-three-fold metrics reject promotion. Anomaly detection remains descriptive and is not granted promotion based on supervised log-loss.

The incumbent is evaluated using the same frozen outer validation rows and labels as the candidate; it is never fit on those rows. Evaluation uses in-memory validation data and does not write a model or training sample to the live database. If the current bundle has no comparable fitted incumbent models, leave the candidate staged and inactive and report `no_comparable_incumbent`.

## Activation and rollback

Because anomaly detection gates signals to `NO_TRADE`, preserve the incumbent anomaly artifact unchanged when its feature schema matches the candidate; if the incumbent detector is fitted but cannot be preserved with the identical schema, reject the candidate. If there is no incumbent anomaly detector, omit the candidate detector from the promoted bundle rather than introducing unmeasured veto behavior. Every supervised model included in a candidate bundle must have a valid same-fold incumbent comparison; one unscorable supervised model rejects the entire bundle.

Keep the currently serving `ModelEnsemble` object in memory while constructing and validating a replacement ensemble from the staged generation. Only after load and promotion checks pass, atomically replace the per-symbol in-memory reference and update the active-generation manifest using a same-directory temporary file plus atomic replace. If either operation fails, preserve/reinstate the previous in-memory ensemble and active manifest. Retain the previous generation; automatic deletion/garbage collection is out of scope. On startup, load the active generation if one is declared; if it cannot load, log a critical error and fall back to the previous retained generation where available, otherwise preserve legacy loading behavior. No serving request may observe a partially loaded ensemble.

## Status and observability

For every candidate, emit a structured outcome containing symbol, candidate generation, incumbent generation or `legacy`, valid fold count, per-model candidate/incumbent mean accuracy and log-loss where comparable, decision (`promoted` or `rejected`), and a stable reason code. Preserve the existing retraining result key for compatibility and add candidate outcome details rather than changing existing response fields. Do not expose filesystem paths, credentials, or feature-row contents through the status endpoint.

## Failure behavior

- Candidate training, persistence, validation, incumbent evaluation, or activation failure must leave the serving model unchanged.
- Rejection is a normal completed retrain outcome and must not advance the active generation.
- Preserve staging candidates for diagnosis; cleanup policy is deferred.
- When no incumbent or comparable model is available, do not bootstrap automatically. The candidate remains inactive for later explicit review.
- Cancellation and service shutdown must not switch active generation.

## Tests and acceptance evidence

Add deterministic tests for comparison boundaries (three vs. two folds, strict log-loss improvement, accuracy tie/decline, model-specific targets, missing incumbent), strict bundle save/load validation, legacy startup compatibility, atomic activation, and rollback on injected save/load/manifest failures. Add an integration-level test around the auto-retrain orchestration proving rejected candidates retain the exact prior serving object and manifest. Run focused ML tests and the full test suite. Do not connect to live MT5, execute trading orders, start production services, or mutate the project's live DuckDB/Redis state.

## Non-goals

- No automated deletion of old model generations.
- No changes to trading signal weights, risk management, inference semantics, or paper/live configuration.
- No migration or rewrite of existing model artifacts until a validated candidate is promoted.
- No human approval UI in this change; unbootstrapped/no-incumbent candidates remain inactive and are surfaced in logs/status.
